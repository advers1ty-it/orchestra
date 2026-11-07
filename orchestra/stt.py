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


def _campioni(path: str):
    """Decodifica un file audio in float32 mono a 16 kHz.

    Non lasciamo decodificare a faster-whisper: la 1.2.1 chiama
    `av.open(..., metadata_errors="ignore")`, e PyAV 19 ha tolto quel
    parametro. Con av 19 installato (che e' quello che pip mette adesso)
    ogni vocale moriva su `TypeError: open() got an unexpected keyword
    argument 'metadata_errors'` prima ancora di leggere l'audio: il
    difetto era nella coppia di librerie, non nel file dell'utente.
    Qui l'apertura la facciamo noi, senza quel parametro, che e' valido
    sia con PyAV vecchio sia con PyAV 19; il modello accetta campioni
    gia' decodificati e non ci passa piu'.
    """
    import av
    import numpy as np

    pezzi = []
    with av.open(path, mode="r") as contenitore:
        if not contenitore.streams.audio:
            raise RuntimeError("il file non contiene audio")
        ricampionatore = av.AudioResampler(format="flt", layout="mono",
                                           rate=16000)
        for frame in contenitore.decode(contenitore.streams.audio[0]):
            for nuovo in ricampionatore.resample(frame):
                pezzi.append(nuovo.to_ndarray().reshape(-1))
        for nuovo in ricampionatore.resample(None):
            pezzi.append(nuovo.to_ndarray().reshape(-1))
    if not pezzi:
        raise RuntimeError("l'audio e' vuoto")
    return np.concatenate(pezzi).astype(np.float32)


def trascrivi(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    if not disponibile():
        raise RuntimeError("whisper non installato")
    model = _modello()
    suffix = os.path.splitext(filename or "")[1] or ".webm"
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio_bytes)
        # Se la decodifica nostra non riesce (av assente, contenitore
        # strano) si ripiega sul percorso: cosi' un ambiente sano
        # continua a funzionare come prima.
        try:
            sorgente = _campioni(path)
        except Exception:  # noqa: BLE001
            sorgente = path
        segments, info = model.transcribe(
            sorgente, language=(_LANG or None), beam_size=1)
        testo = " ".join((s.text or "").strip() for s in segments).strip()
        return testo
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
