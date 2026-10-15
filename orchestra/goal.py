"""Obiettivi persistenti per Orchestra.

Un obiettivo è un lavoro lungo che l'agente è invitato a completare in
autonomia. La persistenza serve a un motivo solo: se il processo si
chiude (errore, riavvio, utente che va a dormire) l'obiettivo non
sparisce, e si può riprendere o interrompere da fuori.

Non è uno scheduler: niente code, niente dipendenze, niente multi-agente.
È un registro di lavori lunghi con stato osservabile.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any


def _home() -> str:
    return os.environ.get("ORCHESTRA_HOME") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "_ goals_fallback",
    )


def _path() -> str:
    return os.path.join(_home(), "goals.json")


def _lock() -> threading.Lock:
    global _GOAL_LOCK
    try:
        return _GOAL_LOCK
    except NameError:
        _GOAL_LOCK = threading.Lock()
        return _GOAL_LOCK


_GOAL_LOCK = threading.Lock()


def _load() -> list[dict[str, Any]]:
    path = _path()
    if not os.path.exists(path):
        return []
    try:
        return json.load(open(path, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(goals: list[dict[str, Any]]) -> None:
    os.makedirs(_home(), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(goals, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _path())


def list_goals() -> list[dict[str, Any]]:
    return _load()


def get(goal_id: str) -> dict[str, Any] | None:
    for g in _load():
        if g.get("id") == goal_id:
            return g
    return None


def _normalizza_lista_id(valori: Any) -> list[str]:
    if valori is None:
        return []
    if isinstance(valori, str):
        valori = [v.strip() for v in valori.split(",")]
    if not isinstance(valori, (list, tuple)):
        raise ValueError("dipendenze non in lista")
    out = []
    for v in valori:
        s = str(v or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _mappa(goals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {g.get("id"): g for g in goals if g.get("id")}


def _ha_ciclo(goals: list[dict[str, Any]]) -> bool:
    by_id = _mappa(goals)
    visitati: set[str] = set()
    in_corso: set[str] = set()

    def visita(gid: str) -> bool:
        if gid in in_corso:
            return True
        if gid in visitati:
            return False
        in_corso.add(gid)
        g = by_id.get(gid) or {}
        for dip in (g.get("depends_on") or []):
            if dip in by_id and visita(dip):
                return True
        in_corso.remove(gid)
        visitati.add(gid)
        return False

    return any(visita(gid) for gid in by_id)


def _valida_collegamenti(
    goals: list[dict[str, Any]],
    *,
    goal_id: str,
    parent_id: str | None,
    depends_on: list[str],
    kind: str,
) -> None:
    if kind not in ("goal", "piano"):
        raise ValueError("kind deve essere 'goal' o 'piano'")
    by_id = _mappa(goals)
    if parent_id is not None:
        if parent_id == goal_id:
            raise ValueError("un goal non puo' essere padre di se stesso")
        if parent_id not in by_id:
            raise ValueError(f"padre sconosciuto: {parent_id}")
    for dip in depends_on:
        if dip == goal_id:
            raise ValueError("un goal non puo' dipendere da se stesso")
        if dip not in by_id:
            raise ValueError(f"dipendenza sconosciuta: {dip}")
    provvisori = []
    for g in goals:
        if g.get("id") == goal_id:
            copia = dict(g)
            copia["parent_id"] = parent_id
            copia["depends_on"] = list(depends_on)
            provvisori.append(copia)
        else:
            provvisori.append(g)
    if _ha_ciclo(provvisori):
        raise ValueError("dipendenze circolari non ammesse")


def create(objective: str, *, profile: str | None = None,
           max_iterations: int = 60, scope: str | None = None,
           parent_id: str | None = None, depends_on: Any = None,
           priority: int = 0, not_before: float | None = None,
           kind: str = "goal", max_attempts: int = 1,
           consenti_parziale: bool = False,
           criteri: list[dict[str, Any]] | None = None,
           recovery: dict[str, Any] | None = None) -> str:
    goal_id = f"g{uuid.uuid4().hex[:16]}"
    now = time.time()
    depends = _normalizza_lista_id(depends_on)
    try:
        priority = int(priority or 0)
    except (TypeError, ValueError):
        raise ValueError("priority deve essere un intero")
    if not_before is not None:
        try:
            not_before = float(not_before)
        except (TypeError, ValueError):
            raise ValueError("not_before deve essere un epoch")
    try:
        max_attempts = max(1, int(max_attempts or 1))
    except (TypeError, ValueError):
        raise ValueError("max_attempts deve essere >= 1")
    if criteri is not None and not isinstance(criteri, list):
        raise ValueError("criteri deve essere una lista")
    if recovery is not None and not isinstance(recovery, dict):
        raise ValueError("recovery deve essere un oggetto")
    goal = {
        "id": goal_id,
        "objective": objective,
        "profile": profile,
        "scope": scope,
        "kind": kind,
        "max_iterations": max(1, int(max_iterations or 1)),
        "parent_id": parent_id,
        "depends_on": depends,
        "priority": priority,
        "not_before": not_before or 0.0,
        "max_attempts": max_attempts,
        "attempts": 0,
        "consenti_parziale": bool(consenti_parziale),
        "criteri": list(criteri or []),
        "recovery": dict(recovery or {}),
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "turns": 0,
        "tokens": 0,
        "last_output": "",
        "error": "",
        "cancelled": False,
    }
    with _lock():
        goals = _load()
        _valida_collegamenti(goals, goal_id=goal_id, parent_id=parent_id,
                             depends_on=depends, kind=kind)
        goals.append(goal)
        _save(goals)
    return goal_id


def update(goal_id: str, **fields: Any) -> None:
    with _lock():
        goals = _load()
        for g in goals:
            if g.get("id") == goal_id:
                g.update(fields)
                g["updated_at"] = time.time()
                break
        _save(goals)


def cancel(goal_id: str) -> bool:
    with _lock():
        goals = _load()
        for g in goals:
            if g.get("id") == goal_id and g.get("status") == "running":
                g["cancelled"] = True
                g["status"] = "cancelled"
                g["updated_at"] = time.time()
                _save(goals)
                return True
    return False


def aggiorna(goal_id: str, *, depends_on: Any = None,
             parent_id: Any = "__invariato__", priority: Any = None,
             not_before: Any = None) -> dict[str, Any]:
    """Ripianifica un goal pending: dipendenze, padre, priorita', schedulazione."""
    with _lock():
        goals = _load()
        by_id = _mappa(goals)
        g = by_id.get(goal_id)
        if not g:
            raise ValueError(f"goal sconosciuto: {goal_id}")
        if g.get("status") not in ("pending",):
            raise ValueError("si ripianifica solo un goal pending")
        nuove_dip = (list(g.get("depends_on") or []) if depends_on is None
                     else _normalizza_lista_id(depends_on))
        nuovo_padre = g.get("parent_id") if parent_id == "__invariato__" else parent_id
        if priority is None:
            nuova_priorita = int(g.get("priority") or 0)
        else:
            try:
                nuova_priorita = int(priority or 0)
            except (TypeError, ValueError):
                raise ValueError("priority deve essere un intero")
        if not_before is None:
            nuovo_quando = float(g.get("not_before") or 0.0)
        else:
            try:
                nuovo_quando = float(not_before)
            except (TypeError, ValueError):
                raise ValueError("not_before deve essere un epoch")
        _valida_collegamenti(goals, goal_id=goal_id, parent_id=nuovo_padre,
                             depends_on=nuove_dip, kind=g.get("kind") or "goal")
        g["depends_on"] = nuove_dip
        g["parent_id"] = nuovo_padre
        g["priority"] = nuova_priorita
        g["not_before"] = nuovo_quando
        g["updated_at"] = time.time()
        _save(goals)
        return dict(g)


def _figli(goals: list[dict[str, Any]], goal_id: str) -> list[dict[str, Any]]:
    return [g for g in goals if (g.get("parent_id") == goal_id)]


def aggiorna_piani() -> int:
    """Chiude automaticamente i contenitori `piano` con figli tutti done.

    Un piano non gira mai un agente: e' un contenitore osservabile. Se un
    figlio fallisce/cancella e non ne restano in pending/running, il piano
    fallisce con il motivo esplicito invece di restare appeso.
    """
    toccati = 0
    with _lock():
        goals = _load()
        by_id = _mappa(goals)
        for g in goals:
            if (g.get("kind") or "goal") != "piano":
                continue
            if g.get("status") not in ("pending", "running"):
                continue
            figli = _figli(goals, g.get("id"))
            if not figli:
                continue
            stati = {f.get("status") for f in figli}
            if stati <= {"done"}:
                g["status"] = "done"
                g["error"] = ""
                g["updated_at"] = time.time()
                toccati += 1
            elif stati & {"failed", "cancelled"} and not (stati & {"pending", "running"}):
                primi = [f for f in figli if f.get("status") in ("failed", "cancelled")]
                g["status"] = "failed"
                g["error"] = ("figlio fallito: " + ", ".join(
                    f"{f.get('id')}:{f.get('status')}" for f in primi[:3]))
                g["updated_at"] = time.time()
                toccati += 1
        if toccati:
            _save(goals)
    return toccati


def dipendenze_mancanti(
    goal: dict[str, Any],
    by_id: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    if by_id is None:
        by_id = _mappa(_load())
    mancanti = []
    for dip in (goal.get("depends_on") or []):
        d = by_id.get(dip)
        if d is None or d.get("status") != "done":
            mancanti.append(dip)
    return mancanti


def bloccato_da_fallimento(
    goal: dict[str, Any],
    by_id: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    if by_id is None:
        by_id = _mappa(_load())
    rotti = []
    for dip in (goal.get("depends_on") or []):
        d = by_id.get(dip)
        if d is not None and d.get("status") in ("failed", "cancelled"):
            rotti.append(dip)
    return rotti


def motivo_non_pronto(
    goal: dict[str, Any],
    by_id: dict[str, dict[str, Any]] | None = None,
    now: float | None = None,
) -> str:
    if (goal.get("kind") or "goal") != "goal":
        return "i piani contenitore non si eseguono direttamente"
    if goal.get("status") != "pending":
        return f"stato {goal.get('status')}, non pending"
    now = time.time() if now is None else float(now)
    if float(goal.get("not_before") or 0.0) > now:
        return "schedulato nel futuro"
    rotti = bloccato_da_fallimento(goal, by_id)
    if rotti:
        return "dipendenza fallita/cancellata: " + ", ".join(rotti)
    mancanti = dipendenze_mancanti(goal, by_id)
    if mancanti:
        return "in attesa di: " + ", ".join(mancanti)
    return ""


def prossimo_pronto(now: float | None = None) -> dict[str, Any] | None:
    aggiorna_piani()
    now = time.time() if now is None else float(now)
    goals = _load()
    by_id = _mappa(goals)
    candidati = []
    for g in goals:
        if not motivo_non_pronto(g, by_id, now):
            candidati.append(g)
    if not candidati:
        return None
    candidati.sort(key=lambda g: (-int(g.get("priority") or 0),
                                  float(g.get("created_at") or 0.0),
                                  str(g.get("id"))))
    return dict(candidati[0])


def _prenota(gid: str) -> dict[str, Any] | None:
    with _lock():
        goals = _load()
        by_id = _mappa(goals)
        g = by_id.get(gid)
        if not g:
            return None
        if motivo_non_pronto(g, by_id):
            return None
        g["attempts"] = int(g.get("attempts") or 0) + 1
        g["status"] = "running"
        g["error"] = ""
        g["updated_at"] = time.time()
        _save(goals)
        return dict(g)


def prenota_prossimo() -> dict[str, Any] | None:
    """Seleziona e prenota il prossimo goal pronto, senza eseguirlo."""
    prossimo = prossimo_pronto()
    if not prossimo:
        return None
    return _prenota(prossimo["id"])


def esegui_prossimo(env: dict[str, str] | None = None,
                    extra_prompt: str = "") -> dict[str, Any] | None:
    """Esegue in modo sincrono il prossimo goal pronto. Torna il goal finale."""
    prenotato = prenota_prossimo()
    if not prenotato:
        return None
    run_goal(prenotato["id"], env=env, extra_prompt=extra_prompt)
    aggiorna_piani()
    return get(prenotato["id"])


def accoda_prossimo(env: dict[str, str] | None = None,
                    extra_prompt: str = "") -> dict[str, Any] | None:
    """Prenota il prossimo goal e lo avvia in un thread daemon."""
    prenotato = prenota_prossimo()
    if not prenotato:
        return None
    env = env or _env()
    threading.Thread(target=run_goal,
                     args=(prenotato["id"], env, extra_prompt),
                     daemon=True).start()
    return prenotato


# --------------------------------------------------------------------------
# Coda automatica: un loop che svuota i goal pronti, uno alla volta.
#
# Uno alla volta, non in parallelo: due agenti sullo stesso registro e
# sullo stesso budget si pestano i piedi, e due run concorrenti sullo
# stesso goals.json si rubano la prenotazione. La coda e' un singolo
# consumatore, e resta spenta di default: accenderla spende token veri.
# --------------------------------------------------------------------------

_sched_lock = threading.Lock()
_sched = {"running": False, "interval": 5.0, "last_id": None,
          "last_status": "", "rounds": 0, "error": ""}


def scheduler_status() -> dict[str, Any]:
    with _sched_lock:
        return dict(_sched)


def scheduler_start(env: dict[str, str] | None = None,
                    interval: float = 5.0) -> bool:
    """Avvia la coda automatica in un thread daemon. False se gia' attiva."""
    with _sched_lock:
        if _sched["running"]:
            return False
        try:
            interval = max(1.0, float(interval or 5.0))
        except (TypeError, ValueError):
            interval = 5.0
        _sched["running"] = True
        _sched["interval"] = interval
        _sched["error"] = ""
    env = env or _env()
    threading.Thread(target=_scheduler_loop, args=(env,), daemon=True).start()
    return True


def scheduler_stop() -> bool:
    with _sched_lock:
        _sched["running"] = False
    return True


def _scheduler_loop(env: dict[str, str]) -> None:
    while True:
        with _sched_lock:
            if not _sched["running"]:
                return
            interval = _sched["interval"]
        try:
            g = esegui_prossimo(env=env)
        except Exception as e:  # noqa: BLE001 - la coda non deve morire
            with _sched_lock:
                _sched["error"] = f"{type(e).__name__}: {e}"
            time.sleep(interval)
            continue
        with _sched_lock:
            _sched["rounds"] += 1
            if g:
                _sched["last_id"] = g.get("id")
                _sched["last_status"] = g.get("status", "")
        time.sleep(0 if g else interval)


def svuota_coda(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Esegue tutti i goal pronti, in ordine, finche' ce ne sono.

    Versione sincrona per CLI e test: torna la lista dei goal finali.
    """
    env = env or _env()
    fatti = []
    while True:
        g = esegui_prossimo(env=env)
        if not g:
            return fatti
        fatti.append(g)


def _env(path: str = "orchestra/.env") -> dict[str, str]:
    try:
        from .providers import ambiente
        return ambiente(path)
    except Exception:
        import os as _os
        return dict(_os.environ)


def _backoff_retry(attempts: int) -> float:
    try:
        n = max(1, int(attempts or 1))
    except (TypeError, ValueError):
        n = 1
    return float(min(300, 5 * n))


def _aggiorna_dopo_fallimento(goal_id: str, motivo: str) -> dict[str, Any]:
    """Registra un fallimento con retry limitato, senza eccezioni.

    Torna il goal aggiornato. Se restano tentativi, il goal torna pending
    con backoff; altrimenti diventa failed con il motivo esplicito.
    """
    with _lock():
        goals = _load()
        by_id = _mappa(goals)
        g = by_id.get(goal_id)
        if not g:
            return {}
        tentativi = int(g.get("attempts") or 0)
        massimi = max(1, int(g.get("max_attempts") or 1))
        now = time.time()
        if tentativi < massimi:
            g["status"] = "pending"
            g["not_before"] = now + _backoff_retry(tentativi)
            g["error"] = f"{motivo} (retry {tentativi}/{massimi})"
        else:
            g["status"] = "failed"
            g["error"] = motivo
        g["updated_at"] = now
        _save(goals)
        return dict(g)


def run_goal(goal_id: str, env: dict[str, str] | None = None,
             extra_prompt: str = "") -> None:
    """Esegue l'obiettivo in autonomia. Aggiorna lo stato mentre gira."""
    goal = get(goal_id)
    if not goal:
        return
    if (goal.get("kind") or "goal") != "goal":
        update(goal_id, status="failed",
               error="i piani contenitore non si eseguono: usare lo scheduler")
        return
    if motivo_non_pronto(goal):
        # Lo scheduler seleziona solo goal pronti; un avvio diretto con
        # dipendenze insoddisfatte non bypassa il piano, resta pending.
        update(goal_id, error=motivo_non_pronto(goal))
        return
    env = env or _env()
    with _lock():
        goals = _load()
        by_id = _mappa(goals)
        g = by_id.get(goal_id)
        if not g or g.get("status") != "pending":
            return
        g["attempts"] = int(g.get("attempts") or 0) + 1
        g["status"] = "running"
        g["error"] = ""
        g["updated_at"] = time.time()
        _save(goals)
        goal = dict(g)
    last_output: list[str] = []
    iterations = {"n": 0}
    cancelled = {"f": False}

    def _cancelled() -> bool:
        g = get(goal_id)
        return bool(g and g.get("cancelled"))

    def on_event(kind: str, data: dict[str, Any] | None) -> None:
        data = data or {}
        if kind in ("contenuto", "testo", "ragionamento"):
            t = data.get("text") or data.get("contenuto") or ""
            if isinstance(t, str) and t.strip():
                last_output.append(t.strip())
                if len(last_output) > 12:
                    last_output.pop(0)
        try:
            if kind in ("user_message", "turn_start"):
                iterations["n"] += 1
                if iterations["n"] <= goal["max_iterations"]:
                    update(goal_id, turns=iterations["n"],
                           last_output="\n\n".join(last_output[-3:]))
        except Exception:
            pass

    def _testo() -> str:
        return "\n\n".join(last_output[-5:])

    try:
        from .agent import Agent, LoopConfig
        from .tools import default_registry, applica_profilo, profilo_per_testo
        from .providers import build_provider, ProviderError

        provider_name = (env.get("ORCHESTRA_PROVIDER") or "openrouter").strip()
        model = env.get("ORCHESTRA_MODEL", "")
        if not model:
            raise RuntimeError(
                "imposta ORCHESTRA_MODEL (e la chiave provider) prima di "
                "lanciare un obiettivo")
        provider = build_provider(provider_name, model=model, env=env)
        reg = default_registry()
        _attacca_delega(reg, env, int(goal.get("max_iterations") or 60),
                        recovery=goal.get("recovery") or {})
        profile = goal.get("profile")
        if profile == "auto":
            profile = profilo_per_testo(goal["objective"])
        if profile and profile != "pieno":
            try:
                applica_profilo(reg, profile)
            except Exception:
                pass
        prompt = (
            "Hai un obiettivo da raggiungere. Lavora in autonomia: analizza, "
            "modifica i file, verifica con comandi oggettivi, e termina solo "
            "quando l'obiettivo è raggiunto oppure quando non puoi più "
            "avanzare.\n\n"
            "Obiettivo:\n" + goal["objective"]
        )
        if extra_prompt and extra_prompt.strip():
            prompt += "\n\nContesto extra:\n" + extra_prompt.strip()
        agent = Agent(provider, reg, prompt, LoopConfig(
            max_iterations=int(goal["max_iterations"]),
            context_limit=int(env.get("ORCHESTRA_CONTEXT_LIMIT", "120000")),
            keep_recent=8,
            reasoning_level=env.get("ORCHESTRA_REASONING", None),
            tool_profile=profile,
        ), on_event=on_event)
        state = agent.run(goal["objective"])
        if _cancelled():
            update(goal_id, status="cancelled", last_output=_testo())
            return
        from .accettazione import valuta_goal as _valuta

        esito = _valuta(
            state,
            consenti_parziale=bool(goal.get("consenti_parziale")),
            criteri=goal.get("criteri") or [],
            radice=os.getcwd(),
        )
        if not esito.ok:
            update(goal_id, last_output=_testo(),
                   tokens=getattr(state, "total_tokens", 0) or 0)
            _aggiorna_dopo_fallimento(goal_id, f"accettazione fallita: {esito.motivo}")
            return
        testo = _testo()
        if esito.dettagli.get("stop_anomalo"):
            testo = f"[parziale accettato: {esito.motivo}]\n\n{testo}".strip()
        update(goal_id, status="done", last_output=testo,
               tokens=getattr(state, "total_tokens", 0) or 0)
    except Exception as e:
        update(goal_id, last_output=_testo())
        _aggiorna_dopo_fallimento(goal_id, f"{type(e).__name__}: {e}")


def _attacca_delega(reg: Any,
                     env: dict[str, str],
                     max_iterations: int,
                     recovery: dict[str, Any] | None = None) -> bool:
    """Collega il tool `delega` a un registro, se possibile.

    Migliore sforzo: se una delle tre difese salta, resta un agente
    senza delega invece di bloccare il goal. Il multi-agente è da
    considerare un'opzionalità, non una dipendenza.
    """
    try:
        from .delega import Delegatore
        from .types import Tool
        from .prompt_figlio import PROMPT_FIGLIO
        from .agent import Agent, LoopConfig
        from .providers import build_provider
    except Exception:
        return False

    nome_provider = env.get("ORCHESTRA_PROVIDER", "openrouter")
    env_chiavi = env

    # Il catalogo serve al figlio per scegliere il modello. Se non ce la
    # fa, il figlio cade sul default del provider: meno ottimale, ma
    # funziona lo stesso.
    _cat = None
    try:
        from .catalog import Catalog
        from .tools import default_registry
        _cat = Catalog.fetch(nome_provider)
    except Exception:
        _cat = None

    passi_padre = max(1, int(max_iterations or 1))
    passi_figlio = max(1, min(passi_padre, 50))
    modello_forzato: dict[str, Any] = {"id": None}

    def fabbrica(obiettivo: str):
        modello = modello_forzato.get("id") or ""
        if not modello and _cat is not None:
            try:
                from .routing import instrada as _instrada
                scelta = _instrada(_cat, obiettivo)
                modello = scelta.modello or ""
            except Exception:
                modello = ""
        try:
            return Agent(
                build_provider(nome_provider, model=modello, env=env_chiavi),
                default_registry(),
                PROMPT_FIGLIO,
                LoopConfig(max_iterations=passi_figlio,
                           context_limit=60_000, keep_recent=6),
                on_event=lambda kind, data: None,
            )
        except Exception:
            raise

    try:
        deleg = Delegatore(fabbrica)
    except Exception:
        return False

    def _delega(obiettivo: str, contesto: str = "") -> str:
        try:
            from .recupero import PoliticaRecupero, delega_con_recupero

            def _forza(modello: str | None) -> None:
                modello_forzato["id"] = modello

            f = delega_con_recupero(
                deleg, obiettivo, contesto,
                policy=PoliticaRecupero(
                    max_retry=(recovery or {}).get("max_retry", 0),
                    modelli_alternativi=(recovery or {}).get("modelli_alternativi", []),
                    accorcia_contesto=(recovery or {}).get("accorcia_contesto", False),
                    max_contesto_chars=(recovery or {}).get("max_contesto_chars", 2000),
                ),
                imposta_modello=_forza,
            )
            return f.per_il_padre()
        except Exception as e:
            return f"[delega fallita: {e}]"

    reg.register(Tool(
        name="delega",
        description=("Affida un compito preciso e circoscritto a un "
                     "sub-agente che parte con una finestra vuota."),
        schema={"type": "object", "properties": {
            "obiettivo": {"type": "string"},
            "contesto": {"type": "string"}},
            "required": ["obiettivo"]},
        handler=_delega,
    ))
    return True
def start_goal(objective: str, env: dict[str, str] | None = None,
               profile: str | None = None,
               max_iterations: int = 60, parent_id: str | None = None,
               depends_on: Any = None, priority: int = 0,
               not_before: float | None = None, kind: str = "goal",
               max_attempts: int = 1, consenti_parziale: bool = False,
               criteri: list[dict[str, Any]] | None = None,
               recovery: dict[str, Any] | None = None) -> str:
    goal_id = create(objective, profile=profile,
                    max_iterations=max_iterations, parent_id=parent_id,
                    depends_on=depends_on, priority=priority,
                    not_before=not_before, kind=kind,
                    max_attempts=max_attempts,
                    consenti_parziale=consenti_parziale,
                    criteri=criteri, recovery=recovery)
    if kind != "goal":
        # Un piano e' un contenitore: si crea e lo scheduler lo chiude
        # quando i figli finiscono. Non parte nessun thread.
        return goal_id
    goal = get(goal_id) or {}
    motivo = motivo_non_pronto(goal)
    if motivo:
        raise RuntimeError(f"goal non pronto: {motivo}")
    env = env or _env()
    threading.Thread(target=run_goal,
                    args=(goal_id, env),
                    daemon=True).start()
    return goal_id
