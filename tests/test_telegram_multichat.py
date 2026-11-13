"""Piu' persone sullo stesso bot Telegram.

Prima il collegamento era una colonna sola (`telegram.chat_id`): il
secondo `/start` sovrascriveva il primo, e la persona di prima smetteva
di ricevere risposte senza che nessuno le dicesse niente. Qui si verifica
che l'elenco sia davvero un elenco, che staccare non stacchi gli altri, e
che le risposte vadano a chi ha chiesto — non alla prima chat dell'elenco,
che con due persone e' la persona sbagliata.
"""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# I collegamenti dei test in una cartella usa e getta.
os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orch_multi_")

import orchestra.telegram as tg  # noqa: E402

PASS, FAIL = [], []
TOKEN = "123456789:" + "a" * 35


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" -- {dettaglio}" if dettaglio and not cond else ""))


class Finto:
    """Un Telegram che risponde come l'API, senza uscire dalla macchina."""

    def __init__(self) -> None:
        self.inviati: list[tuple[str, str]] = []
        self.in_attesa: list[dict] = []
        self.menu: list[dict] = []
        self.ultimo_id = 1000

    def messaggio(self, chat_id, testo, nome="prova"):
        self.ultimo_id += 1
        self.in_attesa.append({
            "update_id": self.ultimo_id,
            "message": {"chat": {"id": chat_id, "username": nome},
                        "text": testo},
        })
        return self.ultimo_id

    def a(self, chat_id):
        return [t for c, t in self.inviati if c == str(chat_id)]

    def a_chi(self):
        return [c for c, _t in self.inviati]

    def __call__(self, url, dati, secondi):
        metodo = url.rsplit("/", 1)[-1]
        if metodo == "sendMessage":
            self.inviati.append((str(dati.get("chat_id")),
                                 str(dati.get("text") or "")))
            return {"ok": True, "result": {"message_id": len(self.inviati)}}
        if metodo == "setMyCommands":
            self.menu.append(dict(dati))
            return {"ok": True, "result": True}
        if metodo == "deleteMyCommands":
            return {"ok": True, "result": True}
        if metodo == "editMessageText":
            self.inviati.append((str(dati.get("chat_id")),
                                 str(dati.get("text") or "")))
            return {"ok": True, "result": True}
        if metodo in ("sendChatAction", "deleteWebhook", "deleteMessage",
                      "answerCallbackQuery"):
            return {"ok": True, "result": True}
        if metodo == "getUpdates":
            offset = dati.get("offset")
            pronti = self.in_attesa if offset is None else [
                u for u in self.in_attesa
                if int(u["update_id"]) >= int(offset)]
            return {"ok": True, "result": pronti}
        raise AssertionError(f"metodo inatteso: {metodo}")


def ponte(finto, bot_id, turno=None):
    def turno_finto(testo, allegati=None, avanzamento=None):
        if turno is not None:
            return turno(testo)
        return f"risposta a: {testo}"

    api = tg.Api(TOKEN, trasporto=finto, scarica=lambda p, m: b"",
                 carica=lambda *a, **k: {"ok": True, "result": {}})
    return tg.Ponte(bot_id, "Prova", api, turno_finto, attesa=0,
                    comandi=lambda nome, arg="", chat="": f"{nome} fatto")


# ------------------------------------------------------- l'elenco delle chat
print("\n[1] Due chat sullo stesso bot, e nessuna stacca l'altra")

tg.salva_token(21, TOKEN)
primo = tg.imposta_chat(21, 111, "Anna")
secondo = tg.imposta_chat(21, 222, "Bruno")
check("il primo collegamento riesce", primo.get("ok") is True, str(primo))
check("anche il secondo, senza togliere il primo",
      secondo.get("ok") is True, str(secondo))
elenco = tg.chat_collegate(21)
check("l'elenco ha tutte e due", len(elenco) == 2, str(elenco))
check("la prima collegata resta la principale",
      tg.chat_di(21) == ("111", "Anna"), str(tg.chat_di(21)))
check("si puo' scrivere da tutte e due",
      tg.chat_collegata(21, 111) and tg.chat_collegata(21, 222))
check("e da una terza no", not tg.chat_collegata(21, 333))
info = tg.stato(21)
check("lo stato dice quante sono", info.get("chat_quante") == 2, str(info))
check("e la riga del pannello non nasconde le altre",
      str(info.get("chat")).endswith("(+1)"), str(info.get("chat")))
check("il pannello riceve l'elenco", len(info.get("chats") or []) == 2,
      str(info.get("chats")))

tg.imposta_chat(21, 111, "Anna Rossi")
check("ricollegare la stessa chat non la duplica",
      len(tg.chat_collegate(21)) == 2, str(tg.chat_collegate(21)))
check("ma aggiorna il nome",
      tg.chat_collegate(21)[0]["nome"] == "Anna Rossi",
      str(tg.chat_collegate(21)))

print("\n[2] Quante chat al massimo, e cosa si dice alla sesta")

tg.salva_token(22, TOKEN)
for i in range(tg.MASSIMO_CHAT):
    tg.imposta_chat(22, 500 + i, f"persona {i}")
check("il tetto e' quello dichiarato",
      len(tg.chat_collegate(22)) == tg.MASSIMO_CHAT,
      str(len(tg.chat_collegate(22))))
sesta = tg.imposta_chat(22, 999, "di troppo")
check("la sesta viene rifiutata", sesta.get("ok") is False, str(sesta))
check("e non entra nell'elenco",
      not tg.chat_collegata(22, 999), str(tg.chat_collegate(22)))
check("il rifiuto dice come liberare un posto",
      "/scollega" in str(sesta.get("errore")), str(sesta.get("errore")))

print("\n[3] Staccare: una sola, o tutte")

tg.imposta_chat(21, 333, "Carla")
tg.dimentica_chat(21, 111)
check("via una, le altre restano",
      len(tg.chat_collegate(21)) == 2, str(tg.chat_collegate(21)))
check("e la principale diventa quella dopo",
      tg.chat_di(21)[0] == "222", str(tg.chat_di(21)))
tg.dimentica_chat(21)
check("senza nome si stacca tutto", tg.chat_collegate(21) == [],
      str(tg.chat_collegate(21)))
check("e il bot non risulta collegato", tg.stato(21)["collegato"] is False,
      str(tg.stato(21)))

print("\n[4] Una chat vuota non e' una chat")

tg.salva_token(23, TOKEN)
tg.imposta_chat(23, 111, "Anna")
vuota = tg.imposta_chat(23, "", "")
check("viene rifiutata", vuota.get("ok") is False, str(vuota))
check("e non crea una riga fantasma",
      [c["chat_id"] for c in tg.chat_collegate(23)] == ["111"],
      str(tg.chat_collegate(23)))

print("\n[5] Il collegamento che c'era prima non si perde")

# Un database di prima dell'aggiornamento: la chat sta nella colonna, e
# l'elenco non esiste ancora. La migrazione deve portarla dentro.
tg.salva_token(24, TOKEN)
tg.dimentica_chat(24)
conn = tg._db()
conn.execute("UPDATE telegram SET chat_id = ?, chat_nome = ? WHERE bot_id = ?",
             ("888", "Vecchia", 24))
conn.commit()
tg._db()  # riapre: qui la migrazione gira
check("la chat vecchia entra nell'elenco",
      tg.chat_collegate(24) == [{"chat_id": "888", "nome": "Vecchia"}],
      str(tg.chat_collegate(24)))
check("e resta una sola, non due copie", len(tg.chat_collegate(24)) == 1,
      str(tg.chat_collegate(24)))

# --------------------------------------------------------------- il ponte
print("\n[6] Dal ponte: ognuno riceve la sua risposta")

finto = Finto()
tg.salva_token(25, TOKEN)
tg.imposta_chat(25, 111, "Anna")
tg.imposta_chat(25, 222, "Bruno")
p = ponte(finto, 25)
p.passo()
finto.messaggio(111, "ciao da Anna")
p.passo()
check("la risposta arriva ad Anna", finto.a("111") and
      "ciao da Anna" in finto.a("111")[-1], str(finto.inviati))
check("e non a Bruno", not any("ciao da Anna" in t for t in finto.a("222")),
      str(finto.inviati))
finto.messaggio(222, "ciao da Bruno")
p.passo()
check("la risposta arriva a Bruno", "ciao da Bruno" in finto.a("222")[-1],
      str(finto.inviati))
finto.messaggio(333, "sono un estraneo")
p.passo()
check("un estraneo non ottiene un turno",
      not any("risposta a:" in t for t in finto.a("333")),
      str(finto.inviati))
check("ma gli si spiega che serve il codice",
      any("collegat" in t for t in finto.a("333")), str(finto.a("333")))

print("\n[7] `/start` aggiunge, non sostituisce")

tg.salva_token(26, TOKEN)
tg.imposta_chat(26, 111, "Anna")
finto2 = Finto()
p2 = ponte(finto2, 26)
p2.passo()
codice = tg.nuovo_codice(26)["codice"]
finto2.messaggio(222, "/start " + codice, nome="Bruno")
p2.passo()
check("la seconda persona entra",
      tg.chat_collegata(26, 222), str(tg.chat_collegate(26)))
check("e la prima non viene buttata fuori", tg.chat_collegata(26, 111),
      str(tg.chat_collegate(26)))
check("il messaggio lo dice, invece di far scoprire dopo",
      "altre 1 chat" in finto2.a("222")[-1], str(finto2.a("222"))[-1:])
finto2.messaggio(222, "/start " + codice, nome="Bruno")
p2.passo()
check("un secondo /start dice che sei gia' dentro",
      "gia'" in finto2.a("222")[-1].lower(), str(finto2.a("222"))[-1:])

print("\n[8] `/scollega` stacca solo chi lo scrive")

tg.salva_token(27, TOKEN)
tg.imposta_chat(27, 111, "Anna")
tg.imposta_chat(27, 222, "Bruno")
finto3 = Finto()
p3 = ponte(finto3, 27)
p3.passo()
finto3.messaggio(222, "/scollega", nome="Bruno")
p3.passo()
check("Bruno esce", not tg.chat_collegata(27, 222), str(tg.chat_collegate(27)))
check("Anna resta", tg.chat_collegata(27, 111), str(tg.chat_collegate(27)))
check("e la conferma dice quante restano",
      "Restano 1 chat" in finto3.a("222")[-1], str(finto3.a("222"))[-1:])
finto3.messaggio(222, "ci sono ancora?")
p3.passo()
check("chi e' uscito non ottiene risposte",
      not any("risposta a:" in t for t in finto3.a("222")),
      str(finto3.a("222")))
finto3.messaggio(111, "ci sono io")
p3.passo()
check("chi resta continua a lavorare",
      "risposta a: ci sono io" in finto3.a("111")[-1],
      str(finto3.a("111")[-1:]))

print("\n[9] Domande e risposte differite vanno a chi ha chiesto")

tg.salva_token(28, TOKEN)
tg.imposta_chat(28, 111, "Anna")
tg.imposta_chat(28, 222, "Bruno")
finto4 = Finto()
p4 = ponte(finto4, 28)
p4._chat_turno = "222"
esito = p4.chiedi_in_chat("domanda_utente", {
    "id": "q1", "domanda": "quale dei due?", "opzioni": ["a", "b"]})
check("la domanda parte", esito, str(esito))
check("e va alla chat del turno, non alla principale",
      finto4.a_chi() and finto4.a_chi()[-1] == "222", str(finto4.inviati))
check("la risposta differita fa lo stesso",
      p4.recapita("lavoro finito") and finto4.a_chi()[-1] == "222",
      str(finto4.inviati))
tg.dimentica_chat(28, 222)
check("se nel frattempo la chat e' stata staccata, non si manda",
      p4.recapita("tardi") is False, str(finto4.inviati[-1:]))

print("\n[10] La rotta del pannello revoca una chat sola")

# Dal pannello si vede l'elenco e si revoca una persona: la rotta deve
# accettare `chat_id`, lasciare le altre collegate, e non dire "fatto" se
# la chat non era in elenco (chi clicca su un elenco vecchio revocherebbe
# la persona sbagliata credendo di aver tolto quella giusta).
from types import SimpleNamespace  # noqa: E402

import orchestra.bots as bots_mod  # noqa: E402
import orchestra.rotte_telegram as rt  # noqa: E402


class FintaRotta(rt.RotteTelegram):
    """La rotta senza il server: si guarda cosa risponde, non il socket."""

    def __init__(self):
        self.app = SimpleNamespace(env={}, telegram_attivi=lambda: [])
        self.esiti = []

    def _json(self, dati, stato=200, **_k):
        self.esiti.append((dati, stato))


vecchio_per_id = bots_mod.per_id_agente
bots_mod.per_id_agente = lambda bid: {"id": int(bid), "nome": "Prova"}
try:
    tg.salva_token(29, TOKEN)
    tg.imposta_chat(29, 111, "Anna")
    tg.imposta_chat(29, 222, "Bruno")
    rotta = FintaRotta()
    rotta._r_post_telegram_scollega(
        "/api/telegram/scollega", {"id": 29, "chat_id": 222}, None)
    dati, stato = rotta.esiti[-1]
    check("la rotta risponde ok", dati.get("ok") is True and stato == 200,
          str(dati))
    check("e ha revocato Bruno", not tg.chat_collegata(29, 222),
          str(tg.chat_collegate(29)))
    check("lasciando Anna al suo posto", tg.chat_collegata(29, 111),
          str(tg.chat_collegate(29)))
    check("lo stato tornato al pannello ha ancora una chat",
          (dati.get("stato") or {}).get("chat_quante") == 1,
          str(dati.get("stato")))

    # L'elenco che il pannello disegna arriva dalla lettura, non dalla
    # revoca: se la lettura non portasse `chats`, i pulsanti non
    # esisterebbero affatto.
    vecchio_tutti = bots_mod.tutti
    bots_mod.tutti = lambda: [{"id": 29, "nome": "Prova"}]
    try:
        lettura = FintaRotta()
        lettura._r_get_telegram("/api/telegram", {}, None)
        elenco, _stato = lettura.esiti[-1]
    finally:
        bots_mod.tutti = vecchio_tutti
    voci = {int(v["bot_id"]): v for v in (elenco.get("bots") or [])}
    restanti = [c.get("chat_id") for c in (voci.get(29, {})
                                           .get("chats") or [])]
    check("la lettura del pannello porta l'elenco delle chat",
          restanti == ["111"], str(restanti))

    rotta._r_post_telegram_scollega(
        "/api/telegram/scollega", {"id": 29, "chat_id": 222}, None)
    dati, stato = rotta.esiti[-1]
    check("revocare una chat gia' via non finge di averla tolta",
          stato == 404 and "error" in dati, str((dati, stato)))
    check("e non tocca chi era rimasto", tg.chat_collegata(29, 111),
          str(tg.chat_collegate(29)))

    rotta._r_post_telegram_scollega(
        "/api/telegram/scollega", {"id": 29}, None)
    dati, stato = rotta.esiti[-1]
    check("senza chat_id stacca tutto", tg.chat_collegate(29) == [],
          str(tg.chat_collegate(29)))
    check("e lo dice nella risposta", (dati.get("scollegata") or "") == "",
          str(dati))
finally:
    bots_mod.per_id_agente = vecchio_per_id

print("\n[11] /stop e /nuova dicono che la sessione e' di tutti")

# La sessione e' una per bot, non per chat: con due persone collegate,
# `/stop` ferma il turno di chiunque e `/nuova` azzera la conversazione
# anche all'altra. Non si corregge qui (una sessione per chat e' un altro
# lavoro), ma chi comanda deve saperlo PRIMA di premere invio.
import orchestra.webapp as webapp_mod  # noqa: E402


class SessioneFinta:
    def __init__(self, busy=True):
        self.busy = busy
        self.fermate = 0
        self.azzerate = 0

    def cancel(self):
        self.fermate += 1

    def reset(self):
        self.azzerate += 1


class AppFinta(webapp_mod.OrchestraApp):
    """La webapp senza __init__: qui interessano i comandi, non l'avvio."""

    def __init__(self, sess):
        self.env = {}
        self._sess = sess

    def _sessione_bot(self, b):
        return self._sess


vecchio_per_id = bots_mod.per_id_agente
bots_mod.per_id_agente = lambda bid: {"id": 31, "nome": "Prova",
                                      "modello": ""}
try:
    tg.salva_token(31, TOKEN)
    tg.imposta_chat(31, 111, "Anna")
    tg.imposta_chat(31, 222, "Bruno")
    app = AppFinta(SessioneFinta(True))
    fuori = app.telegram_comando(31, "stop")
    check("con due chat /stop dice che la sessione e' una sola",
          "una sola" in fuori and "chiunque" in fuori, fuori)
    check("e nomina quante chat tocca", "2 chat collegate" in fuori, fuori)
    check("fermando il turno davvero", app._sess.fermate == 1,
          str(app._sess.fermate))

    app._sess.busy = False
    fuori = app.telegram_comando(31, "nuova")
    check("con due chat /nuova dice che azzera anche agli altri",
          "riparte da zero anche per loro" in fuori, fuori)
    check("e nomina quante chat tocca", "2 chat collegate" in fuori, fuori)
    check("azzerando la conversazione davvero", app._sess.azzerate == 1,
          str(app._sess.azzerate))

    # Una chat sola: i messaggi restano quelli di sempre, senza avvisi.
    tg.dimentica_chat(31, 222)
    app = AppFinta(SessioneFinta(True))
    fuori = app.telegram_comando(31, "stop")
    check("con una chat sola /stop resta com'era",
          fuori == "Ho chiesto di fermare il turno.", fuori)
    app._sess.busy = False
    fuori = app.telegram_comando(31, "nuova")
    check("con una chat sola /nuova resta com'era",
          fuori == ("Nuova conversazione. La precedente resta nella "
                    "cronologia di Orchestra."), fuori)
    # Nessun turno in corso: il messaggio non parla di sessioni condivise,
    # perche' non c'e' niente da fermare e nessuno da avvisare.
    app._sess.busy = False
    fuori = app.telegram_comando(31, "stop")
    check("senza turno in corso non si parla di sessione condivisa",
          "una sola" not in fuori, fuori)
finally:
    bots_mod.per_id_agente = vecchio_per_id

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("falliti:", FAIL)
sys.exit(1 if FAIL else 0)
