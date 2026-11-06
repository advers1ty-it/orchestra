"""I comandi Telegram visti dal lato della sessione.

Il ponte, da solo, sa chi ha scritto e cosa rispondere; non sa fermare
un turno ne' cambiare un modello. Qui si prova quella meta', con una
sessione finta: nessun provider, nessuna chiave, nessuna rete.

Le cose che contano sono tre. `/stop` deve fermare un turno che dal
telefono non si fermerebbe altrimenti. `/modello` non deve poter
scrivere nel bot un nome che non esiste: un modello inventato non
risponde 400, costruisce un client valido che fallisce alla prima
chiamata, e sembra un problema di rete. E lo stato che si manda su
Telegram deve dire cosa sta succedendo, non ripetere il log del turno.
"""

import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orch_tgc_")

import orchestra.bots as bots_mod  # noqa: E402
import orchestra.webapp as webapp  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" -- {dettaglio}" if dettaglio and not cond else ""))


class Stato:
    def __init__(self):
        self.messages = []


class Agente:
    def __init__(self):
        self.state = Stato()
        self.modalita_piano = False


class SessioneFinta:
    """Quello che le funzioni Telegram usano di una Session, e niente altro."""

    def __init__(self):
        self.busy = False
        self.modello = "gpt-4o-mini"
        self.agent = Agente()
        self.steer_chiamate = []
        self.cancellata = False
        self.resettata = False
        self.coda_piena = False
        self.testo = ""
        self.allegati = None
        self.eventi = []
        self.mandato = False

    def modello_in_uso(self):
        return self.modello

    def steer(self, testo):
        if self.coda_piena:
            return False
        self.steer_chiamate.append(testo)
        return True

    def cancel(self):
        self.cancellata = True
        return True

    def reset(self):
        if self.busy:
            raise RuntimeError("sessione occupata")
        self.resettata = True

    def send(self, testo, allegati=None):
        if self.busy:
            return False
        self.busy = True
        self.mandato = True
        self.testo = testo
        self.allegati = allegati
        return True

    def stream(self, timeout=0.4):
        def genera():
            while True:
                if self.eventi:
                    ev = self.eventi.pop(0)
                    if ev.get("kind") == "idle":
                        self.busy = False
                    yield ev
                    if ev.get("kind") == "idle":
                        return
                    continue
                # Come il bridge vero: uno stream non finisce da solo,
                # manda keepalive finche' qualcuno non chiude.
                yield {"kind": "keepalive", "data": {}, "seq": -1, "ts": 0}

        return genera()


class Messaggio:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class CatalogoFinto:
    def __init__(self, modelli):
        self.models = {m: object() for m in modelli}


def app_finta(sessione=None):
    app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
    app.env = {"ORCHESTRA_PROVIDER": "openrouter",
               "ORCHESTRA_MODEL": "gpt-4o-mini"}
    app._bots_runtime = {}
    app._catalog_per_provider = {
        "openrouter": CatalogoFinto(["gpt-4o-mini", "gpt-4o",
                                     "claude-3-5-sonnet"])}
    sess = sessione or SessioneFinta()
    app._sessione_bot = lambda _b: sess
    app.sessione = sess
    return app, sess


bot = bots_mod.crea(nome="Prova")
app, sess = app_finta()

print("\n[1] scegliere un modello da un nome scritto a mano")
check("un nome esatto si trova",
      webapp._scegli_modello("gpt-4o-mini",
                             ["gpt-4o-mini", "gpt-4o"]) == ("gpt-4o-mini", ""))
check("le maiuscole non contano",
      webapp._scegli_modello("GPT-4o",
                             ["gpt-4o-mini", "gpt-4o"]) == ("gpt-4o", ""))
check("un pezzo di nome basta se ne resta uno",
      webapp._scegli_modello("sonnet",
                             ["gpt-4o", "claude-3-5-sonnet"])[0]
      == "claude-3-5-sonnet")
ambiguo, errore = webapp._scegli_modello("gpt-4", ["gpt-4o-mini", "gpt-4o"])
check("un nome ambiguo non si indovina", ambiguo == "" and "gpt-4o" in errore,
      errore)
vuoto, errore2 = webapp._scegli_modello("pippo", ["gpt-4o-mini"])
check("un nome che non esiste viene rifiutato", vuoto == "" and "pippo" in errore2,
      errore2)
check("senza catalogo si accetta, lo dira' chi chiama",
      webapp._scegli_modello("qualsiasi-cosa", []) == ("qualsiasi-cosa", ""))

print("\n[2] la coda del testo per il messaggio di stato")
check("un testo corto resta com'e'", webapp._coda("ciao", 100) == "ciao")
lungo = "prima parte che non serve piu' " + "parola " * 60
coda = webapp._coda(lungo, 40)
check("un testo lungo si taglia dalla testa", coda.startswith("..."), coda[:20])
check("e non supera il limite chiesto", len(coda) <= 43, str(len(coda)))
check("senza tagliare una parola a meta'",
      coda.endswith("parola"), coda[-12:])

print("\n[3] /stop ferma un turno, e non lo inventa se non c'e'")
sess.busy = False
risposta = app.telegram_comando(bot["id"], "stop")
check("senza turno in corso lo dice",
      "Nessun turno" in risposta and "/scollega" in risposta, risposta)
check("e non chiama cancel", sess.cancellata is False)
sess.busy = True
risposta = app.telegram_comando(bot["id"], "stop")
check("con un turno in corso lo ferma", sess.cancellata is True, risposta)
sess.busy = False

print("\n[4] /steer: solo dentro un turno, e mai oltre la coda")
risposta = app.telegram_comando(bot["id"], "steer", "")
check("senza testo spiega l'uso", "Uso: /steer" in risposta, risposta)
risposta = app.telegram_comando(bot["id"], "steer", "vai piano")
check("fuori da un turno non accoda", "Nessun turno" in risposta, risposta)
check("e non chiama steer", sess.steer_chiamate == [],
      str(sess.steer_chiamate))
check("fuori da un turno non prende nemmeno il testo",
      "vai piano" not in str(sess.steer_chiamate), str(sess.steer_chiamate))
sess.busy = True
risposta = app.telegram_comando(bot["id"], "steer", "vai piano")
check("dentro un turno la guida arriva",
      sess.steer_chiamate == ["vai piano"], str(sess.steer_chiamate))
check("e la risposta lo dice", "Guida inviata" in risposta, risposta)
sess.coda_piena = True
risposta = app.telegram_comando(bot["id"], "steer", "ancora")
check("a coda piena lo dice invece di perdere il messaggio",
      "piena" in risposta, risposta)
sess.coda_piena = False
sess.busy = False

print("\n[5] /nuova non butta via un turno in corso")
sess.busy = True
risposta = app.telegram_comando(bot["id"], "nuova")
check("con un turno in corso rifiuta", "/stop" in risposta, risposta)
check("e non resetta", sess.resettata is False)
sess.busy = False
risposta = app.telegram_comando(bot["id"], "nuova")
check("a sessione ferma resetta", sess.resettata is True, risposta)
check("e lo dice", "Nuova conversazione" in risposta, risposta)

print("\n[6] /modello: mostra, e cambia solo nomi che esistono")
risposta = app.telegram_comando(bot["id"], "modello")
check("senza argomento mostra il modello attuale",
      "gpt-4o-mini" in risposta, risposta)
check("e un pezzo di elenco", "claude-3-5-sonnet" in risposta, risposta)
risposta = app.telegram_comando(bot["id"], "modello", "modello-inventato")
check("un modello inventato viene rifiutato",
      "inventato" in risposta and "Nessun modello" in risposta, risposta)
check("e il bot resta com'era",
      (bots_mod.per_id(bot["id"]) or {}).get("modello", "") == "",
      str((bots_mod.per_id(bot["id"]) or {}).get("modello")))
risposta = app.telegram_comando(bot["id"], "modello", "sonnet")
salvato = (bots_mod.per_id(bot["id"]) or {}).get("modello", "")
check("un pezzo di nome non ambiguo cambia il modello",
      salvato == "claude-3-5-sonnet", salvato)
check("e lo dice", "Modello cambiato" in risposta, risposta)
sess.busy = True
risposta = app.telegram_comando(bot["id"], "modello", "gpt-4o")
check("a turno in corso non cambia niente", "turno in corso" in risposta,
      risposta)
sess.busy = False

print("\n[7] /stato dice le tre cose utili, non il log")
risposta = app.telegram_comando(bot["id"], "stato")
check("c'e' il modello in uso", "gpt-4o-mini" in risposta, risposta)
check("c'e' il provider", "openrouter" in risposta, risposta)
check("e se sta lavorando", "libero" in risposta, risposta)
sess.busy = True
check("quando lavora lo dice", "al lavoro" in app.telegram_comando(
    bot["id"], "stato"))
sess.busy = False

print("\n[8] il turno su Telegram: eventi -> una riga di stato")
app, sess = app_finta()
sess.eventi = []
testi = []


def send_con_eventi(testo, allegati=None):
    sess.busy = True
    sess.mandato = True
    sess.testo = testo
    sess.allegati = allegati
    sess.agent.state.messages = [Messaggio("user", testo),
                                 Messaggio("assistant", "Ho letto i test.")]
    sess.eventi = [
        {"kind": "thinking", "data": {"iteration": 2}},
        {"kind": "ragionamento", "data": {"testo": "devo guardare i test"}},
        {"kind": "tool_start", "data": {"name": "run_shell"}},
        {"kind": "contenuto", "data": {"testo": "Ho letto i test"}},
        {"kind": "idle", "data": {"busy": False}},
    ]
    return True


sess.send = send_con_eventi
risposta = app.telegram_turno(bot["id"], "leggi i test", None, testi.append)
check("la risposta finale e' l'ultima dell'assistente",
      risposta == "Ho letto i test.", risposta)
check("il turno ha visto il testo giusto", sess.testo == "leggi i test",
      sess.testo)
check("lo stato e' stato aggiornato mentre girava", bool(testi), str(len(testi)))
primo = testi[0] if testi else ""
insieme = "\n".join(testi)
check("lo stato nomina il bot", "Prova" in primo, primo)
check("e il giro", "giro 2" in primo, primo)
check("il tool in corso compare appena parte",
      "run_shell" in insieme, insieme[-200:])
check("senza incollare tutto il ragionamento",
      "pensa:" in insieme and all(len(t) < 600 for t in testi),
      str([len(t) for t in testi]))

print("\n[9] un turno fermato non produce una risposta finta")
app, sess = app_finta()


def send_fermato(testo, allegati=None):
    sess.busy = True
    sess.mandato = True
    sess.eventi = [
        {"kind": "contenuto", "data": {"testo": "sto scrivendo"}},
        {"kind": "cancel_requested", "data": {}},
        {"kind": "idle", "data": {"busy": False}},
    ]
    return True


sess.send = send_fermato
risposta = app.telegram_turno(bot["id"], "lavora", None, None)
check("un turno fermato dice di essere stato fermato",
      risposta == "Turno interrotto.", risposta)

print("\n[10] un turno gia' occupato non ne fa partire un secondo")
app, sess = app_finta()
sess.busy = True
risposta = app.telegram_turno(bot["id"], "seconda richiesta", None, None)
check("lo dice invece di accodare", "ancora lavorando" in risposta, risposta)
check("e non manda niente", sess.mandato is False)

print("\n[11] un turno che muore senza dire di aver finito")
app, sess = app_finta()


def send_muto(testo, allegati=None):
    # Nessun `idle`: la sessione si ferma e basta. Il ponte non deve
    # restare ad aspettare la scadenza da quindici minuti.
    sess.busy = True
    sess.mandato = True
    sess.agent.state.messages = [Messaggio("assistant", "fatto comunque")]
    sess.eventi = [{"kind": "contenuto", "data": {"testo": "fatto"}}]
    threading.Timer(0.2, _sblocca).start()
    return True


def _sblocca():
    sess.busy = False


sess.send = send_muto
inizio = time.monotonic()
risposta = app.telegram_turno(bot["id"], "lavora", None, None)
passati = time.monotonic() - inizio
check("il turno si chiude da solo", risposta == "fatto comunque", risposta)
check("e non aspetta la scadenza", passati < 10, f"{passati:.1f}s")

print("\n[12] gli allegati arrivano al turno")
app, sess = app_finta()
ricevuti = []


def send_allegati(testo, allegati=None):
    ricevuti.append((testo, allegati))
    sess.busy = True
    sess.mandato = True
    sess.agent.state.messages = [Messaggio("assistant", "ok")]
    sess.eventi = [{"kind": "idle", "data": {"busy": False}}]
    return True


sess.send = send_allegati
app.telegram_turno(bot["id"], "guarda", ["un-allegato"], None)
check("gli allegati passano alla sessione",
      ricevuti == [("guarda", ["un-allegato"])], str(ricevuti))

print()
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("falliti:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
