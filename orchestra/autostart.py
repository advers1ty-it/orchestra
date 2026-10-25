"""Avvio automatico di Orchestra su Windows.

Registra/deregistra Orchestra nella chiave Run dell'utente (HKCU), così il
server parte al login senza privilegi di amministratore. Solo Windows.
"""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Orchestra"


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _comando() -> str:
    root = _root()
    log = os.path.join(root, "orchestra.log")
    err = os.path.join(root, "orchestra.err.log")
    return (
        "powershell -NoProfile -WindowStyle Hidden -Command "
        "\"Start-Process -FilePath 'py' -ArgumentList @('-3','-m','orchestra.cli','web','--port','8737','--no-browser') "
        "-WindowStyle Hidden -RedirectStandardOutput '%s' -RedirectStandardError '%s'\"" % (log, err)
    )


def disponibile() -> bool:
    return sys.platform.startswith("win")


def stato() -> bool:
    if not disponibile():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            try:
                winreg.QueryValueEx(k, VALUE_NAME)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False


def abilita() -> bool:
    if not disponibile():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, _comando())
        return True
    except Exception:
        return False


def disabilita() -> bool:
    if not disponibile():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except Exception:
        return False
