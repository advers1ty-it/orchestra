"""Il ponte Telegram: chi puo' scrivere, cosa succede a chi non puo'.

Nessuna rete: l'API e' una funzione che si puo' sostituire, e le
risposte di Telegram sono un dizionario. Quello che si verifica qui non
e' che Telegram funzioni — quello lo sa Telegram — ma le due cose che
decidono se questo ponte e' sicuro:

  1. un messaggio da una chat NON collegata non fa partire nessun turno,
     nessun tool, nessuna spesa;
  2. un messaggio da una chat collegata arriva all'agente una volta
     sola, e la risposta torna indietro intera anche se e' lunga.

Il resto sono le cose che si vedono solo in uso vero: l'arretrato al
primo giro (un'app che rifa' il lavoro di ieri appena la riapri), il
codice a uso singolo, i file che arrivano e i vocali che si trascrivono,
il messaggio di stato che si aggiorna e poi sparisce, e i comandi che
fermano un turno o cambiano modello senza costo di token.
"""

import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# I dati dei test non devono finire in quelli dell'utente: qui il file
# dei collegamenti e' una cartella temporanea usa e getta.
os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orch_tg_")

import orchestra.stt as stt  # noqa: E402
import orchestra.telegram as tg  # noqa: E402

PASS, FAIL = [], []
TOKEN = "123456789:" + "a" * 35


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" -- {dettaglio}" if dettaglio and not cond else ""))


def cp(testo):
    """Un testo stampabile: la console di Windows non e' UTF-8.

    Un menu contiene il segno di spunta, che in cp1252 non esiste: un
    test che fallisce non deve morire mentre scrive perche' ha fallito.
    """
    return str(testo).encode("cp1252", "replace").decode("cp1252")


class FintoTelegram:
    """Un Telegram che risponde come l'API, senza uscire dalla macchina."""

    def __init__(self):
        self.inviati = []
        self.in_attesa = []
        self.chiamate = []
        self.modifiche = []
        self.cancellati = []
        self.file_chiesti = []
        self.offset = []
        self.ultimo_id = 1000
        self.contenuto = b"contenuto del file"
        # I pulsanti viaggiano in `reply_markup`: senza guardarli, un
        # modulo che non arriva sembrerebbe identico a uno che arriva.
        self.markup = []
        self.callback_risposti = []

    def messaggio(self, chat_id, testo, nome="prova"):
        self.ultimo_id += 1
        self.in_attesa.append({
            "update_id": self.ultimo_id,
            "message": {
                "chat": {"id": chat_id, "username": nome},
                "text": testo,
            },
        })
        return self.ultimo_id

    def allegato(self, chat_id, campo, voce, didascalia="", nome="prova"):
        """Un messaggio con un file dentro, come lo manda Telegram."""
        self.ultimo_id += 1
        messaggio = {"chat": {"id": chat_id, "username": nome},
                     campo: voce}
        if didascalia:
            messaggio["caption"] = didascalia
        self.in_attesa.append({"update_id": self.ultimo_id,
                               "message": messaggio})
        return self.ultimo_id

    def tocco(self, chat_id, dati, message_id=42, nome="prova"):
        """Un pulsante premuto, come lo consegna Telegram."""
        self.ultimo_id += 1
        self.in_attesa.append({
            "update_id": self.ultimo_id,
            "callback_query": {
                "id": f"cb{self.ultimo_id}",
                "from": {"id": chat_id, "username": nome},
                "data": dati,
                "message": {"message_id": message_id,
                            "chat": {"id": chat_id, "username": nome}},
            },
        })
        return self.ultimo_id

    def ultimo_inviato(self):
        return self.inviati[-1][1] if self.inviati else ""

    def testi(self):
        return [t for _c, t in self.inviati]

    def scarica(self, percorso, massimo):
        return self.contenuto

    def __call__(self, url, dati, secondi):
        if isinstance(dati, bytes):
            dati = {}
        metodo = url.rsplit("/", 1)[-1]
        self.chiamate.append((metodo, dict(dati)))
        if metodo == "getMe":
            return {"ok": True, "result": {"id": 1, "username": "prova_bot",
                                           "first_name": "Prova"}}
        if metodo in ("deleteWebhook", "sendChatAction"):
            return {"ok": True, "result": True}
        if metodo == "sendMessage":
            self.inviati.append((str(dati.get("chat_id")), dati.get("text")))
            self.markup.append(dati.get("reply_markup") or "")
            return {"ok": True, "result": {"message_id": len(self.inviati)}}
        if metodo == "editMessageText":
            self.modifiche.append((int(dati.get("message_id") or 0),
                                   dati.get("text")))
            self.markup.append(dati.get("reply_markup") or "")
            return {"ok": True, "result": True}
        if metodo == "answerCallbackQuery":
            self.callback_risposti.append((dati.get("callback_query_id"),
                                           dati.get("text") or ""))
            return {"ok": True, "result": True}
        if metodo == "deleteMessage":
            self.cancellati.append(int(dati.get("message_id") or 0))
            return {"ok": True, "result": True}
        if metodo == "getFile":
            self.file_chiesti.append(dati.get("file_id"))
            return {"ok": True, "result": {
                "file_path": f"files/{dati.get('file_id')}",
                "file_size": len(self.contenuto)}}
        if metodo == "getUpdates":
            offset = dati.get("offset")
            self.offset.append(offset)
            if offset == -1:
                return {"ok": True,
                        "result": ([self.in_attesa[-1]] if self.in_attesa
                                   else [])}
            if offset is None:
                pronti = list(self.in_attesa)
            else:
                pronti = [u for u in self.in_attesa
                          if int(u["update_id"]) >= int(offset)]
            return {"ok": True, "result": pronti}
        raise AssertionError(f"metodo inatteso: {metodo}")


def ponte(finto, risposte=None, bot_id=7, comandi=None, turno=None):
    chiamate = []
    allegati_visti = []

    def finto_turno(testo, allegati=None, avanzamento=None):
        chiamate.append(testo)
        allegati_visti.append(list(allegati or []))
        if turno is not None:
            return turno(testo, allegati, avanzamento)
        if risposte is not None:
            return risposte
        if avanzamento is not None:
            avanzamento("sto facendo")
        return f"risposta a: {testo}"

    api = tg.Api(TOKEN, trasporto=finto, scarica=finto.scarica)
    p = tg.Ponte(bot_id, "Prova", api, finto_turno, comandi=comandi,
                 attesa=0)
    p.allegati_visti = allegati_visti
    return p, chiamate


def comandi_finti(chiamate, risposte=None):
    def comandi(nome, argomento=""):
        chiamate.append((nome, argomento))
        if risposte and nome in risposte:
            return risposte[nome]
        return f"{nome} fatto"

    return comandi


print("\n[1] il token: forma, salvataggio, rimozione")
try:
    tg.salva_token(1, "pippo")
    check("un token che non e' un token viene rifiutato", False)
except ValueError:
    check("un token che non e' un token viene rifiutato", True)
tg.salva_token(1, TOKEN)
check("il token si salva", tg.stato(1)["token"] is True)
tg.imposta_username(1, "@prova_bot")
check("il nome utente si salva senza @",
      tg.stato(1)["username"] == "prova_bot", tg.stato(1)["username"])
tg.imposta_chat(1, 555, "adver")
check("la chat collegata si legge", tg.chat_di(1) == ("555", "adver"))
tg.salva_token(1, "")
check("togliere il token toglie anche chat e nome utente",
      tg.stato(1)["token"] is False and tg.stato(1)["collegato"] is False)
check("il token di un bot mai configurato e' vuoto", tg.token_di(42) == "")

print("\n[2] il codice di collegamento")
tg.salva_token(2, TOKEN)
voce = tg.nuovo_codice(2)
check("il codice ha la lunghezza dichiarata",
      len(voce["codice"]) == tg.LUNGHEZZA_CODICE, voce["codice"])
check("il codice non ha caratteri ambigui",
      not (set(voce["codice"]) & set("01lo0O")), voce["codice"])
check("un codice sbagliato non vale", tg.codice_valido(2, "aaaaaaaa") is False)
check("il codice giusto vale", tg.codice_valido(2, voce["codice"]) is True)
check("e non vale una seconda volta",
      tg.codice_valido(2, voce["codice"]) is False)
tg._CODICI[3] = ("bbbbbbbb", time.time() - 1)
check("un codice scaduto non vale", tg.codice_valido(3, "bbbbbbbb") is False)
voce = tg.nuovo_codice(2)
check("il codice in corso si puo' rileggere",
      tg.codice_in_corso(2) == voce["codice"])
check("il link porta al bot con il codice dentro",
      tg.link("prova_bot", "abc") == "https://t.me/prova_bot?start=abc",
      tg.link("prova_bot", "abc"))
check("il link senza codice e' la chat",
      tg.link("@prova_bot") == "https://t.me/prova_bot")
check("senza nome utente non c'e' link", tg.link("") == "")

print("\n[3] i testi lunghi si spezzano senza perdere niente")
lungo = ("parola " * 1200).strip()
pezzi = tg.dividi(lungo, limite=1000)
check("nessun pezzo supera il limite",
      all(len(p) <= 1000 for p in pezzi), str([len(p) for p in pezzi]))
check("i pezzi ricompongono il testo",
      " ".join(pezzi).replace("  ", " ").strip() == lungo)
check("un testo vuoto non produce pezzi", tg.dividi("   ") == [])

print("\n[4] l'arretrato non si rigioca")
finto = FintoTelegram()
p, chiamate = ponte(finto)
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
finto.messaggio(555, "messaggio di ieri")
primo = p.passo()
check("il primo passo non gestisce niente", primo == 0)
check("il primo passo chiede l'ultimo aggiornamento",
      -1 in finto.offset, str(finto.offset))
check("e non fa partire un turno", chiamate == [], str(chiamate))
finto.messaggio(555, "messaggio di oggi")
p.passo()
p.aspetta()
check("solo il messaggio nuovo arriva all'agente",
      chiamate == ["messaggio di oggi"], str(chiamate))

print("\n[5] chi non e' collegato non fa partire niente")
finto = FintoTelegram()
p, chiamate = ponte(finto)
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
p.passo()  # primo giro: arretrato
finto.messaggio(999, "ciao, esegui qualcosa")
p.passo()
p.aspetta()
check("un estraneo non ottiene un turno", chiamate == [], str(chiamate))
check("gli si spiega che serve il codice",
      "non e' collegata" in finto.ultimo_inviato(),
      finto.ultimo_inviato()[:80])
check("una chat estranea non prende il posto di quella collegata",
      tg.chat_di(7)[0] == "555", tg.chat_di(7)[0])

print("\n[6] il collegamento con il codice")
finto = FintoTelegram()
p, chiamate = ponte(finto)
tg.salva_token(7, TOKEN)
tg.imposta_username(7, "prova_bot")
tg.dimentica_chat(7)
p.passo()
codice = tg.nuovo_codice(7)["codice"]
finto.messaggio(777, f"/start {codice}")
p.passo()
check("col codice giusto la chat si collega",
      tg.chat_di(7) == ("777", "prova"), str(tg.chat_di(7)))
check("il collegamento non costa un turno", chiamate == [], str(chiamate))
check("la risposta dice che e' collegato",
      "Collegato" in finto.ultimo_inviato(), finto.ultimo_inviato()[:80])
finto.messaggio(777, "e adesso?")
p.passo()
p.aspetta()
check("da li' in poi l'agente risponde",
      chiamate == ["e adesso?"], str(chiamate))

finto2 = FintoTelegram()
p2, chiamate2 = ponte(finto2)
tg.dimentica_chat(7)
p2.passo()
finto2.messaggio(888, "/start codiceinventato")
p2.passo()
p2.aspetta()
check("un codice inventato non collega",
      tg.chat_di(7)[0] != "888", tg.chat_di(7)[0])
check("e non fa partire un turno", chiamate2 == [], str(chiamate2))
check("la risposta non dice se un codice esiste",
      "scade dopo" in finto2.ultimo_inviato(),
      finto2.ultimo_inviato()[:80])

print("\n[7] una risposta lunga arriva intera")
finto = FintoTelegram()
p, chiamate = ponte(finto, risposte="y" * 9000)
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
p.passo()
finto.messaggio(555, "scrivimi tanto")
p.passo()
p.aspetta()
check("la risposta e' stata spezzata", len(finto.inviati) >= 3,
      str(len(finto.inviati)))
check("nessun pezzo supera il limite di Telegram",
      all(len(t) <= tg.MAX_TESTO for _c, t in finto.inviati),
      str([len(t) for _c, t in finto.inviati]))
check("i pezzi ricompongono la risposta",
      "".join(t for _c, t in finto.inviati) == "y" * 9000)

print("\n[8] i comandi: /aiuto, /scollega, e chi non e' collegato")
finto = FintoTelegram()
p, chiamate = ponte(finto)
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
p.passo()
finto.messaggio(555, "/aiuto")
p.passo()
aiuto = finto.ultimo_inviato()
check("/aiuto elenca i comandi",
      "/steer" in aiuto and "/stop" in aiuto and "/modello" in aiuto,
      aiuto[:80])
check("e non costa un turno", chiamate == [], str(chiamate))
finto.messaggio(999, "/stato")
p.passo()
check("un comando da una chat estranea non esegue niente",
      "non e' collegata" in finto.ultimo_inviato(),
      finto.ultimo_inviato()[:80])
finto.messaggio(555, "/scollega")
p.passo()
check("/scollega stacca la chat", tg.chat_di(7)[0] == "", tg.chat_di(7)[0])
finto.messaggio(555, "sei ancora li'?")
p.passo()
p.aspetta()
check("dopo /scollega non risponde piu' l'agente", chiamate == [],
      str(chiamate))

print("\n[9] i comandi arrivano a chi sa eseguirli")
finto = FintoTelegram()
visti = []
p, _chiamate = ponte(finto, comandi=comandi_finti(visti))
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
p.passo()
finto.messaggio(555, "/stato")
p.passo()
check("/stato viene delegato",
      visti and visti[-1] == ("stato", ""), str(visti))
finto.messaggio(555, "/modello gpt-4o-mini")
p.passo()
check("/modello passa il nome",
      visti[-1] == ("modello", "gpt-4o-mini"), str(visti))
check("e la risposta di chi esegue torna in chat",
      "modello fatto" in finto.ultimo_inviato(),
      finto.ultimo_inviato()[:60])
finto.messaggio(555, "/pippo")
p.passo()
check("un comando sconosciuto lo dice",
      "non riconosciuto" in finto.ultimo_inviato(),
      finto.ultimo_inviato()[:60])

print("\n[10] un ponte senza comandi non finge di averli")
finto = FintoTelegram()
p, _chiamate = ponte(finto)
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
p.passo()
finto.messaggio(555, "/stop")
p.passo()
check("senza sessione /stop lo dice invece di scollegare",
      "non disponibile" in finto.ultimo_inviato(),
      finto.ultimo_inviato()[:60])
check("e la chat resta collegata", tg.chat_di(7)[0] == "555",
      tg.chat_di(7)[0])

print("\n[11] un turno che esplode non lascia l'utente senza niente")


def rotto(_testo, _allegati=None, _avanzamento=None):
    raise RuntimeError("provider giu'")


finto = FintoTelegram()
api = tg.Api(TOKEN, trasporto=finto, scarica=finto.scarica)
p3 = tg.Ponte(7, "Prova", api, rotto, attesa=0)
p3.passo()
finto.messaggio(555, "fai qualcosa")
p3.passo()
p3.aspetta()
check("l'errore torna in chat invece di sparire",
      "provider giu'" in finto.ultimo_inviato(),
      finto.ultimo_inviato()[:80])

print("\n[12] cosa c'e' dentro un messaggio")
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
foto = tg.allegato_da({"photo": [{"file_id": "p1", "file_size": 10},
                                 {"file_id": "p2", "file_size": 900}],
                       "caption": "che e' questo?"})
check("di una foto si prende la versione piu' grande",
      foto and foto["file_id"] == "p2", str(foto))
check("e la didascalia viaggia con lei",
      foto and foto["didascalia"] == "che e' questo?", str(foto))
check("una foto senza didascalia non inventa un testo",
      tg.allegato_da({"photo": [{"file_id": "p1"}]})["didascalia"] == "")
check("un vocale si riconosce",
      tg.allegato_da({"voice": {"file_id": "v1", "file_size": 300}}
                     )["tipo"] == "voce")
check("un documento porta il suo nome",
      tg.allegato_da({"document": {"file_id": "d1", "file_size": 5,
                                   "file_name": "note.txt"}})["nome"]
      == "note.txt")
check("un messaggio di solo testo non ha allegati",
      tg.allegato_da({"text": "ciao"}) is None)
check("un array di foto vuoto non e' una foto",
      tg.allegato_da({"photo": []}) is None)

print("\n[13] una foto arriva all'agente come immagine")
finto = FintoTelegram()
finto.contenuto = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 60)
p, chiamate = ponte(finto)
p.passo()
finto.allegato(555, "photo", [{"file_id": "p9", "file_size": 68}],
               didascalia="descrivi questa foto")
p.passo()
p.aspetta()
check("il turno parte con la didascalia",
      chiamate == ["descrivi questa foto"], str(chiamate))
allegati = p.allegati_visti[-1]
check("e con un allegato immagine",
      len(allegati) == 1 and getattr(allegati[0], "kind", "") == "image",
      str([getattr(a, "kind", "?") for a in allegati]))
check("il file e' stato chiesto a Telegram", finto.file_chiesti == ["p9"],
      str(finto.file_chiesti))

print("\n[14] un documento di testo diventa testo nel messaggio")
finto = FintoTelegram()
finto.contenuto = "prezzo 12,50\nprezzo 30,00".encode("utf-8")
p, chiamate = ponte(finto)
p.passo()
finto.allegato(555, "document", {"file_id": "d9", "file_size": 25,
                                 "file_name": "prezzi.txt"})
p.passo()
p.aspetta()
check("senza didascalia la richiesta nomina il file",
      chiamate and "prezzi.txt" in chiamate[0], str(chiamate))
allegati = p.allegati_visti[-1]
check("il documento arriva come testo",
      len(allegati) == 1 and getattr(allegati[0], "kind", "") == "testo",
      str([getattr(a, "kind", "?") for a in allegati]))

print("\n[15] un vocale, quando il motore vocale non c'e'")
disponibile_vero = stt.disponibile
stt.disponibile = lambda: False
finto = FintoTelegram()
p, chiamate = ponte(finto)
p.passo()
finto.allegato(555, "voice", {"file_id": "v9", "file_size": 40})
p.passo()
p.aspetta()
check("senza motore vocale il turno non parte", chiamate == [], str(chiamate))
check("e si dice dove si installa",
      "Opzioni" in finto.ultimo_inviato(), finto.ultimo_inviato()[:90])

print("\n[16] un vocale, quando il motore vocale c'e'")
stt.disponibile = lambda: True
trascrivi_vero = stt.trascrivi
stt.trascrivi = lambda dati, nome="": "accendi la luce dello studio"
finto = FintoTelegram()
finto.contenuto = b"OggS" + b"\x00" * 40
p, chiamate = ponte(finto)
p.passo()
finto.allegato(555, "voice", {"file_id": "v8", "file_size": 44})
p.passo()
p.aspetta()
check("il vocale arriva all'agente come testo",
      chiamate == ["accendi la luce dello studio"], str(chiamate))
check("e senza allegati", p.allegati_visti[-1] == [],
      str(p.allegati_visti[-1]))
stt.disponibile = disponibile_vero
stt.trascrivi = trascrivi_vero

print("\n[17] quello che non si scarica, si dice")
finto = FintoTelegram()
p, chiamate = ponte(finto)
p.passo()
finto.allegato(555, "video", {"file_id": "vid", "file_size": 100})
p.passo()
p.aspetta()
check("un video non fa partire un turno", chiamate == [], str(chiamate))
check("e la risposta dice perche'",
      "video" in finto.ultimo_inviato().lower(),
      finto.ultimo_inviato()[:80])
finto.allegato(555, "document", {"file_id": "big", "file_size": 50 << 20,
                                 "file_name": "enorme.bin"})
p.passo()
p.aspetta()
check("un file oltre il limite non si scarica",
      "big" not in finto.file_chiesti, str(finto.file_chiesti))
check("e lo dice con i numeri",
      "MB" in finto.ultimo_inviato(), finto.ultimo_inviato()[:80])

print("\n[18] il messaggio di stato: uno solo, aggiornato, poi tolto")
primo_vero, intervallo_vero = tg.PRIMO_AVVISO, tg.INTERVALLO_PROGRESSO
tg.PRIMO_AVVISO, tg.INTERVALLO_PROGRESSO = 0.0, 10.0


def turno_che_racconta(_testo, _allegati=None, avanzamento=None):
    avanzamento("sto leggendo i test")
    avanzamento("sto leggendo i test, ancora")
    return "fatto"


finto = FintoTelegram()
p, _chiamate = ponte(finto, turno=turno_che_racconta)
p.passo()
finto.messaggio(555, "lavora")
p.passo()
p.aspetta()
check("lo stato e' un messaggio solo",
      finto.testi().count("sto leggendo i test") == 1, str(finto.testi()))
check("e non e' stato modificato a raffica", finto.modifiche == [],
      str(finto.modifiche))
check("alla fine il messaggio di stato sparisce",
      finto.cancellati == [1], str(finto.cancellati))
check("e la risposta resta", finto.testi()[-1] == "fatto", str(finto.testi()))

tg.INTERVALLO_PROGRESSO = 0.0


def turno_lungo(_testo, _allegati=None, avanzamento=None):
    avanzamento("sto leggendo i test")
    avanzamento("sto leggendo i test, ancora")
    return "fatto"


finto = FintoTelegram()
p, _chiamate = ponte(finto, turno=turno_lungo)
p.passo()
finto.messaggio(555, "lavora")
p.passo()
p.aspetta()
check("con il tempo che passa lo stato viene riscritto",
      finto.modifiche and finto.modifiche[-1][1] == "sto leggendo i test, ancora",
      str(finto.modifiche))
check("sempre sullo stesso messaggio",
      finto.modifiche[-1][0] == 1, str(finto.modifiche))
tg.PRIMO_AVVISO, tg.INTERVALLO_PROGRESSO = primo_vero, intervallo_vero

print("\n[19] un messaggio durante un turno e' una guida")
in_corso = threading.Event()
partito = threading.Event()


def turno_bloccato(_testo, _allegati=None, _avanzamento=None):
    partito.set()
    in_corso.wait(timeout=5)
    return "finito"


finto = FintoTelegram()
visti = []
p, chiamate = ponte(finto, comandi=comandi_finti(visti),
                    turno=turno_bloccato)
p.passo()
finto.messaggio(555, "prima richiesta")
p.passo()
check("il turno parte subito", partito.wait(timeout=5) is True)
check("e il ponte sa di essere occupato", p.occupato is True)
finto.messaggio(555, "guarda anche il file B")
p.passo()
check("il testo in piu' diventa una guida, non un secondo turno",
      ("steer", "guarda anche il file B") in visti, str(visti))
check("e non parte un secondo turno", chiamate == ["prima richiesta"],
      str(chiamate))
in_corso.set()
p.aspetta()
check("il turno finisce quando lo lasci andare", p.occupato is False)
check("la sua risposta arriva in chat",
      "finito" in finto.testi(), str(finto.testi()))

print("\n[20] il modulo a bottoni: si manda, si tocca, si riscrive")
finto = FintoTelegram()
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
menu_servizi = {"testo": "Modello: gpt-4o-mini (openrouter)\n"
                         "Scegli il servizio:",
                "tastiera": [[{"testo": "OpenRouter",
                                "dati": "s:openrouter"}],
                             [{"testo": "Groq", "dati": "s:groq"}]]}
menu_modelli = {"testo": "Groq · 2 modelli",
                "tastiera": [[{"testo": "llama-3.3-70b",
                                "dati": "m:groq:0"}]]}
visti_menu = []


def comandi_menu(nome, argomento=""):
    visti_menu.append((nome, argomento))
    if argomento == "cb:s:groq":
        return menu_modelli
    if argomento == "cb:m:groq:0":
        return "Modello cambiato in llama-3.3-70b."
    return menu_servizi


p, _chiamate = ponte(finto, comandi=comandi_menu)
p.passo()
finto.messaggio(555, "/modello")
p.passo()
markup = finto.markup[-1]
check("il menu arriva con dei pulsanti", "inline_keyboard" in markup, cp(markup))
check("i servizi sono i pulsanti",
      "s:openrouter" in markup and "s:groq" in markup, cp(markup))
check("e il testo dice cosa scegliere",
      "Scegli il servizio" in finto.testi()[-1], finto.testi()[-1])

prima = len(finto.modifiche)
finto.tocco(555, "s:groq", message_id=42)
p.passo()
check("il tocco riceve risposta: la rotellina si chiude",
      bool(finto.callback_risposti), str(finto.callback_risposti))
check("e il messaggio si riscrive invece di mandarne un altro",
      len(finto.modifiche) == prima + 1
      and finto.modifiche[-1][0] == 42, str(finto.modifiche[-1:]))
check("con dentro i modelli del servizio scelto",
      "m:groq:0" in finto.markup[-1], cp(finto.markup[-1]))
check("il tocco arriva al comando giusto",
      ("modello", "cb:s:groq") in visti_menu, str(visti_menu))

finto.tocco(555, "m:groq:0", message_id=42)
p.passo()
check("toccare un modello lo applica",
      ("modello", "cb:m:groq:0") in visti_menu, str(visti_menu))
check("la conferma arriva nello stesso messaggio",
      "Modello cambiato" in finto.modifiche[-1][1], str(finto.modifiche[-1]))
check("e i bottoni spariscono, cosi' non si tocca due volte",
      '"inline_keyboard": []' in finto.markup[-1], cp(finto.markup[-1]))

prima = len(finto.modifiche)
finto.tocco(999, "s:groq")
p.passo()
check("un tocco da una chat non collegata non cambia niente",
      len(finto.modifiche) == prima, str(finto.modifiche[prima:]))
check("ma lo dice a chi ha toccato",
      "non e' collegata" in finto.callback_risposti[-1][1],
      str(finto.callback_risposti[-1]))

p2, _ = ponte(finto)
p2.passo()
finto.tocco(555, "s:groq")
p2.passo()
check("un ponte senza comandi non esplode su un tocco",
      "Modulo non disponibile" in finto.callback_risposti[-1][1],
      str(finto.callback_risposti[-1]))

print("\n[21] i collegamenti dei bot eliminati si tolgono")
tg.salva_token(99, TOKEN)
quanti = tg.pulisci(bot_validi=[])
check("un collegamento senza bot viene tolto", quanti >= 1, str(quanti))
check("e il token sparisce con lui", tg.token_di(99) == "")

print()
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("falliti:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
