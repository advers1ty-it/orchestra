"""Dati esterni da Artificial Analysis, usati come prior e non come verita'.

Perche' esiste. Artificial Analysis misura centinaia di modelli con una
suite loro: Intelligence Index, Coding Index, Agentic Index, prezzi,
latenza. Costa tempo e token rifare tutto da capo, e per i modelli di
punta e' la misura piu' ampia che esista.

Perche' non basta. Due limiti, entrambi verificati:

1. Loro restituiscono solo i modelli di prima parte con almeno 1.000
   voti arena. I modelli terze parti — cioe' quasi tutti quelli `:free`
   su OpenRouter — sono esclusi. Sul free tier questa fonte e' vuota.
2. Misurano il modello con i LORO prompt, isolato. Noi dobbiamo sapere
   come si comporta dentro Orchestra, con i nostri tool e il nostro
   formato. Un modello puo' essere forte su coding generico e incapace di
   chiamare `run_shell` come lo chiediamo noi.

Quindi: il dato esterno e' un prior — un'opinione informata da migliaia di
run — e le misure nostre restano la verita' per il routing. Il prior
sceglie la candidates; la misura sceglie il vincitore. Se il prior e'
assente, non succede niente: il catalogo funziona iguale.

Uso (serve una chiave gratuita, https://artificialanalysis.ai/data-api):

    ARTIFICIAL_ANALYSIS_KEY=... in .env
    orchestra models --prior          scarica e salva il prior
    orchestra models --prior-show     mostra la copertura

Nessuna chiave = nessun errore, solo prior vuoto.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

API_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
CACHE_TTL = 24 * 3600  # un giorno: i punteggi muovono lentamente

# Come i loro indici si mappano sulle nostre categorie. Non e' una
# corrispondenza perfetta: e' il loro metro applicato ai nostri task.
# Resta comunque un prior, quindi l'imprecisione e' accettabile.
CATEGORIE_AA = {
    "artificial_analysis_intelligence_index": "reasoning",
    "artificial_analysis_coding_index": "code",
    "artificial_analysis_agentic_index": "tool_use",
    "artificial_analysis_math_index": "reasoning",
    "artificial_analysis_mmlu_pro_index": "instruction",
}


@dataclass
class Prior:
    """Un'opinione esterna su un modello, normalizzata 0..1."""

    scores: dict[str, float] = field(default_factory=dict)
    source: str = ""
    measured_at: float = field(default_factory=time.time)

    def best_category(self) -> tuple[str, float] | None:
        if not self.scores:
            return None
        cat = max(self.scores, key=lambda c: self.scores[c])
        return cat, self.scores[cat]

    def to_dict(self) -> dict[str, Any]:
        return {"scores": dict(self.scores), "source": self.source,
                "measured_at": self.measured_at}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Prior":
        return cls(scores={k: float(v) for k, v in (d.get("scores") or {}).items()},
                   source=d.get("source", ""),
                   measured_at=float(d.get("measured_at", 0.0)))


def _normalizza(v: Any) -> float | None:
    """Loro restituiscono numeri gia' su 0..100. Noi usiamo 0..1."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    return round(f / 100.0, 4)


def chiave() -> str:
    return os.environ.get("ARTIFICIAL_ANALYSIS_KEY", "").strip()


def _cache_path() -> str:
    home = os.environ.get("ORCHESTRA_HOME", ".")
    return os.path.join(home, ".artificial_analysis.json")


def _leggi_cache() -> dict[str, Prior]:
    p = _cache_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: Prior.from_dict(v) for k, v in (raw.get("models") or {}).items()}


def _scrivi_cache(priors: dict[str, Prior]) -> None:
    p = _cache_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    payload = {"models": {k: v.to_dict() for k, v in priors.items()}}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, p)


def _match_id(nome_aa: str) -> str | None:
    """Il loro nome sul nostro id OpenRouter.

    'Claude 3.5 Sonnet' -> 'anthropic/claude-3.5-sonnet'. Non e' una
    corrispondenza affidabile in generale, quindi l'unico caso in cui
    ci fidiamo e' quando il nome contiene ':free' o coincide esatto:
    altrimenti un modello sbagliato con un punteggio giusto e' peggio
    di nessun punteggio.
    """
    s = (nome_aa or "").strip()
    if not s:
        return None
    if "/" in s:  # gia' nel formato OpenRouter
        return s
    return None


def scarica(*, refresh: bool = False) -> tuple[dict[str, Prior], str]:
    """Scarica i prior. Restituisce (prior, messaggio).

    Non solleva mai. Senza chiave o senza rete restituisce la cache, o
    un dizionario vuoto con il motivo: il prior e' un extra, non deve
    mai fermare il resto.
    """
    cached = _leggi_cache()
    if not refresh and cached and any(
            time.time() - p.measured_at < CACHE_TTL for p in cached.values()):
        return cached, f"cache locale ({len(cached)} modelli)"

    k = chiave()
    if not k:
        return cached, ("nessuna ARTIFICIAL_ANALYSIS_KEY: uso la cache"
                        if cached else
                        "nessuna ARTIFICIAL_ANALYSIS_KEY: nessun prior")

    req = urllib.request.Request(API_URL, headers={
        "X-API-Key": k,
        "User-Agent": "orchestra/0.5 (orchestratore locale)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            dati = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return cached, f"HTTP {e.code} dall'API: {e.reason} (uso la cache)"
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return cached, f"rete non disponibile: {e} (uso la cache)"

    priors: dict[str, Prior] = {}
    for m in (dati.get("data") or []):
        mid = _match_id(m.get("name", ""))
        if not mid:
            continue
        scores: dict[str, float] = {}
        for campo_aa, nostra in CATEGORIE_AA.items():
            n = _normalizza((m.get("evaluations") or {}).get(campo_aa))
            if n is not None:
                # una categoria puo' ricevere piu' indici: si tiene il max
                scores[nostra] = max(scores.get(nostra, 0.0), n)
        if scores:
            priors[mid] = Prior(scores=scores, source="artificialanalysis")

    if priors:
        _scrivi_cache(priors)
    return priors, f"scaricati {len(priors)} prior da artificialanalysis"


def copertura(priors: dict[str, Prior], catalogo: dict[str, Any]) -> dict[str, Any]:
    """Quanto del catalogo copre il prior. Serve a dirlo chiaramente."""
    con_free = sum(1 for mid in priors if mid.endswith(":free"))
    return {
        "prior": len(priors),
        "nel_catalogo": sum(1 for mid in priors if mid in catalogo),
        "gratuiti": con_free,
        "catalogo": len(catalogo),
    }
