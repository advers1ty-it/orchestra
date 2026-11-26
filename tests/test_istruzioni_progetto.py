"""Le istruzioni del progetto: AGENTS.md, CLAUDE.md e le altre.

Il difetto che questi controlli prevengono: un agente competente e fuori
contesto, che usa i comandi sbagliati perche' nessuno gli ha detto quali
sono. Il file esiste nel repository, e Orchestra non lo leggeva.

E il secondo difetto: le istruzioni sono del PROGETTO. Se stanno nel
prefisso costruito alla creazione della sessione, attivare un progetto
dopo non le porta, e cambiarlo lascia quelle vecchie. Devono stare nel
blocco volatile, risolte dal progetto attivo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

# Il pannello delle istruzioni: il test [9] ne esegue un pezzo in node.
CORE_PANNELLO = os.path.join(RADICE, "orchestra", "web", "panels-progetto.js")

TMP = tempfile.mkdtemp(prefix="orchestra_istruzioni_")
os.environ["ORCHESTRA_ROOT"] = TMP
# Anche i dati (progetti, memoria) in una cartella di prova: il blocco del
# progetto legge i file toccati da li', e non deve guardare quelli veri.
os.environ["ORCHESTRA_HOME"] = os.path.join(TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra import SYSTEM_PROMPT  # noqa: E402
from orchestra import istruzioni_progetto as ip  # noqa: E402
from orchestra import webapp  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def node_disponibile() -> bool:
    try:
        return subprocess.run(["node", "--version"], capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def estrai_funzione(src: str, intestazione: str) -> str:
    """Il corpo della funzione, contando le graffe (le regex ne contengono)."""
    inizio = src.index(intestazione)
    livello = 0
    for k in range(src.index("{", inizio), len(src)):
        if src[k] == "{":
            livello += 1
        elif src[k] == "}":
            livello -= 1
            if livello == 0:
                return src[inizio:k + 1]
    raise ValueError("funzione non chiusa")


print("\n[1] Senza file non si inventa niente")
ip.svuota_cache()
check("nessun file, nessun blocco", ip.blocco_prompt() == "",
      ip.blocco_prompt()[:120])


print("\n[2] AGENTS.md viene letto")
with open(os.path.join(TMP, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("# Progetto\n\n- Usa `make test`, non `pytest`.\n"
            "- Non toccare `vendor/`.\n")
blocco = ip.blocco_prompt()
check("il contenuto c'e'", "make test" in blocco and "vendor/" in blocco,
      blocco[:200])
check("il blocco dice da dove viene", "AGENTS.md" in blocco, blocco[:120])
check("il blocco e' dopo le regole di sicurezza",
      "vincono le regole di sicurezza" in blocco.lower(), blocco[:300])
check("il prefisso stabile NON porta istruzioni di progetto",
      "make test" not in webapp._prompt_base())
check("e le regole di Orchestra restano davanti",
      webapp._prompt_base().startswith(SYSTEM_PROMPT))


print("\n[3] CLAUDE.md arriva dopo, senza duplicare lo stesso testo")
with open(os.path.join(TMP, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("Stile: frasi brevi.\n")
blocco = ip.blocco_prompt()
check("ci sono entrambi", "make test" in blocco and "frasi brevi" in blocco)
check("AGENTS.md viene prima", blocco.index("AGENTS.md") < blocco.index("CLAUDE.md"))
with open(os.path.join(TMP, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# Progetto\n\n- Usa `make test`, non `pytest`.\n"
            "- Non toccare `vendor/`.\n")
ip.svuota_cache()
copia = ip.blocco_prompt()
check("lo stesso documento due volte non si ripete",
      copia.count("Non toccare `vendor/`") == 1, copia[:200])


print("\n[4] Un file enorme si tronca, e lo dice")
with open(os.path.join(TMP, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("REGOLA " + ("x" * 20000) + "FINE\n")
ip.svuota_cache()
grande = ip.blocco_prompt()
check("il blocco resta nel tetto", len(grande) <= ip.MAX_TOTALE + 300,
      str(len(grande)))
check("il troncamento e' dichiarato", "troncato" in grande, grande[-160:])


print("\n[5] Un file che non si legge non fa cadere il prompt")
ip.svuota_cache()
try:
    os.remove(os.path.join(TMP, "AGENTS.md"))
except OSError:
    pass
check("senza AGENTS.md resta CLAUDE.md", "CLAUDE.md" in ip.blocco_prompt())
check("chiamare due volte non cambia il risultato",
      ip.blocco_prompt() == ip.blocco_prompt())


print("\n[6] Al cambio progetto si rileggono le istruzioni")

P1 = tempfile.mkdtemp(prefix="orchestra_progetto_uno_")
P2 = tempfile.mkdtemp(prefix="orchestra_progetto_due_")
with open(os.path.join(P1, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("Usa `make test`, non `pytest`.\n")
with open(os.path.join(P2, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("Prima `npm run build`, poi `npm test`.\n")

from orchestra import progetti as prj  # noqa: E402
from orchestra.session import LoopConfig, Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402


class ProviderFinto:
    name = "finto"
    model = "finto-1"

    def chat(self, *a, **k):
        raise AssertionError("il test non fa turni")


def volatile_di(sess: Session) -> str:
    return next((m.content for m in sess.agent.state.messages
                 if m.role == "system" and m.name == "__contesto__"), "")


sess = Session(provider=ProviderFinto(), registry=default_registry(),
               system_prompt="PREFISSO-STABILE",
               config=LoopConfig(max_iterations=2))
prefisso = sess.agent.system_prompt

# Il percorso di un progetto si risolve dal nome, come in produzione. Il
# DB vero non si tocca: qui si sostituisce la sola funzione di lookup.
originale = prj.percorso_di
prj.percorso_di = lambda nome: {"progetto-uno": P1,
                                "progetto-due": P2}.get(nome, "")
try:
    sess.imposta_progetto("progetto-uno")
    uno = volatile_di(sess)
    check("attivando un progetto arrivano le sue istruzioni",
          "make test" in uno, uno[:300])
    check("il prefisso stabile non cambia",
          sess.agent.system_prompt == prefisso)
    check("e non contiene istruzioni di progetto",
          "make test" not in sess.agent.system_prompt)

    sess.imposta_progetto("progetto-due")
    due = volatile_di(sess)
    check("al cambio progetto arrivano le istruzioni nuove",
          "npm run build" in due, due[:300])
    check("e quelle del progetto precedente spariscono",
          "make test" not in due, due[:300])

    sess.imposta_progetto("")
    check("tornando senza progetto le istruzioni spariscono",
          "npm run build" not in volatile_di(sess), volatile_di(sess)[:200])
finally:
    prj.percorso_di = originale
    shutil.rmtree(P1, ignore_errors=True)
    shutil.rmtree(P2, ignore_errors=True)

print("\n[7] manca() e percorso_istruzioni(): la domanda del pannello")
ip.svuota_cache()
VUOTO = tempfile.mkdtemp(prefix="orchestra_istruzioni_vuoto_")
try:
    check("cartella vuota: manca() è vero", ip.manca(VUOTO))
    check("e la destinazione è AGENTS.md",
          ip.percorso_istruzioni(VUOTO).name == "AGENTS.md",
          str(ip.percorso_istruzioni(VUOTO)))

    with open(os.path.join(VUOTO, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("Stile: frasi brevi.\n")
    check("con CLAUDE.md non manca più", not ip.manca(VUOTO))
    check("e si mostra CLAUDE.md, non AGENTS.md",
          ip.percorso_istruzioni(VUOTO).name == "CLAUDE.md",
          str(ip.percorso_istruzioni(VUOTO)))

    # Un AGENTS.md vuoto è una scelta dell'utente: non si sovrascrive.
    VUOTO2 = tempfile.mkdtemp(prefix="orchestra_istruzioni_vuoto2_")
    try:
        with open(os.path.join(VUOTO2, "AGENTS.md"), "w", encoding="utf-8"):
            pass
        check("un AGENTS.md vuoto conta come esistente", not ip.manca(VUOTO2))
    finally:
        shutil.rmtree(VUOTO2, ignore_errors=True)

    # Il quarto nome vive in una sottocartella.
    VUOTO3 = tempfile.mkdtemp(prefix="orchestra_istruzioni_vuoto3_")
    try:
        os.makedirs(os.path.join(VUOTO3, ".github"))
        with open(os.path.join(VUOTO3, ".github", "copilot-instructions.md"), "w",
                  encoding="utf-8") as f:
            f.write("Regole Copilot.\n")
        check("copilot-instructions.md conta", not ip.manca(VUOTO3))
        check("e si mostra quello",
              ip.percorso_istruzioni(VUOTO3).name == "copilot-instructions.md",
              str(ip.percorso_istruzioni(VUOTO3)))
    finally:
        shutil.rmtree(VUOTO3, ignore_errors=True)
    # scrivi() e versione(): il salvataggio dell'editor.
    p = os.path.join(VUOTO, "AGENTS.md")
    ip.scrivi(p, "riga1\r\nriga2\r\n")
    with open(p, encoding="utf-8", newline="") as f:
        check("scrivi normalizza gli a capo", f.read() == "riga1\nriga2\n")
    check("versione è stabile", ip.versione("abc") == ip.versione("abc"))
    check("versione cambia col testo", ip.versione("abc") != ip.versione("abd"))
    try:
        ip.scrivi(p, "x" * (ip.MAX_FILE + 1))
        check("scrivi rifiuta oltre il tetto", False, "ha scritto")
    except ValueError:
        check("scrivi rifiuta oltre il tetto", True)
finally:
    shutil.rmtree(VUOTO, ignore_errors=True)


print("\n[8] Le rotte del pannello: GET e POST /api/progetto/istruzioni")
from orchestra.rotte_progetti import RotteProgetti  # noqa: E402


class AppFinta:
    def __init__(self, attivo=""):
        self._attivo = attivo

    def _progetto_attivo(self):
        return self._attivo


class HandlerFinto(RotteProgetti):
    """Solo i pezzi che le rotte usano: app, path e la risposta."""

    def __init__(self, app, path=""):
        self.app = app
        self.path = path
        self.risposta = None

    def _json(self, dati, status=200):
        self.risposta = (dati, status)


R1 = tempfile.mkdtemp(prefix="orchestra_rotte_uno_")
R2 = tempfile.mkdtemp(prefix="orchestra_rotte_due_")
R3 = tempfile.mkdtemp(prefix="orchestra_rotte_tre_")
R4 = tempfile.mkdtemp(prefix="orchestra_rotte_quattro_")
with open(os.path.join(R1, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("Usa `make test`.\n")
with open(os.path.join(R2, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("Stile: frasi brevi.\n")

originale = prj.percorso_di
prj.percorso_di = lambda nome: {"uno": R1, "due": R2, "tre": R3,
                                "quattro": R4}.get(nome, "")
try:
    app = AppFinta()

    h = HandlerFinto(app, "/api/progetto/istruzioni?progetto=uno")
    h._r_get_progetto_istruzioni(h.path, {}, None)
    dati, stato = h.risposta
    check("GET: il progetto con AGENTS.md risulta istruito",
          stato == 200 and dati["esiste"] and dati["file"] == "AGENTS.md",
          str(dati)[:200])
    check("GET: il contenuto arriva", "make test" in dati["contenuto"],
          str(dati)[:200])

    h = HandlerFinto(app, "/api/progetto/istruzioni?progetto=tre")
    h._r_get_progetto_istruzioni(h.path, {}, None)
    dati, stato = h.risposta
    check("GET: un progetto senza file risulta non istruito",
          stato == 200 and dati["esiste"] is False, str(dati)[:200])

    h = HandlerFinto(app, "/api/progetto/istruzioni?progetto=nessuno")
    h._r_get_progetto_istruzioni(h.path, {}, None)
    dati, stato = h.risposta
    check("GET: un progetto sconosciuto è 404", stato == 404, str(dati)[:200])

    # POST su un progetto vuoto: crea AGENTS.md con il modulo.
    h = HandlerFinto(app)
    h._r_post_progetto_istruzioni("", {"progetto": "tre"}, None)
    dati, stato = h.risposta
    check("POST: crea AGENTS.md", stato == 200 and dati["creato"] is True,
          str(dati)[:200])
    creato = os.path.join(R3, "AGENTS.md")
    check("POST: il file esiste davvero", os.path.isfile(creato))
    with open(creato, encoding="utf-8") as f:
        check("POST: il contenuto è il modulo", f.read() == ip.STUB)

    # POST su un progetto con CLAUDE.md: non crea un secondo documento.
    h = HandlerFinto(app)
    h._r_post_progetto_istruzioni("", {"progetto": "due"}, None)
    dati, stato = h.risposta
    check("POST: chi ha CLAUDE.md non riceve AGENTS.md",
          stato == 200 and dati["creato"] is False and dati["file"] == "CLAUDE.md",
          str(dati)[:200])
    check("POST: e AGENTS.md non è stato creato",
          not os.path.isfile(os.path.join(R2, "AGENTS.md")))

    # POST su un progetto già istruito: non sovrascrive.
    with open(os.path.join(R1, "AGENTS.md"), encoding="utf-8") as f:
        prima = f.read()
    h = HandlerFinto(app)
    h._r_post_progetto_istruzioni("", {"progetto": "uno"}, None)
    dati, stato = h.risposta
    with open(os.path.join(R1, "AGENTS.md"), encoding="utf-8") as f:
        dopo = f.read()
    check("POST: un AGENTS.md esistente non si tocca",
          stato == 200 and dati["creato"] is False and prima == dopo,
          str(dati)[:200])

    # Senza progetto: 409, non un file nella cartella sbagliata.
    h = HandlerFinto(AppFinta(""))
    h._r_post_progetto_istruzioni("", {}, None)
    dati, stato = h.risposta
    check("POST: senza progetto attivo è 409", stato == 409, str(dati)[:200])
    # PUT: il salvataggio dell'editor, con la versione letta.
    h = HandlerFinto(app, "/api/progetto/istruzioni?progetto=uno")
    h._r_get_progetto_istruzioni(h.path, {}, None)
    dati, _ = h.risposta
    versione = dati["versione"]
    check("GET: porta la versione del testo", bool(versione), str(dati)[:200])

    h = HandlerFinto(app)
    h._r_put_progetto_istruzioni(
        "", {"progetto": "uno", "contenuto": "Nuovo testo.\n",
             "versione": versione}, None)
    dati, stato = h.risposta
    check("PUT: salva con la versione giusta",
          stato == 200 and dati["salvato"] is True, str(dati)[:200])
    with open(os.path.join(R1, "AGENTS.md"), encoding="utf-8") as f:
        check("PUT: il testo è quello nuovo", f.read() == "Nuovo testo.\n")

    h = HandlerFinto(app)
    h._r_put_progetto_istruzioni(
        "", {"progetto": "uno", "contenuto": "x", "versione": versione}, None)
    dati, stato = h.risposta
    check("PUT: la versione vecchia è un conflitto",
          stato == 409 and dati.get("conflitto") is True, str(dati)[:200])
    check("PUT: il conflitto porta il testo attuale",
          "Nuovo testo" in dati.get("contenuto", ""), str(dati)[:200])
    check("PUT: e la versione con cui riprovare",
          dati.get("versione") == ip.versione("Nuovo testo.\n"), str(dati)[:200])

    # Un secondo tentativo con la STESSA versione vecchia: ancora 409, e
    # il server non scrive. E' la regola su cui il client costruisce il
    # tetto: la conferma vale per una versione sola.
    h = HandlerFinto(app)
    h._r_put_progetto_istruzioni(
        "", {"progetto": "uno", "contenuto": "y", "versione": versione}, None)
    dati2, stato2 = h.risposta
    check("PUT: un secondo tentativo con la versione vecchia è ancora 409",
          stato2 == 409 and dati2.get("conflitto") is True, str(dati2)[:200])
    check("PUT: e la versione attuale non è cambiata",
          dati2.get("versione") == dati.get("versione"), str(dati2)[:200])
    with open(os.path.join(R1, "AGENTS.md"), encoding="utf-8") as f:
        check("PUT: il file è ancora quello di prima",
              f.read() == "Nuovo testo.\n")

    h = HandlerFinto(app)
    h._r_put_progetto_istruzioni(
        "", {"progetto": "quattro", "contenuto": "x", "versione": ""}, None)
    dati, stato = h.risposta
    check("PUT: un progetto senza istruzioni è 404", stato == 404, str(dati)[:200])
    check("PUT: e non crea niente",
          not os.path.isfile(os.path.join(R4, "AGENTS.md")))

    h = HandlerFinto(app)
    h._r_put_progetto_istruzioni(
        "", {"progetto": "uno", "contenuto": "x" * (ip.MAX_FILE + 1),
             "versione": ip.versione("Nuovo testo.\n")}, None)
    dati, stato = h.risposta
    check("PUT: troppo lungo è 400", stato == 400, str(dati)[:200])
finally:
    prj.percorso_di = originale
    for d in (R1, R2, R3, R4):
        shutil.rmtree(d, ignore_errors=True)

print("\n[9] Cambio progetto con modifiche non salvate")
if node_disponibile():
    with open(CORE_PANNELLO, encoding="utf-8") as f:
        pannello = f.read()
    funzione = estrai_funzione(pannello, "async function impostaProgetto() {")
    inizio = pannello.index("// Le istruzioni del progetto:")
    fine = pannello.index("// Scegliere nel menu cambia subito il progetto")
    blocco = pannello[inizio:fine]
    script = (
        "const BLOCCO = " + json.dumps(blocco) + ";\n"
        "const FUNZIONE = " + json.dumps(funzione) + ";\n"
        + r"""
function elem(id) {
  return { id, hidden: false, value: "", textContent: "", disabled: false,
           _click: null, _input: null,
           addEventListener(ev, fn) {
             if (ev === "click") this._click = fn;
             if (ev === "input") this._input = fn;
           }, focus() {} };
}
const elementi = {};
const $ = (id) => (elementi[id] = elementi[id] || elem(id));
const progSelect = { value: "A", addEventListener() {} };
const progFatti = { textContent: "" };
const document = { activeElement: null };
let risposta = { status: 200, ok: true, corpo: {} };
let post = 0;
async function fetch(url, opzioni) {
  if (((opzioni && opzioni.method) || "GET") === "POST") post += 1;
  return { ok: risposta.ok !== false, status: risposta.status || 200,
           json: async () => risposta.corpo || {} };
}
let conferme = 0;
const confirm = () => { conferme += 1; return false; };
let caricato = 0;
async function caricaProgetto() { caricato += 1; }
const _progettoLabel = () => (progSelect.value || "").trim();
const api = new Function(
  "$", "fetch", "_progettoLabel", "confirm", "caricaProgetto",
  "progSelect", "progFatti", "document", "setTimeout",
  BLOCCO + "\nconst impostaProgetto = " + FUNZIONE
  + ";\nreturn { caricaIstruzioniProgetto, modificaIstruzioni,"
  + " impostaProgetto, sporco: () => istruzioniSporco,"
  + " progetto: () => istruzioniProgetto };"
)($, fetch, _progettoLabel, confirm, caricaProgetto, progSelect, progFatti,
  document, setTimeout);
(async () => {
  const editor = elementi["side-progetto-istruzioni-editor"];
  risposta = { status: 200, ok: true,
    corpo: { ok: true, esiste: true, file: "AGENTS.md", versione: "v1",
             contenuto: "testo di A" } };
  await api.caricaIstruzioniProgetto("A");
  await api.modificaIstruzioni();
  editor.value = "MODIFICHE NON SALVATE";
  editor._input();
  progSelect.value = "B";
  const postPrima = post;
  await api.impostaProgetto();
  console.log(JSON.stringify({
    sporco: api.sporco(), progetto: api.progetto(), select: progSelect.value,
    conferme: conferme, post: post - postPrima, editor: editor.value,
    caricato: caricato,
  }));
})();
"""
    )
    d = tempfile.mkdtemp(prefix="orchestra_pannello_")
    percorso = os.path.join(d, "prova.js")
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(script)
    esito = subprocess.run(["node", percorso], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
    if esito.returncode != 0:
        check("il pannello si esegue", False, (esito.stderr or "")[:300])
    else:
        dati = json.loads(esito.stdout)
        check("la conferma è stata chiesta", dati["conferme"] == 1, str(dati))
        check("annullando, il menu resta su A", dati["select"] == "A", str(dati))
        check("il progetto delle istruzioni resta A",
              dati["progetto"] == "A", str(dati))
        check("nessuna POST al server", dati["post"] == 0, str(dati))
        check("caricaProgetto non è stata chiamata",
              dati["caricato"] == 0, str(dati))
        check("l'editor conserva le modifiche",
              dati["editor"] == "MODIFICHE NON SALVATE", str(dati))
        check("il flag resta sporco", dati["sporco"] is True, str(dati))
    shutil.rmtree(d, ignore_errors=True)
else:
    print("  SKIP node non disponibile")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
