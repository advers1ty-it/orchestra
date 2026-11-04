"""I sorgenti del frontend, in un posto solo.

`panels.js` era un file da 5.320 righe; ora ogni area ha il suo
(`panels-bench.js`, `panels-opzioni.js`, ...). I test che leggono il
frontend non devono sapere in quale pezzo sta una funzione: chiedono il
testo dei pannelli, o il bundle, e cercano li'.

L'ordine viene da `webapp.BUNDLE_ORDER` tramite `_ordine`: e' il server a
concatenare i file, quindi e' l'unico posto dove l'ordine e' vero.
"""

import os

from _ordine import ORDER

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "orchestra", "web")

# I file dei pannelli, nell'ordine in cui il server li manda.
PANNELLI = tuple(nome for nome in ORDER if nome.startswith("panels"))


def sorgente(nome):
    with open(os.path.join(WEB, nome), encoding="utf-8") as fh:
        return fh.read()


def pannelli():
    """Tutti i pannelli concatenati: il testo del vecchio panels.js."""
    return "\n;\n".join(sorgente(nome) for nome in PANNELLI)


def bundle(senza=()):
    """Il bundle come lo serve il server, eventualmente senza un file."""
    return "\n;\n".join(sorgente(nome) for nome in ORDER if nome not in senza)
