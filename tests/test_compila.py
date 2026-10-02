"""Ogni file deve compilare. Anche quelli che nessuno esegue.

Un IndentationError in un modulo che nessun test importa passa inosservato
fino al giorno in cui qualcuno lo esegue — e quel giorno è sempre il
giorno in cui non ci si guarda.

È successo mentre si aggiungeva la delega: `cli.py` è rimasto con
quattro spazi di troppo e un `def` cancellato, per sei chiamate di
fila. Il modulo non compilava e la suite non se n'era accorta, perché
nessuna suite importa `cli.py`.

Questo file controlla che tutti i moduli compilino. Costa mezzo
secondo e chiude la classe di difetti più noiosa da diagnosticare: il
file che non parte, senza che nessuno dica perché.
"""

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "orchestra"

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("[1] Ogni modulo del pacchetto deve compilare")
moduli = sorted(p for p in PKG.glob("*.py"))
check("ci sono moduli da controllare", len(moduli) > 5, str(len(moduli)))
for p in moduli:
    try:
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        ok, dove = True, ""
    except SyntaxError as e:
        ok, dove = False, f"riga {e.lineno}: {e.msg}"
    check(f"compila {p.name}", ok, dove)

print("\n[2] E devono anche importare")
# Non tutti: alcuni hanno effetti collaterali per costruzione. Ma
# quelli che il runner usa devono stare in piedi da soli.
for nome in ("cli", "webapp", "session", "catalog", "providers", "agent",
             "delega", "routing", "permissions", "tools", "benchmark",
             "punteggio"):
    if not (PKG / f"{nome}.py").exists():
        continue
    sys.path.insert(0, str(ROOT))
    try:
        __import__(f"orchestra.{nome}")
        ok, dove = True, ""
    except Exception as e:  # noqa: BLE001
        ok, dove = False, f"{type(e).__name__}: {e}"
    check(f"importa {nome}", ok, dove)

print("\n[3] Nessuna funzione può restare senza `def`")
# Il difetto vero di prima: un docstring e un `return` senza la riga
# `def` sopra. Compila? No. Ma un controllo che cerca solo strani
# documenti non lo trova, e un controllo che compila lo trova subito —
# quindi questo e' il controllo economico per un difetto che non
# merita un controllo dedicato.
for p in moduli:
    testo = p.read_text(encoding="utf-8")
    # un modulo che ha una return a fine file senza nessun def e' rotto
    righe = [r for r in testo.split("\n") if r.strip()]
    ha_def = any(r.lstrip().startswith(("def ", "class ")) for r in righe)
    if ha_def:
        continue
    primo = righe[0].strip() if righe else ""
    # un file di sole costanti o un __init__ e' legittimo
    check(f"{p.name} ha almeno una definizione",
          primo.startswith(("#", '"', "'", "from ", "import ", "@")) or
          not righe,
          primo[:60])

# --------------------------------------------------------------------------
# La parte che conta, e che il `ast.parse` NON prende.
#
# Un file puo' compilare benissimo e aver perso la meta' dei suoi
# metodi: e' successo. Uno script che riallineava l'indentazione ha
# spostato fuori dalla classe sette metodi di `Catalog` — `best_for`,
# `select`, `leaderboard`, `measured`, `free`, `by_score`,
# `agent_capable`. Il modulo compilava, `import orchestra.catalog`
# andava, e nessun errore: fino a quando un test ha chiesto
# `best_for` e si e' fermato li'.
#
# Un modulo che perde metodi e' peggio di un modulo che non parte,
# perche' un modulo che non parte lo dice subito. Qui non si dice
# niente: continua a funzionare, con meno.
#
# Per questo la lista dei metodi pubblici e' scritta a mano e non
# generata: se la generassimo dal codice corrente, il difetto
# passerebbe insieme al codice.
print("\n[4] Ogni modulo deve esporre quello che ha sempre esposto")
SUPERFICIE = {
    # modulo: nomi che devono esistere lì
    "orchestra.delega": ["Figlio", "Delegatore"],
    "orchestra.routing": ["categoria", "instrada", "il_successivo", "Scelta"],
    "orchestra.permissions": ["Gate"],
    "orchestra.punteggio": ["PESO_LIVELLO"],
    "orchestra.session": ["Session"],
    "orchestra.webapp": ["OrchestraApp"],
    "orchestra.non_agenti": ["e_agent", "NON_AGENTI"],
    # modulo.classe: nomi che devono esistere sulla CLASSE. Serve
    # perche' i metodi di `Catalog` stanno sulla classe e non sul
    # modulo: cercarli sul modulo dà "mancano tutti" ogni volta, che
    # è un controllo che non controlla niente e sembra rotto.
    "orchestra.catalog.Catalog": [
        "with_tools", "agent_capable", "best_for", "by_score",
        "leaderboard", "measured", "select", "free", "fetch", "save",
        "ignoti_sui_tool", "stale_measurements", "segnala_senza_tool",
        "load_measurements"],
    "orchestra.session.Session": [
        "send", "snapshot", "instradamento_attivo", "instradamento_ora",
        "attiva_delega", "resoconto_deleghe"],
    "orchestra.types.ToolRegistry": ["register", "activate", "deactivate",
                                     "active", "api_payload"],
}
for nome, attesi in SUPERFICIE.items():
    try:
        # Prima prova il nome per intero: se e' un modulo, e' un
        # modulo. Solo se non si importa, l'ultimo pezzo e' una classe
        # dentro il modulo che precede.
        #
        # I due tentativi, e non una regola dedotta dal nome: la
        # regola ("l'ultimo pezzo e' sempre una classe") e' sbagliata
        # per meta' dei casi, e un controllo sbagliato per meta' e'
        # peggio di nessun controllo perche' segnala cose false e
        # impara che si puo' ignorarlo.
        try:
            __import__(nome)
            soggetto = sys.modules[nome]
        except ImportError:
            modulo, _, ultimo = nome.rpartition(".")
            __import__(modulo)
            soggetto = getattr(sys.modules[modulo], ultimo)
        mancanti = [a for a in attesi if not hasattr(soggetto, a)]
        check(f"{nome.rsplit('.', 1)[-1]} espone {len(attesi)} nomi",
              not mancanti, f"mancano: {mancanti}")
    except Exception as e:  # noqa: BLE001
        check(f"{nome.split('.')[-1]} importa", False, str(e)[:70])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)