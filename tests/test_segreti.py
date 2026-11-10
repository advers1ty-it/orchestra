"""I file dei segreti non devono essere leggibili da altri utenti.

`keys.py` scriveva gia' 0600; il token remoto, il token Nous e lo stato
del tunnel no. Questo test prova l'helper condiviso: contenuto, scrittura
atomica di fatto (il file c'e' e non e' vuoto) e permessi su POSIX.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.segreti import rendi_privato, scrivi_privato, scrivi_privato_bytes  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def modo(percorso):
    return stat.S_IMODE(os.stat(percorso).st_mode)


tmp = tempfile.mkdtemp(prefix="segreti-")

print("[1] Scrittura di un testo")
p = os.path.join(tmp, "token.json")
scrivi_privato(p, '{"token": "x"}')
check("il file esiste", os.path.isfile(p), p)
with open(p, encoding="utf-8") as f:
    check("il contenuto e' quello scritto", f.read() == '{"token": "x"}')
if os.name != "nt":
    check("i permessi sono 0600", modo(p) == 0o600, oct(modo(p)))
else:
    print("  SKIP permessi 0600: su Windows chmod non e' un ACL completo")

print("\n[2] Un file gia' largo viene stretto")
q = os.path.join(tmp, "vecchio.json")
with open(q, "w", encoding="utf-8") as f:
    f.write("x")
os.chmod(q, 0o666)
rendi_privato(q)
if os.name != "nt":
    check("rendi_privato porta a 0600", modo(q) == 0o600, oct(modo(q)))
else:
    print("  SKIP permessi 0600 su Windows")

print("\n[3] Byte e cartelle annidate")
r = os.path.join(tmp, "config", "sotto", ".env")
scrivi_privato_bytes(r, b"A=1\nB=2\n")
check("la cartella annidata esiste", os.path.isdir(os.path.dirname(r)), r)
with open(r, "rb") as f:
    check("i byte sono intatti", f.read() == b"A=1\nB=2\n")
if os.name != "nt":
    check("anche i byte sono 0600", modo(r) == 0o600, oct(modo(r)))

print("\n[4] Nessun temporaneo lasciato dietro")
residui = [n for n in os.listdir(tmp) if n.startswith(".token.")]
check("nessun .token.* temporaneo", not residui, str(residui))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
