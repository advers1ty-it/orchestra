"""
Budget: quanto si spende, e dove si smette.

TRASVERSALE, NON PER MODELLO

I contatori vivono in un unico stato condiviso (`SESSIONE_GLOBALE`), non
uno per provider/modello. La ragione e' semplice: un tetto di spesa serve
a rispondere a "quanto ho speso oggi", e la bolletta non distingue fra
modelli. Con uno stato per modello il limite era aggregato ma mai
applicato -- tre modelli con $5 di tetto ciascuno fanno $15, e il numero
che avevi chiesto di non superare era 5.

`record_usage` e' inoltre l'unica via d'ingresso del consumo, e alimenta
anche i contatori giorno/mese. Prima quei contatori si aggiornavano solo
qui dentro, ma l'agente non passava di qui -- chiamava `add_usage` sullo
stato -- quindi restavano a zero per sempre: un tetto dichiarato, e mai
fatto rispettare da nessuno.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Chiave unica dello stato condiviso. Non e' un id di sessione: e' un nome
# fisso, ed e' esattamente il punto. Tutti gli agenti del processo ci
# scrivono sopra.
SESSIONE_GLOBALE = "__globale__"


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

    # Limiti trasversali: persistono su disco e non si azzerano da soli,
    # solo col calendario. Sono quelli che rispondono a "quanto ho speso".
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
    """Stato del budget. Uno per processo, condiviso da tutti i modelli."""

    session_id: str = SESSIONE_GLOBALE
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
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

    # Quanto hanno speso i singoli modelli. Non conta ai fini del limite --
    # il limite e' trasversale -- ma e' la risposta a "chi me l'ha fatto
    # spendere", che e' la prima domanda appena si sfora.
    spesa_per_modello: dict[str, float] = field(default_factory=dict)

    # Storico per reporting
    history: list[UsageSnapshot] = field(default_factory=list)

    # Lock: il server HTTP e' multithread e due turni possono sovrapporsi.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_usage(self, prompt_tokens: int, completion_tokens: int,
                  cost_usd: float, model: str, category: str = "") -> None:
        """Aggiunge consumo ai contatori sessione e task.

        Non controlla i limiti: quello lo fa `check_limits`, che il
        chiamante invoca subito dopo. Tenerli separati permette di
        verificare dopo aver sommato, e a un test di provare le due cose
        indipendentemente.
        """
        total = prompt_tokens + completion_tokens
        with self._lock:
            self.session_prompt_tokens += prompt_tokens
            self.session_completion_tokens += completion_tokens
            self.session_total_tokens += total
            self.session_cost_usd += cost_usd
            self.session_requests += 1

            self.task_prompt_tokens += prompt_tokens
            self.task_completion_tokens += completion_tokens
            self.task_total_tokens += total
            self.task_cost_usd += cost_usd
            self.task_iterations += 1

            if model:
                self.spesa_per_modello[model] = (
                    self.spesa_per_modello.get(model, 0.0) + cost_usd)

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
        """Azzera i contatori del task, all'inizio di ogni send.

        I contatori sessione NON si toccano: sono trasversali e servono
        proprio a durare piu' di un task.
        """
        with self._lock:
            self.task_prompt_tokens = 0
            self.task_completion_tokens = 0
            self.task_total_tokens = 0
            self.task_cost_usd = 0.0
            self.task_iterations = 0

    def check_limits(self, giorno: float = 0.0, mese: float = 0.0) -> list[str]:
        """Controlla tutti i limiti. Ritorna le violazioni (vuota se ok).

        `giorno` e `mese` sono il consumo gia' accumulati oggi e questo mese.
        Stanno fuori da questo oggetto perche' sopravvivono al processo, e
        vanno passati: senza, il tetto giornaliero sarebbe calcolato su un
        contatore che riparte da zero a ogni riavvio -- che per un tetto di
        spesa vuol dire non esistere, si aggira riavviando.
        """
        violations: list[str] = []
        with self._lock:
            # Limiti sessione
            if self.session_total_tokens > self.limits.max_tokens_per_session:
                violations.append(
                    f"Token sessione: {self.session_total_tokens:,} > "
                    f"{self.limits.max_tokens_per_session:,}")
            if self.session_cost_usd > self.limits.max_cost_usd_per_session:
                violations.append(
                    f"Costo sessione: ${self.session_cost_usd:.2f} > "
                    f"${self.limits.max_cost_usd_per_session:.2f}")
            if self.session_requests > self.limits.max_requests_per_session:
                violations.append(
                    f"Richieste sessione: {self.session_requests} > "
                    f"{self.limits.max_requests_per_session}")

            # Limiti task
            if self.task_total_tokens > self.limits.max_tokens_per_task:
                violations.append(
                    f"Token task: {self.task_total_tokens:,} > "
                    f"{self.limits.max_tokens_per_task:,}")
            if self.task_cost_usd > self.limits.max_cost_usd_per_task:
                violations.append(
                    f"Costo task: ${self.task_cost_usd:.2f} > "
                    f"${self.limits.max_cost_usd_per_task:.2f}")
            if self.task_iterations > self.limits.max_iterations_per_task:
                violations.append(
                    f"Iterazioni task: {self.task_iterations} > "
                    f"{self.limits.max_iterations_per_task}")

            # Limiti trasversali, contando quello speso prima di adesso.
            # Quattro decimali, non due: sotto il dollaro la virgola
            # renderebbe il messaggio "Speso oggi: $0.00 > $0.00", che non
            # dice niente -- ed è proprio lì che si lavora quando si
            # sperimentano i tetti.
            if giorno > self.limits.max_cost_usd_per_day:
                violations.append(
                    f"Speso oggi: ${giorno:.4f} > "
                    f"${self.limits.max_cost_usd_per_day:.4f}")
            if mese > self.limits.max_cost_usd_per_month:
                violations.append(
                    f"Speso questo mese: ${mese:.4f} > "
                    f"${self.limits.max_cost_usd_per_month:.4f}")

        return violations

    def get_summary(self) -> dict[str, Any]:
        """Riepilogo per UI e log."""
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
                        "tokens": round(
                            self.session_total_tokens
                            / max(1, self.limits.max_tokens_per_session) * 100, 1),
                        "cost": round(
                            self.session_cost_usd
                            / max(0.01, self.limits.max_cost_usd_per_session) * 100, 1),
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
                "per_modello": {k: round(v, 4)
                                for k, v in sorted(self.spesa_per_modello.items(),
                                                   key=lambda kv: -kv[1])},
            }


class BudgetGuard:
    """Guardia centrale. Una per processo, stato trasversale a tutti i modelli.

    I contatori giorno/mese stanno qui e non in BudgetState perche' devono
    sopravvivere al processo: su disco.
    """

    _instance: "BudgetGuard | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "BudgetGuard":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        # Un solo stato, condiviso. La chiave e' fissa: non e' un modo per
        # averne di piu', e' il modo per averne uno solo.
        self.states: dict[str, BudgetState] = {SESSIONE_GLOBALE: BudgetState()}
        self.global_daily_cost = 0.0
        self.global_monthly_cost = 0.0
        self._last_day = datetime.now().date()
        self._last_month = datetime.now().replace(day=1).date()
        self._load_global()

    # -- persistenza giorno/mese -------------------------------------------

    @property
    def _percorso(self) -> str:
        return os.path.join(os.path.dirname(__file__), "budget_global.json")

    def _load_global(self) -> None:
        if os.path.exists(self._percorso):
            try:
                with open(self._percorso, "r", encoding="utf-8") as f:
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
        try:
            data = {
                "daily_cost": self.global_daily_cost,
                "monthly_cost": self.global_monthly_cost,
                "last_day": self._last_day.isoformat(),
                "last_month": self._last_month.isoformat(),
            }
            with open(self._percorso, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _reset_if_new_period(self) -> None:
        """Azzera giorno/mese se il calendario e' girato."""
        now = datetime.now()
        today = now.date()
        this_month = now.replace(day=1).date()

        if today != self._last_day:
            self.global_daily_cost = 0.0
            self._last_day = today
        if this_month != self._last_month:
            self.global_monthly_cost = 0.0
            self._last_month = this_month

    # -- stato -------------------------------------------------------------

    @property
    def stato(self) -> BudgetState:
        """Lo stato unico. Creato in `__init__`, quindi sempre presente."""
        return self.states[SESSIONE_GLOBALE]

    def get_or_create_session(self, session_id: str | None = None,
                              limits: BudgetLimits | None = None) -> BudgetState:
        """Torna lo stato trasversale. `session_id` e' accolto e ignorato.

        Resta nella firma perche' i chiamanti esistenti lo passano, e
        toccarli tutti per un parametro che ora non significa piu' niente
        sarebbe rumore. Meglio un argomento documentato che una modifica
        in cinque file.

        Con `limits=None` si leggono da `ORCHESTRA_BUDGET`: e' il percorso
        normale, quello di chi costruisce un Agent senza configurare niente.
        Se si tornassero e basta i default, un tetto salvato dal pannello
        Opzioni non verrebbe mai applicato -- il valore c'e', si vede
        nell'interfaccia, e non fa niente.
        """
        stato = self.stato
        if limits is not None:
            stato.limits = limits
        else:
            stato.limits = self.limits_da_env()
        return stato

    def remove_session(self, session_id: str | None = None) -> None:
        """Non rimuove niente: lo stato e' uno e resta."""
        return None

    # -- consumo -----------------------------------------------------------

    def record_usage(self, prompt_tokens: int, completion_tokens: int,
                     cost_usd: float, model: str, category: str = "") -> list[str]:
        """Registra consumo e controlla i limiti. Ritorna le violazioni.

        E' l'unica via d'ingresso del consumo: aggiorna lo stato, i
        contatori giorno/mese, e verifica tutto insieme. Se un chiamante
        somma da solo senza passare di qui, il tetto giornaliero mente.
        """
        self._reset_if_new_period()

        stato = self.stato
        stato.add_usage(prompt_tokens, completion_tokens, cost_usd, model, category)

        self.global_daily_cost += cost_usd
        self.global_monthly_cost += cost_usd
        self._save_global()

        return stato.check_limits(
            giorno=self.global_daily_cost, mese=self.global_monthly_cost)

    def limits_da_env(self) -> BudgetLimits:
        """Legge i limiti da `ORCHESTRA_BUDGET` (.env, JSON).

        Chiave assente, vuota o illeggibile -> limiti di default. Nessun
        limite configurato e' una scelta legittima, non un errore.
        """
        from .providers import load_env
        try:
            env = load_env(os.path.join(os.path.dirname(__file__), ".env"))
            raw = (env.get("ORCHESTRA_BUDGET") or "").strip()
            if not raw:
                return BudgetLimits()
            d = json.loads(raw)
            return BudgetLimits(
                max_tokens_per_task=d.get("task_tokens") or 200_000,
                max_cost_usd_per_task=d.get("task_cost") or 5.0,
                max_iterations_per_task=d.get("task_iters") or 50,
                max_tokens_per_session=d.get("sess_tokens") or 1_000_000,
                max_cost_usd_per_session=d.get("sess_cost") or 10.0,
                max_requests_per_session=d.get("sess_reqs") or 500,
                max_cost_usd_per_day=d.get("day_cost") or 50.0,
                max_cost_usd_per_month=d.get("month_cost") or 200.0,
            )
        except Exception:
            return BudgetLimits()

    def get_global_summary(self) -> dict[str, Any]:
        """Riepilogo giorno/mese per la UI."""
        self._reset_if_new_period()
        return {
            "daily": {
                "cost_usd": round(self.global_daily_cost, 4),
                "limit_usd": self.stato.limits.max_cost_usd_per_day,
                "pct": round(self.global_daily_cost
                             / max(0.01, self.stato.limits.max_cost_usd_per_day) * 100, 1),
            },
            "monthly": {
                "cost_usd": round(self.global_monthly_cost, 4),
                "limit_usd": self.stato.limits.max_cost_usd_per_month,
                "pct": round(self.global_monthly_cost
                             / max(0.01, self.stato.limits.max_cost_usd_per_month) * 100, 1),
            },
        }


# Accesso comodo
def budget_guard() -> BudgetGuard:
    return BudgetGuard()
