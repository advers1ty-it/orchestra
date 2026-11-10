"""La cartella dati non finisce in un repository.

`ORCHESTRA_HOME` e' una scelta esplicita, e puo' puntare dentro un
progetto. Se ci punta, un `git add -A` basta a portare permessi,
storico e chiavi in un commit: qui si verifica che la cartella si
protegga da sola, che sulla radice del repository Orchestra si fermi
invece di ignorare il progetto intero, e che fuori da git non cambi
niente.
"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import dati  # noqa: E402
from orchestra import permessi_persistenza as pp  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)


vecchio_home = os.environ.get("ORCHESTRA_HOME")
vecchio_forza = os.environ.get("ORCHESTRA_HOME_FORZA")
radice = tempfile.mkdtemp(prefix="dati-home-")
repo = os.path.join(radice, "progetto")
os.makedirs(repo)
git("init", "-q", cwd=repo)

try:
    print("\n[1] Dentro un repository la cartella si ignora da sola")
    os.environ["ORCHESTRA_HOME"] = os.path.join(repo, "dati")
    os.environ.pop("ORCHESTRA_HOME_FORZA", None)
    dati._PROTETTE.clear()
    cartella = dati.cartella_dati()
    check("la cartella esiste", os.path.isdir(cartella), cartella)
    ignora = os.path.join(cartella, ".gitignore")
    check("il .gitignore c'e'", os.path.isfile(ignora))
    testo = open(ignora, encoding="utf-8").read() if os.path.exists(ignora) else ""
    check("ignora tutto", "*" in testo.split(), testo)

    # La prova che conta: il file dei permessi viene scritto davvero e
    # git continua a non vederlo.
    pp.salva(["C:\\progetti\\segreto"], [])
    check("permessi.json e' stato scritto",
          os.path.isfile(os.path.join(cartella, "permessi.json")))
    stato = git("status", "--porcelain", cwd=repo)
    check("git status resta pulito", stato.stdout.strip() == "", stato.stdout)

    print("\n[2] Sulla radice del repository si rifiuta di partire")
    os.environ["ORCHESTRA_HOME"] = repo
    os.environ.pop("ORCHESTRA_HOME_FORZA", None)
    dati._PROTETTE.clear()
    errore = None
    try:
        dati.cartella_dati()
    except RuntimeError as e:
        errore = str(e)
    check("solleva con un messaggio utile",
          errore is not None and "ORCHESTRA_HOME" in errore, str(errore))
    check("non scrive un .gitignore che ignorerebbe il progetto",
          not os.path.exists(os.path.join(repo, ".gitignore")))

    print("\n[3] Con ORCHESTRA_HOME_FORZA=1 si puo' forzare")
    os.environ["ORCHESTRA_HOME_FORZA"] = "1"
    dati._PROTETTE.clear()
    try:
        dati.cartella_dati()
        partito = True
    except RuntimeError:
        partito = False
    check("parte", partito)
    check("e non tocca il .gitignore del progetto",
          not os.path.exists(os.path.join(repo, ".gitignore")))

    print("\n[4] Fuori da un repository non si scrive niente")
    os.environ.pop("ORCHESTRA_HOME_FORZA", None)
    fuori = tempfile.mkdtemp(prefix="dati-fuori-")
    os.environ["ORCHESTRA_HOME"] = fuori
    dati._PROTETTE.clear()
    dati.cartella_dati()
    check("nessun .gitignore",
          not os.path.exists(os.path.join(fuori, ".gitignore")))
finally:
    if vecchio_home is None:
        os.environ.pop("ORCHESTRA_HOME", None)
    else:
        os.environ["ORCHESTRA_HOME"] = vecchio_home
    if vecchio_forza is None:
        os.environ.pop("ORCHESTRA_HOME_FORZA", None)
    else:
        os.environ["ORCHESTRA_HOME_FORZA"] = vecchio_forza
    dati._PROTETTE.clear()
    shutil.rmtree(radice, ignore_errors=True)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
