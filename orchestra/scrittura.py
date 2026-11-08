"""Scrittura di un file di testo senza lasciarne una versione a meta'.

Perche' un modulo e non due righe dentro i tool.

`Path.write_text` apre il file, lo tronca e scrive. Se il processo muore
fra il troncamento e la fine — un crash, un `kill`, Windows che chiude la
macchina — il file resta a zero byte o tagliato a meta', e la versione
buona non esiste piu'. Il checkpoint aiuta, ma e' la copia di PRIMA: chi
riapre il progetto trova un file rotto e deve sapere che esiste un undo.

La scrittura atomica toglie il problema alla radice: si scrive tutto su
un file temporaneo nella stessa cartella, si forza il contenuto sul disco
e poi si sostituisce il vecchio con `os.replace`, che sul filesystem e'
un'operazione sola. O c'e' il file vecchio, o c'e' quello nuovo: mai un
file a meta'.

La stessa cartella non e' un dettaglio: `os.replace` e' atomico solo
dentro lo stesso filesystem, e la cartella temporanea di sistema puo'
stare su un altro disco (o su un altro punto di mount).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def scrivi_testo(percorso: str | Path, testo: str) -> None:
    """Scrive `testo` in `percorso` in modo atomico, in UTF-8.

    Solleva OSError come farebbe `write_text`: chi chiama gia' gestisce
    il caso "non ho i permessi" e non deve scoprire un tipo nuovo.
    """
    _scrivi_atomico(percorso, testo.encode("utf-8"))


def scrivi_bytes(percorso: str | Path, dati: bytes) -> None:
    """Scrive `dati` in modo atomico, byte per byte.

    Serve a chi modifica un file che non era UTF-8: `edit_file` legge un
    .txt cp1252, sostituisce una riga e deve restituirlo in cp1252. Con
    `scrivi_testo` il file tornerebbe UTF-8, cioe' cambiato in tutte le
    righe con un accento — lo stesso danno dei fine riga, in un'altra
    forma. I byte sono l'unica scrittura che non decide niente al posto
    di chi chiama.
    """
    _scrivi_atomico(percorso, dati)


def _scrivi_atomico(percorso: str | Path, dati: bytes) -> None:
    p = Path(percorso)
    cartella = p.parent
    cartella.mkdir(parents=True, exist_ok=True)

    fd, temporaneo = tempfile.mkstemp(prefix=".orchestra-", dir=str(cartella))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dati)
            f.flush()
            # Senza fsync il contenuto puo' essere ancora nella cache del
            # sistema quando `os.replace` rende visibile il nome nuovo:
            # un blackout lascerebbe il nome giusto e il contenuto vuoto.
            os.fsync(f.fileno())
        if p.exists():
            # Il file temporaneo nasce con i permessi di mkstemp (0600):
            # senza questo, sovrascrivere un file leggibile da altri lo
            # renderebbe privato, e il cambio non si nota finche' qualcosa
            # non prova ad aprirlo.
            try:
                shutil.copymode(p, temporaneo)
            except OSError:
                pass
        os.replace(temporaneo, p)
    except BaseException:
        # Anche su KeyboardInterrupt: un temporaneo orfano nella cartella
        # di lavoro e' spazzatura che nessuno riconosce come propria.
        try:
            os.unlink(temporaneo)
        except OSError:
            pass
        raise
