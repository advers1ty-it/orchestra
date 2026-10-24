"""Automazione minima del computer via API Windows/SendKeys.

Non richiede dipendenze: usa PowerShell + System.Drawing/System.Windows.Forms
euser32.dll presenti di default su Windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..types import Tool


def _consento(azione: str, dettagli: str) -> bool:
    """Chiede il permesso dove c'e' qualcuno; altrimenti nega.

    Negare senza canale e' il default sicuro: nessun automatismo da tastiera
    o click su un sistema senza un utente che ha visto la finestra.
    """
    try:
        from orchestra.tools import _gate
        gate = _gate()
    except Exception:  # noqa: BLE001
        gate = None
    if gate is None:
        import os as _os
        return _os.environ.get("ORCHESTRA_COMPUTER_USE", "").strip().lower() in {
            "1", "true", "yes", "si"}
    try:
        return bool(gate.chiedi_all_utente("computer", azione, dettagli))
    except Exception:  # noqa: BLE001
        return False


def _powershell(exe: str = 'powershell.exe') -> str | None:
    return shutil.which(exe) or shutil.which('powershell')


def _run_pw(script: str, timeout: int = 30) -> tuple[int, str, str]:
    ps = _powershell()
    if not ps:
        return 1, "", "PowerShell non trovato"
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            text=True, capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return 1, "", f"timeout {timeout}s"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{type(e).__name__}: {e}"
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _scratch_path(name: str) -> Path:
    try:
        from orchestra.tools import _root
        base = _root()
    except Exception:
        base = Path(tempfile.gettempdir())
    return base / name


def tool_computer_screenshot() -> Tool:
    def handler(nome_file: str = "") -> str:
        if not nome_file:
            nome_file = "schermo.png"
        if not str(nome_file).lower().endswith((".png", ".jpg", ".jpeg")):
            nome_file += ".png"
        out = _scratch_path(nome_file)
        os.makedirs(out.parent, exist_ok=True)
        out_s = str(out).replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$img=New-Object System.Drawing.Bitmap($b.Width,$b.Height); "
            "$g=[System.Drawing.Graphics]::FromImage($img); "
            "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
            "$img.Save('%s', [System.Drawing.Imaging.ImageFormat]::Png); "
            "$g.Dispose(); $img.Dispose(); "
            "Write-Output ($b.Width.ToString()+'x'+$b.Height.ToString())"
        ) % out_s
        rc, out_txt, err = _run_pw(script)
        if rc != 0 or err or not out.exists():
            return ("Screenshot fallito: "
                    + (err or out_txt or "motivo sconosciuto"))
        return (f"Screenshot salvato: {out} ({out_txt}, "
                f"{out.stat().st_size} byte)")

    return Tool(
        name="computer_screenshot",
        description=(
            "Cattura lo schermo principale in PNG. Usalo solo se devi "
            "verificare aspetto visivo o quando non puoi leggere il testo "
            "diversamente."
        ),
        schema={"type": "object",
                "properties": {"nome_file": {
                    "type": "string",
                    "description": "Nome del file PNG da creare (opzionale)."}},
                "required": []},
        handler=handler,
    )


def _esc_type(s: str) -> str:
    """Escape per SendKeys: le parentesi/brace sono speciali."""
    # SendKeys richiede { } per i tasti speciali; le parentesi graffe
    # della stringa utente vanno raddoppiate.
    return s.replace("{", "{{").replace("}", "}}")


def tool_computer_click() -> Tool:
    def handler(x: int, y: int, bottone: str = "sinistro") -> str:
        try:
            x = int(x); y = int(y)
        except (TypeError, ValueError):
            return "x e y devono essere interi"
        if not _consento("computer_click",
                         f"cliccare {bottone} in ({x},{y})"):
            return ("Azione negata: click su sistema non autorizzato. "
                    "Abilita ORCHESTRA_COMPUTER_USE=1 o conferma dal "
                    "pannello Permessi.")
        btn = "LEFT" if str(bottone).lower() in ("sinistro", "left",
                                                  "sx") else "RIGHT"
        if btn == "LEFT":
            flag_down, flag_up = 2, 4
        else:
            flag_down, flag_up = 8, 16
        script = (
            'Add-Type @"using System;using System.Runtime.InteropServices;'
            'public class CU{[DllImport("user32.dll")]public static extern '
            'bool SetCursorPos(int x,int y);[DllImport("user32.dll")]public '
            'static extern void mouse_event(uint f,uint dx,uint dy,uint dw,'
            'UIntPtr ex);}@"; '
            f'[CU]::SetCursorPos({x},{y}) | Out-Null; Start-Sleep -ms 100; '
            f'[CU]::mouse_event({flag_down},{x},{y},0,[UIntPtr]::Zero); '
            f'[CU]::mouse_event({flag_up},{x},{y},0,[UIntPtr]::Zero); '
            '"click_ok"'
        )
        rc, out_txt, err = _run_pw(script)
        if rc != 0 or err:
            return f"click fallito: {err or out_txt}"
        return f"click {btn.lower()} in ({x},{y}) eseguito"

    return Tool(
        name="computer_click",
        description=(
            "Muove il cursore e clicca a coordinate assolute dello schermo. "
            "Usalo solo se davvero necessario; coordinate sbagliate possono "
            "attivare azioni indesiderate."
        ),
        schema={"type": "object", "properties": {
            "x": {"type": "integer", "description": "coordinata X."},
            "y": {"type": "integer", "description": "coordinata Y."},
            "bottone": {"type": "string", "description": "sinistro (default) o destro."}},
            "required": ["x", "y"]},
        handler=handler,
    )


def tool_computer_type() -> Tool:
    def handler(testo: str = "") -> str:
        t = testo if isinstance(testo, str) else str(testo or "")
        if not t:
            return "serve testo da scrivere"
        if not _consento("computer_type", f"scrivere {len(t)} caratteri"):
            return ("Azione negata: scrittura su sistema non autorizzata. "
                    "Abilita ORCHESTRA_COMPUTER_USE=1 o conferma dal "
                    "pannello Permessi.")
        # non inviamo caratteri che SendKeys interpreta come sequenze per il
        # controllo (es. +, ^, %): li mettiamo letterali via @{} non e'
        # supportato, quindi li escapovamo come testo; SendKeys tratta %+^
        # come modificatori solo se li si passa singoli, nel testo normale
        # non servono caratteri speciali ulteriori.
        safe = _esc_type(t)
        cmd = ("Add-Type -AssemblyName System.Windows.Forms; "
               f"[System.Windows.Forms.SendKeys]::SendWait('{safe}')")
        # SendKeys non tollera apostrofo singolo; lo gestiamo aparte.
        if "'" in safe:
            # usa il modulo alternative: salvato nel clipboard, poi Ctrl+V
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$c=Get-Clipboard -Raw; Set-Clipboard -Value '%s'; "
                "[System.Windows.Forms.SendKeys]::SendWait('^v'); "
                "Set-Clipboard -Value $c"
            ) % safe.replace("'", "''")
            rc, out, err = _run_pw(ps)
        else:
            rc, out, err = _run_pw(cmd)
        if rc != 0 or err:
            return f"scrittura fallita: {err or out}"
        return f"scritti {len(t)} caratteri"

    return Tool(
        name="computer_type",
        description=(
            "Scrive testo come se fosse la tastiera (SendKeys) nella "
            "finestra attiva. Usalo solo dopo aver messo a fuoco il campo."
        ),
        schema={"type": "object", "properties": {
            "testo": {"type": "string", "description": "Testo da scrivere."}},
            "required": ["testo"]},
        handler=handler,
    )


def tool_computer_open() -> Tool:
    def handler(app: str = "") -> str:
        a = (app or "").strip()
        if not a:
            return "serve nome/programma o varle"
        if not _consento("computer_open", f"avviare app: {a}"):
            return ("Azione negata: apertura sistema non autorizzata. "
                    "Abilita ORCHESTRA_COMPUTER_USE=1 o conferma dal "
                    "pannello Permessi.")
        escaped = a.replace("'", "''")
        script = f"Start-Process '{escaped}' -PassThru | Select-Object -ExpandProperty Id"
        rc, out_txt, err = _run_pw(script)
        if rc != 0 or err:
            return f"apertura fallita: {err or out_txt}"
        return f"processo avviato: {out_txt}" if out_txt else "processo avviato"

    return Tool(
        name="computer_open",
        description=(
            "Apre un programma o sito locale via il sistema. Usa nomi "
            "noti (notepad, calc) oppure un percorso/modalità supportata."
        ),
        schema={"type": "object", "properties": {
            "app": {"type": "string",
                    "description": "Nome o percorso da aprire."}},
                "required": ["app"]},
        handler=handler,
    )
