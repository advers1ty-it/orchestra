"""Tool cron: gestire job programmati (crea, modifica, elimina, esegui, lista).

Un solo tool con un parametro `azione` per non moltiplicare i tool nel prompt.
"""

from __future__ import annotations

import json
from typing import Any

from ..types import Tool
import orchestra.cron as cron_mod


def _j(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


def tool_cron() -> Tool:
    def handler(
        azione: str = "lista",
        id: str = "",
        nome: str = "",
        schedule: str = "",
        action_type: str = "goal",
        objective: str = "",
        profile: str = "auto",
        command: str = "",
        enabled: bool = True,
    ) -> str:
        azione = (azione or "lista").strip().lower()
        try:
            if azione in ("lista", "list", "elenca"):
                jobs = cron_mod.list_jobs()
                if not jobs:
                    return "Nessun job cron."
                out = []
                for j in jobs:
                    out.append(f"{j.get('id')} | {j.get('nome')} | {j.get('schedule')} | "
                               f"{'on' if j.get('enabled') else 'off'} | next={j.get('next_run')} | "
                               f"last={j.get('last_status')} ({j.get('last_run')})")
                return "\n".join(out)

            if azione in ("stato", "status", "scheduler"):
                return _j(cron_mod.scheduler_status())
            if azione in ("autostart_stato", "autostart_status", "autostart"):
                import orchestra.autostart as as_mod
                return _j({"disponibile": as_mod.disponibile(), "attivo": as_mod.stato()})
            if azione in ("autostart_on", "autostart_attiva", "autostart_enable"):
                import orchestra.autostart as as_mod
                ok = as_mod.abilita()
                return "autostart attivato" if ok else "autostart non disponibile"
            if azione in ("autostart_off", "autostart_disattiva", "autostart_disable"):
                import orchestra.autostart as as_mod
                ok = as_mod.disabilita()
                return "autostart disattivato" if ok else "autostart non disponibile"

            if azione in ("avvia_scheduler", "start_scheduler", "avvia"):
                ok = cron_mod.scheduler_start()
                return "scheduler cron avviato" if ok else "scheduler cron gia' attivo"

            if azione in ("ferma_scheduler", "stop_scheduler", "ferma"):
                cron_mod.scheduler_stop()
                return "scheduler cron fermato"

            if azione in ("crea", "create", "aggiungi", "add"):
                if action_type == "shell":
                    action = {"command": command}
                else:
                    action = {"objective": objective, "profile": profile}
                job = cron_mod.crea(nome, schedule, action_type, action, enabled=enabled)
                return f"job creato: {job.get('id')} ({job.get('nome')}) next={job.get('next_run')}"

            if azione in ("modifica", "update", "mod"):
                if not id:
                    return "ERRORE: id richiesto"
                campi = {}
                if nome:
                    campi["nome"] = nome
                if schedule:
                    campi["schedule"] = schedule
                if action_type:
                    campi["action_type"] = action_type
                if objective or command:
                    if action_type == "shell":
                        campi["action"] = {"command": command}
                    else:
                        campi["action"] = {"objective": objective, "profile": profile}
                campi["enabled"] = bool(enabled)
                j = cron_mod.aggiorna(id, **campi)
                if j is None:
                    return "ERRORE: job sconosciuto"
                return f"job aggiornato: {j.get('id')} next={j.get('next_run')}"

            if azione in ("elimina", "delete", "rimuovi", "remove"):
                if not id:
                    return "ERRORE: id richiesto"
                ok = cron_mod.elimina(id)
                return "eliminato" if ok else "ERRORE: job sconosciuto"

            if azione in ("abilita", "enable"):
                if not id:
                    return "ERRORE: id richiesto"
                ok = cron_mod.abilita(id, True)
                return "abilitato" if ok else "ERRORE: job sconosciuto"

            if azione in ("disabilita", "disable"):
                if not id:
                    return "ERRORE: id richiesto"
                ok = cron_mod.abilita(id, False)
                return "disabilitato" if ok else "ERRORE: job sconosciuto"

            if azione in ("esegui", "run", "run_now", "esegui_ora"):
                if not id:
                    return "ERRORE: id richiesto"
                r = cron_mod.esegui_job(id)
                return _j(r)

            if azione in ("dettagli", "get", "dettaglio"):
                if not id:
                    return "ERRORE: id richiesto"
                j = cron_mod.get(id)
                if not j:
                    return "ERRORE: job sconosciuto"
                return _j(j)

            return ("ERRORE: azione sconosciuta. Usa: lista, crea, modifica, elimina, "
                    "abilita, disabilita, esegui, dettagli, stato, avvia_scheduler, "
                    "ferma_scheduler.")
        except Exception as e:  # noqa: BLE001
            return f"ERRORE: {type(e).__name__}: {e}"

    return Tool(
        name="cron",
        description=("Gestisce job programmati (cron): crea/modifica/elimina job che eseguono "
                     "obiettivi o comandi shell a orari programmati (espressione cron a 5 campi "
                     "o shortcut @daily, @hourly, @weekly, @monthly, @yearly, @reboot). "
                     "Azioni: lista, crea, modifica, elimina, abilita, disabilita, esegui, "
                     "dettagli, stato, avvia_scheduler, ferma_scheduler."),
        schema={
            "type": "object",
            "properties": {
                "azione": {"type": "string", "description": "lista|crea|modifica|elimina|abilita|disabilita|esegui|dettagli|stato|avvia_scheduler|ferma_scheduler"},
                "id": {"type": "string", "description": "id del job (per modifica/elimina/esegui/dettagli)"},
                "nome": {"type": "string", "description": "nome del job"},
                "schedule": {"type": "string", "description": "espressione cron 5 campi o shortcut (@daily, @hourly, @weekly, @monthly, @yearly, @reboot)"},
                "action_type": {"type": "string", "description": "goal (default) o shell"},
                "objective": {"type": "string", "description": "obiettivo da eseguire (se action_type=goal)"},
                "profile": {"type": "string", "description": "profilo strumenti per il goal (auto/base/ricerca/skill/pieno)"},
                "command": {"type": "string", "description": "comando shell (se action_type=shell)"},
                "enabled": {"type": "boolean", "description": "abilitato (default true)"},
            },
            "required": [],
        },
        handler=handler,
    )
