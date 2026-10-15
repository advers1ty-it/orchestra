"""Strumenti browser, senza dipendenze oltre alla standard library.

Hanno bisogno di un browser di sistema solo per fare rendering reale (JS) o
screenshot. Il fetch testuale leggero e' gia' in `web_tools`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .types import Tool
from .web_tools import _html_a_testo, _titolo


def _browser_exe() -> str | None:
    cand: list[str] = []
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe",
                 "chromium", "chromium.exe"):
        w = shutil.which(name)
        if w:
            cand.append(w)
    cand += [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Chromium\Application\chrome.exe",
        r"C:\Program Files\Chromium\Application\chrome.exe",
    ]
    for p in cand:
        if os.path.exists(p):
            return p
    return None


def _safe_url(u: str) -> tuple[str, str | None]:
    u = (u or "").strip()
    if not u:
        return "", "serve un indirizzo"
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        u = "https://" + u
    p = urlparse(u)
    if p.scheme not in {"http", "https"}:
        return "", f"schema non ammesso: {p.scheme or '-'}"
    if not p.hostname:
        return "", "indirizzo non valido"
    return u, None


def tool_browser_apri() -> Tool:
    def handler(url: str = "") -> str:
        u, err = _safe_url(url)
        if err:
            return err
        try:
            import webbrowser
            aperto = webbrowser.open_new_tab(u)
        except Exception as e:  # noqa: BLE001
            return f"non riesco ad aprire il browser: {type(e).__name__}: {e}"
        return f"Browser aperto su {u} (tabs={aperto})"

    return Tool(
        name="browser_apri",
        description=(
            "Apre un indirizzo nel browser di sistema dell'utente (in una "
            "nuova scheda). Ti serve se la pagina va davvero aperta o se \n"
            "serve interazione manuale: la lettura testuale e' meglio di "
            "`web_leggi`/`browser_render`."
        ),
        schema={"type": "object", "properties": {
            "url": {"type": "string", "description": "Indirizzo http o https."}},
            "required": ["url"]},
        handler=handler,
    )


def tool_browser_render() -> Tool:
    def handler(url: str = "") -> str:
        u, err = _safe_url(url)
        if err:
            return err
        exe = _browser_exe()
        if not exe:
            # riutilizza il fetch leggero esistente
            import urllib.request
            req = urllib.request.Request(u, headers={
                "User-Agent": "Mozilla/5.0 (compatible; Orchestra/1.0)"})
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    grezzo = r.read(1_200_000).decode(
                        r.headers.get_content_charset() or "utf-8", "replace")
            except Exception as e:  # noqa: BLE001
                return f"browser non disponibile e fetch leggero fallito: {e}"
            return _html_a_testo(grezzo)[:6000] or f"Non trovo testo su {u}."
        work = os.path.join(tempfile.gettempdir(), "orchestra_browser")
        os.makedirs(work, exist_ok=True)
        try:
            r = subprocess.run(
                [exe, "--headless=new", "--disable-gpu",
                 "--no-first-run", "--disable-extensions",
                 f"--user-data-dir={work}",
                 "--disable-background-networking",
                 "--dump-dom", u],
                text=True, capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            return f"timeout: il browser non ha risposto in 40 s per {u}"
        except Exception as e:  # noqa: BLE001
            return f"non riesco ad eseguire il browser: {type(e).__name__}: {e}"
        grezzo = (r.stdout or "")
        if not grezzo and r.stderr:
            return f"il browser ha fallito su {u}: {r.stderr[:400]}"
        if not grezzo:
            return f"il browser non ha estratto nulla per {u}"
        if r.returncode not in (0, 1) and not grezzo:
            return (f"il browser non ha risposto correttamente ({r.returncode}): "
                    f"{r.stderr[:300]}")
        titolo = _titolo(grezzo)
        testo = _html_a_testo(grezzo)
        if not testo:
            return (f"Pagina senza testo estraibile su {u} "
                    f"({len(grezzo)} byte grezzi — magari JSON/PDF/immagine).")
        if len(testo) > 6000:
            testo = testo[:6000] + f"\n\n[...troncato: {len(testo)} caratteri]"
        prefisso = f"# {titolo}\n{u}\n\n" if titolo else f"{u}\n\n"
        return prefisso + testo

    return Tool(
        name="browser_render",
        description=(
            "Apre una pagina con un browser reale (Chrome/Edge sesso del "
            "sistema, headless) ed estrae il testo dopo l'esecuzione del "
            "JavaScript. Usa questo quando una pagina si disegna col JS e "
            "`web_leggi` torna vuoto o incompleto. Se non c'e' un browser di "
            "sistema disponibile fa un fetch leggero di ripiego."
        ),
        schema={"type": "object", "properties": {
            "url": {"type": "string", "description": "Indirizzo http o https."}},
            "required": ["url"]},
        handler=handler,
    )


def tool_browser_screenshot() -> Tool:
    def handler(url: str = "", nome_file: str = "") -> str:
        u, err = _safe_url(url)
        if err:
            return err
        exe = _browser_exe()
        if not exe:
            return ("Manca un browser di sistema (Chrome/Edge). Il "
                    "screenshot della pagina non e' disponibile.")
        if not nome_file:
            nome_file = "screenshot_" + u.split("/")[-1].replace("?", "_")
        if not nome_file.lower().endswith(".png"):
            nome_file += ".png"
        try:
            from orchestra.tools import _root
            base = _root()
        except Exception:
            base = Path(tempfile.gettempdir())
        out_path = base / nome_file
        work = os.path.join(tempfile.gettempdir(), "orchestra_browser")
        os.makedirs(work, exist_ok=True)
        cmd = [exe, "--headless=new",
               f"--screenshot={out_path}",
               "--disable-gpu", "--window-size=1280,800",
               f"--user-data-dir={work}",
               "--no-first-run", "--disable-extensions",
               "--hide-scrollbars", "--disable-background-networking", u]
        try:
            r = subprocess.run(cmd, text=True, capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            return f"timeout (40 s) generando screenshot di {u}"
        except Exception as e:  # noqa: BLE001
            return f"errore screenshot: {type(e).__name__}: {e}"
        if not out_path.exists():
            return (f"Il screenshot non e' stato creato: {u}.\n"
                    f"stderr: {(r.stderr or '')[:300]}")
        return f"Screenshot salvato: {out_path} ({out_path.stat().st_size} byte)"

    return Tool(
        name="browser_screenshot",
        description=(
            "Rende la pagina in headless (Chrome/Edge di sistema) e salva "
            "uno screenshot PNG nel workdir. Usalo se devi vedere l'aspetto "
            "visivo, non solo il testo."
        ),
        schema={"type": "object", "properties": {
            "url": {"type": "string", "description": "Indirizzo http o https."},
            "nome_file": {"type": "string",
                          "description": "Nome del file PNG (opzionale)."}},
        "required": ["url"]},
        handler=handler,
    )
