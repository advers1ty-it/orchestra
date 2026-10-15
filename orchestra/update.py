"""Aggiornamento da GitHub per chi non ha git né account GitHub.

Flusso: legge la versione locale, chiede a GitHub l'ultima release, se
diversa scarica lo zip e lo applica sopra la cartella di installazione.

Conservati sempre (mai sovrascritti):
  .env, token.txt, goals.json di fallback, DB e contatori runtime.

Funziona anche con repo privato tramite un token di SOLA LETTURA
(contents:read sul solo repo orchestra), letto da:
  1. variabile d'ambiente ORCHESTRA_UPDATE_TOKEN
  2. file token.txt nella cartella di installazione

Col repo pubblico il token non serve piu': resta supportato solo come
ripiego se un giorno il repo tornasse privato.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass


API_RELEASES = "https://api.github.com/repos/{repo}/releases/latest"

# File/cartelle che un aggiornamento non deve mai toccare: chiavi,
# token, stato runtime. Tutto il resto viene dalla release.
CONSERVA = {
    ".env",
    "token.txt",
    "goals.json",
    "budget_global.json",
    "storico.db",
    "memoria_indice.db",
    "goals.json.tmp",
    "__pycache__",
    "_ goals_fallback",
    "_dati_test",
}


class UpdateError(RuntimeError):
    pass


@dataclass
class InfoRelease:
    tag: str
    versione: str
    zip_url: str


def scegli_asset(release: dict, fallback_zipball: str = "") -> str:
    """Sceglie lo zip da scaricare: prima un asset .zip della release,
    altrimenti lo zipball del sorgente (serve token se privato)."""
    assets = release.get("assets") or []
    for a in assets:
        url = str(a.get("browser_download_url") or "")
        nome = str(a.get("name") or "")
        if url and nome.lower().endswith(".zip"):
            return url
    return fallback_zipball or str(release.get("zipball_url") or "")


def radice_installazione() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def versione_locale() -> str:
    from . import __version__
    return __version__


def leggi_token() -> str:
    token = (os.environ.get("ORCHESTRA_UPDATE_TOKEN") or "").strip()
    if token:
        return token
    for base in (radice_installazione(), os.getcwd()):
        p = os.path.join(base, "token.txt")
        try:
            with open(p, encoding="utf-8") as fh:
                token = fh.read().strip().split()[0]
            if token:
                return token
        except (OSError, IndexError):
            continue
    raise UpdateError(
        "token di aggiornamento mancante: imposta ORCHESTRA_UPDATE_TOKEN "
        "o metti token.txt nella cartella di installazione")


def token_se_disponibile() -> str | None:
    """Token se configurato, altrimenti None (repo pubblico: non serve)."""
    try:
        return leggi_token()
    except UpdateError:
        return None


def _richiesta(url: str, token: str | None) -> urllib.request.Request:
    r = urllib.request.Request(url, headers={
        "User-Agent": "orchestra-updater",
        "Accept": "application/vnd.github+json",
    })
    if token:
        r.add_header("Authorization", "Bearer " + token)
    return r


def versione_da_tag(tag: str) -> str:
    return (tag or "").strip().lstrip("v")


def ultima_release(repo: str, token: str | None) -> InfoRelease:
    try:
        with urllib.request.urlopen(
                _richiesta(API_RELEASES.format(repo=repo), token),
                timeout=30) as f:
            d = json.load(f)
    except Exception as e:  # noqa: BLE001 - rete varia, messaggio unico
        raise UpdateError(f"GitHub non raggiungibile: {e}")
    tag = str(d.get("tag_name") or "")
    zip_url = str(d.get("zipball_url") or "")
    if not tag or not zip_url:
        raise UpdateError("nessuna release pubblicata su GitHub")
    return InfoRelease(tag=tag, versione=versione_da_tag(tag), zip_url=zip_url)


def controlla(repo: str, token: str | None = None) -> dict:
    """Dice se c'e' un aggiornamento, senza scaricare niente."""
    if token is None:
        token = token_se_disponibile()
    rel = ultima_release(repo, token)
    loc = versione_locale()
    return {"locale": loc, "remota": rel.versione, "tag": rel.tag,
            "aggiornamento": rel.versione != loc, "zip_url": rel.zip_url}


def scarica(zip_url: str, token: str | None, dest: str) -> None:
    try:
        with urllib.request.urlopen(_richiesta(zip_url, token),
                                    timeout=120) as f:
            with open(dest, "wb") as fh:
                shutil.copyfileobj(f, fh)
    except Exception as e:  # noqa: BLE001
        raise UpdateError(f"download fallito: {e}")


def _conservare(rel_path: str) -> bool:
    parti = rel_path.split(os.sep)
    return rel_path in CONSERVA or parti[0] in CONSERVA or parti[-1] in CONSERVA


def _radice_zip(nomi: list[str]) -> str:
    primi = [n.split("/")[0] for n in nomi if "/" in n]
    if not primi:
        raise UpdateError("zip della release vuoto o malformato")
    radice = primi[0]
    if any(p != radice for p in primi):
        raise UpdateError("zip della release con piu' radici")
    return radice + "/"


def applica(zip_path: str, root: str | None = None) -> dict:
    """Applica uno zip release sopra root, con backup e conserve."""
    root = os.path.abspath(root or radice_installazione())
    with zipfile.ZipFile(zip_path) as z:
        nomi = z.namelist()
        base = _radice_zip(nomi)
        tmp = tempfile.mkdtemp(prefix="orchestra-update-")
        try:
            z.extractall(tmp)
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(tmp, ignore_errors=True)
            raise UpdateError(f"zip non valido: {e}")
        src = os.path.join(tmp, base.rstrip("/"))
        try:
            backup = root + ".backup"
            if os.path.isdir(backup):
                shutil.rmtree(backup)
            # Backup leggero: solo i file che verranno sovrascritti.
            copiati = []
            for dp, _dirs, files in os.walk(src):
                rel = os.path.relpath(dp, src)
                for fn in files:
                    rel_path = os.path.normpath(os.path.join(rel, fn))
                    if _conservare(rel_path):
                        continue
                    dst = os.path.join(root, rel_path)
                    if os.path.isfile(dst):
                        bdst = os.path.join(backup, rel_path)
                        os.makedirs(os.path.dirname(bdst), exist_ok=True)
                        shutil.copy2(dst, bdst)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(os.path.join(dp, fn), dst)
                    copiati.append(rel_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return {"file": len(copiati), "backup": backup if os.path.isdir(backup) else ""}


def aggiorna(repo: str, token: str | None = None,
             root: str | None = None) -> dict:
    """Controlla, scarica e applica. Torna il resoconto."""
    if token is None:
        token = token_se_disponibile()
    info = controlla(repo, token)
    if not info["aggiornamento"]:
        return {"aggiornato": False, **info}
    fd, tmpzip = tempfile.mkstemp(suffix=".zip", prefix="orchestra-rel-")
    os.close(fd)
    try:
        scarica(info["zip_url"], token, tmpzip)
        esito = applica(tmpzip, root)
    finally:
        try:
            os.unlink(tmpzip)
        except OSError:
            pass
    return {"aggiornato": True, **info, **esito}
