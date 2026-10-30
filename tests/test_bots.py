"""I bot: identita' salvate, sessioni separate, e il ponte fra due bot.

Nessuna rete: i provider sono finti e rispondono con lo stesso formato
degli altri test. Il punto non e' provare un modello, ma quattro cose
che rendono un bot diverso da un'etichetta:

1. il registro salvato (nomi, allowlist, provider validi);
2. una sessione per bot, con la sua conversazione e il suo progetto;
3. `bot_chiedi`, con il tetto di profondita' e l'allowlist;
4. la cronologia che non si mescola fra identita'.

Il test gira in una cartella dati temporanea: non deve toccare i bot
veri, ne' il `.env` dell'installazione.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

_TMP = tempfile.mkdtemp(prefix="orchestra_bots_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import bots as bt  # noqa: E402
from orchestra import progetti as pr  # noqa: E402
from orchestra import LoopConfig  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import LLMResponse  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class ProviderFinto:
    """Un provider che risponde sempre la stessa frase."""

    def __init__(self, risposta="ho fatto"):
        self.name = "finto"
        self.model = "finto-1"
        self.risposta = risposta
        self.chiamate = []

    def chat(self, messages, tools=None, **kw):
        self.chiamate.append([(m.role, (m.content or "")[:80])
                              for m in messages])
        return LLMResponse(content=self.risposta, model=self.model)


def sessione(nome="", risposta="ho fatto", *, bot="", risolutore=None,
             parla_con=None) -> Session:
    s = Session(provider=ProviderFinto(risposta), registry=default_registry(),
                system_prompt="sei un agente",
                config=LoopConfig(max_iterations=3))
    # L'identita' va impostata alla nascita, come fa l'app: se arrivasse
    # dopo il primo salvataggio, la riga nello storico resterebbe senza
    # bot e il filtro non la troverebbe.
    s.bot = bot
    if risolutore is not None:
        s.attiva_bot(risolutore, nome=nome, parla_con=parla_con or [])
    return s


print("\n[1] Il registro: creare, leggere, non duplicare")
a = bt.crea("Grok", provider="openrouter", modello="x-ai/grok-4.7",
            persona="Rispondi secco.", parla_con=[])
check("il bot torna con un id", int(a.get("id", 0)) > 0, str(a))
check("il nome e' quello scritto", a.get("nome") == "Grok", str(a.get("nome")))
check("il provider e' salvato", a.get("provider") == "openrouter")
check("la persona e' salvata", a.get("persona") == "Rispondi secco.")
check("l'allowlist vuota resta vuota", a.get("parla_con") == [],
      str(a.get("parla_con")))
check("si ritrova per nome", (bt.per_nome("grok") or {}).get("id") == a["id"])
check("il nome non distingue maiuscole",
      (bt.per_nome("GROK") or {}).get("id") == a["id"])
check("si ritrova per id", (bt.per_id(a["id"]) or {}).get("nome") == "Grok")
try:
    bt.crea("grok")
    check("un nome doppio viene rifiutato", False)
except ValueError as e:
    check("un nome doppio viene rifiutato", True)
    check("e lo dice", "esiste gia'" in str(e), str(e))
try:
    bt.crea("Senza provider", provider="non-esiste")
    check("un provider inventato viene rifiutato", False)
except ValueError as e:
    check("un provider inventato viene rifiutato", True)
    check("elenca i provider veri", "openrouter" in str(e), str(e))
try:
    bt.crea("Senza profilo", profilo="magico")
    check("un profilo inventato viene rifiutato", False)
except ValueError as e:
    check("un profilo inventato viene rifiutato", True)

check("un nome con la virgola non si spezza",
      bt._norm_nome("Grok, il bot") == "Grok il bot",
      bt._norm_nome("Grok, il bot"))
check("gli spazi doppi si normalizzano",
      bt._norm_nome("  Grok   veloce ") == "Grok veloce",
      bt._norm_nome("  Grok   veloce "))

print("\n[2] L'allowlist: o esiste, o e' un no")
b = bt.crea("Scrittore", provider="openai", modello="gpt-x",
            parla_con=["Grok"])
check("si puo' nominare un bot che esiste", b["parla_con"] == ["Grok"],
      str(b["parla_con"]))
try:
    bt.crea("Refuso", parla_con=["Grokko"])
    check("un nome sbagliato viene rifiutato", False)
except ValueError as e:
    check("un nome sbagliato viene rifiutato", True)
    check("e dice quale non esiste", "Grokko" in str(e), str(e))
try:
    bt.crea("Narciso", parla_con=["Narciso"])
    check("un bot non puo' parlare con se stesso", False)
except ValueError as e:
    check("un bot non puo' parlare con se stesso", True)

agg = bt.aggiorna(a["id"], persona="Rispondi come un pirata.",
                  parla_con=["Scrittore"])
check("l'aggiornamento cambia la persona",
      (agg or {}).get("persona") == "Rispondi come un pirata.", str(agg))
check("e l'allowlist", (agg or {}).get("parla_con") == ["Scrittore"],
      str((agg or {}).get("parla_con")))
check("i campi non toccati restano",
      (agg or {}).get("provider") == "openrouter", str(agg))

print("\n[3] `bot_chiedi`: la risposta arriva, col nome di chi l'ha data")
b_sess = sessione("Scrittore", "risposta di Scrittore", bot="Scrittore")
registro = {}

def risolutore(nome):
    trovato = bt.per_nome(nome)
    if trovato is None:
        return None
    return {"nome": trovato["nome"], "sessione": b_sess}

a_sess = sessione("Grok", "risposta di Grok", risolutore=risolutore,
                  parla_con=["Scrittore"])
tool = a_sess.registry.get("bot_chiedi")
check("il tool e' registrato", tool is not None)
esito = tool.handler("Scrittore", "scrivi due righe sul mare", attesa=10)
check("la risposta e' quella del bot", "risposta di Scrittore" in esito, esito)
check("e dice da chi viene", "[risposta dal bot Scrittore]" in esito, esito)
check("il destinatario ha ricevuto il messaggio",
      any("[messaggio dal bot Grok]" in (m.content or "")
          for m in b_sess.agent.state.messages),
      str([(m.role, m.content[:40]) for m in b_sess.agent.state.messages]))
check("il destinatario ha lavorato davvero",
      bool(getattr(b_sess.agent.state, "messages", [])),
      str(len(b_sess.agent.state.messages)))

print("\n[4] I limiti: profondita', allowlist, se stesso")
a_sess._bot_depth = 1
esito = tool.handler("Scrittore", "ancora", attesa=5)
check("un bot dentro una chiamata non richiama",
      "non puo' chiamare un altro bot da dentro" in esito, esito)
a_sess._bot_depth = 0

senza = sessione("Solo", "x", risolutore=risolutore, parla_con=[])
esito = senza.registry.get("bot_chiedi").handler("Scrittore", "ciao")
check("senza allowlist non parla con nessuno",
      "non puo' parlare con nessun altro" in esito, esito)

altro = sessione("Grok", "x", risolutore=risolutore, parla_con=["Altro"])
esito = altro.registry.get("bot_chiedi").handler("Scrittore", "ciao")
check("chi non e' in allowlist viene fermato",
      "non ha il permesso" in esito, esito)
check("e dice con chi puo' parlare", "Altro" in esito, esito)

esito = a_sess.registry.get("bot_chiedi").handler("Grok", "ciao")
check("un bot non puo' chiamare se stesso",
      "non puo' chiamare se stesso" in esito, esito)

def risolutore_vuoto(nome):
    return None

orfano = sessione("Orfano", "x", risolutore=risolutore_vuoto,
                  parla_con=["Fantasma"])
esito = orfano.registry.get("bot_chiedi").handler("Fantasma", "ciao")
check("un bot che non esiste non risponde",
      "non esiste" in esito, esito)

print("\n[5] Destinatario occupato o che non parte: si dice, non si inventa")
class SessioneFinta:
    def __init__(self, *, busy=False, invia=True, finito=True, testo=""):
        self.busy = busy
        self._invia = invia
        self._finito = finito
        self.agent = type("A", (), {"state": type(
            "S", (), {"messages": [type("M", (), {"role": "assistant",
                                                  "content": testo})()]})()})()

    def send(self, testo, bot_depth=0):
        return self._invia

    def wait(self, timeout=None):
        return self._finito


def con_sessione(oggetto):
    def r(nome):
        return {"nome": "Finto", "sessione": oggetto}
    return r

occupato = sessione("Grok", "x", risolutore=con_sessione(
    SessioneFinta(invia=False)), parla_con=["Finto"])
esito = occupato.registry.get("bot_chiedi").handler("Finto", "ciao", attesa=5)
check("un invio rifiutato lo dice", "riprova fra poco" in esito, esito)

lento = sessione("Grok", "x", risolutore=con_sessione(
    SessioneFinta(finito=False)), parla_con=["Finto"])
esito = lento.registry.get("bot_chiedi").handler("Finto", "ciao", attesa=5)
check("un bot ancora al lavoro non e' un risultato",
      "sta ancora lavorando" in esito and "non e' un risultato" in esito,
      esito)

vuoto = sessione("Grok", "x", risolutore=con_sessione(
    SessioneFinta(testo="")), parla_con=["Finto"])
esito = vuoto.registry.get("bot_chiedi").handler("Finto", "ciao", attesa=5)
check("una risposta vuota non e' un risultato",
      "senza una risposta" in esito, esito)

troppo = sessione("Grok", "x", risolutore=con_sessione(
    SessioneFinta(testo="ok")), parla_con=["Finto"])
esito = troppo.registry.get("bot_chiedi").handler(
    "Finto", "x" * (Session.BOT_MESSAGGIO_MAX + 1))
check("un messaggio enorme viene fermato",
      "troppo lungo" in esito, esito)

print("\n[6] Una sessione per bot, con progetto e cronologia separate")
progetto_dir = os.path.join(_TMP, "sito")
os.makedirs(progetto_dir, exist_ok=True)
pr.registra("Sito", progetto_dir)
b_sess.imposta_progetto("Sito")
check("il progetto del bot e' quello scelto",
      b_sess.progetto == "Sito", b_sess.progetto)
check("e l'agente lo sa", b_sess.agent.progetto == "Sito")

b_sess.send("scrivi il titolo")
check("il turno parte", b_sess.wait(timeout=10))
from orchestra.storico import storico  # noqa: E402

righe = storico().elenco(limite=5, bot="Scrittore")
check("la conversazione e' salvata col nome del bot",
      bool(righe) and righe[0].get("bot") == "Scrittore", str(righe[:1]))
check("il filtro non mostra le altre identita'",
      storico().elenco(limite=5, bot="Nessuno") == [],
      str(storico().elenco(limite=5, bot="Nessuno")))

print("\n[7] Nell'app: creare, attivare, tornare indietro")
from orchestra import keys as keys_mod  # noqa: E402
from orchestra.webapp import OrchestraApp  # noqa: E402

# Il test non deve scrivere nel .env dell'installazione: si annulla la
# scrittura, che e' l'unico effetto collaterale dell'attivazione.
originale_scrivi = keys_mod.scrivi
keys_mod.scrivi = lambda *a, **k: None
try:
    create = []

    def make_session(provider, model, *, persona="", nome_bot=""):
        s = Session(provider=ProviderFinto("ok"),
                    registry=default_registry(),
                    system_prompt=("sei un agente"
                                   + (f" {persona}" if persona else "")),
                    config=LoopConfig(max_iterations=3))
        s.bot = nome_bot
        create.append((provider, model, persona, nome_bot))
        return s

    OrchestraApp._make_session = staticmethod(make_session)
    app = OrchestraApp({"ORCHESTRA_PROVIDER": "openrouter",
                        "ORCHESTRA_MODEL": "modello-base"}, session=None)
    app.session = make_session("openrouter", "modello-base")
    principale = app.session

    creato = app.crea_bot(nome="Capo", provider="", modello="",
                          persona="secco", progetto="Sito",
                          parla_con=[])
    check("l'app crea un bot", creato.get("nome") == "Capo", str(creato))
    elenco = app.elenco_bot()
    capo = [b for b in elenco if b["nome"] == "Capo"]
    check("l'elenco contiene il bot", len(capo) == 1, str(elenco))
    check("nessuno e' attivo all'inizio",
          all(not b["attivo"] for b in elenco), str(elenco))

    app.attiva_bot(creato["id"])
    check("attivare cambia la sessione", app.session is not principale)
    check("la sessione sa di essere il bot", app.session.bot == "Capo")
    check("il bot attivo e' quello", (app.bot_attivo() or {}).get("nome") == "Capo")
    check("il progetto del bot e' applicato",
          app.session.progetto == "Sito", app.session.progetto)
    check("l'elenco segna l'attivo",
          [b for b in app.elenco_bot() if b["attivo"]][0]["nome"] == "Capo")
    check("il bot ha il tool per parlare",
          "bot_chiedi" in app.session.registry)

    app.attiva_bot(None)
    check("disattivare riporta la sessione di prima",
          app.session is principale, "sessione principale persa")
    check("e non c'e' un bot attivo", app.bot_attivo() is None)

    app.attiva_bot(creato["id"])
    prima_sessione = app.session
    app.attiva_bot(None)
    app.attiva_bot(creato["id"])
    check("riattivare riusa la stessa sessione",
          app.session is prima_sessione, "la conversazione e' stata persa")

    # Modifica: la configurazione cambia e la sessione viva viene rifatta,
    # altrimenti il bot continuerebbe col prompt vecchio.
    app.aggiorna_bot(creato["id"], persona="allegro")
    check("modificare ricostruisce la sessione",
          app.session is not prima_sessione)
    check("col nuovo prompt",
          "allegro" in app.session.agent.system_prompt,
          app.session.agent.system_prompt[-60:])

    # Eliminare il bot attivo prima torna all'agente principale, poi
    # toglie la riga: non si puo' restare su un'identita' che non c'e'.
    app.elimina_bot(creato["id"])
    check("eliminare il bot attivo torna al principale",
          app.session is principale)
    check("e la riga sparisce",
          not [b for b in app.elenco_bot() if b["nome"] == "Capo"],
          str(app.elenco_bot()))
finally:
    keys_mod.scrivi = originale_scrivi

print("\n[8] Le rotte HTTP dei bot, con un server vero")
from orchestra import webapp  # noqa: E402

app_http = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app_http.env = {"ORCHESTRA_PROVIDER": "openrouter", "ORCHESTRA_MODEL": "m"}
app_http.session = principale
app_http.ready = True
app_http.error = ""
app_http.remoto_attivo = False
app_http.token_remoto = ""
app_http._storico = None
app_http._bots_runtime = {}
app_http._bot_attivo_id = 0
app_http._sessione_principale = None
webapp.Handler.app = app_http

import socket  # noqa: E402


def porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    n = s.getsockname()[1]
    s.close()
    return n


def richiesta(percorso, corpo=None):
    dati = None
    intestazioni = {}
    if corpo is not None:
        dati = json.dumps(corpo).encode("utf-8")
        intestazioni["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_HTTP + percorso, data=dati,
                                 headers=intestazioni,
                                 method="POST" if dati else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


PORT_HTTP = porta_libera()
BASE_HTTP = f"http://127.0.0.1:{PORT_HTTP}"
server = webapp.ThreadingHTTPServer(("127.0.0.1", PORT_HTTP), webapp.Handler)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(0.3)
keys_mod.scrivi = lambda *a, **k: None
try:
    stato, d = richiesta("/api/bots")
    check("GET /api/bots risponde", stato == 200 and d.get("ok") is True,
          f"{stato} {str(d)[:120]}")
    check("porta i provider validi", "openrouter" in (d.get("providers") or []))
    check("porta i progetti per il modulo", isinstance(d.get("progetti"), list))

    stato, d = richiesta("/api/bots/crea",
                         {"nome": "HttpBot", "persona": "prova"})
    check("POST crea un bot",
          stato == 200 and d.get("bot", {}).get("nome") == "HttpBot",
          f"{stato} {str(d)[:160]}")
    http_id = (d.get("bot") or {}).get("id")

    stato, d = richiesta("/api/bots/crea", {"nome": "HttpBot"})
    check("un doppione risponde 400", stato == 400, str(stato))
    check("e il messaggio e' chiaro", "esiste gia'" in (d.get("error") or ""),
          str(d.get("error")))

    stato, d = richiesta("/api/bots/aggiorna",
                         {"id": http_id, "persona": "nuova persona"})
    check("POST aggiorna", stato == 200
          and d.get("bot", {}).get("persona") == "nuova persona",
          f"{stato} {str(d)[:160]}")

    stato, d = richiesta("/api/bots/attiva", {"id": http_id})
    check("POST attiva cambia identita'", stato == 200
          and app_http.session.bot == "HttpBot", f"{stato} {str(d)[:160]}")
    check("e la risposta porta il bot",
          (d.get("bot") or {}).get("nome") == "HttpBot")

    stato, d = richiesta("/api/state")
    check("lo stato espone il bot attivo",
          (d.get("bot") or {}).get("nome") == "HttpBot", str(d.get("bot")))
    check("lo stato espone il modello della sessione",
          bool(d.get("model")), str(d.get("model")))

    stato, d = richiesta("/api/bots/attiva", {"id": None})
    check("POST attiva null torna al principale", stato == 200
          and app_http.session is principale, f"{stato} {str(d)[:120]}")

    # Il lavoro in background si prova PRIMA di eliminare: eliminare un
    # bot con un lavoro in corso e' giustamente rifiutato, e la risposta
    # sarebbe un 409 che non c'entra con la rotta che si vuole provare.
    stato, d = richiesta("/api/bots/avvia",
                         {"id": http_id, "testo": "lavoro via http"})
    check("POST avvia accoda un lavoro",
          stato == 200 and d.get("ok") is True, f"{stato} {str(d)[:160]}")
    scadenza_http = time.time() + 10
    voce = None
    while time.time() < scadenza_http:
        _, elenco_http = richiesta("/api/bots")
        voce = next((x for x in (elenco_http.get("bots") or [])
                     if x.get("id") == http_id), None)
        if voce and not voce.get("busy") and not voce.get("coda") \
                and not voce.get("in_corso"):
            break
        time.sleep(0.05)
    check("il lavoro HTTP e' finito",
          bool(voce and voce.get("ultimo") and voce["ultimo"].get("ok")),
          str(voce))
    stato, d = richiesta("/api/bots/avvia", {"id": http_id, "testo": "  "})
    check("un compito vuoto risponde 400", stato == 400, str(stato))

    stato, d = richiesta("/api/bots/elimina", {"id": http_id})
    check("POST elimina", stato == 200 and d.get("ok") is True,
          f"{stato} {str(d)[:120]}")
    stato, d = richiesta("/api/bots/elimina", {"id": http_id})
    check("eliminare due volte risponde 404", stato == 404, str(stato))

    stato, d = richiesta("/api/bots/attiva", {"id": 999999})
    check("attivare un bot inesistente risponde 400", stato == 400, str(stato))
finally:
    keys_mod.scrivi = originale_scrivi
    server.shutdown()
    server.server_close()


print("\n[9] Due bot lavorano davvero insieme")
java_dir = os.path.join(_TMP, "java")
web_dir = os.path.join(_TMP, "web")
os.makedirs(java_dir, exist_ok=True)
os.makedirs(web_dir, exist_ok=True)
pr.registra("JavaPar", java_dir)
pr.registra("WebPar", web_dir)

traccia = {"attivi": 0, "max": 0, "radici": {}}
traccia_lock = threading.Lock()


class ProviderTraccia:
    """Risponde dopo mezzo secondo e registra chi stava lavorando.

    Il sonno non e' decorazione: e' quello che rende osservabile il
    parallelismo. Due turni istantanei potrebbero non sovrapporsi mai e
    il test direbbe "non in parallelo" anche se il codice e' giusto.
    """

    name = "traccia"
    model = "traccia-1"

    def chat(self, messages, tools=None, **kw):
        testo = ""
        for m in reversed(messages):
            if m.role == "user":
                testo = m.content or ""
                break
        with traccia_lock:
            traccia["attivi"] += 1
            traccia["max"] = max(traccia["max"], traccia["attivi"])
        try:
            # La root e' thread-local: dentro il turno ogni bot deve
            # vedere la SUA cartella, non quella dell'ultimo che l'ha
            # impostata.
            radice = pr._root_sessione()
            with traccia_lock:
                traccia["radici"][testo.split()[0]] = radice
            time.sleep(0.5)
            return LLMResponse(content="fatto: " + testo[:40],
                               model=self.model)
        finally:
            with traccia_lock:
                traccia["attivi"] -= 1


def make_session_par(provider, model, *, persona="", nome_bot=""):
    s = Session(provider=ProviderTraccia(), registry=default_registry(),
                system_prompt="sei un agente",
                config=LoopConfig(max_iterations=2))
    s.bot = nome_bot
    return s


OrchestraApp._make_session = staticmethod(make_session_par)
app_par = OrchestraApp({"ORCHESTRA_PROVIDER": "openrouter",
                        "ORCHESTRA_MODEL": "modello-par"}, session=None)
app_par.session = make_session_par("openrouter", "modello-par")
gigi = app_par.crea_bot(nome="GigiPar", progetto="JavaPar")
alberto = app_par.crea_bot(nome="AlbertoPar", progetto="WebPar")

r1 = app_par.avvia_lavoro_bot(gigi["id"], "java: sistema il parser")
r2 = app_par.avvia_lavoro_bot(alberto["id"], "sito: crea la home")
check("due bot accettano un lavoro insieme",
      r1.get("ok") is True and r2.get("ok") is True, str((r1, r2)))
r3 = app_par.avvia_lavoro_bot(gigi["id"], "java: aggiungi i test")
check("un secondo compito sullo stesso bot va in coda",
      r3.get("ok") is True and r3.get("in_coda", 0) >= 1, str(r3))

scadenza = time.time() + 20
voci = {}
while time.time() < scadenza:
    voci = {b["nome"]: b for b in app_par.elenco_bot()}
    if voci and all(not b["busy"] and not b["coda"] and not b["in_corso"]
                    for b in voci.values()):
        break
    time.sleep(0.05)
check("tutti i lavori sono finiti",
      bool(voci) and all(not b["busy"] and not b["coda"]
                         and not b["in_corso"] for b in voci.values()),
      str(voci))
check("i due bot hanno lavorato insieme",
      traccia["max"] >= 2, f"max concorrenti: {traccia['max']}")


def stessa_radice(a, b):
    return os.path.normcase(os.path.realpath(a or "")) == \
        os.path.normcase(os.path.realpath(b or ""))


check("Gigi ha lavorato nella cartella Java",
      stessa_radice(traccia["radici"].get("java:"), java_dir),
      str(traccia["radici"]))
check("Alberto ha lavorato nella cartella del sito",
      stessa_radice(traccia["radici"].get("sito:"), web_dir),
      str(traccia["radici"]))
check("il risultato di Gigi e' l'ultimo compito della sua coda",
      "aggiungi i test" in ((voci.get("GigiPar") or {}).get("ultimo") or {})
      .get("risposta", ""), str(voci.get("GigiPar")))
check("il risultato di Alberto e' il suo",
      "crea la home" in ((voci.get("AlbertoPar") or {}).get("ultimo") or {})
      .get("risposta", ""), str(voci.get("AlbertoPar")))
check("la sessione attiva non e' cambiata", app_par.session.bot == "",
      app_par.session.bot)

# Un errore di battitura non deve produrre una fila illimitata.
app_par.MAX_LAVORI_BOT = 1
try:
    app_par.avvia_lavoro_bot(gigi["id"], "java: uno")
    try:
        app_par.avvia_lavoro_bot(gigi["id"], "java: due")
        check("la coda ha un tetto", False)
    except RuntimeError as e:
        check("la coda ha un tetto", "troppi lavori" in str(e), str(e))
    while app_par.elenco_bot() and any(
            b["busy"] or b["coda"] for b in app_par.elenco_bot()):
        time.sleep(0.05)
finally:
    app_par.MAX_LAVORI_BOT = 20

try:
    app_par.avvia_lavoro_bot(999999, "x")
    check("un bot inesistente viene rifiutato", False)
except ValueError as e:
    check("un bot inesistente viene rifiutato", "inesistente" in str(e), str(e))
try:
    app_par.avvia_lavoro_bot(gigi["id"], "   ")
    check("un compito vuoto viene rifiutato", False)
except ValueError as e:
    check("un compito vuoto viene rifiutato", "compito" in str(e), str(e))

print("\n[10] Cambiare bot mentre uno lavora")


def ultima_risposta(sess):
    for m in reversed(sess.snapshot().get("messages", [])):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            return m["content"]
    return ""


traccia["max"] = 0
traccia["attivi"] = 0
app_sw = OrchestraApp({"ORCHESTRA_PROVIDER": "openrouter",
                       "ORCHESTRA_MODEL": "modello-sw"}, session=None)
app_sw.session = make_session_par("openrouter", "modello-sw")
primo = app_sw.crea_bot(nome="PrimoSw")
secondo = app_sw.crea_bot(nome="SecondoSw")

app_sw.attiva_bot(primo["id"])
app_sw.session.send("primo: lavoro lungo")
time.sleep(0.1)
check("il primo sta lavorando", app_sw.session.busy)
sess_primo = app_sw.session

cambio = app_sw.attiva_bot(secondo["id"])
check("si cambia bot mentre il primo lavora",
      cambio.get("ok") is True and app_sw.session.bot == "SecondoSw",
      str(cambio))
check("il turno del primo continua da solo", sess_primo.busy,
      "la sessione lasciata si e' fermata")

ritorno = app_sw.attiva_bot(primo["id"])
check("si torna sul primo mentre sta ancora lavorando",
      ritorno.get("ok") is True and app_sw.session is sess_primo,
      str(ritorno))
check("e il suo turno e' ancora vivo", app_sw.session.busy)
check("un secondo messaggio alla stessa sessione viene rifiutato",
      sess_primo.send("ancora") is False)

app_sw.attiva_bot(secondo["id"])
app_sw.session.send("secondo: altro lavoro")
check("anche il secondo parte", app_sw.session.busy)
scadenza_sw = time.time() + 10
while time.time() < scadenza_sw and (sess_primo.busy
                                     or app_sw.session.busy):
    time.sleep(0.05)
check("i due turni si sono sovrapposti", traccia["max"] >= 2,
      f"max concorrenti: {traccia['max']}")

app_sw.attiva_bot(primo["id"])
risposta_primo = ultima_risposta(app_sw.session)
check("tornando al primo c'e' la sua risposta",
      "fatto: primo:" in risposta_primo, risposta_primo)
app_sw.attiva_bot(secondo["id"])
risposta_secondo = ultima_risposta(app_sw.session)
check("e il secondo ha la sua, non quella del primo",
      "fatto: secondo:" in risposta_secondo, risposta_secondo)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
shutil.rmtree(_TMP, ignore_errors=True)
sys.exit(1 if FAIL else 0)
