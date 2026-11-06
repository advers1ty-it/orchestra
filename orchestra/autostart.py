"""Avvio automatico di Orchestra su Windows.

Registra/deregistra Orchestra nella chiave Run dell'utente (HKCU), cosi' il
server parte al login senza privilegi di amministratore. Solo Windows.

L'interprete registrato e' quello che sta eseguendo questo processo
(sys.executable), non `py -3`: il launcher `py` sceglie da solo la versione
"predefinita", e su una macchina con piu' Python (o con una registrazione
rimasta indietro) puo' puntare a un percorso che non esiste piu'. Il
6/11/2026 e' successo esattamente questo: la voce nella chiave Run c'era,
il pannello diceva "attivo", e al login la console rispondeva "Unable to
create process using ... : impossibile trovare il file specificato".
Un avvio automatico che non parte lasciando scritto "attivo" e' peggio di
un avvio automatico assente, quindi lo stato adesso controlla anche che
l'interprete registrato esista ancora e che il comando sia nella forma
giusta; se non lo e', `info()` dice perche' e il pannello propone "Ripara".
"""

from __future__ import annotations

import os
import re
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Orchestra"
PORTA = "8737"


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dati() -> str:
    """La cartella dati dell'installazione (dove finisce tutto il resto)."""
    try:
        from . import dati as dati_mod
        return dati_mod.cartella_dati()
    except Exception:
        return _root()


def _scrivibile(cartella: str) -> bool:
    """Si puo' davvero scrivere qui? L'unico modo di saperlo e' provare.

    Serve perche' `-RedirectStandardOutput` su una cartella in sola lettura
    non fa partire niente: Start-Process si ferma prima, e con la finestra
    nascosta l'errore non lo vede nessuno. Le installazioni normali sono in
    %LOCALAPPDATA% ed e' tutto scrivibile; un'installazione in Program Files
    (o un `pip install` in un Python di sistema) non lo e'.
    """
    prova = os.path.join(cartella, ".orchestra-scrivibile")
    try:
        with open(prova, "w", encoding="utf-8"):
            pass
        os.remove(prova)
        return True
    except OSError:
        return False


def _cartella_lavoro() -> str:
    """Dove far girare il processo: la radice se e' un'installazione da
    sorgente (contiene il pacchetto), altrimenti la cartella dati — che
    esiste e si puo' scrivere per costruzione."""
    root = _root()
    if os.path.isdir(os.path.join(root, "orchestra")):
        return root
    return _dati()


def _cartella_log() -> str:
    root = _root()
    return root if _scrivibile(root) else _dati()


def _avvio() -> tuple[str, list[str]]:
    """L'eseguibile da lanciare e gli argomenti che vanno prima del modulo.

    sys.executable e' il Python che sta girando adesso: se Orchestra parte,
    quello esiste per definizione. `py -3` resta solo come ripiego per i
    casi in cui sys.executable non c'e' (interprete incassato senza path).
    """
    exe = sys.executable or ""
    if exe and os.path.isfile(exe):
        return exe, []
    return "py", ["-3"]


def _citato(valore: str) -> str:
    """Una stringa fra apici singoli per PowerShell (l'apice si raddoppia)."""
    return "'" + valore.replace("'", "''") + "'"


def _comando() -> str:
    cartella = _cartella_lavoro()
    log = os.path.join(_cartella_log(), "orchestra.log")
    err = os.path.join(_cartella_log(), "orchestra.err.log")
    exe, prima = _avvio()
    argomenti = prima + ["-m", "orchestra.cli", "web", "--port", PORTA,
                         "--no-browser"]
    elenco = ",".join(_citato(a) for a in argomenti)
    # `-WorkingDirectory` non e' un dettaglio: `-m orchestra.cli` cerca il
    # pacchetto nella cartella corrente, e al login quella e' System32.
    return (
        "powershell -NoProfile -WindowStyle Hidden -Command "
        "\"Start-Process -FilePath %s -ArgumentList @(%s) -WorkingDirectory %s "
        "-WindowStyle Hidden -RedirectStandardOutput %s "
        "-RedirectStandardError %s\""
        % (_citato(exe), elenco, _citato(cartella), _citato(log), _citato(err))
    )


def disponibile() -> bool:
    return sys.platform.startswith("win")


def _interprete_registrato(comando: str) -> str:
    """Il percorso dopo `-FilePath`, se c'e'."""
    trovato = re.search(r"-FilePath\s+'([^']*)'", comando or "")
    return trovato.group(1) if trovato else ""


def _valore() -> str:
    """Il comando scritto nella chiave Run, stringa vuota se non c'e'."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_READ) as k:
        try:
            valore, _ = winreg.QueryValueEx(k, VALUE_NAME)
        except FileNotFoundError:
            return ""
    return str(valore or "")


def problema_del_comando(comando: str) -> str:
    """Cosa impedirebbe a questa voce di avviare Orchestra ("" se va bene).

    Sta fuori da `info()` perche' e' una regola sul testo, non sul registro:
    cosi' si puo' provare senza Windows, e la regola che finisce nel test e'
    la stessa che gira davvero.
    """
    interprete = _interprete_registrato(comando)
    if not interprete:
        return "la voce registrata non indica un programma"
    if not os.path.isfile(interprete):
        return "il programma registrato non esiste piu' (%s)" % interprete
    if "-WorkingDirectory" not in comando:
        return ("la voce registrata non indica la cartella di Orchestra: "
                "il modulo non verrebbe trovato")
    return ""


def info() -> dict[str, object]:
    """Stato dell'avvio automatico, con il motivo se non puo' funzionare.

    `attivo` dice solo che la voce esiste; `problema` dice se quella voce,
    cosi' com'e', non farebbe partire niente. Sono due domande diverse e
    rispondere alla prima fingendo di aver risposto alla seconda e' il
    difetto da cui viene questo file.
    """
    fuori: dict[str, object] = {"disponibile": disponibile(), "attivo": False,
                                "comando": "", "problema": ""}
    if not fuori["disponibile"]:
        return fuori
    try:
        comando = _valore()
    except Exception:
        return fuori
    if not comando:
        return fuori
    fuori["attivo"] = True
    fuori["comando"] = comando
    fuori["problema"] = problema_del_comando(comando)
    return fuori


def stato() -> bool:
    return bool(info()["attivo"])


def abilita() -> bool:
    if not disponibile():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, _comando())
        return True
    except Exception:
        return False


def disabilita() -> bool:
    if not disponibile():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except Exception:
        return False
