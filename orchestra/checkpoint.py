"""Checkpoint dei file: com'era un file prima che l'agente lo toccasse.

PERCHE' ESISTE

Un agente che scrive e' utile; un agente che scrive e non si puo'
annullare e' un rischio che un utente senza competenze non dovrebbe
correre. Prima `write_file` riscriveva diretto: se il modello sbagliava
file, l'unica copia era quella gia' sovrascritta. I worktree isolano i
bot, non la chat.

Qui ogni scrittura lascia una copia di com'era prima, e `annulla_ultima`
rimette a posto l'ultima. E' un undo a passi: clicca due volte e torni
indietro due scritture.

COSA NON E'

Non e' un sistema di versionamento e non e' git: non unisce, non
confligge, non conserva la storia per sempre. Tiene le ultime `MAX_VOCI`
scritture e butta le piu' vecchie. Un file da oltre `MAX_BYTE` non viene
copiato: meglio dire "questo non si annulla" che riempire il disco di
copie e scoprirlo dopo.

DOVE STANNO

Nella cartella dati di Orchestra (`dati.percorso("checkpoint")`), non nel
progetto: un `.checkpoint` nella root finirebbe nei diff, nei commit e
nelle ricerche dell'agente. La copia e' legata al percorso assoluto, e
l'annullamento la rimette dov'era.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# Quante scritture si possono annullare all'indietro. Trenta copre un
# turno di lavoro normale senza trasformare la cartella dati in un
# archivio.
MAX_VOCI = 30
# Un file oltre questo non si copia. Non e' un limite di sicurezza: e'
# il punto in cui una copia costa piu' di quanto l'annullamento valga.
MAX_BYTE = 5_000_000

_LOCK = threading.RLock()


def _dir() -> Path:
    from .dati import percorso

    p = Path(percorso("checkpoint"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _manifest() -> Path:
    return _dir() / "manifest.json"


def _voci() -> list[dict[str, Any]]:
    try:
        with open(_manifest(), encoding="utf-8") as f:
            data = json.load(f)
        voci = data.get("voci") if isinstance(data, dict) else data
        return [v for v in (voci or []) if isinstance(v, dict)]
    except (OSError, ValueError, TypeError):
        return []


def _salva(voci: list[dict[str, Any]]) -> None:
    """Scrittura atomica: un manifest troncato perderebbe tutti i backup."""
    p = _manifest()
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"voci": voci}, f, indent=1)
    os.replace(tmp, p)


def _prune(voci: list[dict[str, Any]]) -> None:
    while len(voci) > MAX_VOCI:
        vecchia = voci.pop(0)
        nome = vecchia.get("backup")
        if nome:
            try:
                (_dir() / nome).unlink()
            except OSError:
                pass


def _accoda(voce: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        voci = _voci()
        voci.append(voce)
        _prune(voci)
        _salva(voci)
    return voce


def registra(p: Path, radice: Path, azione: str) -> dict[str, Any] | None:
    """Salva com'era `p` prima della scrittura. None se non si puo'.

    Non solleva mai: un checkpoint fallito non deve impedire di salvare
    il lavoro. Quando la copia non e' possibile lascia una voce
    `saltata` invece di niente: cosi' l'undo si ferma li' e dice perche',
    anziche' saltare indietro a una modifica precedente e sembrare che
    abbia annullato quella sbagliata.
    """
    try:
        p = Path(p)
        voce: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "ts": time.time(),
            "assoluto": str(p),
            "azione": azione,
            "esisteva": p.is_file(),
            "backup": "",
            "byte": 0,
        }
        try:
            voce["percorso"] = p.relative_to(Path(radice)).as_posix()
        except (ValueError, OSError):
            voce["percorso"] = str(p)
        if voce["esisteva"]:
            try:
                voce["byte"] = p.stat().st_size
            except OSError as e:
                voce["saltata"] = f"non riesco a leggere il file: {e}"
                return _accoda(voce)
            if voce["byte"] > MAX_BYTE:
                voce["saltata"] = (
                    f"il file supera {MAX_BYTE} byte e non ne ho copiato "
                    f"una versione")
                return _accoda(voce)
            dest = _dir() / f"{voce['id']}.bak"
            try:
                shutil.copy2(p, dest)
            except OSError as e:
                voce["saltata"] = f"copia di sicurezza fallita: {e}"
                return _accoda(voce)
            voce["backup"] = dest.name
        return _accoda(voce)
    except Exception:  # noqa: BLE001 - non deve mai fermare la scrittura
        return None


def annulla_ultima() -> dict[str, Any] | None:
    """Rimette a posto l'ultima scrittura. None se non c'e' niente.

    Solleva RuntimeError se il backup esiste nel manifest ma non sul
    disco: e' l'unico caso in cui non si puo' mantenere la promessa, e
    va detto invece di dire "annullato" senza aver toccato niente.
    """
    with _LOCK:
        voci = _voci()
        if not voci:
            return None
        voce = voci.pop()
        if voce.get("saltata"):
            # La voce serviva a fermare l'undo qui: consumata, si toglie.
            _salva(voci)
            raise RuntimeError(
                f"questa modifica non e' annullabile: {voce['saltata']}")
        p = Path(str(voce.get("assoluto") or ""))
        if not str(p):
            _salva(voci)
            raise RuntimeError("checkpoint senza percorso")
        try:
            if voce.get("esisteva") and voce.get("backup"):
                src = _dir() / str(voce["backup"])
                if not src.is_file():
                    voci.append(voce)
                    _salva(voci)
                    raise RuntimeError(
                        "la copia di sicurezza non c'e' piu': non posso "
                        "rimettere il file com'era")
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, p)
                azione = "ripristinato"
            elif not voce.get("esisteva"):
                if p.is_file():
                    p.unlink()
                azione = "rimosso"
            else:
                voci.append(voce)
                _salva(voci)
                raise RuntimeError("checkpoint senza copia di sicurezza")
        except RuntimeError:
            raise
        except OSError as e:
            voci.append(voce)
            _salva(voci)
            raise RuntimeError(f"non riesco ad annullare: {e}") from e
        nome = voce.get("backup")
        if nome:
            try:
                (_dir() / str(nome)).unlink()
            except OSError:
                pass
        _salva(voci)
        return {**voce, "azione_fatta": azione}


def storico(limite: int = MAX_VOCI) -> list[dict[str, Any]]:
    """Le ultime scritture, dalla piu' recente. Per la UI e i test."""
    with _LOCK:
        return list(reversed(_voci()))[:limite]


def svuota() -> None:
    """Solo per i test: azzera registro e copie."""
    with _LOCK:
        for voce in _voci():
            nome = voce.get("backup")
            if nome:
                try:
                    (_dir() / str(nome)).unlink()
                except OSError:
                    pass
        _salva([])
