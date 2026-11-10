"""File che contengono segreti: scritti in modo atomico e privati.

Un token in un file 0644 e' un token che ogni altro utente della macchina
puo' leggere. `keys.py` lo faceva gia' bene; gli altri file no. Qui c'e'
una sola implementazione: si scrive su un temporaneo nella stessa
cartella, si mettono i permessi prima di pubblicarlo, e si sostituisce
con `os.replace` (atomico sullo stesso filesystem).

Su Windows `os.chmod` non e' un ACL completo: il file resta protetto
dagli ACL ereditati della cartella, e questo helper non li peggiora. Su
POSIX il file e' 0600, che e' quello che serve.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def rendi_privato(path: str | os.PathLike[str]) -> None:
    """Prova a portare un file esistente a 0600. Non solleva mai."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _scrivi(path: str | os.PathLike[str], dati: bytes) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dati)
            f.flush()
            os.fsync(f.fileno())
        # Prima del replace: il file non e' mai visibile con permessi larghi.
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, p)
        rendi_privato(p)
        return p
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def scrivi_privato(path: str | os.PathLike[str], testo: str) -> Path:
    """Scrive `testo` in UTF-8, atomico, con permessi da segreto."""
    return _scrivi(path, testo.encode("utf-8"))


def scrivi_privato_bytes(path: str | os.PathLike[str], dati: bytes) -> Path:
    """Come `scrivi_privato`, per contenuti gia' in byte (es. un `.env`)."""
    return _scrivi(path, bytes(dati))
