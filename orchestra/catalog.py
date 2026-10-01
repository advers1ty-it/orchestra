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

# Le categorie sono i "tipi di richiesta": e' su queste che si instrada.
# Le prime sei sono generiche, le ultime descrivono il lavoro vero e
# proprio — e servono perche' "codice" da solo non basta: un modello
# bravo in Python non e' per forza bravo in JavaScript o in React.
CATEGORIES: list[str] = [
    "code", "reasoning", "writing", "extraction", "instruction", "tool_use",
    "js", "web", "app",
]

CATEGORY_LABEL: dict[str, str] = {
    "code": "Codice",
    "reasoning": "Ragionamento",
    "writing": "Scrittura",
    "extraction": "Estrazione",
    "instruction": "Istruzioni",
    "tool_use": "Uso tool",
    "js": "Coding JavaScript",
    "web": "Coding web (HTML/CSS)",
    "app": "Coding app (React Native)",
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
        params = raw.get("supported_parameters")
        arch = raw.get("architecture") or {}
        # `supported_parameters` e' un campo di OpenRouter. Groq, NVIDIA,
        # Together e Cerebras non lo inviano: senza quel campo NON si puo'
        # dire che un modello non sa fare tool-calling, si puo' solo dire
        # che l'API non lo dichiara. Confondere le due cose faceva
        # scartare il catalogo intero di quei provider — 81 modelli
        # NVIDIA diventavano zero — e il menu servizio restava vuoto
        # senza dire perche'.
        # None = non dichiarato. Il benchmark poi lo scopre per davvero.
        if params is None:
            supports_tools = None
        else:
            supports_tools = "tools" in params or "tool_choice" in params
        return cls(
            id=raw.get("id", ""),
            context_length=int(raw.get("context_length") or 0),
            # OpenRouter esprime i prezzi come stringa per token
            prompt_price=_num(pricing.get("prompt")),
            completion_price=_num(pricing.get("completion")),
            supports_tools=supports_tools,
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
    # Quanti test sono passati e quanti ne erano, per categoria.
    # Senza questi la percentuale nasconde la base: 50% su 2 test e
    # 50% su 20 sembrano la stessa misura, e non lo sono. Con 2-3 test
    # per categoria la differenza e' enorme: due terzi su due test e
    # due terzi su venti non sono confrontabili, e il numero da solo
    # non lo dice.
    frazioni: dict[str, int] = field(default_factory=dict)
    task_per_cat: dict[str, int] = field(default_factory=dict)
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
            "frazioni": self.frazioni,
            "task_per_cat": self.task_per_cat,
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
            # HERMES_HOME punta gia' alla cartella di Hermes. Appiattirla
            # sotto ancora "AppData/Local/hermes" produceva un percorso
            # doppio tipo
            #   ...\hermes\AppData\Local\hermes\orchestra\catalog_x.json
            # che funziona (salvataggio e lettura puntano allo stesso
            # posto) ma mette i dati in una cartella che nessuno cerca.
            # Se la base finisce gia' per Hermes, si aggiunge solo
            # "orchestra".
            if os.name == "nt":
                se_hermes = home.rstrip("\\/").lower().endswith("hermes")
                base = (os.path.join(home, "orchestra") if se_hermes
                        else os.path.join(home, "AppData", "Local", "hermes", "orchestra"))
            else:
                base = os.path.join(home, ".orchestra")
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
            if info.supports_tools is False:
                # dichiarato incapace: per Orchestra non serve. Se il
                # campo non c'e' invece non lo scartiamo — non lo
                # sappiamo, e "non lo so" e' diverso da "no". Lo scopre
                # il benchmark, che e' l'unica misura onesta.
                continue
            prev = cat.models.get(info.id)
            prof = ModelProfile(info=info)
            if prev:
                prof.capabilities = prev.capabilities
                prof.scores = prev.scores
                prof.frazioni = prev.frazioni
                prof.task_per_cat = prev.task_per_cat
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
                # un salvataggio vecchio non ha questi campi: si
                # caricano vuoti e la frazione semplicemente non si
                # mostra, invece di mentire showing 0/0
                prof.frazioni = dict(blob.get("frazioni") or {})
                prof.task_per_cat = dict(blob.get("task_per_cat") or {})
                prof.frazioni = blob.get("frazioni") or {}
                prof.task_per_cat = blob.get("task_per_cat") or {}
                prof.capabilities.update(blob.get("capabilities") or {})
                prof.last_measured = blob.get("last_measured", 0)
                # un "no" sui tool, appreso dalla risposta del provider,
                # si rilegge. Senza, ogni turno riprova lo stesso modello
                # e il ciclo non converge mai.
                if blob.get("supports_tools") is False:
                    prof.info.supports_tools = False
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

    def segnala_senza_tool(self, model_id: str) -> bool:
        """Segna un modello come incapace di tool-calling. Ritorna True se salvato.

        Serve perche' alcuni provider NON dichiarano il tool-calling nel
        loro catalogo: il campo arriva vuoto, che vuol dire "non lo so",
        non "no". Un modello che non lo supporta viene allora scelto come
        se lo supportasse, e la richiesta muore con un HTTP 400 che
        sembra di rete.

        Quando il provider lo dice nella risposta, si crede al provider
        e si scrive il fatto. La prossima volta non verra' piu' scelto,
        anche dopo un riavvio: e' una misura, non una congettura.
        """
        prof = self.models.get(model_id)
        if prof is None or prof.info.supports_tools is False:
            return False
        prof.info.supports_tools = False
        self.save()
        return True

    def save(self) -> None:
        import os as _os

        data = {
            "provider": self.provider,
            "saved_at": time.time(),
            "models": {
                # supports_tools si salva SOLO quando e' un no. Il si'
                # arriva dal provider e si rileggge a ogni fetch: tenere
                # un "true" scaduto significa ignorare un provider che
                # nel frattempo ha tolto il supporto. Un no, invece, e'
                # una misura — l'ho appena appreso dalla risposta — e va
                # tenuto, altrimenti il ciclo riparte da capo ogni turno.
                mid: {"scores": p.scores, "capabilities": p.capabilities,
                      "last_measured": p.last_measured,
                      # la base campionaria viaggia con il punteggio.
                      # Senza, il 100% di un modello e il 100% di un
                      # altro sono la stessa riga anche se uno e' stato
                      # misurato su una categoria sola: e la tabella
                      # promette che la frazione sia confrontabile,
                      # cosa che senza il denominatore non e'.
                      "frazioni": getattr(p, "frazioni", {}),
                      "task_per_cat": getattr(p, "task_per_cat", {}),
                      **({"supports_tools": False}
                         if p.info.supports_tools is False else {})}
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
        """Modelli utilizzabili come agenti: sanno fare tool-calling.

        Un modello che non regge i tool non e' Orchestra: e' un endpoint
        di chat. Non "meno utile" — uselesse al nostro scopo, perche' un
        agente senza strumenti non puo' leggere un file, eseguire un
        comando o chiederti un permesso. Percio' qui si esclude sul
        principio, non per prudenza.

        "Non lo so" pero' resta "non lo so". Solo un False esplicito
        tiene fuori: un provider che non dichiara il campo non sta
        dicendo che il modello non regge, e trattare il silenzio come
        un no farebbe sparire interi cataloghi (Groq non dichiara
        niente, e costerebbe tutto anche i suoi modelli migliori).
        """
        return [p for p in self.models.values() if p.info.supports_tools is not False]

    def agent_capable(self, p: ModelProfile) -> bool:
        """Questo profilo puo' fare il lavoro di Orchestra?

        Tre casi, non due. Il terzo e' il motivo per cui questa
        funzione esiste invece di un `if supports_tools`.

        - True: il provider lo dichiara
        - False: il provider lo nega, o l'abbiamo appreso da un 400
        - None: il provider non lo dice. Non lo scartiamo — ma non lo
          trattiamo nemmeno come adatto: e' sconosciuto, e su uno
          sconosciuto non si fa affidamento.
        """
        return p.info.supports_tools is not False

    def ignoti_sui_tool(self) -> list[str]:
        """Modelli di cui il provider non dichiara il tool-calling.

        Non sono un errore: sono una domanda aperta. Elencarli serve a
        capire quanto del catalogo e' davvero utilizzabile, e a decidere
        se vale la pena misurarli col benchmark.
        """
        return sorted(mid for mid, p in self.models.items()
                      if p.info.supports_tools is None)

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
