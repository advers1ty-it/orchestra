"""Tool git: leggere lo stato del repository, senza cambiarlo.

Perché esiste
-------------
Per sapere cosa ha toccato l'agente, l'unica strada era `run_shell` con
`git status`, `git diff` o `git log`: comandi che funzionano, ma che
finiscono nello stesso canale di comandi che scrivono, e con un output
che può essere enorme. Un `git diff --stat` su un repository grande
riempie il contesto di nomi di file e l'agente non vede più la riga che
conta.

Qui le tre letture che servono davvero hanno una forma sola, non
interpretano argomenti arbitrari e passano da `subprocess` senza shell.
L'output è tagliato a un tetto esplicito, e il taglio viene DICHIARATO:
un output che finisce a metà senza dirlo sembra completo, e l'agente
corregge la riga sbagliata.

Commit e push non sono qui
--------------------------
Questo tool non li esegue: sono azioni che cambiano il repository e
richiedono una conferma esplicita. Restano nella shell, dove il gate le
chiede davvero (anche quando il comando gira dentro la cartella di
lavoro). Aggiungerle qui senza quella conferma sarebbe un secondo modo
per scrivere, e il primo che dimentica il controllo sarebbe quello
usato.
"""

from __future__ import annotations

import shutil
import subprocess

from ..types import Tool
from ._guard import _root, _sandbox_env

# Quanto output torna al modello. `git status` su un repo con molti file
# non tracciati può superare abbondantemente questa soglia; il taglio è
# dichiarato sotto. Dodici kilobyte sono circa 150 righe di nomi: già
# troppe per una diagnosi, abbastanza per non perdere il file che conta.
TETTO_USCITA = 12_000

# `git log -n` ha già un limite suo: oltre cinquanta commit si guarda la
# storia, non lo stato del lavoro. Il numero è anche il massimo che il
# modello può chiedere.
MAX_LOG = 50

TIMEOUT = 20


def _limita(testo: str) -> str:
    """Taglia l'output e dice quanto ne ha mostrato.

    Il taglio avviene all'ultimo fine riga prima del tetto: una riga di
    `git status` tagliata a metà (un percorso troncato) è peggio di una
    riga in meno, perché sembra un file che esiste davvero.
    """
    if len(testo) <= TETTO_USCITA:
        return testo
    tagliato = testo[:TETTO_USCITA]
    if "\n" in tagliato:
        tagliato = tagliato.rsplit("\n", 1)[0]
    return (tagliato + f"\n... [output troncato: {len(testo)} caratteri in "
            f"totale, qui i primi {len(tagliato)}]")


def _errore(r: subprocess.CompletedProcess) -> str:
    """L'errore di git, tagliato e con l'exit code."""
    msg = (r.stderr or r.stdout or "").strip()
    if "not a git repository" in msg.lower():
        return f"NON È UN REPOSITORY GIT: {_root()}"
    return f"ERRORE GIT (exit {r.returncode}):\n" + _limita(
        msg or "(nessun messaggio)")


def _git(argomenti: list[str]) -> subprocess.CompletedProcess:
    """Esegue git senza shell, nella root, con un ambiente senza segreti."""
    env = _sandbox_env()
    env.update({
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        # `git status` può aggiornare l'indice per le statistiche: qui non
        # deve scrivere niente, nemmeno un lock.
        "GIT_OPTIONAL_LOCKS": "0",
    })
    return subprocess.run(
        # `core.fsmonitor=false`: un repository può configurare un
        # programma da eseguire mentre git guarda lo stato. Qui git deve
        # solo leggere, non lanciare comandi scritti nel repository.
        ["git", "--no-pager", "-c", "core.fsmonitor=false", *argomenti],
        cwd=str(_root()),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
    )


def tool_git() -> Tool:
    def handler(azione: str = "status", limite: int = 10) -> str:
        a = (azione or "status").strip().lower()
        if a in ("commit", "push"):
            return ("NON ESEGUITO: `git` è in sola lettura. Commit e push "
                    "richiedono una conferma esplicita e passano dalla "
                    "shell; questo tool non li esegue.")
        if a not in ("status", "diff_stat", "log"):
            return ("Azione non disponibile: "
                    f"{azione!r}. Usa status, diff_stat o log. "
                    "Commit e push non sono azioni di questo tool.")

        if shutil.which("git") is None:
            return ("git non è installato o non è nel PATH: senza git "
                    "non posso leggere il repository.")

        try:
            if a == "status":
                # `git status` non accetta `--no-color` in tutte le
                # versioni, e con l'output catturato non e' un terminale:
                # non aggiunge colore comunque.
                r = _git(["status", "--short", "--branch"])
                if r.returncode != 0:
                    return _errore(r)
                testo = (r.stdout or "").strip()
                return "git status:\n" + _limita(
                    testo or "(working tree pulito)")

            if a == "diff_stat":
                # Niente driver esterni né textconv: anche `diff --stat`
                # può eseguire un programma configurato nel repository.
                r = _git(["diff", "--stat", "--no-color", "--no-ext-diff",
                          "--no-textconv"])
                if r.returncode != 0:
                    return _errore(r)
                testo = (r.stdout or "").strip()
                return "git diff --stat:\n" + _limita(
                    testo or "(nessuna differenza non committata)")

            # log
            try:
                n = max(1, min(int(limite or 10), MAX_LOG))
            except (TypeError, ValueError):
                n = 10
            r = _git(["log", "--oneline", "--decorate=short", "--no-color",
                      f"-n{n}"])
            if r.returncode != 0:
                err = (r.stderr or "").lower()
                if ("does not have any commits" in err
                        or "non ha ancora" in err):
                    return f"Nessun commit in {_root()}."
                return _errore(r)
            testo = (r.stdout or "").strip()
            return f"git log (ultimi {n}):\n" + _limita(
                testo or "(nessun commit)")
        except subprocess.TimeoutExpired:
            return f"TIMEOUT dopo {TIMEOUT}s: git non ha risposto."
        except FileNotFoundError:
            return ("git non è installato o non è nel PATH: senza git "
                    "non posso leggere il repository.")
        except OSError as e:
            return f"NON RIESCO A ESEGUIRE GIT: {e}"

    return Tool(
        name="git",
        description=(
            "Reads git state without changing the repository: status "
            "(short branch and files), diff_stat (unstaged diff --stat), "
            "log (one line per commit). The output is capped and says when "
            "it was truncated. It does NOT commit or push: those actions "
            "require explicit confirmation and are not part of this tool."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {
                    "type": "string",
                    "enum": ["status", "diff_stat", "log"],
                    "default": "status",
                    "description": (
                        "What to read: status, diff_stat (unstaged changes), "
                        "or log. Default: status."
                    ),
                },
                "limite": {
                    "type": "integer",
                    "default": 10,
                    "description": (
                        "For log: how many commits, 1-50. Default 10. "
                        "Ignored by status and diff_stat."
                    ),
                },
            },
        },
        handler=handler,
    )
