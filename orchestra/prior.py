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

from .providers import ambiente, load_env

# Dove sta il .env: stessa regola del resto del progetto.
#
# Prima `chiave()` leggeva os.environ e basta, e questo modulo era
# l'unico in tutto Orchestra che non passava da `ambiente()`. La
# chiave c'era, scritta e corretta, nel .env — e per prior.py non
# esisteva: il pannello diceva "nessuna ARTIFICIAL_ANALYSIS_KEY" con
# la chiava a tre righe di distanza.
#
# Il sintomo e' peggiore di un crash: il server risponde, il pannello
# si apre, e dice una cosa falsa. Un modulo che non trova la
# configurazione dovrebbe dirlo guardando la stessa fonte da cui
# gliela metti.
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

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
    return ambiente(_ENV_PATH).get("ARTIFICIAL_ANALYSIS_KEY", "").strip()


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


def _norm_id(s: str) -> str:
    """Un id sul formato di OpenRouter, in minuscolo e senza extra.

    `provider/modello`, `provider/modello:free`, `provider/modello:beta`
    diventano la stessa cosa. Senza questo, lo stesso modello su tre
    righe diverse del catalogo non viene riconosciuto e il prior
    finisce scartato — che e' successo.
    """
    s = (s or "").strip().lower()
    if ":" in s:
        s = s.split(":", 1)[0]
    s = s.strip("/")
        # Gli spazi diventano trattini: "DeepSeek V4.1 Flash" e
        # "deepseek/deepseek-v4.1-flash" sono lo stesso nome scritto in due
        # modi, e senza questo il match non aggancia niente.
    s = s.replace(" ", "-").replace("_", "-")
    return s.strip("-")


def _togli_parentesi(s: str) -> str:
    """Il nome loro senza la variante.

    "GLM-5.3 (Max)" -> "glm-5.3". La variante sta fra parentesi e da
    noi finisce dopo i due punti (`openai/gpt-5.4:xhigh`), quindi
    toglierla non perde niente e rende confrontabile il resto.
    """
    s = s.split("(", 1)[0]
    s = s.split("[", 1)[0]
    return s.strip()


def _match_id(nome_aa: str, catalogo: dict[str, Any] | None = None) -> str | None:
    """Il loro nome sul nostro id del catalogo.

    "GLM-5.3 (Max)" -> "z-ai/glm-5.3", "GPT-5.4 (Xhigh)" ->
    "openai/gpt-5.4". La regola e' che il nostro id FINISCE col loro
    nome ripulito: il provider sta prima della "/", il nome del
    modello dopo, e coincide.

    Perche' questa e non una somiglianza: una somiglianza trova anche
    quello sbagliato, e un prior attaccato al modello sbagliato e'
    peggio di nessun prior. Il prior e' un parere, quindi sbagliarlo
    non e' una catastrofe — ma e' comunque una bug che si propaga
    nelle scelte e da li' non si vede piu' nulla.

    Prima accettava solo i nomi che contenevano gia' una "/", cioe'
    nessuno di quelli che l'API restituisce: zero match, sempre. Il
    modulo scaricava 689 modelli e ne teneva 0, senza dire perche'.

    Se piu' di un id finisce collo stesso nome, non si sceglie: si
    dichiara l'ambiguita'. Il prior manca, ma manca in modo che si
    possa leggere.
    """
    s = _norm_id(_togli_parentesi(nome_aa))
    if not s or not catalogo:
        return None

    esatti = [m for m in catalogo if _norm_id(m) == s]
    if len(esatti) == 1:
        return esatti[0]

    candidati = [m for m in catalogo if _norm_id(m).endswith(s)]
    if len(candidati) == 1:
        return candidati[0]
    if len(candidati) > 1:
        # Due id che finiscono con lo stesso nome non sono sempre due
        # modelli diversi: openai/gpt-5.4 e openai/gpt-5.4:high sono
        # lo stesso modello con due varianti, e il prior e' sul modello.
        # Se normalizzati coincidono, non e' ambiguità: e' lo stesso
        # nome due volte. Si prende il primo in ordine, cosi' la scelta
        # e' sempre la stessa.
        if len({_norm_id(m) for m in candidati}) == 1:
            return sorted(candidati)[0]
        return None
    return None

def scarica(*, refresh: bool = False,
            catalogo: dict[str, Any] | None = None) -> tuple[dict[str, Prior], str]:
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
        mid = _match_id(m.get("name", ""), catalogo)
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
