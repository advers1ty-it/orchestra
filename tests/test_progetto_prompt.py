"""La scheda del progetto nel prompt: percorso, nota, alias, ora, git, piani.

Perche' esiste: il blocco progetto diceva solo il nome e gli ultimi file
toccati. Un agente che riapre un progetto dopo giorni non sapeva in che
cartella stava scrivendo oltre al nome, non sapeva cosa l'utente aveva
annotato su quel lavoro, non sapeva che giorno fosse, su che ramo fosse,
quante modifiche ci fossero, ne' che esistevano piani gia' scritti.

Il test copre le sei cose chieste, e le due invarianti:

1. senza progetto il blocco resta vuoto (il prompt non cambia);
2. il blocco sta nel volatile, e il prefisso stabile non si tocca.

Niente rete: il provider e' finto e non viene mai chiamato. Il progetto,
la memoria e i dati stanno in cartelle temporanee.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

# ORCHESTRA_HOME prima degli import: progetti e memoria leggono l'ambiente
# all'import, e senza questa riga il test scriverebbe nei dati veri.
_TMP = tempfile.mkdtemp(prefix="orchestra_progetto_prompt_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)
os.environ["ORCHESTRA_ROOT"] = os.path.join(_TMP, "radice")

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

from orchestra import progetti as pr                              # noqa: E402
from orchestra.session import LoopConfig, Session                 # noqa: E402
from orchestra.tools import default_registry                      # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class ProviderFinto:
    name = "finto"
    model = "finto-1"

    def chat(self, *a, **k):
        raise AssertionError("il test non fa turni: nessuna chiamata al modello")


def volatile_di(sess: Session) -> str:
    return next((m.content for m in sess.agent.state.messages
                 if m.role == "system" and m.name == "__contesto__"), "")


def git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=30)


print("\n[1] Senza progetto il blocco non esiste")

sess = Session(provider=ProviderFinto(), registry=default_registry(),
               system_prompt="PREFISSO-STABILE",
               config=LoopConfig(max_iterations=2))
check("nessun progetto, nessun blocco", sess.agent._blocco_progetto() == "",
      sess.agent._blocco_progetto()[:120])

# ---------------------------------------------------------------------------
# Un progetto vero: cartella git, nota, alias, quattro piani.
P = os.path.join(_TMP, "lavori", "sito-ristorante")
os.makedirs(os.path.join(P, "plans"), exist_ok=True)
with open(os.path.join(P, "README.md"), "w", encoding="utf-8") as f:
    f.write("# Sito\n")
for i, nome in enumerate(("vecchio.md", "menu.md", "ordini.md", "nuovo.md")):
    percorso = os.path.join(P, "plans", nome)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(f"# {nome}\n")
    # mtime distinti: l'ordine nel prompt e' quello dei piu' recenti.
    os.utime(percorso, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))

pr.registra("Sito Ristorante", P,
            note="Cliente: Trattoria da Gino.\nConsegna: venerdi'.",
            alias="restaurant site, menu, ristorante")

HA_GIT = shutil.which("git") is not None
if HA_GIT:
    git("init", "-q", cwd=P)
    git("add", "-A", cwd=P)
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "-m", "prima", cwd=P)
    with open(os.path.join(P, "modificato.txt"), "w", encoding="utf-8") as f:
        f.write("x\n")
else:
    print("  (git non installato: i controlli su ramo e modifiche saltano)")

PULITO = os.path.join(_TMP, "lavori", "senza-git")
os.makedirs(PULITO, exist_ok=True)
pr.registra("Senza Git", PULITO, note="", alias="")

sess.imposta_progetto("Sito Ristorante")
blocco = sess.agent._blocco_progetto()

print("\n[2] Percorso, nota e alias")

check("il percorso c'e'", "Cartella del progetto:" in blocco
      and os.path.abspath(P) in blocco, blocco[:400])
check("la nota c'e', su una riga sola",
      "Cliente: Trattoria da Gino. Consegna: venerdi'." in blocco, blocco[:500])
check("gli alias ci sono",
      "Chiamato anche:" in blocco and "restaurant site" in blocco
      and "menu" in blocco, blocco[:500])

print("\n[3] Data, ora e git")

adesso = datetime.now()
check("la data e l'ora ci sono",
      bool(re.search(r"Siamo \S+ \d{1,2} \w+ \d{4}, ore \d{2}:\d{2}\.",
                     blocco)), blocco[:400])
check("la data e' quella di oggi",
      f"{adesso.day} " in blocco and f"{adesso.year}" in blocco, blocco[:400])

if HA_GIT:
    check("il ramo c'e'", re.search(r"Git: ramo `[^`]+`", blocco) is not None,
          blocco[:600])
    check("conta le modifiche non committate",
          "1 file con modifiche non committate" in blocco, blocco[:600])

print("\n[4] Gli ultimi piani, non tutti")

check("i tre piani piu' recenti ci sono",
      "`nuovo.md`" in blocco and "`ordini.md`" in blocco
      and "`menu.md`" in blocco, blocco[:700])
check("il piano vecchio resta fuori", "`vecchio.md`" not in blocco,
      blocco[:700])

print("\n[5] Il blocco sta nel volatile, il prefisso non si tocca")

volatile = volatile_di(sess)
check("la scheda e' nel messaggio volatile",
      "Cartella del progetto:" in volatile and "Siamo " in volatile,
      volatile[:400])
check("il prefisso stabile e' rimasto quello",
      sess.agent.system_prompt == "PREFISSO-STABILE",
      sess.agent.system_prompt[:80])

print("\n[6] Il blocco resta corto")

check("un progetto normale non sfonda i 2.000 caratteri",
      len(blocco) < 2000, str(len(blocco)))
pr.registra("Nota Lunga", P, note="x" * 5000, alias="")
sess.imposta_progetto("Nota Lunga")
lungo = sess.agent._blocco_progetto()
check("la nota lunga si tronca e lo dichiara",
      "…" in lungo and "x" * 400 not in lungo, lungo[:400])
check("anche con la nota lunga il blocco resta corto",
      len(lungo) < 2500, str(len(lungo)))

print("\n[7] Senza git e senza nota non si inventa niente")

sess.imposta_progetto("Senza Git")
senza = sess.agent._blocco_progetto()
check("nessuna riga git per un progetto non git", "Git:" not in senza,
      senza[:400])
check("nessuna nota vuota", "Nota del progetto:" not in senza, senza[:400])
check("il percorso c'e' lo stesso", os.path.abspath(PULITO) in senza,
      senza[:400])

print("\n[8] Tornando senza progetto il blocco sparisce")

sess.imposta_progetto("")
check("di nuovo vuoto", sess.agent._blocco_progetto() == "")

# ---------------------------------------------------------------------------
if HA_GIT:
    git("add", "-A", cwd=P)
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "-m", "pulito", cwd=P)
    sess.imposta_progetto("Sito Ristorante")
    pulito = sess.agent._blocco_progetto()
    check("albero pulito: lo dice, invece di contare zero",
          "nessuna modifica non committata" in pulito, pulito[:600])

print(f"\n{PASS.__len__()} passati, {len(FAIL)} falliti")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
    sys.exit(1)
