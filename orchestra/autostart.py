"""Avvio automatico di Orchestra, su Windows e su Linux.

Su Windows registra/deregistra Orchestra nella chiave Run dell'utente
(HKCU), cosi' il server parte al login senza privilegi di amministratore.
Su Linux scrive un file `.desktop` in `~/.config/autostart`, il meccanismo
standard di GNOME, KDE e degli altri desktop.

L'interprete registrato e' quello che sta eseguendo questo processo
(sys.executable), non `py -3`: il launcher `py` sceglie da solo la versione
"predefinita", e su una macchina con piu' Python (o con una registrazione
rimasta indietro) puo' puntare a un percorso che non esiste piu'.
Il 6/11/2026 e' successo esattamente questo: la voce nella chiave Run c'era,
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
WINDOWS = sys.platform.startswith("win")
LINUX = sys.platform.startswith("linux")


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
    """Il comando registrato, nel formato della piattaforma corrente."""
    if LINUX:
        return _comando_linux()
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


def _linux_file() -> str:
    """Il file .desktop dell'avvio automatico."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "autostart", "orchestra.desktop")


def _linux_quota(valore: str) -> str:
    """Virgolette per il campo Exec di un .desktop."""
    return '"' + valore.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _comando_linux() -> str:
    """Il comando che parte al login.

    Preferisce il launcher dell'installazione, che conosce il venv e i
    log; se non c'e' (installazione da wheel) usa l'interprete corrente.
    In entrambi i casi non apre il browser: al login non c'e' nessuno
    davanti allo schermo.
    """
    launcher = os.path.join(_root(), "Avvia-Orchestra.sh")
    if os.path.isfile(launcher):
        return ("env ORCHESTRA_NO_BROWSER=1 "
                + _linux_quota(launcher) + " avvia --no-browser")
    exe = sys.executable or "python3"
    return ("env ORCHESTRA_NO_BROWSER=1 " + _linux_quota(exe)
            + " -m orchestra.cli web --port " + PORTA + " --no-browser")


def disponibile() -> bool:
    return WINDOWS or LINUX


def _interprete_registrato(comando: str) -> str:
    """Il percorso dopo `-FilePath`, se c'e' (formato Windows)."""
    trovato = re.search(r"-FilePath\s+'([^']*)'", comando or "")
    return trovato.group(1) if trovato else ""


def _programma_linux(comando: str) -> str:
    """Il primo programma fra virgolette nel comando Linux."""
    trovato = re.search(r'"([^"]+)"', comando or "")
    return trovato.group(1) if trovato else ""


def _valore() -> str:
    """Il comando scritto nell'avvio automatico, vuoto se non c'e'."""
    if LINUX:
        try:
            with open(_linux_file(), encoding="utf-8") as f:
                for riga in f:
                    if riga.startswith("Exec="):
                        return riga[5:].strip()
        except OSError:
            return ""
        return ""
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
    if LINUX:
        programma = _programma_linux(comando)
        if not programma:
            return "la voce registrata non indica un programma"
        if not os.path.exists(programma):
            return "il programma registrato non esiste piu' (%s)" % programma
        if "orchestra.cli" not in comando and not programma.endswith("Avvia-Orchestra.sh"):
            return ("la voce registrata non avvia il server di Orchestra")
        return ""
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
    if LINUX:
        percorso = _linux_file()
        contenuto = "\n".join([
            "[Desktop Entry]",
            "Type=Application",
            "Name=Orchestra",
            "Comment=Avvia il server di Orchestra al login",
            "Exec=" + _comando_linux(),
            "Path=" + _cartella_lavoro(),
            "Terminal=false",
            "X-GNOME-Autostart-enabled=true",
            "",
        ])
        try:
            os.makedirs(os.path.dirname(percorso), exist_ok=True)
            with open(percorso, "w", encoding="utf-8", newline="\n") as f:
                f.write(contenuto)
            return True
        except OSError:
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
    if LINUX:
        try:
            os.remove(_linux_file())
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True
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
