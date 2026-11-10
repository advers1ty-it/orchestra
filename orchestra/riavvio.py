"""Rilanciare il server senza chiudere e riaprire l'applicazione.

Da Telegram il riavvio e' un comando: il processo che risponde in chat
deve diventare quello nuovo, senza che nessuno tocchi il computer. Qui
c'e' l'unica cosa che serve sapere per farlo: con che riga di comando e'
partito questo processo.

PERCHE' NON BASTA `sys.argv`

Il launcher avvia `python -m orchestra.cli web --port 8737 --no-browser`.
In quel caso `sys.argv[0]` e' il percorso di `orchestra/cli.py`, non
l'interprete: eseguirlo come script romperebbe gli import relativi del
pacchetto. `sys.orig_argv` (Python 3.10+) tiene invece la riga vera,
compreso il `-m`, ed e' quella che si rilancia. Se manca, si ricostruisce
dal nome del modulo in `__main__`, e in ultima istanza si prova
`[interprete] + argv`, che e' giusto per un programma avviato come file
singolo.

PERCHE' `execv` E NON UN SOTTOPROCESSO

Un `Popen` seguito da `os._exit` lascerebbe due processi per un istante e
un pid nuovo da inseguire; `execv` sostituisce l'immagine del processo,
quindi il pid resta lo stesso e non c'e' nessun genitore da aspettare.
Le socket di ascolto non vengono ereditate (PEP 446 le rende non
ereditabili), quindi la porta si libera da sola.
"""

from __future__ import annotations

import os
import sys


def comando_riavvio(argv: list[str] | None = None,
                    executable: str | None = None, *,
                    frozen: bool | None = None,
                    orig_argv: list[str] | None = None) -> list[str]:
    """La riga che rilancia questo processo com'e' adesso.

    Gli argomenti sono parametri per i test, non opzioni da riga di
    comando: `argv` e `executable` sostituiscono `sys.argv` e
    `sys.executable`, `orig_argv` sostituisce `sys.orig_argv` e `frozen`
    il caso dell'eseguibile impacchettato.
    """
    argv = list(sys.argv if argv is None else argv)
    exe = executable or sys.executable
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        # Un eseguibile non ha un modulo da rilanciare: e' l'eseguibile
        # stesso, con gli argomenti di adesso (argv[0] e' il suo percorso).
        return [exe] + argv[1:]
    if orig_argv is None:
        orig_argv = getattr(sys, "orig_argv", None)
    if orig_argv:
        # `python -m orchestra.cli web ...`: la riga originale, che e'
        # l'unica a sapere che si e' partiti da un modulo. Il primo
        # elemento e' l'interprete di allora: si usa quello di adesso,
        # che puo' essere un venv diverso.
        return [exe] + [str(a) for a in list(orig_argv)[1:]]
    # Ripiego senza `orig_argv`: il modulo in esecuzione, se c'e'. Un
    # `-m` ricostruito e' meglio di un file di modulo eseguito come
    # script, che perderebbe gli import relativi del pacchetto.
    modulo = getattr(sys.modules.get("__main__"), "__spec__", None)
    nome = getattr(modulo, "name", "") or ""
    if nome:
        return [exe, "-m", nome] + argv[1:]
    return [exe] + argv


def riavvia(argv: list[str] | None = None) -> None:
    """Sostituisce il processo con uno identico. Non torna indietro.

    Chi chiama ha gia' fermato cron, processi dei tool e tunnel: qui
    resta solo da svuotare i buffer (o le ultime righe di log andrebbero
    perse con l'immagine vecchia) e cedere il posto.
    """
    comando = comando_riavvio(argv)
    for flusso in (sys.stdout, sys.stderr):
        try:
            flusso.flush()
        except Exception:  # noqa: BLE001 - un buffer chiuso non ferma il riavvio
            pass
    os.execv(comando[0], comando)
