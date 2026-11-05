"""Scritture atomiche e comandi distruttivi: due buchi della stessa famiglia.

Il primo: un file si scrive in due tempi e un crash lascia la versione
rotta. Il secondo: `rm -rf src/` sta dentro la root, quindi il confine
non lo ferma, e il checkpoint non copre le cancellazioni.

Si verifica il comportamento vero, non la presenza della funzione: si
rompe `os.replace` e si guarda se il file di partenza e' ancora intero.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT_TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_TESTS)

_root = tempfile.mkdtemp(prefix="sicura-")
os.environ["ORCHESTRA_ROOT"] = _root
os.environ.pop("ORCHESTRA_HOME", None)

from orchestra import policy, scrittura  # noqa: E402
from orchestra import tools as T  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("\n[1] Scrivere non lascia il file a meta'")
p = Path(_root) / "sottocartella" / "nota.txt"
scrittura.scrivi_testo(p, "prima versione\n")
check("il file c'e' e ha il contenuto esatto",
      p.read_text(encoding="utf-8") == "prima versione\n", p and "contenuto diverso")
check("la cartella e' stata creata", p.parent.is_dir())

# Il crash nel punto peggiore: fra la scrittura del temporaneo e la
# sostituzione. Se il codice scrivesse direttamente sul file, qui il
# vecchio contenuto sarebbe gia' perso.
with mock.patch("orchestra.scrittura.os.replace", side_effect=OSError("disco pieno")):
    try:
        scrittura.scrivi_testo(p, "seconda versione")
        rotto = False
    except OSError:
        rotto = True
check("l'errore arriva a chi chiama", rotto)
check("il file vecchio e' intatto",
      p.read_text(encoding="utf-8") == "prima versione\n",
      p.read_text(encoding="utf-8"))
avanzi = [f.name for f in p.parent.iterdir() if f.name.startswith(".orchestra-")]
check("nessun temporaneo lasciato in giro", avanzi == [], str(avanzi))

print("\n[2] I tool scrivono con la stessa strada")
registro = T.default_registry()
tools = {t.name: t for t in (registro.tool(n) for n in (
    "write_file", "edit_file", "run_shell")) if t is not None}
scrittura_tool = tools.get("write_file")
check("write_file esiste", scrittura_tool is not None)
if scrittura_tool:
    esito = scrittura_tool.handler(path="dentro.txt", content="ciao\n")
    check("scrive e lo dice", "creato" in esito, esito)
    check("il contenuto e' quello richiesto",
          (Path(_root) / "dentro.txt").read_text(encoding="utf-8") == "ciao\n")
edit = tools.get("edit_file")
if edit:
    (Path(_root) / "edit.txt").write_text("rosso verde", encoding="utf-8")
    esito = edit.handler(path="edit.txt", trova="verde", sostituisci="blu")
    check("edit_file modifica e lo dice", "1" in esito, esito)
    check("il file contiene la sostituzione",
          (Path(_root) / "edit.txt").read_text(encoding="utf-8") == "rosso blu",
          (Path(_root) / "edit.txt").read_text(encoding="utf-8"))

print("\n[3] Cosa va chiesto e cosa no")
da_chiedere = [
    "rm -rf build",
    "rm -f vecchio.log",
    "git reset --hard",
    "git clean -fd",
    "git checkout -- .",
    "git stash drop",
    "del /s /q temp",
    "Remove-Item -Recurse -Force out",
    "rd /s /q cache",
    "truncate -s 0 dati.json",
]
for cmd in da_chiedere:
    check(f"chiede per: {cmd}", policy.rischio_operativo(cmd) is not None,
          str(policy.rischio_operativo(cmd)))
normali = [
    "git status",
    "npm test",
    "rm nota.txt",
    "python -m pytest -q",
    "git commit -m 'x'",
    "cat README.md",
]
for cmd in normali:
    check(f"non chiede per: {cmd}", policy.rischio_operativo(cmd) is None,
          str(policy.rischio_operativo(cmd)))
check("`rm -rf /` resta bloccato, non solo confermato",
      policy.motivo_blocco("rm -rf /") is not None)

print("\n[4] Senza nessuno a cui chiedere, non si esegue")
shell = tools.get("run_shell")
check("run_shell esiste", shell is not None)
if shell:
    os.environ.pop("ORCHESTRA_CONSENTI_DISTRUTTIVI", None)
    T.set_permission_gate(None)
    cartella = Path(_root) / "lavoro"
    cartella.mkdir(exist_ok=True)
    (cartella / "importante.txt").write_text("non cancellarmi", encoding="utf-8")
    # Il comando viene rifiutato PRIMA di partire: il file deve esserci
    # ancora, e questo e' il controllo che conta.
    esito = shell.handler(command="rm -rf lavoro")
    check("il rifiuto lo dice", "NON ESEGUITO" in esito, esito[:120])
    check("il file e' ancora li'", (cartella / "importante.txt").exists())

print("\n[5] Con il gate, si chiede e si rispetta la risposta")
if shell:
    class GateFinto:
        def __init__(self, risposta):
            self.risposta = risposta
            self.domande = []

        def chiedi_all_utente(self, percorso, azione, dettaglio=""):
            self.domande.append((percorso, azione, dettaglio))
            return self.risposta

    gate = GateFinto(False)
    T.set_permission_gate(gate)
    esito = shell.handler(command="rm -rf lavoro")
    check("ha chiesto", len(gate.domande) == 1, str(gate.domande))
    check("come azione distruttiva, non 'eseguire'",
          gate.domande and gate.domande[0][1] == "distruggere",
          str(gate.domande))
    check("il no ferma il comando", "NON ESEGUITO" in esito, esito[:120])
    check("il file e' ancora li'", (cartella / "importante.txt").exists())

    gate = GateFinto(True)
    T.set_permission_gate(gate)
    shell.handler(command="rm -rf lavoro")
    check("il si esegue", not (cartella / "importante.txt").exists())
    # Un comando innocuo non deve passare dal permesso dei distruttivi.
    gate2 = GateFinto(True)
    T.set_permission_gate(gate2)
    esito = shell.handler(command="git status --short")
    check("un comando normale non chiede", not gate2.domande, str(gate2.domande))
    T.set_permission_gate(None)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
