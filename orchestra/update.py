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

import os
import sys

if __name__ == "__main__" and os.path.dirname(os.path.abspath(__file__)) in sys.path:
    # Eseguito come file, la sua cartella e' in sys.path e copre la
    # stdlib (orchestra/types.py oscura types): si toglie di mezzo
    # prima di qualsiasi altro import.
    sys.path.remove(os.path.dirname(os.path.abspath(__file__)))

import io
import json
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
    # Stato personale: mai sovrascritto (e mai nel repo, vedi .gitignore).
    "memory.md",
    "memoria_config.json",
    "nous_auth.json",
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


def versione_locale(root: str | None = None) -> str:
    """Versione installata, letta dal file senza importare l'app.

    Non usare import qui: questo modulo deve girare anche quando l'app
    e' rotta (e' proprio allora che l'update serve di piu').
    """
    base = os.path.abspath(root or radice_installazione())
    p = os.path.join(base, "orchestra", "__init__.py")
    try:
        with open(p, encoding="utf-8") as fh:
            testo = fh.read()
    except OSError:
        return "sconosciuta"
    import re
    m = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", testo)
    return m.group(1) if m else "sconosciuta"


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


def controlla(repo: str, token: str | None = None,
              root: str | None = None) -> dict:
    """Dice se c'e' un aggiornamento, senza scaricare niente."""
    if token is None:
        token = token_se_disponibile()
    rel = ultima_release(repo, token)
    loc = versione_locale(root)
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


# Estensioni di codice: solo queste partecipano alla pulizia dei file
# obsoleti. Dati, log, chiavi e stato (.md/.db/.json/.log/.env/...)
# non si toccano mai, nemmeno se non sono piu' nella release.
_EXT_CODICE = {".py", ".pyw", ".js", ".jsx", ".ts", ".html", ".htm",
               ".css", ".bat", ".cmd", ".ps1"}


def applica(zip_path: str, root: str | None = None) -> dict:
    """Applica uno zip release sopra root, con backup e conserve.

    Oltre a copiare i file nuovi, rimuove il codice obsoleto: file con
    estensione di codice che non sono piu' nella release e non sono
    conservati (es. orchestra/tools.py dopo il passaggio a tools/).
    Senza questa pulizia, un file vecchio resta accanto alla cartella
    nuova e Python importa quello sbagliato — app morta all'avvio.
    """
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
            # --- pulizia del codice obsoleto ---
            nuovi = set()
            for n in nomi:
                if n.startswith(base) and not n.endswith("/"):
                    nuovi.add(os.path.normpath(n[len(base):]))
            top_zip = {p.split(os.sep)[0] for p in nuovi}
            nome_backup = os.path.basename(backup)
            rimossi = []
            for dp, _dirs, files in os.walk(root):
                rel_dp = os.path.relpath(dp, root)
                if rel_dp == ".":
                    top = None  # file in radice: si valutano uno a uno
                else:
                    top = rel_dp.split(os.sep)[0]
                    if top == nome_backup or top not in top_zip:
                        continue
                for fn in files:
                    rel_path = os.path.normpath(os.path.join(rel_dp, fn))
                    if rel_path in nuovi or _conservare(rel_path):
                        continue
                    if os.path.splitext(fn)[1].lower() not in _EXT_CODICE:
                        continue
                    try:
                        os.remove(os.path.join(dp, fn))
                        rimossi.append(rel_path)
                    except OSError:
                        pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    esito = {"file": len(copiati), "backup": backup if os.path.isdir(backup) else ""}
    if rimossi:
        esito["rimossi"] = rimossi
    return esito


def aggiorna(repo: str, token: str | None = None,
             root: str | None = None) -> dict:
    """Controlla, scarica e applica. Torna il resoconto."""
    if token is None:
        token = token_se_disponibile()
    info = controlla(repo, token, root=root)
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


if __name__ == "__main__":
    # Uso standalone: `python orchestra/update.py --auto --root <dir>`.
    # Non importa l'app di proposito: deve girare anche quando l'app
    # e' rotta (e' proprio allora che serve aggiornare).
    import argparse
    _p = argparse.ArgumentParser(prog="update.py",
                                 description="Aggiorna Orchestra da GitHub.")
    _p.add_argument("--auto", action="store_true",
                    help="aggiorna solo se c'e' una versione nuova")
    _p.add_argument("--check", action="store_true",
                    help="mostra locale/remota senza scaricare")
    _p.add_argument("--repo", default="advers1ty-it/orchestra")
    _p.add_argument("--root", default=None,
                    help="cartella installazione (default: directory corrente)")
    _p.add_argument("--token", default=None)
    _a = _p.parse_args()
    _root = os.path.abspath(_a.root or os.getcwd())
    try:
        if _a.check:
            _info = controlla(_a.repo, _a.token, root=_root)
            print(f"locale {_info['locale']} · remota {_info['remota']}"
                  + (" · AGGIORNAMENTO DISPONIBILE" if _info["aggiornamento"]
                     else " · aggiornato"))
        elif _a.auto:
            _info = controlla(_a.repo, _a.token, root=_root)
            if not _info["aggiornamento"]:
                print(f"già aggiornato ({_info['locale']})")
            else:
                print(f"aggiornamento {_info['locale']} -> {_info['remota']}...")
                _esito = aggiorna(_a.repo, _a.token, root=_root)
                print(f"aggiornato alla {_esito['remota']} ({_esito['file']} file)")
                for _r in _esito.get("rimossi") or []:
                    print(f"  rimosso obsoleto: {_r}")
        else:
            _esito = aggiorna(_a.repo, _a.token, root=_root)
            if not _esito["aggiornato"]:
                print(f"già aggiornato ({_esito['locale']})")
            else:
                print(f"aggiornato {_esito['locale']} -> {_esito['remota']} "
                      f"({_esito['file']} file)")
    except UpdateError as _e:
        print(f"update: {_e}", file=sys.stderr)
        sys.exit(1)
