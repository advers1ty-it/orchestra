"""Dove stanno i file dell'installazione.

`webapp.py` e i gestori delle rotte hanno bisogno degli stessi percorsi.
Due copie della stessa derivazione (`dirname(abspath(__file__))`) sono due
posti in cui sbagliare, e sbagliare qui vuol dire leggere il `.env` di
un'altra cartella — che non fallisce: restituisce un file vuoto, e l'app
sembra senza chiavi.
"""

from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
