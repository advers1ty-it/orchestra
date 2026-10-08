"""
Budget guard for Orchestra.

Tracks token usage and costs per session/task, enforces limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timedelta
import threading
import json
import os


@dataclass
class BudgetLimits:
    """Limiti di spesa configurabili."""
    # Limiti per sessione (reset a ogni nuova sessione)
    max_tokens_per_session: int = 1_000_000      # ~$10-50 a seconda del modello
    max_cost_usd_per_session: float = 10.0       # $10 per sessione
    max_requests_per_session: int = 500          # numero max di turni

    # Limiti per task singolo (un send)
    max_tokens_per_task: int = 200_000           # ~$2-10 per task
    max_cost_usd_per_task: float = 5.0           # $5 per task
    max_iterations_per_task: int = 50            # safety net

    # Limiti globali (persistono su disco)
    max_cost_usd_per_day: float = 50.0           # $50/giorno
    max_cost_usd_per_month: float = 200.0        # $200/mese


@dataclass
class UsageSnapshot:
    """Fotografia dell'uso a un momento."""
    timestamp: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    category: str = ""


@dataclass
class BudgetState:
    """Stato del budget per una sessione."""
    session_id: str
    started_at: str
    limits: BudgetLimits = field(default_factory=BudgetLimits)

    # Contatori sessione
    session_prompt_tokens: int = 0
    session_completion_tokens: int = 0
    session_total_tokens: int = 0
    session_cost_usd: float = 0.0
    session_requests: int = 0

    # Contatori task corrente
    task_prompt_tokens: int = 0
    task_completion_tokens: int = 0
    task_total_tokens: int = 0
    task_cost_usd: float = 0.0
    task_iterations: int = 0

    # Storico per reporting
    history: list[UsageSnapshot] = field(default_factory=list)

    # Lock per thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_usage(self, prompt_tokens: int, completion_tokens: int, cost_usd: float, model: str, category: str = "") -> None:
        """Aggiunge usage e controlla i limiti."""
        total = prompt_tokens + completion_tokens
        with self._lock:
            # Aggiorna contatori sessione
            self.session_prompt_tokens += prompt_tokens
            self.session_completion_tokens += completion_tokens
            self.session_total_tokens += total
            self.session_cost_usd += cost_usd
            self.session_requests += 1

            # Aggiorna contatori task
            self.task_prompt_tokens += prompt_tokens
            self.task_completion_tokens += completion_tokens
            self.task_total_tokens += total
            self.task_cost_usd += cost_usd
            self.task_iterations += 1

            # Storico
            self.history.append(UsageSnapshot(
                timestamp=datetime.now().isoformat(),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total,
                cost_usd=cost_usd,
                model=model,
                category=category,
            ))

    def reset_task(self) -> None:
        """Resetta i contatori del task (chiamato all'inizio di ogni send)."""
        with self._lock:
            self.task_prompt_tokens = 0
            self.task_completion_tokens = 0
            self.task_total_tokens = 0
            self.task_cost_usd = 0.0
            self.task_iterations = 0

    def check_limits(self) -> list[str]:
        """Controlla tutti i limiti. Ritorna lista di violazioni (vuota se ok)."""
        violations = []
        with self._lock:
            # Limiti sessione
            if self.session_total_tokens > self.limits.max_tokens_per_session:
                violations.append(f"Token sessione: {self.session_total_tokens:,} > {self.limits.max_tokens_per_session:,}")
            if self.session_cost_usd > self.limits.max_cost_usd_per_session:
                violations.append(f"Costo sessione: ${self.session_cost_usd:.2f} > ${self.limits.max_cost_usd_per_session:.2f}")
            if self.session_requests > self.limits.max_requests_per_session:
                violations.append(f"Richieste sessione: {self.session_requests} > {self.limits.max_requests_per_session}")

            # Limiti task
            if self.task_total_tokens > self.limits.max_tokens_per_task:
                violations.append(f"Token task: {self.task_total_tokens:,} > {self.limits.max_tokens_per_task:,}")
            if self.task_cost_usd > self.limits.max_cost_usd_per_task:
                violations.append(f"Costo task: ${self.task_cost_usd:.2f} > ${self.limits.max_cost_usd_per_task:.2f}")
            if self.task_iterations > self.limits.max_iterations_per_task:
                violations.append(f"Iterazioni task: {self.task_iterations} > {self.limits.max_iterations_per_task}")

        return violations

    def get_summary(self) -> dict[str, Any]:
        """Ritorna un summary per UI/logging."""
        with self._lock:
            return {
                "session": {
                    "tokens": self.session_total_tokens,
                    "cost_usd": round(self.session_cost_usd, 4),
                    "requests": self.session_requests,
                    "limits": {
                        "max_tokens": self.limits.max_tokens_per_session,
                        "max_cost": self.limits.max_cost_usd_per_session,
                        "max_requests": self.limits.max_requests_per_session,
                    },
                    "usage_pct": {
                        "tokens": round(self.session_total_tokens / self.limits.max_tokens_per_session * 100, 1),
                        "cost": round(self.session_cost_usd / self.limits.max_cost_usd_per_session * 100, 1),
                    },
                },
                "task": {
                    "tokens": self.task_total_tokens,
                    "cost_usd": round(self.task_cost_usd, 4),
                    "iterations": self.task_iterations,
                    "limits": {
                        "max_tokens": self.limits.max_tokens_per_task,
                        "max_cost": self.limits.max_cost_usd_per_task,
                        "max_iterations": self.limits.max_iterations_per_task,
                    },
                },
            }


class BudgetGuard:
    """Guardia centrale per i budget. Una per processo."""

    _instance: "BudgetGuard | None" = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.states: dict[str, BudgetState] = {}
        self.global_daily_cost = 0.0
        self.global_monthly_cost = 0.0
        self._last_day = datetime.now().date()
        self._last_month = datetime.now().replace(day=1).date()
        self._load_global()

    def _load_global(self) -> None:
        """Carica contatori globali da disco."""
        path = os.path.join(os.path.dirname(__file__), "budget_global.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.global_daily_cost = data.get("daily_cost", 0.0)
                self.global_monthly_cost = data.get("monthly_cost", 0.0)
                last_day = data.get("last_day")
                last_month = data.get("last_month")
                if last_day:
                    self._last_day = datetime.fromisoformat(last_day).date()
                if last_month:
                    self._last_month = datetime.fromisoformat(last_month).date()
                self._reset_if_new_period()
            except Exception:
                pass

    def _save_global(self) -> None:
        """Salva contatori globali su disco."""
        path = os.path.join(os.path.dirname(__file__), "budget_global.json")
        try:
            data = {
                "daily_cost": self.global_daily_cost,
                "monthly_cost": self.global_monthly_cost,
                "last_day": self._last_day.isoformat(),
                "last_month": self._last_month.isoformat(),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _reset_if_new_period(self) -> None:
        """Resetta contatori se è cambiato giorno/mese."""
        now = datetime.now()
        today = now.date()
        this_month = now.replace(day=1).date()

        if today != self._last_day:
            self.global_daily_cost = 0.0
            self._last_day = today
        if this_month != self._last_month:
            self.global_monthly_cost = 0.0
            self._last_month = this_month

    def get_or_create_session(self, session_id: str, limits: BudgetLimits | None = None) -> BudgetState:
        """Ottiene o crea lo stato budget per una sessione."""
        with self._lock:
            if session_id not in self.states:
                self.states[session_id] = BudgetState(
                    session_id=session_id,
                    started_at=datetime.now().isoformat(),
                    limits=limits or BudgetLimits(),
                )
            elif limits:
                self.states[session_id].limits = limits
            return self.states[session_id]

    def remove_session(self, session_id: str) -> None:
        """Rimuove una sessione (es. alla fine)."""
        with self._lock:
            self.states.pop(session_id, None)

    def record_usage(self, session_id: str, prompt_tokens: int, completion_tokens: int,
                     cost_usd: float, model: str, category: str = "") -> list[str]:
        """Registra usage e controlla limiti. Ritorna violazioni."""
        self._reset_if_new_period()

        state = self.get_or_create_session(session_id)
        state.add_usage(prompt_tokens, completion_tokens, cost_usd, model, category)

        # Aggiorna globali
        self.global_daily_cost += cost_usd
        self.global_monthly_cost += cost_usd
        self._save_global()

        # Controlla limiti
        violations = state.check_limits()

        # Limiti globali
        if self.global_daily_cost > state.limits.max_cost_usd_per_day:
            violations.append(f"Budget giornaliero superato: ${self.global_daily_cost:.2f} > ${state.limits.max_cost_usd_per_day:.2f}")
        if self.global_monthly_cost > state.limits.max_cost_usd_per_month:
            violations.append(f"Budget mensile superato: ${self.global_monthly_cost:.2f} > ${state.limits.max_cost_usd_per_month:.2f}")

        return violations

    def get_global_summary(self) -> dict[str, Any]:
        """Summary globale per UI."""
        self._reset_if_new_period()
        return {
            "daily": {
                "cost_usd": round(self.global_daily_cost, 4),
                "limit_usd": self.states[next(iter(self.states))].limits.max_cost_usd_per_day if self.states else 50.0,
                "pct": round(self.global_daily_cost / 50.0 * 100, 1),
            },
            "monthly": {
                "cost_usd": round(self.global_monthly_cost, 4),
                "limit_usd": self.states[next(iter(self.states))].limits.max_cost_usd_per_month if self.states else 200.0,
                "pct": round(self.global_monthly_cost / 200.0 * 100, 1),
            },
        }


# Singleton accessor
def budget_guard() -> BudgetGuard:
    return BudgetGuard()