"""Catalogo modelli e capacità.

Due cose che qui stanno separate e vanno tenute separate:

1. `ModelInfo` — cosa dice il provider di un modello (finestra, prezzi,
   supporto tool). Viene da `list_models()` ed è FATTO, misurato.

2. `Capability` — a cosa serve un modello (codice, ragionamento, testo).
   È una nostra **ipotesi**, non un fatto. Non esiste un campo "capacita'"
   in nessuna API: lo dichiariamo noi e poi il benchmark la verifica o la
   smentisce.

La confusione fra le due cose e' il rischio principale di questo modulo.
Se mescoliamo "ha tool-calling" (fatto) con "sa fare codice" (ipotesi) in
un unico campo, finiamo per fidarci di un'opinione. Qui stanno separati e
`Capability.confidence` dice quanto siamo convinti — `unknown` di default,
perche' il valore onesto e' quello che non sappiamo ancora.

Sul "quale modello e' piu' potente": non esiste. Un modello puo' batterne
un altro in codice e perderlo in ragionamento, e la classifica cambia ogni
settimana. Per questo il benchmark misura per CATEGORIA DI COMPITO e non
un punteggio unico. Vedi `benchmark.py`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

# Le categorie sono nostre e servono al routing. Ogni benchmark task
# ne dichiara una, cosi' i risultati si possono aggregare per uso.
Category = Literal[
    "code",        # scrivere e far funzionare codice
    "reasoning",   # logica, matematica, piano multi-step
    "writing",     # testo, prosa, spiegazioni
    "extraction",  # tirare fuori informazioni da testo non strutturato
    "instruction", # seguire istruzioni precise, rispettare vincoli
    "tool_use",    # usare i tool correttamente e in sequenza
]

CATEGORIES: list[str] = [
    "code", "reasoning", "writing", "extraction", "instruction", "tool_use",
]

CATEGORY_LABEL: dict[str, str] = {
    "code": "Codice",
    "reasoning": "Ragionamento",
    "writing": "Scrittura",
    "extraction": "Estrazione",
    "instruction": "Istruzioni",
    "tool_use": "Uso tool",
}


@dataclass
class ModelInfo:
    """Fatti su un modello, letti dal provider."""

    id: str
    context_length: int = 0
    prompt_price: float = 0.0    # $/1M token di input
    completion_price: float = 0.0  # $/1M token di output
    supports_tools: bool = False
    supports_vision: bool = False

    @property
    def is_free(self) -> bool:
        return self.prompt_price == 0 and self.completion_price == 0

    @property
    def short(self) -> str:
        """Nome corto, per la UI: 'qwen/qwen3.8-27b:free' -> 'qwen3.8-27b'."""
        s = self.id.split("/")[-1]
        for suffix in (":free", ":beta", ":nitro", ":extended", ":thinking"):
            s = s.replace(suffix, "")
        return s

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Costo in dollari. Formato OpenRouter: prezzi per 1M token."""
        return (
            prompt_tokens / 1_000_000 * self.prompt_price
            + completion_tokens / 1_000_000 * self.completion_price
        )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "ModelInfo":
        pricing = raw.get("pricing") or {}
        params = raw.get("supported_parameters") or []
        arch = raw.get("architecture") or {}
        return cls(
            id=raw.get("id", ""),
            context_length=int(raw.get("context_length") or 0),
            # OpenRouter esprime i prezzi come stringa per token
            prompt_price=_num(pricing.get("prompt")),
            completion_price=_num(pricing.get("completion")),
            supports_tools="tools" in params or "tool_choice" in params,
            supports_vision=arch.get("input_modalities", []) != ["text"]
            or "image" in (raw.get("input_modalities") or []),
        )


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------
# Capacità: IPOTESI nostre, verificate dal benchmark
# --------------------------------------------------------------------------

# Perché sono `unknown` e non dichiarazioni: nessuna API ci dice cosa sa
# fare un modello. Riempiamo con i risultati del benchmark, che è l'unico
# modo onesto di saperlo.
CAPABILITY_HINTS: dict[str, dict[str, str]] = {
    "code": {
        "*code*": "alta",
        "coder": "alta",
        "cune": "alta",
        "starcoder": "alta",
    },
    "reasoning": {
        "*think*": "alta",
        "*reason*": "alta",
        "ultra": "alta",
    },
}


@dataclass
class ModelProfile:
    """Un modello come lo vede Orchestra: fatti + ipotesi, tenuti separati."""

    info: ModelInfo
    # categoria -> confidenza: high | medium | low | unknown
    capabilities: dict[str, str] = field(default_factory=dict)
    # punteggi misurati dal benchmark, categoria -> 0..1
    scores: dict[str, float] = field(default_factory=dict)
    last_measured: float = 0.0

    def confidence(self, category: str) -> str:
        if category in self.scores:
            # misurato: la confidenza e' la copertura dei dati
            return "measured"
        return self.capabilities.get(category, "unknown")

    def best_for(self, category: str) -> bool:
        """Il modello e' la scelta migliore per questa categoria?

        Solo se l'hai MISURATO e stai battendo la media. Un modello senza
        dati non e' "il migliore", e' sconosciuto: non lo consigliamo.
        """
        s = self.scores.get(category)
        if s is None:
            return False
        others = [v for k, v in self.scores.items() if k == category]
        if not others:
            return False
        return s >= 0.8 and s == max(others)

    def to_dict(self) -> dict[str, Any]:
        return {
            "info": asdict(self.info),
            "capabilities": self.capabilities,
            "scores": self.scores,
            "last_measured": self.last_measured,
        }


class Catalog:
    """I modelli disponibili su un provider, con le misurazioni del benchmark.

    I risultati del benchmark sono persistiti su disco: senza, si
    rimesurerebbe tutto a ogni avvio e il routing sarebbe lento.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.models: dict[str, ModelProfile] = {}
        self._path = self._store_path(provider)

    @staticmethod
    def _store_path(provider: str) -> str:
        import os

        base = os.environ.get("ORCHESTRA_HOME")
        if not base:
            home = os.environ.get("HERMES_HOME") or os.path.expanduser("~")
            base = os.path.join(
                home, "AppData", "Local", "hermes", "orchestra"
            ) if os.name == "nt" else os.path.join(home, ".orchestra")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, f"catalog_{provider}.json")

    @classmethod
    def fetch(cls, provider: str) -> "Catalog":
        """Scarica l'elenco reale dal provider e carica le misurazioni."""
        cat = cls(provider)
        from .providers import build_provider

        p = build_provider(provider, model="", env=_env())
        for raw in p._list_models_raw():
            if not raw.get("id"):
                continue
            info = ModelInfo.from_api(raw)
            if not info.supports_tools:
                # senza tool-calling un modello non serve a Orchestra
                continue
            prev = cat.models.get(info.id)
            prof = ModelProfile(info=info)
            if prev:
                prof.capabilities = prev.capabilities
                prof.scores = prev.scores
                prof.last_measured = prev.last_measured
            prof.capabilities = {c: "unknown" for c in CATEGORIES}
            cat.models[info.id] = prof
        cat.load_measurements()
        return cat

    def load_measurements(self) -> int:
        """Carica le misurazioni dal disco. Ritorna quante ne ha applicate.

        Applica solo ai modelli già presenti: se il provider non espone più
        un modello (lo ritira dal catalogo), lo ignora. Però se in futuro
        torna, le sue misurazioni sono ancora sul disco e valgono — quindi
        non le cancelliamo, le lasciamo lì per quando serve.
        """
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0
        applied = 0
        for mid, blob in (data.get("models") or {}).items():
            if mid in self.models:
                prof = self.models[mid]
                prof.scores = blob.get("scores") or {}
                prof.capabilities.update(blob.get("capabilities") or {})
                prof.last_measured = blob.get("last_measured", 0)
                applied += 1
        return applied

    def stale_measurements(self) -> list[str]:
        """Modelli misurati che il provider non offre piu'.

        Non e' un errore: i free tier cambiano spesso. E' informazione utile
        per capire se un punteggio che stai guardando e' ancora attuale.
        """
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        return [mid for mid in (data.get("models") or {}) if mid not in self.models]

    def save(self) -> None:
        import os as _os

        data = {
            "provider": self.provider,
            "saved_at": time.time(),
            "models": {
                mid: {"scores": p.scores, "capabilities": p.capabilities,
                      "last_measured": p.last_measured}
                for mid, p in self.models.items()
            },
        }
        # scrittura atomica: un file corrotto qui significa perdere tutte
        # le misurazioni, e rimuoverle costa un benchmark intero
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        _os.replace(tmp, self._path)

    # -- query -------------------------------------------------------------

    def with_tools(self) -> list[ModelProfile]:
        return [p for p in self.models.values() if p.info.supports_tools]

    def free(self) -> list[ModelProfile]:
        return [p for p in self.with_tools() if p.info.is_free]

    def measured(self) -> list[ModelProfile]:
        return [p for p in self.models.values() if p.scores]

    def by_score(self, category: str) -> list[ModelProfile]:
        """Modelli ordinati per punteggio nella categoria, migliore prima."""
        return sorted(
            [p for p in self.models.values() if category in p.scores],
            key=lambda p: p.scores[category],
            reverse=True,
        )

    def select(self, *, free: bool = False, paid: bool = False,
               only_tools: bool = True) -> list[ModelProfile]:
        """Modelli per fascia di prezzo, in ordine stabile.

        Serve al benchmark e al router. L'ordine e' alfabetico per id:
        un confronto ripetibile e' piu' utile di un elenco che cambia
        a ogni esecuzione, e 'il primo' deve significare sempre la stessa
        cosa quando si fa un batch.
        """
        src = self.with_tools() if only_tools else list(self.models.values())
        if free:
            src = [p for p in src if p.info.is_free]
        elif paid:
            src = [p for p in src if not p.info.is_free]
        return sorted(src, key=lambda p: p.info.id)

    def best_for(self, category: str, *, free_only: bool = False) -> ModelProfile | None:
        """Il migliore misurato per una categoria.

        Se non ci sono misurazioni, `None`. Non torna "il modello
        predefinito": un modello non misurato non e' la scelta migliore,
        e' sconosciuto, e la differenza conta quando si tratta di soldi
        del cliente.
        """
        cands = self.by_score(category)
        if free_only:
            cands = [c for c in cands if c.info.is_free]
        return cands[0] if cands else None

    def leaderboard(self, category: str, limit: int = 10) -> list[tuple[str, float]]:
        return [(p.info.short, p.scores[category]) for p in self.by_score(category)[:limit]]


def _env() -> dict[str, str]:
    import os

    from .providers import load_env

    here = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ)
    env.update(load_env(os.path.join(here, ".env")))
    return env
