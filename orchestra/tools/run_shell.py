"""Tool run_shell: eseguire un comando, con il root come confine."""

from __future__ import annotations

import os
import subprocess

from ..types import Tool
from ._guard import (
    _detect_posix_shell,
    _kill_tree,
    _root,
    _sandbox_env,
    _sq,
    dimentica_processo,
    registra_processo,
    verifica_comando,
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
        # Policy, confine della root, file di credenziali, comandi
        # distruttivi: tutti i controlli stanno in `verifica_comando`,
        # perche' dal 0.5.83 li deve passare anche `processo`. Duplicarli
        # qui vorrebbe dire due copie che divergono, e la seconda copia
        # sarebbe quella con il buco.
        blocco = verifica_comando(command)
        if blocco:
            return blocco

        shell_cmd = command
        if posix:
            # via esplicita: niente quoting da cmd, e `;` torna a essere un
            # separatore come il modello si aspetta
            shell_cmd = f'"{posix}" -lc {_sq(command)}'
        creationflags = 0
        if os.name == "nt":
            # nuovo process group: libera taskkill di chiudere tutto l'albero.
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        # Su POSIX il nuovo process group lo fa `start_new_session`, non
        # `preexec_fn=os.setsid`. Passarli tutti e due non e' ridondante:
        # e' un errore. `start_new_session` chiama setsid() in C prima di
        # `preexec_fn`, e la seconda chiamata trova il processo gia' capo
        # della sessione e solleva EPERM — in Python si vede come
        # "Exception occurred in preexec_fn", che uccide il comando. Su
        # Windows quel ramo non girava mai, quindi il difetto e' rimasto
        # invisibile finche' la CI non ha eseguito i test su Linux.
        # `start_new_session` e' anche l'unica forma sicura con thread
        # attivi (il server HTTP ne ha sempre).
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
            )
        # Da qui in poi il processo e' visibile a chi annulla: senza
        # registrazione `cancel()` aspettava la fine naturale del comando.
        registra_processo(proc)
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
        finally:
            dimentica_processo(proc)
        # Un processo ucciso da fuori (cancel) torna con un codice di
        # uscita che dipende dall'OS: dirlo esplicitamente evita che il
        # modello legga l'output parziale come "comando finito".
        if getattr(proc, "_orchestra_interrotto", False):
            return (f"INTERROTTO: comando terminato dalla cancellazione "
                    f"(exit={r.returncode}).\n{(r.stdout or '')[:2000]}")

        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        hint = ""
        if not posix:
            hint = (
                "\n\n[nota ambiente: shell cmd.exe, non bash. Usa ' && ' per "
                "combinare i comandi, il ';' NON funziona e non segnala errore. "
                "Le variabili $VAR non vengono espanse.]"
            )
        # Il taglio si DICE. Otto kilobyte sono tanti, e un output che
        # finisce a meta' senza una riga che lo dichiari sembra un output
        # completo: l'agente legge un traceback tagliato, conclude che il
        # difetto e' l'ultima riga che ha visto, e corregge quella. Meglio
        # una riga in piu' che una diagnosi su un testo mutilato.
        testa = out[:8000]
        if len(out) > len(testa):
            testa += (f"\n... [output tagliato: {len(out)} caratteri in "
                      f"totale, qui i primi {len(testa)}]")
        return f"exit={r.returncode}\n{testa}{hint}"

    desc = ("Runs a shell command and returns stdout, stderr and the exit "
            "code.")
    if posix:
        desc += " A POSIX shell is available: ';' works as a separator."
    else:
        desc += (" Careful: on Windows the separator is ' && ', ';' does not "
                 "work.")
    desc += (" Paths outside the working directory are blocked when they can "
             "be recognized; this is a best-effort boundary, not an OS sandbox.")

    return Tool(
        name="run_shell",
        description=desc,
        schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": (
     "The command to run. It may name ABSOLUTE paths: if they lie "
     "outside the working directory the user is asked (once / for this "
     "session / always / never) and the command waits for the answer. "
     "There is nothing to explain about asking."
 )},
                "timeout": {"type": "integer",
                            "description": "Timeout in seconds.",
                            "default": 60},
            },
            "required": ["command"],
        },
        handler=handler,
    )
