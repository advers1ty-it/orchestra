"""Tool processo: avviare, leggere e fermare un comando che resta vivo."""

from __future__ import annotations

from ..types import Tool
from . import processi
from ._guard import verifica_comando


def _testo_avvio(esito: dict) -> str:
    """Il messaggio di un avvio, che deve dire subito la verita' vera.

    Un id valido non vuol dire un server che risponde. Se il processo e'
    morto durante l'attesa, il tool lo dice adesso e allega l'output:
    altrimenti l'agente apre la pagina, non trova niente, e spende tre
    iterazioni a cercare un difetto nel codice che invece e' un
    `EADDRINUSE` gia' scritto nel log.
    """
    righe = [f"Comando: {esito.get('comando') or ''}",
             f"Cartella: {esito['cwd']}",
             f"Log: {esito['log']}"]
    if esito.get("vivo"):
        testa = (f"AVVIATO {esito['id']} (pid {esito['pid']}), ancora vivo "
                 f"dopo {esito['durata']}s.")
        corpo = "\n".join(righe)
        corpo += (f"\nLeggi l'output con processo(azione=\"leggi\", "
                  f"id=\"{esito['id']}\"); fermalo con "
                  f"processo(azione=\"ferma\", id=\"{esito['id']}\").")
    else:
        testa = (f"USCITO SUBITO {esito['id']} (codice {esito['codice']}) "
                 f"dopo {esito['durata']}s.\n"
                 f"Il comando e' morto durante l'avvio, quindi non c'e' "
                 f"niente da leggere piu' tardi: la ragione e' nell'output "
                 f"qui sotto.")
        corpo = "\n".join(righe)
    uscita = (esito.get("uscita") or "").strip()
    if uscita:
        corpo += f"\n--- output ---\n{uscita}"
    if esito.get("nota"):
        corpo += f"\n[{esito['nota']}]"
    return f"{testa}\n{corpo}"


def _testo_lettura(esito: dict) -> str:
    righe = [f"{esito['id']} — {esito['stato']}",
             f"Comando: {esito['cmd']}" if esito.get("cmd") else "",
             f"Log: {esito['log']}"]
    righe = [r for r in righe if r]
    uscita = (esito.get("uscita") or "").strip()
    if uscita:
        righe.append("--- output ---")
        righe.append(uscita)
    else:
        righe.append("(nessun output finora)")
    if esito.get("nota"):
        righe.append(f"[{esito['nota']}]")
    return "\n".join(righe)


def tool_processo() -> Tool:
    def handler(azione: str = "elenca", comando: str = "", cwd: str = ".",
                id: str = "", righe: int = 80, attesa: float = 2.0) -> str:
        azione = (azione or "").strip().lower()
        if azione in ("avvia", "start"):
            # Gli stessi controlli di `run_shell`, dalla stessa funzione:
            # un comando in background non e' una scorciatoia attorno ai
            # permessi, e `rm -rf src &` deve chiedere come `rm -rf src`.
            blocco = verifica_comando(comando)
            if blocco:
                return blocco
            esito = processi.avvia(comando, cwd=cwd, attesa=attesa)
            if esito.get("errore"):
                return f"NON AVVIATO: {esito['errore']}"
            return _testo_avvio(esito)
        if azione == "leggi":
            if not (id or "").strip():
                return ("MANCA L'ID: serve l'id del processo che vuoi "
                        "leggere (lo stampa 'avvia'; 'elenca' li mostra tutti).")
            esito = processi.leggi(id, righe=righe)
            if esito.get("errore"):
                return esito["errore"]
            return _testo_lettura(esito)
        if azione == "ferma":
            if not (id or "").strip():
                return ("MANCA L'ID: serve l'id del processo da fermare "
                        "('elenca' li mostra tutti).")
            esito = processi.ferma(id)
            if esito.get("errore"):
                return esito["errore"]
            if esito.get("giafinito"):
                return f"{esito['id']} — {esito['stato']}: niente da fermare."
            righe_out = [f"FERMATO {esito['id']} — {esito['stato']}."]
            uscita = (esito.get("uscita") or "").strip()
            if uscita:
                righe_out.append("--- ultime righe ---")
                righe_out.append(uscita)
            if esito.get("nota"):
                righe_out.append(f"[{esito['nota']}]")
            return "\n".join(righe_out)
        if azione in ("elenca", "lista", "elenco"):
            esito = processi.elenca()
            if not esito["totale"]:
                return ("NESSUN PROCESSO: in questa sessione non hai avviato "
                        "niente con 'processo'. Per un comando breve usa "
                        "run_shell.")
            righe_out = [f"{esito['vivi']} vivi su {esito['totale']}:"]
            for p in esito["processi"]:
                righe_out.append(f"  {p['id']:5} {p['stato']:42} "
                                 f"{p['cmd']}")
            return "\n".join(righe_out)
        return (f"AZIONE NON VALIDA: '{azione}'. Usa avvia, leggi, ferma o "
                f"elenca.")

    return Tool(
        name="processo",
        description=(
            "Starts a long-running command and keeps it alive across tool "
            "calls, then reads its output and stops it. Use it for dev "
            "servers, watchers, tunnels: commands that never finish. "
            "run_shell WAITS and kills the command at its timeout, so a "
            "server started there is gone before you can open it. Flow: "
            "azione='avvia' returns an id and says immediately whether the "
            "process is still alive (a command that dies at startup — port "
            "in use, missing module — is reported with its output right "
            "there); azione='leggi' returns the last lines of the log "
            "without consuming them; azione='ferma' kills the whole process "
            "tree; azione='elenca' lists what is running. The same "
            "permission checks as run_shell apply. Processes stop when "
            "Orchestra exits."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {
                    "type": "string",
                    "enum": ["avvia", "leggi", "ferma", "elenca"],
                    "description": (
                        "avvia (start)|leggi (read the log)|ferma "
                        "(stop)|elenca (list). Default 'elenca'."),
                },
                "comando": {
                    "type": "string",
                    "description": (
                        "The command to run, for azione='avvia'. It may "
                        "name ABSOLUTE paths: if they lie outside the "
                        "working directory the user is asked, exactly as "
                        "with run_shell."),
                },
                "cwd": {
                    "type": "string",
                    "description": (
                        "Working directory for the command, relative to the "
                        "project. Default '.'."),
                    "default": ".",
                },
                "id": {
                    "type": "string",
                    "description": (
                        "Process id returned by azione='avvia' (like 'p1'). "
                        "Required for leggi and ferma."),
                },
                "righe": {
                    "type": "integer",
                    "description": (
                        "How many lines from the end of the log to return "
                        "(default 80). The output is not consumed: reading "
                        "twice gives the same lines."),
                    "default": 80,
                },
                "attesa": {
                    "type": "number",
                    "description": (
                        "Seconds to wait after starting, to catch a command "
                        "that dies immediately (default 2). Only used by "
                        "'avvia'."),
                    "default": 2.0,
                },
            },
            "required": ["azione"],
        },
        handler=handler,
    )
