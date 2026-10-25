"""Cron: esecuzione programmata di job (obiettivi, comandi shell).

Un job e' una regola "quando" + "cosa fare". La parte "quando" e' una
espressione cron a 5 campi (minuto ora giorno mese giorno-settimana) oppure
uno shortcut (@hourly, @daily, @weekly, @monthly, @yearly, @reboot). La
parte "cosa" e' un'azione: un obiettivo (che l'agente esegue come goal) o
un comando shell.

Il modulo e' deliberatamente indipendente dal goal scheduler: quello esegue
i goal pronti in coda; questo decide QUANDO far partire un job, e poi
delega l'esecuzione a goal.start_goal o a subprocess.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import threading
import time
import uuid
from typing import Any

from .dati import cartella_dati, percorso

_SHORTCUTS = {
    "@reboot": None,
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

_LOCK = threading.Lock()
_SCHED = {"running": False, "interval": 30.0, "last_id": None,
          "last_status": "", "rounds": 0, "error": ""}


def _path() -> str:
    return percorso("cron.json")


def _load() -> list[dict[str, Any]]:
    path = _path()
    if not os.path.exists(path):
        return []
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return data
    return []


def _save(jobs: list[dict[str, Any]]) -> None:
    cartella_dati()
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _path())


def _lock() -> threading.Lock:
    return _LOCK


# ---------------------------------------------------------------------------
# Parsing cron
# ---------------------------------------------------------------------------

def normalizza_schedule(expr: str) -> str:
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("schedule vuota")
    low = expr.lower()
    if low in _SHORTCUTS:
        if _SHORTCUTS[low] is None:
            return "@reboot"
        return _SHORTCUTS[low]
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("schedule non valida: servono 5 campi (min ora giorno mese dow) o uno shortcut @...")
    # valida parsing
    for i, (p, (lo, hi)) in enumerate(zip(parts, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)])):
        _parse_field(p, lo, hi)
    return expr


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    field = field.strip()
    if field == "*":
        return set(range(lo, hi + 1))
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("campo cron vuoto")
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError("step non valido")
        else:
            base = part
        if base == "*":
            rng = range(lo, hi + 1)
        elif "-" in base:
            a, b = base.split("-", 1)
            a = int(a); b = int(b)
            rng = range(a, b + 1)
        else:
            # valore singolo (con eventuale step ignorato)
            v = int(base)
            if v < lo or v > hi:
                raise ValueError(f"valore {v} fuori range {lo}-{hi}")
            return {v}
        for v in rng:
            if lo <= v <= hi and (v - lo) % step == 0:
                out.add(v)
    # normalizza dow 7 -> 0
    return out


def _matches(expr: str, dt: datetime.datetime) -> bool:
    if expr == "@reboot":
        return False  # gestito a parte
    parts = expr.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    mins = _parse_field(minute, 0, 59)
    hours = _parse_field(hour, 0, 23)
    doms = _parse_field(dom, 1, 31)
    months = _parse_field(month, 1, 12)
    dows = _parse_field(dow, 0, 7)
    dows = {0 if d == 7 else d for d in dows}
    if dt.minute not in mins:
        return False
    if dt.hour not in hours:
        return False
    if dt.month not in months:
        return False
    dom_match = dt.day in doms
    cron_dow = (dt.weekday() + 1) % 7
    dow_match = cron_dow in dows
    dom_star = (dom.strip() == "*")
    dow_star = (dow.strip() == "*")
    if not dom_star and not dow_star:
        day_ok = dom_match or dow_match
    elif not dom_star:
        day_ok = dom_match
    elif not dow_star:
        day_ok = dow_match
    else:
        day_ok = True
    return day_ok


def prossima_esecuzione(expr: str, base: datetime.datetime | None = None) -> str | None:
    if expr == "@reboot":
        return None
    if base is None:
        base = datetime.datetime.now()
    dt = base.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    limite = base + datetime.timedelta(days=366)
    while dt <= limite:
        if _matches(expr, dt):
            return dt.isoformat(timespec="seconds")
        dt += datetime.timedelta(minutes=1)
    return None


def descrizione_schedule(expr: str) -> str:
    expr = (expr or "").strip()
    if expr in _SHORTCUTS:
        return expr
    # tentativo di traduzione umana minimale
    return expr


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_jobs() -> list[dict[str, Any]]:
    with _lock():
        return [dict(j) for j in _load()]


def get(job_id: str) -> dict[str, Any] | None:
    for j in _load():
        if j.get("id") == job_id:
            return dict(j)
    return None


def _valida_azione(action_type: str, action: Any) -> None:
    if action_type not in ("goal", "shell"):
        raise ValueError("action_type deve essere 'goal' o 'shell'")
    if not isinstance(action, dict):
        raise ValueError("action deve essere un oggetto")
    if action_type == "goal":
        if not (action.get("objective") or "").strip():
            raise ValueError("obiettivo mancante")
    elif action_type == "shell":
        if not (action.get("command") or "").strip():
            raise ValueError("comando mancante")


def crea(nome: str, schedule: str, action_type: str, action: dict[str, Any],
         enabled: bool = True) -> dict[str, Any]:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome richiesto")
    sched = normalizza_schedule(schedule)
    _valida_azione(action_type, action)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    job = {
        "id": uuid.uuid4().hex[:12],
        "nome": nome,
        "schedule": sched,
        "action_type": action_type,
        "action": action,
        "enabled": bool(enabled),
        "created_at": now,
        "last_run": None,
        "next_run": prossima_esecuzione(sched) if sched != "@reboot" else now,
        "last_status": "",
        "last_output": "",
        "run_count": 0,
    }
    if sched == "@reboot":
        job["next_run"] = now
    with _lock():
        jobs = _load()
        jobs.append(job)
        _save(jobs)
    return dict(job)


def aggiorna(job_id: str, **campi) -> dict[str, Any] | None:
    with _lock():
        jobs = _load()
        target = None
        for j in jobs:
            if j.get("id") == job_id:
                target = j
                break
        if target is None:
            return None
        if "nome" in campi and campi["nome"] is not None:
            n = str(campi["nome"]).strip()
            if n:
                target["nome"] = n
        if "schedule" in campi and campi["schedule"] is not None:
            sched = normalizza_schedule(str(campi["schedule"]))
            target["schedule"] = sched
        if "action_type" in campi and campi["action_type"] is not None:
            target["action_type"] = str(campi["action_type"])
        if "action" in campi and campi["action"] is not None:
            target["action"] = campi["action"]
        if "enabled" in campi and campi["enabled"] is not None:
            target["enabled"] = bool(campi["enabled"])
        _valida_azione(target["action_type"], target["action"])
        # ricalcola next_run
        if target.get("enabled"):
            if target["schedule"] == "@reboot":
                target["next_run"] = datetime.datetime.now().isoformat(timespec="seconds")
            else:
                target["next_run"] = prossima_esecuzione(target["schedule"])
        else:
            target["next_run"] = None
        _save(jobs)
        return dict(target)


def elimina(job_id: str) -> bool:
    with _lock():
        jobs = _load()
        nuovi = [j for j in jobs if j.get("id") != job_id]
        if len(nuovi) == len(jobs):
            return False
        _save(nuovi)
        return True


def abilita(job_id: str, on: bool) -> bool:
    r = aggiorna(job_id, enabled=on)
    return r is not None


# ---------------------------------------------------------------------------
# Esecuzione
# ---------------------------------------------------------------------------

def _env_default(env=None):
    if env is not None:
        return env
    try:
        from .providers import ambiente
        return ambiente("orchestra/.env")
    except Exception:
        import os as _os
        return dict(_os.environ)


def esegui_job(job_id: str, env=None) -> dict[str, Any]:
    env = _env_default(env)
    with _lock():
        jobs = _load()
        target = None
        for j in jobs:
            if j.get("id") == job_id:
                target = j
                break
        if target is None:
            return {"ok": False, "error": "job sconosciuto"}
    job = target
    now = datetime.datetime.now().isoformat(timespec="seconds")
    risultato: dict[str, Any] = {"ok": False}
    try:
        if job.get("action_type") == "goal":
            from . import goal as goal_mod
            a = job.get("action") or {}
            gid = goal_mod.start_goal(
                (a.get("objective") or "").strip(),
                env=env,
                profile=(a.get("profile") or "auto"),
                max_iterations=int(a.get("max_iterations") or 60),
                priority=int(a.get("priority") or 0),
                kind=(a.get("kind") or "goal"),
            )
            risultato = {"ok": True, "goal_id": gid}
            out = f"goal avviato: {gid}"
        elif job.get("action_type") == "shell":
            a = job.get("action") or {}
            cmd = (a.get("command") or "").strip()
            cp = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                timeout=int(a.get("timeout") or 300))
            risultato = {"ok": cp.returncode == 0, "code": cp.returncode,
                         "stdout": cp.stdout[-2000:], "stderr": cp.stderr[-2000:]}
            out = (cp.stdout or "")[-500:] or (cp.stderr or "")[-500:]
        else:
            risultato = {"ok": False, "error": "action_type sconosciuto"}
            out = "action_type sconosciuto"
    except Exception as e:  # noqa: BLE001
        risultato = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        out = str(e)

    # aggiorna stato job
    with _lock():
        jobs = _load()
        for j in jobs:
            if j.get("id") == job_id:
                j["last_run"] = now
                j["last_status"] = "ok" if risultato.get("ok") else "errore"
                j["last_output"] = (out or "")[:1000]
                j["run_count"] = int(j.get("run_count") or 0) + 1
                # ricalcola next_run
                sched = j.get("schedule")
                if sched == "@reboot":
                    j["enabled"] = False
                    j["next_run"] = None
                elif j.get("enabled"):
                    j["next_run"] = prossima_esecuzione(sched)
                break
        _save(jobs)
    with _lock():
        _SCHED["last_id"] = job_id
        _SCHED["last_status"] = "ok" if risultato.get("ok") else "errore"
    return risultato


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def scheduler_status() -> dict[str, Any]:
    with _lock():
        return dict(_SCHED)


def scheduler_start(env=None, interval: float = 30.0) -> bool:
    with _lock():
        if _SCHED["running"]:
            return False
        try:
            interval = max(5.0, float(interval or 30.0))
        except (TypeError, ValueError):
            interval = 30.0
        _SCHED["running"] = True
        _SCHED["interval"] = interval
        _SCHED["error"] = ""
    env = _env_default(env)
    threading.Thread(target=_scheduler_loop, args=(env,), daemon=True).start()
    return True


def scheduler_stop() -> bool:
    with _lock():
        _SCHED["running"] = False
    return True


def _scheduler_loop(env: dict[str, str]) -> None:
    while True:
        with _lock():
            if not _SCHED["running"]:
                return
            interval = _SCHED["interval"]
        now = datetime.datetime.now()
        try:
            for job in list_jobs():
                if not job.get("enabled"):
                    continue
                nr = job.get("next_run")
                if not nr:
                    continue
                try:
                    nr_dt = datetime.datetime.fromisoformat(nr)
                except ValueError:
                    continue
                if nr_dt <= now:
                    try:
                        esegui_job(job["id"], env=env)
                    except Exception as e:  # noqa: BLE001
                        with _lock():
                            _SCHED["error"] = f"{type(e).__name__}: {e}"
        except Exception as e:  # noqa: BLE001
            with _lock():
                _SCHED["error"] = f"{type(e).__name__}: {e}"
        # aggiorna rounds
        with _lock():
            _SCHED["rounds"] = _SCHED.get("rounds", 0) + 1
        time.sleep(interval)
