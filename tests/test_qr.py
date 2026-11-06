"""Il QR: struttura, non bellezza.

Questo test non prova che un telefono lo legga — quello l'ho verificato
a mano facendo rileggere le matrici a zbar, che non e' una dipendenza di
Orchestra e non entra nella suite. Qui si controlla quello che puo'
rompersi senza che nessuno se ne accorga:

  - la dimensione corrisponde alla versione giusta;
  - i tre pattern di posizione ci sono, e la riga/colonna dei tempi
    alterna come deve (un errore li' sposta tutti i bit di uno, e il QR
    diventa un rettangolo di rumore);
  - i testi troppo lunghi dicono di esserlo, invece di produrre una
    matrice sbagliata;
  - l'SVG e' quello che il pannello si aspetta.
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestra.qr as qr  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" -- {dettaglio}" if dettaglio and not cond else ""))


def pattern_posizione(m, riga, colonna):
    """Il 7x7 del pattern: anello scuro, dentro chiaro, nucleo scuro."""
    for r in range(7):
        for c in range(7):
            scuro = r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)
            if bool(m[riga + r][colonna + c]) != scuro:
                return False
    return True


print("\n[1] dimensioni e versione")
casi = {
    "ciao": 1,
    "https://t.me/o?start=a": 2,
    "https://t.me/prova_bot?start=abcdefgh": 3,
    "https://t.me/orchestra_assistente_bot?start=k7m2nq4p": 3,
    "https://t.me/b?start=" + "z" * 90: 6,
}
for testo, versione in casi.items():
    m = qr.matrice(testo)
    lato_atteso = versione * 4 + 17
    check(f"{len(testo.encode())} byte -> versione {versione}",
          len(m) == lato_atteso and len(m[0]) == lato_atteso,
          f"lato {len(m)} invece di {lato_atteso}")

print("\n[2] i pattern che un lettore cerca per primo")
m = qr.matrice("https://t.me/prova_bot?start=abcdefgh")
n = len(m)
check("pattern in alto a sinistra", pattern_posizione(m, 0, 0))
check("pattern in alto a destra", pattern_posizione(m, 0, n - 7))
check("pattern in basso a sinistra", pattern_posizione(m, n - 7, 0))
check("la riga dei tempi alterna",
      all(m[6][i] == (1 if i % 2 == 0 else 0) for i in range(8, n - 8)),
      str([m[6][i] for i in range(8, n - 8)]))
check("la colonna dei tempi alterna",
      all(m[i][6] == (1 if i % 2 == 0 else 0) for i in range(8, n - 8)),
      str([m[i][6] for i in range(8, n - 8)]))
check("il modulo sempre scuro c'e'", m[n - 8][8] == 1)
check("ogni cella ha un valore (0 o 1)",
      all(v in (0, 1) for fila in m for v in fila))

print("\n[3] la stessa stringa da' sempre lo stesso disegno")
a = qr.matrice("https://t.me/prova_bot?start=abcdefgh")
b = qr.matrice("https://t.me/prova_bot?start=abcdefgh")
check("due chiamate, stessa matrice", a == b)
impronta = hashlib.sha256(
    "\n".join("".join(str(v) for v in fila) for fila in a).encode()
).hexdigest()[:16]
# Blocca la matrice di oggi: se un giorno un ritocco la cambia, lo dice
# qui invece di dirlo un telefono che non legge piu'.
# Un blocco volontario: questa matrice l'ho fatta rileggere da zbar (13
# casi, versioni 1-10) e questo e' il suo impronta. Se un ritocco la
# cambia, lo dice qui invece di dirlo un telefono che non legge piu'.
check("la matrice non e' cambiata sotto i piedi",
      impronta == "332ddfef98fbe38b", impronta)

print("\n[4] i testi troppo lunghi lo dicono")
try:
    qr.matrice("x" * 272)
    check("272 byte vengono rifiutati", False)
except qr.ErroreQR:
    check("272 byte vengono rifiutati", True)
check("271 byte entrano", len(qr.matrice("x" * 271)) == 57)

print("\n[5] l'SVG si puo' mostrare")
disegno = qr.svg("https://t.me/prova_bot?start=abcdefgh", modulo=5, bordo=3)
lato = (len(m) + 6) * 5
check("e' un documento svg", disegno.startswith("<svg")
      and disegno.endswith("</svg>"))
check("ha le misure giuste", f'width="{lato}"' in disegno,
      disegno[:120])
check("lo sfondo bianco c'e'", 'fill="#fff"' in disegno)
check("i moduli neri sono rettangoli", disegno.count("<rect") > 50,
      str(disegno.count("<rect")))
check("niente testo dentro (non c'e' niente da iniettare)",
      "<text" not in disegno and "<script" not in disegno)

print()
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("falliti:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
