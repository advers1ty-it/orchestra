"""L'installer Linux: un file, con la stessa forma di quello Windows.

Non prova a scaricare GitHub: la rete non e' una dipendenza del test. Controlla
le cose che si possono rompere in silenzio — CRLF in uno script che Linux non
sa eseguire, sintassi bash rotta, un installer che non crea il venv o non
mette il comando `orchestra`, un launcher che non conosce start/stop/log.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def leggi(percorso: str) -> str:
    with open(percorso, encoding="utf-8", newline="") as f:
        return f.read()


INSTALLER = os.path.join(ROOT, "installer", "Installa-Orchestra.sh")
LAUNCH = os.path.join(ROOT, "Orchestra.sh")
AVVIA = os.path.join(ROOT, "Avvia-Orchestra.sh")

print("\n[1] I file ci sono, sono eseguibili e sono LF")
for percorso in (INSTALLER, LAUNCH, AVVIA):
    nome = os.path.basename(percorso)
    check(f"{nome} esiste", os.path.isfile(percorso), percorso)
    if not os.path.isfile(percorso):
        continue
    testo = leggi(percorso)
    check(f"{nome} ha lo shebang bash", testo.startswith("#!/usr/bin/env bash"),
          testo[:60])
    check(f"{nome} non ha CRLF", "\r\n" not in testo, "contiene \\r\\n")
    if os.name != "nt":
        check(f"{nome} e' eseguibile", os.access(percorso, os.X_OK), percorso)

print("\n[2] La sintassi bash regge")
bash = shutil.which("bash")
if bash:
    for percorso in (INSTALLER, LAUNCH, AVVIA):
        r = subprocess.run([bash, "-n", percorso], text=True,
                           capture_output=True, timeout=30)
        check(f"{os.path.basename(percorso)}: bash -n", r.returncode == 0,
              (r.stderr or r.stdout)[:300])
else:
    print("  SKIP bash non disponibile: la sintassi non e' stata eseguita")

print("\n[3] L'installer fa le cose che servono")
testo = leggi(INSTALLER) if os.path.isfile(INSTALLER) else ""
for frammento, perche in (
    ("ORCHESTRA_RELEASE_API", "l'API della release e' sostituibile nei test"),
    ("releases/latest", "scarica l'ultima release"),
    ("venv", "crea l'ambiente isolato"),
    ("requirements.txt", "installa le funzioni aggiuntive"),
    ("--no-deps", "si puo' installare senza dipendenze"),
    ("--no-sistema", "si puo' evitare l'installazione dei pacchetti di sistema"),
    ("--sistema", "si puo' chiedere l'installazione dei pacchetti di sistema"),
    ("python3-venv", "conosce il pacchetto venv di Debian/Ubuntu"),
    ("apt-get", "supporta Debian/Ubuntu"),
    ("dnf", "supporta Fedora"),
    ("pacman", "supporta Arch"),
    ("zypper", "supporta openSUSE"),
    ("apk", "supporta Alpine"),
    (".local/bin", "registra il comando orchestra"),
    ("applications", "crea il launcher del menu"),
    ("ca-certificates", "spiega come riparare i certificati su Linux"),
):
    check(f"contiene {perche}", frammento in testo, frammento)

print("\n[4] Il launcher conosce i comandi veri")
launch = leggi(LAUNCH) if os.path.isfile(LAUNCH) else ""
for comando in ("avvia", "ferma", "riavvia", "log", "stato"):
    check(f"gestisce {comando}", comando in launch, comando)
check("non uccide per nome tutti i processi", "pkill -f" not in launch,
      "un pattern largo puo' colpire processi estranei")
check("aspetta la porta prima di dire pronto", "_attendi_porta" in launch)
check("scrive il PID in un file", "orchestra.pid" in launch)
check("valida il PID letto", "read -r pid" in launch)
check("riconosce il processo solo sulla porta giusta", "--port $PORTA" in launch)
check("distingue un processo vivo da un server in ascolto", "non risponde" in launch)

print("\n[5] La CLI e il launcher, senza avviare il server")
if bash:
    r = subprocess.run([bash, INSTALLER, "--help"], text=True,
                       capture_output=True, timeout=30)
    check("installer --help: 0", r.returncode == 0, r.stderr[:300])
    check("--help spiega --no-deps", "--no-deps" in r.stdout, r.stdout[:300])
    check("--help spiega --no-sistema", "--no-sistema" in r.stdout, r.stdout[:300])
    r2 = subprocess.run([bash, LAUNCH, "aiuto"], text=True,
                        capture_output=True, timeout=30)
    check("launcher aiuto: 0", r2.returncode == 0, r2.stderr[:300])
    check("aiuto nomina ferma", "ferma" in r2.stdout, r2.stdout[:300])
else:
    print("  SKIP comandi: bash non disponibile")

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
