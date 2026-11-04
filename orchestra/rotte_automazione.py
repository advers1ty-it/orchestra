"""Cose che partono da sole: goal, scheduler, cron, autostart, tunnel remoto.

I gestori sono metodi della classe `RotteAutomazione`, che `Rotte` compone
insieme alle altre. Le rotte si dichiarano con `@rotta` accanto al codice
che le serve; la tabella e il dispatch stanno in `rotte.py` e in
`webapp.Handler._instrada`.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from .rotte import rotta


# Le rotte: percorso e metodo nel decoratore, il corpo
# sotto. Il commento sopra ogni gestore dice perche' esiste.
class RotteAutomazione:
    @rotta("GET", "/api/remote/info")
    def _r_get_remote_info(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        self._json(self._info_remoto())

    @rotta("GET", "/api/remote/status")
    def _r_get_remote_status(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        self._json(self._api_remote_status({}))

    @rotta("GET", "/api/goal/status")
    def _r_get_goal_status(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        import urllib.parse as _up
        parsed = _up.urlparse(self.path)
        gid = (_up.parse_qs(parsed.query).get("id") or [None])[0]
        from . import goal as goal_mod
        if gid:
            g = goal_mod.get(gid)
            if not g:
                self._json({"error": "goal sconosciuto"}, 404)
            else:
                self._json(g)
        else:
            self._json({"goals": goal_mod.list_goals()})

    @rotta("GET", "/api/goal/ready")
    def _r_get_goal_ready(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        from . import goal as goal_mod
        pronti = [g for g in goal_mod.list_goals()
                  if not goal_mod.motivo_non_pronto(g)]
        self._json({"pronti": pronti})

    @rotta("GET", "/api/scheduler/status")
    def _r_get_scheduler_status(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from . import goal as goal_mod
        self._json(goal_mod.scheduler_status())

    @rotta("GET", "/api/cron/jobs")
    def _r_get_cron_jobs(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        from . import cron as cron_mod
        self._json({"jobs": cron_mod.list_jobs()})

    @rotta("GET", "/api/cron/scheduler/status")
    def _r_get_cron_scheduler_status(self, path: str, body: dict[str, Any],
                                     s: Any) -> None:
        from . import cron as cron_mod
        self._json(cron_mod.scheduler_status())

    @rotta("GET", "/api/autostart/status")
    def _r_get_autostart_status(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from . import autostart as as_mod
        self._json({"disponibile": as_mod.disponibile(),
                    "attivo": as_mod.stato()})

    @rotta("POST", "/api/remote/start")
    def _r_post_remote_start(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        self._json(self._api_remote_start(body))

    @rotta("POST", "/api/remote/stop")
    def _r_post_remote_stop(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        self._json(self._api_remote_stop(body))

    @rotta("POST", "/api/remote/status")
    def _r_post_remote_status(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        self._json(self._api_remote_status(body))

    @rotta("POST", "/api/remote/info")
    def _r_post_remote_info(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        self._json(self._info_remoto())

    @rotta("POST", "/api/goal/start")
    def _r_post_goal_start(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        objective = (body.get("objective") or "").strip() if isinstance(body, dict) else ""
        if not objective:
            self._json({"error": "objective richiesto"}, 400)
            return
        profile = (body.get("profile") or "auto").strip() if isinstance(body, dict) else "auto"
        max_iters = 60
        max_attempts = 1
        priority = 0
        not_before = None
        criteri = None
        recovery = None
        depends_on = None
        parent_id = None
        kind = "goal"
        consenti_parziale = False
        if isinstance(body, dict):
            try:
                max_iters = int(body.get("max_iterations") or 60)
                max_attempts = int(body.get("max_attempts") or 1)
                priority = int(body.get("priority") or 0)
            except (TypeError, ValueError):
                max_iters = 60
                max_attempts = 1
                priority = 0
            try:
                if body.get("not_before") is not None:
                    not_before = float(body.get("not_before"))
            except (TypeError, ValueError):
                not_before = None
            depends_on = body.get("depends_on")
            parent_id = (body.get("parent_id") or None)
            kind = (body.get("kind") or "goal")
            consenti_parziale = bool(body.get("consenti_parziale"))
            criteri = body.get("criteri")
            recovery = body.get("recovery")
        from . import goal as goal_mod
        try:
            gid = goal_mod.start_goal(
                objective, env=self.app.env, profile=profile,
                max_iterations=max_iters, parent_id=parent_id,
                depends_on=depends_on, priority=priority,
                not_before=not_before, kind=kind,
                max_attempts=max_attempts,
                consenti_parziale=consenti_parziale,
                criteri=criteri, recovery=recovery)
        except (RuntimeError, ValueError) as e:
            self._json({"error": f"goal non avviato: {e}"}, 409)
            return
        self._json({"ok": True, "id": gid})
        return

    @rotta("POST", "/api/goal/run-next")
    def _r_post_goal_run_next(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        from . import goal as goal_mod
        try:
            g = goal_mod.accoda_prossimo(env=self.app.env)
        except (RuntimeError, ValueError) as e:
            self._json({"error": f"scheduler: {e}"}, 409)
            return
        if not g:
            self._json({"ok": False, "error": "nessun goal pronto"})
            return
        self._json({"ok": True, "id": g.get("id")})
        return

    @rotta("POST", "/api/scheduler/start")
    def _r_post_scheduler_start(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        interval = 5.0
        if isinstance(body, dict) and body.get("interval") is not None:
            try:
                interval = float(body.get("interval"))
            except (TypeError, ValueError):
                interval = 5.0
        from . import goal as goal_mod
        ok = goal_mod.scheduler_start(env=self.app.env, interval=interval)
        if not ok:
            self._json({"ok": False, "error": "scheduler gia' attivo"})
            return
        self._json({"ok": True})
        return

    @rotta("POST", "/api/scheduler/stop")
    def _r_post_scheduler_stop(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        from . import goal as goal_mod
        goal_mod.scheduler_stop()
        self._json({"ok": True})
        return

    @rotta("POST", "/api/cron/create")
    def _r_post_cron_create(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import cron as cron_mod
        try:
            nome = (body.get("nome") or "").strip() if isinstance(body, dict) else ""
            schedule = (body.get("schedule") or "").strip() if isinstance(body, dict) else ""
            action_type = (body.get("action_type") or "goal").strip() if isinstance(body, dict) else "goal"
            if action_type == "shell":
                action = {"command": (body.get("command") or "").strip() if isinstance(body, dict) else ""}
            else:
                action = {
                    "objective": (body.get("objective") or "").strip() if isinstance(body, dict) else "",
                    "profile": (body.get("profile") or "auto").strip() if isinstance(body, dict) else "auto",
                }
            enabled = True
            if isinstance(body, dict) and body.get("enabled") is not None:
                enabled = bool(body.get("enabled"))
            job = cron_mod.crea(nome, schedule, action_type, action, enabled=enabled)
        except (ValueError, RuntimeError) as e:
            self._json({"error": str(e)}, 400)
            return
        self._json({"ok": True, "job": job})
        return

    @rotta("POST", "/api/cron/update")
    def _r_post_cron_update(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import cron as cron_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        if not jid:
            self._json({"error": "id richiesto"}, 400)
            return
        campi = {}
        if isinstance(body, dict):
            if body.get("nome") is not None:
                campi["nome"] = body.get("nome")
            if body.get("schedule") is not None:
                campi["schedule"] = body.get("schedule")
            if body.get("action_type") is not None:
                campi["action_type"] = body.get("action_type")
            if body.get("enabled") is not None:
                campi["enabled"] = bool(body.get("enabled"))
            if body.get("objective") is not None or body.get("command") is not None:
                at = body.get("action_type") or "goal"
                if at == "shell":
                    campi["action"] = {"command": (body.get("command") or "").strip()}
                else:
                    campi["action"] = {"objective": (body.get("objective") or "").strip(),
                                       "profile": (body.get("profile") or "auto").strip()}
        try:
            job = cron_mod.aggiorna(jid, **campi)
        except (ValueError, RuntimeError) as e:
            self._json({"error": str(e)}, 400)
            return
        if job is None:
            self._json({"error": "job sconosciuto"}, 404)
            return
        self._json({"ok": True, "job": job})
        return

    @rotta("POST", "/api/cron/delete")
    def _r_post_cron_delete(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import cron as cron_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        ok = cron_mod.elimina(str(jid or ""))
        self._json({"ok": ok})
        return

    @rotta("POST", "/api/cron/run")
    def _r_post_cron_run(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        from . import cron as cron_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        r = cron_mod.esegui_job(str(jid or ""), env=self.app.env)
        self._json(r)
        return

    @rotta("POST", "/api/cron/scheduler/start")
    def _r_post_cron_scheduler_start(self, path: str, body: dict[str, Any],
                                     s: Any) -> None:
        from . import cron as cron_mod
        interval = 30.0
        if isinstance(body, dict) and body.get("interval") is not None:
            try:
                interval = float(body.get("interval"))
            except (TypeError, ValueError):
                interval = 30.0
        ok = cron_mod.scheduler_start(env=self.app.env, interval=interval)
        self._json({"ok": True} if ok else {"ok": False, "error": "gia' attivo"})
        return

    @rotta("POST", "/api/cron/scheduler/stop")
    def _r_post_cron_scheduler_stop(self, path: str, body: dict[str, Any],
                                    s: Any) -> None:
        from . import cron as cron_mod
        cron_mod.scheduler_stop()
        self._json({"ok": True})
        return

    @rotta("POST", "/api/autostart/enable")
    def _r_post_autostart_enable(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        from . import autostart as as_mod
        ok = as_mod.abilita()
        self._json({"ok": ok, "attivo": as_mod.stato()})
        return

    @rotta("POST", "/api/autostart/disable")
    def _r_post_autostart_disable(self, path: str, body: dict[str, Any],
                                  s: Any) -> None:
        from . import autostart as as_mod
        ok = as_mod.disabilita()
        self._json({"ok": ok, "attivo": as_mod.stato()})
        return

    @rotta("POST", "/api/goal/stop")
    def _r_post_goal_stop(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        gid = (body.get("id") if isinstance(body, dict) else None)
        from . import goal as goal_mod
        ok = goal_mod.cancel(str(gid or ""))
        self._json({"ok": ok})
        return
