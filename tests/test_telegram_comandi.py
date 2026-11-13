"""I comandi del ponte Telegram: livello di reasoning, obiettivo, consiglio.

Dal telefono si poteva accendere e spegnere il VEDERE il ragionamento, ma
il LIVELLO — quanto pensa il modello — no: esisteva solo `/api/reasoning`,
cioe' il pannello sul computer. E i due comandi che avviano lavoro non-chat
(un obiettivo, un consiglio del tavolo) non esistevano affatto.

Questi test coprono le tre cose nuove senza rete: provider e moduli esterni
sono sostituiti, perche' quello che si prova e' il comando (decide, scrive,
risponde), non il modello.
"""

from __future__ import annotations

import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "ORCHESTRA_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestra.goal as goal_mod  # noqa: E402
import orchestra.webapp as webapp_mod  # noqa: E402
from orchestra.providers import load_env  # noqa: E402
from orchestra.reasoning import (  # noqa: E402
    REASONING_LEVELS, livello_da_argomento,
)
from orchestra.telegram import COMANDI_AGENTE, COMANDI_MENU, GUIDA  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


def _app():
    """Un'app senza __init__: qui si provano i comandi, non l'avvio."""
    app = object.__new__(webapp_mod.OrchestraApp)
    app.env = {}
    return app


def _sessione(busy: bool = False):
    return SimpleNamespace(
        busy=busy,
        agent=SimpleNamespace(
            config=SimpleNamespace(reasoning_level=None)))


# ---------------------------------------------------- la lettura del livello
print("\n[1] Un argomento e' un livello, un interruttore, o niente")

check("`high` e' un livello", livello_da_argomento("high") == "high")
check("`MAX` normalizzato", livello_da_argomento(" MAX ") == "max")
check("`auto` toglie il livello (stringa vuota)",
      livello_da_argomento("auto") == "",
      repr(livello_da_argomento("auto")))
check("`on` NON e' un livello: resta l'interruttore",
      livello_da_argomento("on") is None)
check("una parola a caso non e' un livello",
      livello_da_argomento("pippo") is None)
check("tutti i livelli veri passano",
      all(livello_da_argomento(x) == x for x in REASONING_LEVELS))

# Il comando vecchio non e' stato toccato: senza argomento e con on/off fa
# quello che faceva prima, e una parola che non e' un livello non deve
# diventare un interruttore silenzioso.
app_prova = _app()
for parola in ("on", "off", "mostra", "nascondi", "1", "0"):
    check(f"`{parola}` resta un interruttore, non un livello",
          livello_da_argomento(parola) is None)
out = app_prova._telegram_ragionamento({"id": 0}, "medio")
check("una parola che non e' un livello non spegne il ragionamento",
      "Uso" in out, out)
check("e il messaggio nomina i livelli",
      "high" in out and "auto" in out, out)

# ------------------------------------------------ il comando c'e' davvero
print("\n[2] Il ponte li conosce e li pubblicizza")

for comando in ("obiettivo", "consiglio", "reasoning"):
    check(f"/{comando} e' nella lista accettata",
          comando in COMANDI_AGENTE)
nel_menu = {voce for voce, _ in COMANDI_MENU}
for comando in ("obiettivo", "consiglio", "reasoning"):
    check(f"/{comando} e' nel menu di Telegram", comando in nel_menu)
check("la guida spiega il livello",
      "/reasoning <livello>" in GUIDA and "xhigh" in GUIDA)
check("la guida spiega obiettivo e consiglio",
      "/obiettivo" in GUIDA and "/consiglio" in GUIDA)

# ------------------------------------------------------ /reasoning <livello>
print("\n[3] `/reasoning high` imposta e salva")

cartella = tempfile.mkdtemp()
percorso_env = os.path.join(cartella, ".env")
with open(percorso_env, "w", encoding="utf-8") as f:
    f.write("ORCHESTRA_MODEL=vecchio\n")
vecchio_path = webapp_mod.ENV_PATH
webapp_mod.ENV_PATH = percorso_env
try:
    app = _app()
    sess = _sessione()
    out = app._telegram_livello_reasoning(sess, "high")
    check("il livello vale subito sulla sessione",
          sess.agent.config.reasoning_level == "high",
          str(sess.agent.config.reasoning_level))
    check("ed e' scritto nel .env",
          load_env(percorso_env).get("ORCHESTRA_REASONING") == "high",
          str(load_env(percorso_env)))
    check("le altre righe restano",
          load_env(percorso_env).get("ORCHESTRA_MODEL") == "vecchio")
    check("la risposta dice quale livello",
          "high" in out, out)
    check("e che vale per tutte le sessioni, non solo questa chat",
          "tutte le sessioni" in out, out)

    # `auto` deve TOGLIERE un livello gia' impostato, non solo non
    # rompere: si parte da `max` e si controlla che resti None.
    nuova = _sessione()
    app._telegram_livello_reasoning(nuova, "max")
    out = app._telegram_livello_reasoning(nuova, "")
    check("`auto` toglie il livello",
          nuova.agent.config.reasoning_level is None,
          str(nuova.agent.config.reasoning_level))
    check("`auto` svuota anche il .env",
          (load_env(percorso_env).get("ORCHESTRA_REASONING") or "") == "",
          repr(load_env(percorso_env).get("ORCHESTRA_REASONING")))
    check("e la risposta parla di automatico",
          "automatico" in out.lower(), out)
    check("anche `auto` dice la portata",
          "tutte le sessioni" in out, out)

    occupata = _sessione(busy=True)
    out = app._telegram_livello_reasoning(occupata, "max")
    check("con un turno in corso non cambia niente",
          occupata.agent.config.reasoning_level is None and "/stop" in out, out)
finally:
    webapp_mod.ENV_PATH = vecchio_path
    for nome in os.listdir(cartella):
        os.remove(os.path.join(cartella, nome))
    os.rmdir(cartella)

# ------------------------------------------------------------- /obiettivo
print("\n[4] `/obiettivo` crea, e senza testo elenca")

app = _app()
salvati = (goal_mod.list_goals, goal_mod.start_goal)
try:
    goal_mod.list_goals = lambda: [
        {"id": "g1", "objective": "scrivi il report", "status": "pending"},
        {"id": "g2", "objective": "fatto ieri", "status": "done"},
    ]
    out = app._telegram_obiettivo("")
    check("l'elenco mostra gli aperti", "scrivi il report" in out, out)
    check("e non i conclusi", "fatto ieri" not in out, out)

    visti: dict = {}

    def _start(testo, **kw):
        visti["testo"] = testo
        visti["env"] = kw.get("env")
        return "gid9"

    goal_mod.start_goal = _start
    out = app._telegram_obiettivo("  sistema il bug  ")
    check("crea con il testo ripulito", visti.get("testo") == "sistema il bug",
          str(visti.get("testo")))
    check("passa la configurazione dell'app", visti.get("env") is app.env)
    check("la risposta dice che e' partito", "gid9" in out, out)

    def _rotto(testo, **kw):
        raise RuntimeError("provider senza chiave")

    goal_mod.start_goal = _rotto
    out = app._telegram_obiettivo("x")
    check("un errore si legge, non esplode",
          "non avviato" in out and "provider senza chiave" in out, out)
finally:
    goal_mod.list_goals, goal_mod.start_goal = salvati

# -------------------------------------------------------------- /consiglio
print("\n[5] `/consiglio` formatta il tavolo")

app = _app()
app.consiglia_tavolo = lambda decisione: {
    "seats": ["buffett", "bezos"],
    "why": {"buffett": "guarda il downside"},
    "note": "manca un tecnico",
}
out = app._telegram_consiglio("compro o aspetto?")
check("il seat c'e'", "buffett" in out and "bezos" in out, out)
check("e il perche' accanto", "guarda il downside" in out, out)
check("e la nota del Chair", "manca un tecnico" in out, out)
check("senza argomento spiega l'uso",
      "/consiglio <decisione>" in app._telegram_consiglio(""),
      app._telegram_consiglio(""))


def _esplode(decisione):
    raise ValueError("roster vuoto")


app.consiglia_tavolo = _esplode
check("un errore del tavolo si legge, non esplode",
      "non disponibile" in app._telegram_consiglio("x"))

# ------------------------------------------------- il modulo a bottoni
print("\n[6] `/ragionamento` senza argomento apre i pulsanti")

import orchestra.bots as bots_mod  # noqa: E402
import orchestra.telegram as tg_mod  # noqa: E402

cartella2 = tempfile.mkdtemp()
env2 = os.path.join(cartella2, ".env")
with open(env2, "w", encoding="utf-8") as f:
    f.write("")
vecchio_env = webapp_mod.ENV_PATH
webapp_mod.ENV_PATH = env2
salvati_tg = (tg_mod.ragionamento, tg_mod.imposta_ragionamento, 
              bots_mod.per_id_agente)
stato = {"mostra": True, "scritti": []}
tg_mod.ragionamento = lambda bot_id: stato["mostra"]


def _imposta(bot_id, valore):
    stato["mostra"] = bool(valore)
    stato["scritti"].append(bool(valore))
    return True


tg_mod.imposta_ragionamento = _imposta
bots_mod.per_id_agente = lambda bid: {"id": 0, "nome": "Prova",
                                      "modello": ""}
try:
    app = _app()
    sess = _sessione()
    app._sessione_bot = lambda b: sess
    modulo = app._telegram_modulo_ragionamento({"id": 0}, sess, "")
    check("e' un modulo con i pulsanti",
          isinstance(modulo, dict) and bool(modulo.get("tastiera")), str(modulo))
    toccabili = [p["dati"] for riga in modulo["tastiera"] for p in riga]
    check("ci sono mostra e nascondi",
          "g:v:on" in toccabili and "g:v:off" in toccabili, str(toccabili))
    check("ci sono tutti i livelli, piu' auto",
          all(f"g:l:{v}" in toccabili for v in ["auto"] + REASONING_LEVELS),
          str(toccabili))
    check("c'e' un modo per chiudere", "g:x" in toccabili, str(toccabili))
    check("il testo dice lo stato di adesso",
          "In chat: acceso" in modulo["testo"], modulo["testo"])
    # Due portate diverse: il livello e' di Orchestra (una sola volta per
    # tutte le sessioni), la vista e' del bot. Scritte uguali, il modulo
    # faceva credere che entrambe valessero solo per questa chat.
    check("il livello dichiara di valere per tutte le sessioni",
          "tutte le sessioni" in modulo["testo"], modulo["testo"])
    check("e la vista dichiara di valere solo per questo bot",
          "solo questo bot" in modulo["testo"], modulo["testo"])

    toccato = app._telegram_modulo_ragionamento({"id": 0}, sess, "g:l:high")
    check("un livello toccato vale subito",
          sess.agent.config.reasoning_level == "high",
          str(sess.agent.config.reasoning_level))
    check("e il segno si sposta sul livello nuovo",
          any(p["testo"] == "✓ high"
              for riga in toccato["tastiera"] for p in riga),
          str(toccato["tastiera"]))
    check("e il modulo dice che ha applicato",
          "high" in toccato["testo"].split("\n")[0], toccato["testo"])

    toccato = app._telegram_modulo_ragionamento({"id": 0}, sess, "g:l:auto")
    check("`auto` toglie il livello anche da pulsante",
          sess.agent.config.reasoning_level is None,
          str(sess.agent.config.reasoning_level))
    check("e il segno torna su auto",
          any(p["testo"] == "✓ auto"
              for riga in toccato["tastiera"] for p in riga))

    toccato = app._telegram_modulo_ragionamento({"id": 0}, sess, "g:v:off")
    check("mostra/nascondi funziona da pulsante",
          stato["mostra"] is False and stato["scritti"] == [False],
          str(stato))
    check("e il modulo dice spento",
          "In chat: spento" in toccato["testo"], toccato["testo"])
    check("e la conferma della vista resta per-chat",
          "in questa chat" in toccato["testo"].split("\n")[0],
          toccato["testo"])

    check("chiudere non cambia niente",
          "lascio" in str(app._telegram_modulo_ragionamento(
              {"id": 0}, sess, "g:x")))
    check("un livello inventato non passa",
          "scaduto" in str(app._telegram_modulo_ragionamento(
              {"id": 0}, sess, "g:l:pippo")))

    # Il percorso vero: il tocco arriva al comando, che lo smista al modulo.
    fuori = app.telegram_comando(0, "reasoning", "cb:g:x")
    check("un tocco arriva al modulo del ragionamento",
          isinstance(fuori, dict) and "lascio" in str(fuori.get("testo")),
          str(fuori))
    fuori = app.telegram_comando(0, "ragionamento", "")
    check("e senza argomento il comando risponde col modulo",
          isinstance(fuori, dict) and bool(fuori.get("tastiera")), str(type(fuori)))
finally:
    webapp_mod.ENV_PATH = vecchio_env
    (tg_mod.ragionamento, tg_mod.imposta_ragionamento,
     bots_mod.per_id_agente) = salvati_tg
    for nome in os.listdir(cartella2):
        os.remove(os.path.join(cartella2, nome))
    os.rmdir(cartella2)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
