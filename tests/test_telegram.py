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
        # I file che il ponte manda passano da un trasporto multipart
        # separato, quindi si registrano a parte dalle chiamate JSON.
        self.file_inviati = []

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

    def allegato(self, chat_id, campo, voce, didascalia="", nome="prova",
                 gruppo=""):
        """Un messaggio con un file dentro, come lo manda Telegram."""
        self.ultimo_id += 1
        messaggio = {"chat": {"id": chat_id, "username": nome},
                     campo: voce}
        if didascalia:
            messaggio["caption"] = didascalia
        if gruppo:
            # Un album: ogni foto e' un aggiornamento suo, legato agli altri
            # solo da questo identificativo.
            messaggio["media_group_id"] = gruppo
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

    def carica(self, url, campi, campo_file, allegato, secondi):
        nome, dati, tipo = allegato
        metodo = url.rsplit("/", 1)[-1]
        self.chiamate.append((metodo, dict(campi)))
        self.file_inviati.append({"metodo": metodo, "campo": campo_file,
                                  "nome": nome, "byte": len(dati),
                                  "tipo": tipo,
                                  "didascalia": campi.get("caption") or ""})
        return {"ok": True,
                "result": {"message_id": 900 + len(self.file_inviati)}}

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


def ponte(finto, risposte=None, bot_id=7, comandi=None, turno=None,
          tocco=None, risposta=None):
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

    api = tg.Api(TOKEN, trasporto=finto, scarica=finto.scarica,
                 carica=finto.carica)
    p = tg.Ponte(bot_id, "Prova", api, finto_turno, comandi=comandi,
                 tocco=tocco, risposta=risposta, attesa=0)
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

print("\n[18b] le azioni sono messaggi nuovi, e restano")
primo_vero, intervallo_vero = tg.PRIMO_AVVISO, tg.INTERVALLO_PROGRESSO
azione_vera = tg.INTERVALLO_AZIONE
tg.PRIMO_AVVISO, tg.INTERVALLO_PROGRESSO, tg.INTERVALLO_AZIONE = 0.0, 10.0, 0.0


def turno_con_azioni(_testo, _allegati=None, avanzamento=None):
    avanzamento("sto leggendo i test", "\U0001f6e0 bash \u00b7 pytest")
    avanzamento("sto leggendo i test, ancora",
               "\U0001f6e0 read \u00b7 orchestra/app.py")
    return "fatto"


finto = FintoTelegram()
p, _chiamate = ponte(finto, turno=turno_con_azioni)
p.passo()
finto.messaggio(555, "lavora")
p.passo()
p.aspetta()
testi = finto.testi()
# Il segno del tool e' un'emoji: nei confronti si toglie, perche' la
# console di Windows non sa stamparla (cp1252).
segno = "\U0001f6e0 "
azioni = [t for t in testi if t.startswith(segno)]
check("ogni azione e' un messaggio suo",
      sum(1 for t in azioni if "pytest" in t) == 1
      and sum(1 for t in azioni if "app.py" in t) == 1,
      str([t.replace(segno, "") for t in azioni]))
check("e le azioni restano in chat", len(azioni) == 2,
      str([t.replace(segno, "") for t in azioni]))
check("il pensiero non le porta con se' nel messaggio riscritto",
      finto.modifiche == [], str(finto.modifiche))
check("la sintesi sparisce, le azioni no",
      len(finto.cancellati) == 1 and len(azioni) == 2,
      f"cancellati={finto.cancellati} azioni={len(azioni)}")
check("la risposta resta l'ultima cosa", testi[-1] == "fatto",
      str(testi[-1]))

# Due azioni partite insieme e un turno che finisce subito: la coda
# non si perde, e non diventa una raffica di messaggi.
tg.INTERVALLO_AZIONE = 10.0

finto = FintoTelegram()
p, _chiamate = ponte(finto, turno=turno_con_azioni)
p.passo()
finto.messaggio(555, "lavora")
p.passo()
p.aspetta()
azioni = [t for t in finto.testi() if t.startswith(segno)]
check("le azioni rimaste in coda partono insieme",
      len(azioni) == 1 and "pytest" in azioni[0] and "app.py" in azioni[0],
      str([t.replace(segno, "") for t in azioni]))
tg.PRIMO_AVVISO, tg.INTERVALLO_PROGRESSO = primo_vero, intervallo_vero
tg.INTERVALLO_AZIONE = azione_vera

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

print("\n[22] un permesso arriva in chat, e si risponde con un pulsante")
finto = FintoTelegram()
tg.salva_token(7, TOKEN)
tg.imposta_chat(7, 555, "adver")
decisi = []


def tocco_finto(dati):
    decisi.append(dati)
    return "Permesso concesso per sempre."


p, _ = ponte(finto, tocco=tocco_finto)
p.passo()
tg.pulisci_sospesi(7)
arrivato = p.chiedi_in_chat("permission_request", {
    "id": "p1", "percorso": "D:/Documenti/x.txt", "azione": "leggere",
    "dettaglio": "", "motivo": "fuori dalla cartella di lavoro"})
check("il permesso si manda in chat", arrivato is True)
check("con il percorso scritto per esteso",
      "D:/Documenti/x.txt" in finto.ultimo_inviato(), finto.ultimo_inviato())
check("e quattro pulsanti, come nella finestra",
      all(("d:" + c + ":") in finto.markup[-1] for c in "uswm"),
      cp(finto.markup[-1]))
voce = tg.sospeso(7)
check("la richiesta resta aperta finche' non si risponde",
      voce is not None, str(voce))

finto.tocco(555, "d:w:" + voce["token"], message_id=901)
p.passo()
check("il tocco arriva a chi sa rispondere",
      decisi == ["d:w:" + voce["token"]], str(decisi))
check("e il messaggio dice com'e' finita",
      "concesso per sempre" in finto.modifiche[-1][1],
      cp(finto.modifiche[-1]))
check("senza lasciare pulsanti vivi",
      '"inline_keyboard": []' in finto.markup[-1], cp(finto.markup[-1]))
# Il ponte non chiude la richiesta: chiude chi sa rispondere, che e' anche
# l'unico a poter controllare che il token sia quello giusto. Qui il
# risponditore finto non chiude, quindi la richiesta resta aperta — ed e'
# esattamente quello che deve succedere.
check("il ponte non decide e non chiude: lo fa chi risponde",
      tg.sospeso(7) is not None, str(tg.sospeso(7)))
tg.pulisci_sospesi(7)

print("\n[23] una domanda: si tocca un'opzione, o si scrive")
finto = FintoTelegram()
tg.imposta_chat(7, 555, "adver")
scelte = []
risposte_scritte = []


def tocco_domanda(dati):
    scelte.append(dati)
    return "Risposta inviata: name"


def risposta_vera(testo):
    """Come la webapp: consegna la risposta e chiude la domanda."""
    risposte_scritte.append(testo)
    tg.chiudi(7)
    return "Risposta inviata."


p, _ = ponte(finto, tocco=tocco_domanda, risposta=risposta_vera)
p.passo()
tg.pulisci_sospesi(7)
p.chiedi_in_chat("domanda_utente", {
    "id": "d1", "tipo": "domanda", "testo": "Quale nome preferisci?",
    "opzioni": ["nome", "name"]})
check("la domanda si manda in chat",
      "Quale nome preferisci?" in finto.ultimo_inviato(),
      cp(finto.ultimo_inviato()))
voce = tg.sospeso(7)
check("con un pulsante per opzione, e il token dentro",
      ("r:1:" + voce["token"]) in finto.markup[-1], cp(finto.markup[-1]))
check("e dice che si puo' scrivere la risposta",
      "scriv" in finto.ultimo_inviato(), cp(finto.ultimo_inviato()))
check("la domanda e' quella che il ponte conosce",
      voce["tipo"] == "domanda" and voce["opzioni"] == ["nome", "name"], str(voce))

finto.tocco(555, "r:1:" + voce["token"], message_id=903)
p.passo()
check("toccare un'opzione la consegna",
      scelte == ["r:1:" + voce["token"]], str(scelte))

# La risposta scritta: e' la risposta, non una guida al turno.
tg.sospendi(7, {"tipo": "domanda", "id": "d2", "token": "abcd",
                "opzioni": ["si'"], "message_id": 904, "chat": "555"})
finto.messaggio(555, "meglio nome")
p.passo()
check("scrivere mentre una domanda e' aperta e' la risposta",
      risposte_scritte == ["meglio nome"], str(risposte_scritte))
check("e non un nuovo turno", len(p.allegati_visti) == 0, str(p.allegati_visti))
check("e il modulo si chiude diventando un promemoria della risposta",
      finto.modifiche[-1][0] == 904
      and "Risposta: meglio nome" in finto.modifiche[-1][1],
      cp(finto.modifiche[-1:]))

# Un permesso aperto: il testo non decide, e lo si dice.
finto2 = FintoTelegram()
chiamate_risposta = []
p2, _ = ponte(finto2, risposta=lambda t: chiamate_risposta.append(t) or "no")
p2.passo()
tg.sospendi(7, {"tipo": "permesso", "id": "p3", "token": "efgh",
                "message_id": 905, "chat": "555"})
finto2.messaggio(555, "si'")
p2.passo()
check("con un permesso aperto il testo arriva a chi risponde",
      chiamate_risposta == ["si'"], str(chiamate_risposta))
check("e la richiesta resta aperta, perche' un si' non dice per quanto vale",
      tg.sospeso(7) is not None, "la richiesta si e' chiusa da sola")
tg.pulisci_sospesi(7)

print("\n[24] i file del turno tornano in chat")
finto = FintoTelegram()
tg.imposta_chat(7, 555, "adver")
cartella = tempfile.mkdtemp(prefix="orch_file_")
percorsi = {}
for nome, contenuto in (("report.pdf", b"%PDF-1.4 finto"),
                        ("foto.png", b"\x89PNG finto"),
                        ("script.py", b"print(1)")):
    percorso = os.path.join(cartella, nome)
    with open(percorso, "wb") as f:
        f.write(contenuto)
    percorsi[nome] = percorso


def turno_con_file(testo, allegati, avanzamento):
    return {"testo": "Fatto: ecco il report.",
            "file": [{"percorso": percorsi["report.pdf"], "nome": "report.pdf"},
                     {"percorso": percorsi["foto.png"], "nome": "foto.png"}]}


p, _ = ponte(finto, turno=turno_con_file)
p.passo()
finto.messaggio(555, "fammi il report")
p.passo()
check("il turno e' finito prima di guardare",
      p.aspetta(5), "il turno non e' finito")
check("il testo della risposta arriva comunque",
      "ecco il report" in finto.testi()[-1], cp(finto.testi()[-1:]))
check("e i file vengono allegati",
      [f["nome"] for f in finto.file_inviati] == ["report.pdf", "foto.png"],
      str(finto.file_inviati))
check("un PDF parte come documento",
      finto.file_inviati[0]["metodo"] == "sendDocument"
      and finto.file_inviati[0]["campo"] == "document",
      str(finto.file_inviati[0]))
check("un'immagine parte come foto, cosi' si vede dentro la chat",
      finto.file_inviati[1]["metodo"] == "sendPhoto",
      str(finto.file_inviati[1]))
check("con i byte veri del file", finto.file_inviati[0]["byte"] > 0,
      str(finto.file_inviati[0]))
check("e il tipo giusto",
      finto.file_inviati[0]["tipo"] == "application/pdf",
      finto.file_inviati[0]["tipo"])

# Troppo grande: non si manda, ma si dice dove sta.
finto.file_inviati = []
grande = os.path.join(cartella, "enorme.pdf")
with open(grande, "wb") as f:
    f.write(b"x" * (tg.MASSIMO_INVIO + 10))
p._manda_file("555", [{"percorso": grande, "nome": "enorme.pdf"}])
check("un file oltre il limite non si manda", finto.file_inviati == [],
      str(finto.file_inviati))
check("ma si dice dove sta",
      "enorme.pdf" in finto.testi()[-1] and cartella in finto.testi()[-1],
      cp(finto.testi()[-1]))

# Un turno che scrive otto file: ne arrivano cinque, e lo dice.
finto.file_inviati = []
molti = []
for i in range(8):
    percorso = os.path.join(cartella, "doc" + str(i) + ".pdf")
    with open(percorso, "wb") as f:
        f.write(b"%PDF")
    molti.append({"percorso": percorso, "nome": "doc" + str(i) + ".pdf"})
p._manda_file("555", molti)
check("al massimo cinque allegati per turno", len(finto.file_inviati) == 5,
      str(len(finto.file_inviati)))
check("e dice quanti ne restano fuori", "Altri 3" in finto.testi()[-1],
      cp(finto.testi()[-1]))

print("\n[25] quali file del turno vale la pena allegare")
adesso = time.time()
vecchio = os.path.join(cartella, "vecchio.pdf")
with open(vecchio, "wb") as f:
    f.write(b"%PDF vecchio")
os.utime(vecchio, (adesso - 3600, adesso - 3600))
dentro_moduli = os.path.join(cartella, "node_modules")
os.makedirs(dentro_moduli, exist_ok=True)
with open(os.path.join(dentro_moduli, "dentro.pdf"), "wb") as f:
    f.write(b"%PDF")
trovati = tg.file_del_turno(cartella, adesso - 60, massimo=99)
nomi = [t["nome"] for t in trovati]
check("i file scritti durante il turno ci sono", "report.pdf" in nomi, str(nomi))
check("quelli di prima no", "vecchio.pdf" not in nomi, str(nomi))
check("il codice non e' un allegato", "script.py" not in nomi, str(nomi))
check("e non si guarda dentro node_modules", "dentro.pdf" not in nomi, str(nomi))
check("un turno senza file non allega niente",
      tg.file_del_turno(os.path.join(cartella, "manca"), adesso) == [])
# I file di stato di Orchestra non sono lavoro del turno: memory.md lo
# riscrive l'agente ogni volta che lo legge, e ritrovarselo allegato a ogni
# risposta riempie la chat di cose che nessuno ha chiesto.
memoria = os.path.join(cartella, "memory.md")
with open(memoria, "wb") as f:
    f.write(b"- vuole il poster corretto\n")
nomi = [t["nome"] for t in tg.file_del_turno(cartella, adesso - 60, massimo=99)]
check("memory.md non si allega", "memory.md" not in nomi, str(nomi))
check("ma il report del turno si'", "report.pdf" in nomi, str(nomi))

print("\n[27] un album: tre foto insieme sono una richiesta sola")
finto = FintoTelegram()
finto.contenuto = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 60)
p, chiamate = ponte(finto)
p.passo()
# L'attesa resta lunga per tutto il test: a chiudere l'album ci pensa la
# chiamata esplicita, non l'orologio. Un test che dorme e' un test che
# prima o poi fallisce da solo.
attesa_vera = tg.ATTESA_ALBUM
tg.ATTESA_ALBUM = 30.0
try:
    finto.allegato(555, "photo", [{"file_id": "a1", "file_size": 68}],
                   didascalia="metti il logo nel poster", gruppo="g1")
    p.passo()
    finto.allegato(555, "photo", [{"file_id": "a2", "file_size": 68}],
                   gruppo="g1")
    p.passo()
    finto.allegato(555, "photo", [{"file_id": "a3", "file_size": 68}],
                   gruppo="g1")
    p.passo()
    p.aspetta()
    check("nessun turno prima dell'ultima foto", chiamate == [], str(chiamate))
    with p._album_lock:
        voce = p._album["g1"]
        voce["timer"].cancel()
        voce["visto"] = 0.0
    p._chiudi_album("g1")
    p.aspetta()
finally:
    tg.ATTESA_ALBUM = attesa_vera

check("parte un turno solo", len(chiamate) == 1, str(chiamate))
check("con la didascalia dell'album",
      chiamate == ["metti il logo nel poster"], str(chiamate))
allegati = p.allegati_visti[-1] if p.allegati_visti else []
check("e tutte e tre le foto", len(allegati) == 3, str(len(allegati)))
check("chieste a Telegram una per una",
      finto.file_chiesti == ["a1", "a2", "a3"], str(finto.file_chiesti))
check("l'album non resta appeso", not p._album, str(list(p._album)))

print("\n[21] i collegamenti dei bot eliminati si tolgono")
tg.salva_token(99, TOKEN)
quanti = tg.pulisci(bot_validi=[])
check("un collegamento senza bot viene tolto", quanti >= 1, str(quanti))
check("e il token sparisce con lui", tg.token_di(99) == "")

print("\n[26] il vocale: i campioni li decodifica Orchestra")
# faster-whisper 1.2.1 chiama av.open(metadata_errors=...), che PyAV 19
# ha tolto: ogni vocale moriva su un TypeError che non dipendeva dal
# file. Ora l'audio lo apriamo noi, senza quel parametro, e al modello
# arrivano campioni gia' decodificati (che non passano da quel codice).
import struct  # noqa: E402
import tempfile  # noqa: E402
import wave  # noqa: E402

ha_av = True
try:
    import av  # noqa: F401
    import numpy  # noqa: F401
except Exception:  # noqa: BLE001
    ha_av = False

if not ha_av:
    print("  --   av/numpy assenti: la decodifica non e' verificabile qui")
else:
    cartella_voce = tempfile.mkdtemp(prefix="orch_stt_")
    percorso_voce = os.path.join(cartella_voce, "voce.wav")
    with wave.open(percorso_voce, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", (i % 200) - 100)
                               for i in range(16000)))
    campioni = stt._campioni(percorso_voce)
    check("un secondo di audio sono 16000 campioni float32",
          len(campioni) == 16000 and str(campioni.dtype) == "float32",
          f"{len(campioni)} {campioni.dtype}")

    class ModelloFinto:
        sorgente = None

        def transcribe(self, sorgente, **_kw):
            self.sorgente = sorgente
            return [], None

    modello = ModelloFinto()
    disponibile_vero = stt.disponibile
    modello_vero = stt._modello
    stt.disponibile = lambda: True
    stt._modello = lambda: modello
    try:
        with open(percorso_voce, "rb") as f:
            dati_voce = f.read()
        stt.trascrivi(dati_voce, "voce.wav")
    finally:
        stt.disponibile = disponibile_vero
        stt._modello = modello_vero
    check("al modello arrivano campioni, non un percorso da riaprire",
          not isinstance(modello.sorgente, (str, bytes)),
          type(modello.sorgente).__name__)

print()
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("falliti:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
