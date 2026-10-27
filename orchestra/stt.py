"""Speech-to-text opzionale basato su faster-whisper.

Modulo opzionale: se faster-whisper non e' installato, disponibile()
ritorna False e le funzioni di trascrizione sollevano RuntimeError.
L'installazione e' guidata dall'app (endpoint /api/stt/install), come
per cloudflared nel tunneling: l'utente non deve sapere pip.
"""
import io
import os
import subprocess
import sys
import tempfile
import threading
import time

_MODEL = None
_MODEL_NAME = os.environ.get("ORCHESTRA_STT_MODEL", "base")
_LANG = os.environ.get("ORCHESTRA_STT_LANG", "it")
_lock = threading.Lock()

_install_state = {"status": "idle", "error": None, "started": 0.0}
_install_thread = None


def disponibile() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def stato() -> dict:
    return {
        "disponibile": disponibile(),
        "installazione": _install_state["status"],
        "errore": _install_state["error"],
    }


def _installa_worker() -> None:
    global _install_state
    _install_state = {"status": "installing", "error": None, "started": time.time()}
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "faster-whisper"],
            capture_output=True, text=True, timeout=600,
        )
        if r.returncode == 0:
            _install_state["status"] = "done"
        else:
            _install_state["status"] = "error"
            _install_state["error"] = (r.stderr or r.stdout or "errore pip")[-800:]
    except Exception as e:  # noqa: BLE001
        _install_state["status"] = "error"
        _install_state["error"] = str(e)


def avvia_installazione() -> bool:
    global _install_thread
    if disponibile():
        _install_state["status"] = "done"
        return True
    if _install_state["status"] == "installing":
        return True
    _install_thread = threading.Thread(target=_installa_worker, daemon=True)
    _install_thread.start()
    return True


def _modello():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _lock:
        if _MODEL is not None:
            return _MODEL
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
        return _MODEL


def trascrivi(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    if not disponibile():
        raise RuntimeError("whisper non installato")
    model = _modello()
    suffix = os.path.splitext(filename or "")[1] or ".webm"
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio_bytes)
        segments, info = model.transcribe(
            path, language=(_LANG or None), beam_size=1)
        testo = " ".join((s.text or "").strip() for s in segments).strip()
        return testo
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
