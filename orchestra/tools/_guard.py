"""Le guardie condivise da tutti i tool.

Stavano in `tools.py` miste ai tool, e per questo non si potevano usare
da un tool senza importare anche i tool. Ora stanno qui, da sole.

C'e' il confine del root (`_safe_path`, `_percorso_fuori`,
`_check_shell_access`), il gate dei permessi impostato dalla web UI, e
le cose di shell (ambiente scrubbed, uccisione dell'albero, ricerca di
una shell POSIX).

Il modello non è un confine di sicurezza: queste funzioni leggono i
propri limiti invece di fidarsi che il modello faccia la cosa giusta.
"""

from __future__ import annotations

import os
import signal as _signal
import subprocess
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------
# Il root


# confini: il modello non può leggere fuori da qui, per quanto chieda.
#
# ROOT è valutato all'import e ricalcolato solo se cambia
# ORCHESTRA_ROOT. Senza questo, il benchmark — che cambia la root per ogni
# task — avrebbe tool che scrivono nella directory del primo import, e
# ogni verifica fallirebbe guardando il posto sbagliato. Il sintomo era un
# benchmark intero a 0.00: sembrava che i modelli fossero pessimi, quando
# il codice non aveva mai scritto dove credevamo.
def _root() -> Path:
    return Path(os.environ.get("ORCHESTRA_ROOT", ".")).resolve()


ROOT = _root()

# Il gate dei permessi, impostato dalla web UI all'avvio. None in CLI e
# benchmark: senza nessuno a cui chiedere, la risposta e' negare.
_GATE: Any = None


def set_permission_gate(gate: Any) -> None:
    global _GATE
    _GATE = gate


def _gate() -> Any:
    return _GATE


def _safe_path(rel: str) -> Path:
    """Risolve un path, dentro la root per default, fuori solo se autorizzato.

    Legge la root al momento della chiamata, non quella congelata
    all'import: vedi `_root()`. Il benchmark cambia la root a ogni task.

    Fuori dalla root non e' un errore: e' una domanda. Se c'e' qualcuno
    in grado di rispondere — la web UI — gli si chiede, e la risposta
    vale per questa volta, per la sessione, o per mai. Se non c'e'
    nessuno (CLI, benchmark) si nega, perche' il default sicuro e'
    negare e non tirare a indovinare.
    """
    root = _root()
    p = (root / rel).resolve()

    dentro = str(p).startswith(str(root))
    if dentro:
        return p

    gate = _gate()
    if gate is None:
        raise ValueError(f"path fuori dal root consentito: {rel}")
    if gate.chiedi_all_utente(str(p), "leggere", f"{rel} → {p}"):
        return p
    raise PermissionError(
        f"accesso fuori dalla cartella di lavoro non autorizzato: {p}. "
        f"La cartella di lavoro è {root}."
    )


# --------------------------------------------------------------------------
# I subprocessi


def _sandbox_env() -> dict[str, str]:
    """Ambiente scrubbed per i processi figli.

    Non passiamo mai le credenziali del processo padre (chiavi API, token,
    secret) ai subprocessi: un `printenv`, un `python -c 'import os;
    print(...)'` o un child process compromesso potrebbe leggerle. Lasciamo
    PATH, temporanee, locale: senza questi la shell non parte.
    """
    keep_prefixes = ("PATH", "HOME", "USERPROFILE", "TMP", "TEMP", "LANG",
                     "LC_", "SYSTEMROOT", "COMSPEC", "WINDIR", "TERM",
                     "ORCHESTRA_ROOT")
    out: dict[str, str] = {}
    for key, val in os.environ.items():
        upper = key.upper()
        sensitive = any(tok in upper for tok in
                        ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "AUTH",
                         "CREDENTIAL", "DATABASE", "DSN"))
        if sensitive:
            continue
        if upper.startswith(keep_prefixes) or upper in {"USER", "LOGNAME",
                                                        "SHELL", "PWD"}:
            out[key] = val
    # Fallback minimale se non c'e' PATH.
    if "PATH" not in out and "Path" not in out:
        path = os.environ.get("PATH", "")
        if path:
            out["PATH"] = path
    return out


def _kill_tree(pid: int) -> None:
    """Termina il processo e tutti i figli.

    subprocess.run con timeout uccide solo il processo principale; i
    figli (server avviati dal comando, make ricorsivi) restano zombie.
    Qui chiudiamo tutto l'albero, anche se non possiamo sempre farlo con
    garanzie a livello OS (serve il sandbox di processo vero per quello).
    """
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(pid, _signal.SIGKILL)
            except ProcessLookupError:
                pass
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, _signal.SIGKILL)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Il controllo della shell


# Percorsi che non hanno senso dentro un progetto e che ci riportano fuori
# dal root (o che tentano di aggirarlo). Match conservative: pochi falsi
# positivi sono preferibili a lasciare passare una lettura.
_SUSPICIOUS = (
    r"\.env",
    r"id_rsa",
    r"\.ssh",
    r"\.aws",
    r"\.gnupg",
    r"credentials",
    r"\.git/config",
    r"\.npmrc",
    r"\.netrc",
    r"\.git-credentials",
    r"win\.ini",
    r"system32",
    r"/etc/",
    r"sam\b",
    r"\.config/orchestra",
)


def _percorso_fuori(command: str) -> str:
    """Il percorso che il comando tocca ed esce dalla root, o "".

    Restituisce il percorso e non un booleano perche' serve al gate
    come SOGGETTO della domanda. Passandogli la root — cioe' dicendogli
    "guarda se questa cartella e' fuori dalla root" while lei e' la
    root stessa — la risposta e' sempre "dentro", e il permesso viene
    concesso senza chiedere nulla. E' successo: l'agente si e' sentito
    dire che non poteva toccare C:\\Users\\adver\\TraceAppNew senza che
    all'utente comparisse mai la domanda.

    Approssimazione dichiarata: non e' un sandbox e non puo' esserlo
    qui dentro. Un `curl`, un `python -c` o una catena di pipe possono
    arrivare ovunque senza mai nominare un percorso. Quello che
    facciamo e' fermare gli errori ovvi — `..`, un percorso assoluto,
    la home — che sono anche la maggior parte degli incidenti reali, e
    chiedere il permesso su quelli invece di negare in silenzio.

    Dichiararlo e' parte del lavoro: un controllo che sembra totale e
    non lo e' e' peggio di nessun controllo, perche' ci si fiderebbe
    troppo.
    """
    import re

    low = command.lower()

    def come_windows(s: str) -> str:
        # /c/Users/... -> C:\Users\...  (stile msys/git-bash)
        m2 = re.match(r"^/([a-z])/(.*)$", s)
        if m2 and os.name == "nt":
            resto = m2.group(2).replace("/", "\\")
            return f"{m2.group(1).upper()}:\\{resto}" if resto else f"{m2.group(1).upper()}:\\"
        return s

    # L'ordine conta. Prima le drive msys (/c/Users/...), PERCHE' se
    # scatta prima /users/... il percorso resta in forma Unix, il gate lo
    # risolve sulla drive corrente e la domanda arriva con un percorso
    # che l'utente non riconosce — se non lo riconosce, non autorizza.
    #
    # Si cerca nella versione minuscola ma si restituisce il testo
    # ORIGINALE: nel riquadro deve comparire C:\\Users\\adver\\TraceAppNew
    # come l'ha scritto l'agente, non tutto minuscolo. Un percorso che
    # l'utente non riconosce e' un percorso che non autorizza.
    for m in re.finditer(r"/[a-z](?:/[^\s'\";|&)<>]*)?", low):
        originale = command[m.start():m.end()]
        tradotto = come_windows(originale)
        if tradotto.lower() != originale.lower():
            return tradotto
    for m in re.finditer(r"[a-z]:[\\/](?:[^\s'\";|&)<>]{0,200})", low):
        return command[m.start():m.end()].rstrip("/\\") or command[m.start():m.start() + 2]
    for m in re.finditer(r"/(?:users|home|root|mnt|media)/[^\s'\";|&)<>]{0,200}", low):
        return come_windows(command[m.start():m.end()].rstrip("/"))
    if "../" in command or "..\\" in command:
        # si risolve solo il PRIMO token che sembra un percorso: passare
        # l'intero comando a resolve() lo tratta come un nome di file e
        # produce una destinazione sbagliata
        for m in re.finditer(r"[^\s'\";|&)<>]*\.\.[^\s'\";|&)<>]*", command):
            try:
                return str((_root() / m.group(0)).resolve())
            except Exception:  # noqa: BLE001
                return str(_root())
        return str(_root())
    if low.startswith("~/"):
        return os.path.expanduser("~")
    for pat in _SUSPICIOUS:
        if re.search(pat, low):
            return os.path.join(os.path.expanduser("~"), pat.strip("^$"))
    return ""


def _check_shell_access(command: str) -> str | None:
    """Rifiuta i comandi che uscirebbero dal root o toccherebbero segreti.

    Non è un sandbox: non ferma `curl`, che può scaricare quello che vuole.
    Ferma gli errori ovvi — il percorso esplicito e i file di credenziali —
    che sono anche la maggior parte degli incidenti reali. Un sandbox vero
    richiede isolamento a livello di processo e non sta in un tool handler.
    """
    import re

    low = command.lower()

    # 1) percorsi che escono dal root
    if "../" in command or "..\\" in command:
        # ../ dentro il root è tecnicamente dentro, ma non vale la pena
        # distinguere: il modello deve usare path puliti
        return f"il comando contiene '..' (escape dal root): {command[:120]}"

    # 2) percorsi assoluti Windows
    if re.search(r"[a-z]:[\\/]", low):
        return f"il comando contiene un percorso assoluto: {command[:120]}"

    # 3) home esplicita
    if "/home/" in low or "/root/" in low or low.startswith("~/") or "/users/" in low:
        return f"il comando punta fuori dal progetto: {command[:120]}"

    # 4) file di credenziali
    for pat in _SUSPICIOUS:
        if re.search(pat, low):
            return f"accesso a un file protetto ('{pat}'): {command[:120]}"

    return None


def _detect_posix_shell() -> str | None:
    """Cerca una shell POSIX.

    `shutil.which` è il metodo giusto: cerca nel PATH reale, che su questa
    macchina include /usr/bin (git-bash/MSYS) anche se Git non è in
    "C:\\Program Files". I percorsi hardcoded fallivano e ci lasciavano
    sulla shell cmd, cioè quella che produce i falsi successi.
    """
    if os.name == "posix":
        return "/bin/sh"
    import shutil

    for name in ("bash", "sh"):
        found = shutil.which(name)
        if found:
            return found.replace("\\", "/")
    return None


def _sq(s: str) -> str:
    """ quoting per -lc: il comando va in una singola stringa con gli apici
    singoli raddoppiati. Non è un involucro di sicurezza (il comando è del
    modello e gira comunque con i permessi dell'utente), serve solo a non
    far mangere gli apici al quoting di cmd. """
    return "'" + s.replace("'", "'\\''") + "'"
