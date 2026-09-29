"""Tool di base: filesystem, shell, calcolo.

Sono i tool che un orchestratore deve avere per essere utile. Ognuno è
piccolo e dichiara il proprio schema con precisione — uno schema vago è la
causa numero uno di chiamate sbagliate.

Ogni handler è difensivo: legge i propri limiti (path traversal, dimensioni,
timeout) invece di fidarsi che il modello faccia la cosa giusta. Il modello
non è un confine di sicurezza.
"""

from __future__ import annotations

import os
import subprocess
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


def _safe_path(rel: str) -> Path:
    """Risolve un path relativo dentro ROOT, bloccando il traversal.

    Legge la root al momento della chiamata, non quella congelata
    all'import: vedi `_root()`. Il benchmark cambia la root a ogni task.
    """
    root = _root()
    p = (root / rel).resolve()
    if not str(p).startswith(str(root)):
        raise ValueError(f"path fuori dal root consentito: {rel}")
    return p


# --------------------------------------------------------------------------


def tool_read_file() -> Tool:
    def handler(path: str, max_lines: int = 400) -> str:
        p = _safe_path(path)
        if not p.exists():
            return f"NON ESISTE: {path}"
        if p.is_dir():
            entries = sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())
            return f"DIRECTORY {path}:\n" + "\n".join(entries[:max_lines])
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        numbered = [f"{i+1:>5}| {l}" for i, l in enumerate(lines[:max_lines])]
        tail = (
            f"\n... [{len(lines) - max_lines} righe rimanenti non mostrate]"
            if len(lines) > max_lines
            else ""
        )
        return "\n".join(numbered) + tail

    return Tool(
        name="read_file",
        description="Legge un file di testo con numeri di riga, o elenca una directory.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relativo alla root di lavoro."},
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
                "path": {"type": "string", "description": "Path relativo alla root di lavoro."},
                "content": {"type": "string", "description": "Contenuto completo del file."},
            },
            "required": ["path", "content"],
        },
        handler=handler,
    )


def tool_list_dir() -> Tool:
    def handler(path: str = ".") -> str:
        p = _safe_path(path)
        if not p.is_dir():
            return f"NON È UNA DIRECTORY: {path}"
        out = []
        for x in sorted(p.iterdir()):
            rel = x.relative_to(ROOT)
            if x.is_dir():
                n = len(list(x.rglob("*")))
                out.append(f"[dir]  {rel}/  ({n} elementi)")
            else:
                out.append(f"[file] {rel}  ({x.stat().st_size} byte)")
        return "\n".join(out[:300]) or "(vuota)"

    return Tool(
        name="list_dir",
        description="Elenca il contenuto di una directory con dimensioni.",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory, default '.'.", "default": "."}
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
       `head -2 ../../....env` leggeva le chiavi API di Hermes. Il root è
       un confine di sicurezza, non una convenzione, quindi va imposto
       anche a questo tool — non solo dichiarato.

    3. L'output non è garantito UTF-8. Senza errors="replace" un byte 0x8a
       solleva UnicodeDecodeError dentro subprocess e uccide il tool,
       facendo perdere il risultato di un comando che è andato a buon fine.
    """

    posix = _detect_posix_shell()

    def handler(command: str, timeout: int = 60) -> str:
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
        try:
            r = subprocess.run(
                shell_cmd,
                shell=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(_root()),
            )
        except subprocess.TimeoutExpired:
            return f"TIMEOUT dopo {timeout}s: comando interrotto"
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
                "command": {"type": "string", "description": "Comando da eseguire."},
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
    r"\.config/hermes",
)


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


def default_registry() -> ToolRegistry:
    """Il set di base. Espandibile: i tool del cliente si aggiungono qui."""
    r = ToolRegistry()
    r.register(tool_read_file())
    r.register(tool_write_file())
    r.register(tool_list_dir())
    r.register(tool_run_shell())
    r.register(tool_calculate())
    return r


SYSTEM_PROMPT = """Sei Orchestra, un agente tecnico.

Come lavori:
- Usa gli strumenti per fare, non per confermare che hai fatto. Se ti serve un dato, leggilo.
- Se uno strumento restituisce un errore, leggi l'errore e correggi. Non ripetere la stessa chiamata identica.
- Preferisci `list_dir` e `read_file` a indovinare il contenuto di un file.
- Rispondi in modo conciso. Niente preamboli, niente ripetizioni di quello che hai già detto.
- Quando hai finito, dì in una riga cosa hai fatto e dove sta il risultato."""
