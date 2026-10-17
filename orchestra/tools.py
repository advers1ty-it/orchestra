"""Tool di base: filesystem, shell, calcolo.

Sono i tool che un orchestratore deve avere per essere utile. Ognuno è
piccolo e dichiara il proprio schema con precisione — uno schema vago è la
causa numero uno di chiamate sbagliate.

Ogni handler è difensivo: legge i propri limiti (path traversal, dimensioni,
timeout) invece di fidarsi che il modello faccia la cosa giusta. Il modello
non è un confine di sicurezza.
"""

import signal as _signal


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


import os
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from .types import Tool, ToolRegistry


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


def tool_read_file() -> Tool:
    def handler(path: str, max_lines: int = 400, start_line: int = 1) -> str:
        p = _safe_path(path)
        if not p.exists():
            return f"NON ESISTE: {path}"
        if p.is_dir():
            entries = sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())
            return f"DIRECTORY {path}:\n" + "\n".join(entries[:max_lines])
        try:
            start_line = max(1, int(start_line or 1))
        except (TypeError, ValueError):
            start_line = 1
        try:
            max_lines = max(1, min(int(max_lines or 400), 2000))
        except (TypeError, ValueError):
            max_lines = 400
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        # start_line è 1-based, come i numeri che si vedono a schermo:
        # chiedere "riga 500" e ricevere dalla 501 è il tipo di errore che
        # non si nota finché non si modifica la riga sbagliata.
        fetta = lines[start_line - 1:start_line - 1 + max_lines]
        numbered = [f"{i + start_line:>5}| {l}" for i, l in enumerate(fetta)]
        tail = (
            f"\n... [{len(lines) - (start_line - 1 + max_lines)} righe rimanenti non mostrate]"
            if len(lines) > start_line - 1 + max_lines
            else ""
        )
        head = f"... [prime {start_line - 1} righe omesse]\n" if start_line > 1 else ""
        if not numbered:
            return f"VUOTO OLTRE LA RIGA {start_line}: {path} ha {len(lines)} righe."
        return head + "\n".join(numbered) + tail

    return Tool(
        name="read_file",
        description="Legge un file di testo con numeri di riga, o elenca una directory.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Percorso relativo alla root, o ASSOLUTO: un percorso fuori dalla root chiede il permesso all utente."},
                "start_line": {
                    "type": "integer",
                    "description": "Riga da cui partire (1 = inizio, default 1).",
                    "default": 1,
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Righe massime da leggere (default 400).",
                    "default": 400,
                },
            },
            "required": ["path"],
        },
        handler=handler,
    )


def tool_write_file() -> Tool:
    def handler(path: str, content: str) -> str:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        p.write_text(content, encoding="utf-8")
        verb = "aggiornato" if existed else "creato"
        return f"File {verb}: {path} ({len(content)} caratteri, {content.count(chr(10))+1} righe)"

    return Tool(
        name="write_file",
        description="Scrive un file di testo, creando le directory necessarie.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Percorso relativo alla root, o ASSOLUTO: un percorso fuori dalla root chiede il permesso all utente."},
                "content": {"type": "string", "description": "Contenuto completo del file."},
            },
            "required": ["path", "content"],
        },
        handler=handler,
    )


def tool_list_dir() -> Tool:
    def handler(path: str = ".", max_items: int = 300,
                pattern: str = "") -> str:
        p = _safe_path(path)
        if not p.is_dir():
            return f"NON È UNA DIRECTORY: {path}"
        # max_items era già applicato (tagliava a 300) ma non era nello
        # schema: il modello lo passava per buon senso e moriva con
        # "unexpected keyword argument". Esposto = il modello lo può
        # chiedere e gli si risponde.
        try:
            max_items = max(1, min(int(max_items or 300), 5000))
        except (TypeError, ValueError):
            max_items = 300
        out = []
        # _root() e non la costante ROOT: ROOT viene congelata all'import,
        # e se il processo cambia ORCHESTRA_ROOT dopo, il confronto
        # fallirebbe sempre e ogni percorso — anche interno — uscirebbe
        # per esteso. Meglio una riga lunga che un elenco illeggibile.
        base = _root()
        for x in sorted(p.iterdir()):
            # pattern (es. '*.py'): su una cartella grande non si vuole
            # tutto, si vuole quel tipo. Filtro sul NOME, come il glob che
            # l'agente scriverebbe a mano in `run_shell`.
            if pattern and not fnmatch(x.name, pattern):
                continue
            # relative_to(base) solleva quando l'utente ha autorizzato
            # una cartella FUORI dalla root e l'agente la elenca: senza
            # questo, il permesso concesso non serve a nulla perche' il
            # listing muore con un ValueError. Fuori dalla root mostriamo
            # il percorso per esteso, che e' anche l'unica forma che
            # l'agente puo' riaprire.
            try:
                rel = x.relative_to(base)
            except ValueError:
                rel = x
            if x.is_dir():
                n = len(list(x.rglob("*")))
                out.append(f"[dir]  {rel}/  ({n} elementi)")
            else:
                out.append(f"[file] {rel}  ({x.stat().st_size} byte)")
        if not out and pattern:
            return f"NESSUN ELEMENTO '{pattern}' in {path}"
        return "\n".join(out[:max_items]) or "(vuota)"

    return Tool(
        name="list_dir",
        description="Elenca il contenuto di una directory con dimensioni.",
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Directory, default '.'. Può essere ASSOLUTA: se è fuori "
                        "dalla root, all'utente compare la domanda sul permesso."
                    ),
                    "default": ".",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Elementi massimi da elencare (default 300).",
                    "default": 300,
                },
                "pattern": {
                    "type": "string",
                    "description": "Filtra per nome con un glob, es. '*.py'. Vuoto = tutto.",
                    "default": "",
                },
            },
        },
        handler=handler,
    )


def tool_run_shell() -> Tool:
    """Esegue un comando shell, con i guard del root applicati.

    Tre problemi reali risolti qui.

    1. `shell=True` su Windows usa cmd.exe, NON bash. I due dialetti
       divergono in modo che produce falsi successi: `;` non è un separatore
       in cmd, quindi `cmd1; cmd2` esegue solo cmd1 e restituisce exit 0 —
       il secondo comando sparisce SENZA errore e il modello legge "tutto
       ok". (Osservato in un test e2e: 3 iterazioni spese a diagnosticare
       un output vuoto che era un comando mai eseguito.) Se c'è una shell
       POSIX nel PATH la usiamo; altrimenti lo diciamo al modello.

    2. Senza guardia, `run_shell` rendeva inutile quella di `read_file`:
       `head -2 ../../....env` leggeva le chiavi API. Il root è
       un confine di sicurezza, non una convenzione, quindi va imposto
       anche a questo tool — non solo dichiarato.

    3. L'output non è garantito UTF-8. Senza errors="replace" un byte 0x8a
       solleva UnicodeDecodeError dentro subprocess e uccide il tool,
       facendo perdere il risultato di un comando che è andato a buon fine.
    """

    posix = _detect_posix_shell()

    def handler(command: str, timeout: int = 60) -> str:
        # Il percorso e' il confine di sicurezza, e vale anche per la
        # shell: se l'agente chiede il permesso per read_file e poi usa
        # `cat` per arrivarci lo stesso, il permesso non protegge
        # niente. Quindi si chiede ANCHE qui, con la stessa domanda.
        #
        # La domanda e' per il comando intero, non per il percorso
        # singolo: un comando puo' toccare tre file, e chiedere per
        # uno e poi eseguirlo cosi' com'e' sarebbe autorizzare tutto.
        gate = _gate()
        fuori = _percorso_fuori(command)
        concesso = False
        if gate is not None and fuori:
            # si chiede sul percorso REALE che il comando tocca, non
            # sulla root: chiedere "questa cartella e' fuori dalla root"
            # indicando la root stessa e' una domanda con la risposta
            # gia' scritta, e non e' quello che e' successo
            concesso = gate.chiedi_all_utente(fuori, "eseguire",
                                              f"comando: {command[:200]}")
            if not concesso:
                return (
                    "NON ESEGUITO: comando fuori dalla cartella di lavoro, "
                    f"permesso non concesso per {fuori}.\n"
                    f"Il root consentito è {_root()}.\n"
                    f"Comando: {command[:200]}"
                )
        elif fuori and gate is None:
            # nessuno a cui chiedere (CLI, benchmark): si nega, e si dice
            # perche' invece di lasciare che fallisca in silenzio. Si
            # dice anche l'alternativa: un blocco che non dice cosa fare
            # costringe il modello a indovinare e a riprovare
            return (
                f"NON ESEGUITO: il comando tocca {fuori}, fuori dalla "
                f"cartella di lavoro ({_root()}), e non c'è nessuno a cui "
                f"chiedere il permesso.\n"
                f"Usa un percorso relativo dentro il progetto, oppure "
                f"avvia Orchestra con ORCHESTRA_ROOT su quella cartella."
            )

        # _check_shell_access gira SOLO senza gate, oppure quando il gate
        # non ha avuto niente da dire (nessun percorso fuori).
        #
        # Con il gate che ha concesso, farlo comunque era unENDO di
        # rispondere due volte: l'utente autorizzava "per questa sessione",
        # il gate concedeva, e subito dopo questo controllo diceva "BLOCCATO
        # per sicurezza". Due risposte contraddittorie alla stessa domanda,
        # e la seconda vinceva. Il gate e' l'autorita': e' piu' severo,
        # perche' nega i percorsi sensibili senza domanda.
        if not (gate is not None and fuori and concesso):
            denied = _check_shell_access(command)
            if denied:
                return (
                    f"BLOCCATO per sicurezza: {denied}\n"
                    f"Il root consentito è {ROOT}. Usa path relativi dentro il progetto."
                )

        shell_cmd = command
        if posix:
            # via esplicita: niente quoting da cmd, e `;` torna a essere un
            # separatore come il modello si aspetta
            shell_cmd = f'"{posix}" -lc {_sq(command)}'
        creationflags = 0
        preexec_fn = None
        if os.name == "nt":
            # nuovo process group: libera taskkill di chiudere tutto l'albero.
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            try:
                preexec_fn = os.setsid
            except AttributeError:
                preexec_fn = None
        if posix:
            # Passa il comando come singolo argomento a bash -lc.
            # Niente shell=True: con cmd.exe i backslash e le virgolette
            # venivano corrotti (echo 'ciao' -> unexpected EOF).
            proc = subprocess.Popen(
                [posix, "-lc", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                cwd=str(_root()),
                env=_sandbox_env(),
                creationflags=creationflags,
                start_new_session=(os.name != "nt"),
                preexec_fn=preexec_fn,
            )
        else:
            proc = subprocess.Popen(
                shell_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                cwd=str(_root()),
                env=_sandbox_env(),
                creationflags=creationflags,
                start_new_session=(os.name != "nt"),
                preexec_fn=preexec_fn,
            )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            r = subprocess.CompletedProcess(
                args=shell_cmd, returncode=proc.returncode, stdout=stdout,
                stderr=stderr)
        except subprocess.TimeoutExpired:
            _kill_tree(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return f"TIMEOUT dopo {timeout}s: comando interrotto e processo terminato"

        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        hint = ""
        if not posix:
            hint = (
                "\n\n[nota ambiente: shell cmd.exe, non bash. Usa ' && ' per "
                "combinare i comandi, il ';' NON funziona e non segnala errore. "
                "Le variabili $VAR non vengono espanse.]"
            )
        return f"exit={r.returncode}\n{out[:8000]}{hint}"

    desc = "Esegue un comando shell e restituisce stdout, stderr e codice di uscita."
    if posix:
        desc += " Ambiente POSIX disponibile: puoi usare ';' per i separatori."
    else:
        desc += " Attenzione: su Windows il separatore è ' && ', il ';' non funziona."
    desc += (
        " Attenzione: i percorsi che escono dalla directory di lavoro "
        "vengono bloccati."
    )

    return Tool(
        name="run_shell",
        description=desc,
        schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": (
     "Comando da eseguire. Può nominare percorsi ASSOLUTI: se sono "
     "fuori dalla cartella di lavoro, all'utente compare una domanda "
     "con le scelte (una volta / per questa sessione / sempre / mai) e "
     "il comando aspetta la risposta. Non serve spiegare come chiedere."
 )},
                "timeout": {"type": "integer", "description": "Timeout in secondi.", "default": 60},
            },
            "required": ["command"],
        },
        handler=handler,
    )


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
    far mangare gli apici al quoting di cmd. """
    return "'" + s.replace("'", "'\\''") + "'"


def tool_calculate() -> Tool:
    def handler(expression: str) -> str:
        # valutazione ristretta: solo lettere, numeri e operatori. Niente
        # eval su input del modello — quello è il vettore classico.
        import ast
        import operator as op

        allowed = {
            ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
            ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
            ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos,
        }

        def walk(node: Any) -> Any:
            if isinstance(node, ast.Expression):
                return walk(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in allowed:
                return allowed[type(node.op)](walk(node.left), walk(node.right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
                return allowed[type(node.op)](walk(node.operand))
            raise ValueError(f"espressione non consentita: {type(node).__name__}")

        try:
            return str(walk(ast.parse(expression, mode="eval")))
        except Exception as e:
            return f"ERRORE: {e}"

    return Tool(
        name="calculate",
        description="Calcola un'espressione aritmetica. Supporta + - * / // % **.",
        schema={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Espressione aritmetica, es. '(3+4)*2'"}
            },
            "required": ["expression"],
        },
        handler=handler,
    )


# --------------------------------------------------------------------------


# Profili di carico dei tool. Servono per non mandare tutto al modello su
# ogni turno: il buco dichiarato era proprio la politica di attivazione,
# non la primitiva. Qui c'e' la mappa; la decisione resta esplicita e
# ispezionabile, nessuna automazione silenziosa.
_PROFILI: dict[str, tuple[str, ...]] = {
    "base": ("read_file", "write_file", "list_dir", "run_shell",
             "calculate"),
    "ricerca": ("read_file", "write_file", "list_dir", "run_shell",
                "calculate", "memoria", "web_cerca", "web_leggi",
                "storico_cerca"),
    "skill": ("read_file", "skill_cerca", "skill_genera", "skill_importa",
             "skill_leggi"),
    "pieno": (),  # sentinella: attiva tutto quello che e' registrato
}


def applica_profilo(registry: ToolRegistry, nome: str) -> None:
    """Stringe il registry a un profilo. `pieno` riporta tutto attivo.

    Non rimuove i tool, disattiva solo quelli fuori profilo: un blocco
    può riattivare strumenti dopo, senza dover re-registrarli.
    """
    if nome not in _PROFILI:
        raise KeyError(f"profilo strumenti sconosciuto: {nome}. "
                       f"Disponibili: {sorted(_PROFILI)}")
    tutti = set(registry.all_names())
    if nome == "pieno":
        registry.activate(*tutti)
        return
    voluti = set(_PROFILI[nome])
    for n in tutti:
        if n in voluti:
            registry.activate(n)
        else:
            registry.deactivate(n)


def profilo_per_testo(testo: str) -> str:
    """Sceglie un profilo da un testo. Euristica esplicita e conservativa.

    Meglio un profilo più ampio del necessario che uno troppo stretto:
    un tool mancante è un fallimento visibile, uno di troppo solo costo.
    """
    t = (testo or "").lower()
    if any(k in t for k in ("skill", "procedura", "workflow")):
        return "skill"
    if any(k in t for k in ("cerca", "web", "ricerca", "articolo",
                            "notizie", "memoria", "history")):
        return "ricerca"
    # default: programmare / file / shell / locale
    return "base"

def default_registry() -> ToolRegistry:
    """Il set di base. Espandibile: i tool del cliente si aggiungono qui."""
    r = ToolRegistry()
    r.register(tool_read_file())
    r.register(tool_write_file())
    r.register(tool_list_dir())
    r.register(tool_run_shell())
    r.register(tool_calculate())
    # La memoria. Strumento e non iniezione: iniettare tutta la memoria
    # a ogni turno costa token in proporzione a quanto ricordi, e una
    # memoria che cresce per mesi avvelena il contesto di ogni richiesta.
    # Adesso l'agente cerca quello che gli serve e paga solo per quello.
    from .memoria_tools import tool_memoria
    r.register(tool_memoria())
    # Il web. I dieci tool che c'erano facevano tutti la stessa cosa:
    # leggere e scrivere sul disco. Non uno cercava niente, quindi una
    # domanda che dipende da fatti esterni non aveva risposta — non
    # perché il modello non lo sapesse, ma perché non poteva saperlo.
    #
    # DuckDuckGo senza chiave: coerente col resto, che è gratis e gira
    # in locale. Se `ddgs` non è installata il tool lo dice e Orchestra
    # resta esattamente quella di prima.
    from .web_tools import tool_web_cerca, tool_web_leggi
    r.register(tool_web_cerca())
    r.register(tool_web_leggi())
    # Cercare nelle conversazioni passate. Lo storico conservava e non
    # faceva ritrovare: l'unico modo era aprire le chat una a una, e
    # l'indice che c'era era per sessione, non per contenuto. Lo stesso
    # difetto della memoria, con l'indice FTS5 già scritto e non collegato.
    from .storico_tools import tool_storico_cerca
    r.register(tool_storico_cerca())
    # Le skill vengono dopo: i loro tool hanno senso solo se l'indice
    # sa di cosa parla, e l'indice si riempie con skill_importa. Ma
    # sono attivi subito — un tool che si accende solo dopo che
    # l'hai usato una volta e' un tool che non usi mai.
    import orchestra.skill_tools as _st
    _st.registra(r)
    # Browser: apertura/render/screenshot. Il rendering reale usa Chrome o
    # Edge di sistema: assente, si degrada a fetch testuale.
    from .browser_tools import (
        tool_browser_apri, tool_browser_render, tool_browser_screenshot)
    r.register(tool_browser_apri())
    r.register(tool_browser_render())
    r.register(tool_browser_screenshot())
    # Automazione computer via API Windows native (niente pip).
    from .computer_tools import (
        tool_computer_screenshot, tool_computer_click,
        tool_computer_type, tool_computer_open)
    r.register(tool_computer_screenshot())
    r.register(tool_computer_click())
    r.register(tool_computer_type())
    r.register(tool_computer_open())
    return r


SYSTEM_PROMPT = """Sei Orchestra, un agente tecnico.

Come lavori:
- Usa gli strumenti per fare, non per confermare che hai fatto. Se ti serve un dato, leggilo.
- Se uno strumento restituisce un errore, leggi l'errore e correggi. Non ripetere la stessa chiamata identica.
- Preferisci `list_dir` e `read_file` a indovinare il contenuto di un file.
- Rispondi in modo conciso. Niente preamboli, niente ripetizioni di quello che hai già detto.
- Quando hai finito, dì in una riga cosa hai fatto e dove sta il risultato.

Quando cercare sul web:
- La tua conoscenza ha una data di taglio. Se la domanda dipende da un fatto
  che può essere cambiato dopo — prezzi, versioni, notizie, documentazione,
  chi è in carica oggi — cerca con `web_cerca` invece di rispondere a memoria.
- Se rispondi a memoria su una cosa che puoi verificare, dillo: "questo lo so
  fino a <data>, se vuoi te lo verifico". Non presentare un ricordo come un
  fatto attuale.
- `web_cerca` dà titoli e riassunti; `web_leggi` apre la pagina. Se il
  riassunto non basta, apri il risultato invece di indovinare dal titolo.
- Cerca solo quando serve: per cose che sai già, cercare è rumore e costa tempo.

Fuori dalla cartella di lavoro:
- Gli strumenti accettano percorsi ASSOLUTI, non solo relativi. Puoi quindi
  leggere C:\\Users\\adver\\pippo senza portare nulla dentro il progetto.
- Se il percorso è fuori, all'utente compare una domanda con quattro
  scelte: una volta, per questa sessione, sempre, mai. Non devi fare nulla:
  la domanda la fa lo strumento e aspetta. Tu non hai strumenti per
  chiedere e non devi spiegare come fare.
- Se l'utente nega, il messaggio lo dice. Non riprovare lo stesso percorso
  con un altro strumento e non presentarlo come un errore: è una risposta,
  non un guasto. Rispettala e prova un'altra strada, o spiega in una riga
  che ti serve quel permesso.
- Alcuni percorsi non sono negabili da nessuna scelta (file di credenziali,
  cartelle di sistema). Se è così, lo strumento lo dice: è una decisione
  del sistema, non un errore da riprovare.
- Non dire mai "non posso accedere a <cartella>" senza averci provato. Se
  hai la conferma che è irraggiungibile, allora sì, e in una riga spiega
  perché e cosa hai tentato."""
