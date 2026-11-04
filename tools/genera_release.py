"""Costruisce l'asset .zip di una release, nel formato che l'updater vuole.

PERCHE' ESISTE

La 0.5.69 e' stata pubblicata con uno zip "piatto": i file alla radice
dell'archivio invece che dentro una sola cartella. L'updater rifiuta un
archivio con piu' radici — e ha ragione, perche' non saprebbe cosa
sovrascrivere — quindi l'aggiornamento falliva con "zip della release con
piu' radici" e restava la versione locale.

Il formato giusto e' quello che `git archive --prefix` produce: una sola
cartella `<nome-versione>/` con dentro tutto il tracciato. Non c'e'
motivo di costruirlo a mano, e ogni volta che lo si costruisce a mano si
puo' sbagliare di nuovo.

    python tools/genera_release.py            # versione dal pacchetto
    python tools/genera_release.py 0.5.70     # versione esplicita

Scrive `orchestra-<versione>.zip` nella cartella corrente e stampa il
digest sha256 da confrontare con quello dell'asset caricato.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import zipfile


def versione(root: str) -> str:
    with open(os.path.join(root, "orchestra", "__init__.py"),
              encoding="utf-8") as f:
        m = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", f.read())
    if not m:
        raise SystemExit("versione non trovata in orchestra/__init__.py")
    return m.group(1)


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ver = sys.argv[1] if len(sys.argv) > 1 else versione(root)
    prefisso = f"orchestra-{ver}/"
    out = os.path.join(os.getcwd(), f"orchestra-{ver}.zip")
    if os.path.exists(out):
        os.remove(out)
    # `git archive` prende solo i file tracciati: niente dati locali,
    # niente chiavi, niente .cloud-attachments. Ed e' l'unico modo per
    # avere il prefisso di cartella senza riscriverlo a mano.
    r = subprocess.run(
        ["git", "archive", "--format=zip", f"--prefix={prefisso}",
         "-o", out, "HEAD"],
        cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr.strip() or "git archive fallito", file=sys.stderr)
        return 1

    with zipfile.ZipFile(out) as z:
        nomi = [n for n in z.namelist() if not n.endswith("/")]
        radici = {n.split("/")[0] for n in nomi}
    if radici != {f"orchestra-{ver}"}:
        print(f"ERRORE: radici multiple nell'archivio: {sorted(radici)}",
              file=sys.stderr)
        return 1
    # La versione dentro l'archivio deve essere quella del nome: un asset
    # chiamato 0.5.70 che si presenta come 0.5.69 farebbe aggiornare per
    # sempre.
    with zipfile.ZipFile(out) as z:
        with z.open(prefisso + "orchestra/__init__.py") as f:
            testo = f.read().decode("utf-8")
    m = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", testo)
    if not m or m.group(1) != ver:
        print(f"ERRORE: dentro l'archivio c'e' la versione "
              f"{m.group(1) if m else '?'}, non {ver}", file=sys.stderr)
        return 1

    with open(out, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    print(f"{out}")
    print(f"{len(nomi)} file, {os.path.getsize(out) // 1024} KB")
    print(f"sha256:{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
