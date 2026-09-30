"""Layer provider: normalizzazione delle differenze reali tra API.

Obiettivo dichiarato: NON fingere che le API siano identiche. Ogni adapter
espone le differenze che cambiano il comportamento del loop, invece di
appiattirle in un'interfaccia che mente.

Ad oggi: OpenAI-compatibili (OpenRouter, Groq, NVIDIA, Together, vLLM...).
Il punto di innesto per Anthropic nativo è `AnthropicAdapter`.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

from .types import LLMResponse, Message, ToolCall, new_id


class ProviderError(RuntimeError):
    """Errore del provider. Tre flag, non uno:

    - `retryable`  ha senso ritentare (429, 5xx, rete)?
    - `unusable`   il modello non e' raggiungibile da noi, e ritentare non
                   serve. Esempio reale: OpenRouter riserva alcuni modelli
                   free a un elenco chiuso di harness e risponde 403 "only
                   available on agentic harnesses". Senza questo flag quel
                   modello segna 0.00 su ogni task e sembra scarso, quando
                   e' semplicemente irraggiungibile — e il benchmark
                   finisce per consigliare il modello sbagliato.
    - `status`     il codice HTTP, se c'e'.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status: int = 0,
        unusable: bool = False,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.unusable = unusable


# Status che valgono la pena ritentare: rete intasata o quota esaurita.
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class OpenAICompatAdapter:
    """Adapter per qualunque endpoint che parli la chat-completions di OpenAI.

    Copre la maggior parte dei provider che ci serviranno. La normalizzazione
    che facciamo qui è minima ma sufficiente: prendiamo `tool_calls` e
    ricostruiamo `ToolCall`, tollerando i provider che mandano campi extra.

    User-Agent. Non è un dettaglio: alcuni modelli gratuiti su OpenRouter
    sono rifiutati con 403 se il client non si dichiara un agente. Il
    messaggio è esplicito — "only available on agentic harnesses" — ma
    nel benchmark arrivava come 403 generico, e un modello che funziona
    perfettamente nella chat segnava 0.00 su ogni task. Dichiararsi è
    anche la cosa giusta da fare: siamo un agente.
    """

    UA = "Orchestra/0.2 (agentic CLI; +https://github.com/local/orchestra)"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        name: str = "openai-compat",
        timeout: int = 120,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    # -- trasporto ---------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.extra_headers.pop("User-Agent", self.UA),
            **self.extra_headers,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:500]
            except Exception:
                pass
            # "only available on agentic harnesses": il provider riserva il
            # modello a un elenco chiuso di client. Non e' un errore da
            # ritentare e non dice niente sulla qualita' del modello, quindi
            # lo marchiamo a parte (vedi ProviderError.unusable).
            harness_locked = "agentic harnesses" in (detail or "").lower()
            raise ProviderError(
                f"{self.name}: HTTP {e.code} — {detail or e.reason}",
                retryable=e.code in RETRYABLE_STATUS,
                status=e.code,
                unusable=harness_locked,
            ) from e
        except urllib.error.URLError as e:
            # errori di rete: quasi sempre transitori
            raise ProviderError(
                f"{self.name}: errore di rete — {e.reason}", retryable=True
            ) from e

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"{self.name}: risposta non-JSON: {raw[:200]}") from e

    # -- API pubblica ------------------------------------------------------

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_api() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if stop:
            payload["stop"] = stop

        data = self._post("/chat/completions", payload)
        return self._normalize(data)

    def _normalize(self, data: dict[str, Any]) -> LLMResponse:
        # Gatekeeper: alcuni gateway (OpenRouter incluso) rispondono HTTP 200
        # e nascondono l'errore dentro il corpo JSON, es.
        #   {"error": {"message": "Provider returned an empty response",
        #              "code": 502, ...}}
        # Senza questo controllo il fallimento si presenta come "nessuna
        # choice" e il retry non scatta, perché non è un errore di rete.
        # In produzione è la differenza fra recuperare da solo e no.
        err = data.get("error")
        if err:
            if isinstance(err, str):
                msg, code = err, 0
            else:
                msg = err.get("message") or json.dumps(err)[:300]
                code = err.get("code") or 0
            # 502/503/429 del provider sono transitori anche se HTTP era 200
            transient = code in (408, 409, 425, 429, 500, 502, 503, 504, 529)
            raise ProviderError(
                f"{self.name}: errore nel corpo della risposta "
                f"(code={code or 'n/a'}): {msg}",
                retryable=transient,
                status=int(code) if isinstance(code, int) else 0,
                # 403 "only available on agentic harnesses" NON e' un errore
                # nostro: quel modello e' riservato a un elenco chiuso di
                # client. Segnalarlo permette al benchmark di escluderlo
                # invece di segnare 0.00 e farlo sembrare un modello scarso.
                unusable="only available on agentic harnesses" in str(msg).lower(),
            )

        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                f"{self.name}: nessuna choice nella risposta — "
                f"{json.dumps(data)[:300]}"
            )
        ch = choices[0]
        msg = ch.get("message") or {}

        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if not name:
                continue
            calls.append(
                ToolCall(
                    id=tc.get("id") or new_id(),
                    name=name,
                    arguments=fn.get("arguments") or "{}",
                )
            )

        usage = data.get("usage") or {}
        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=calls,
            model=data.get("model") or self.model,
            prompt_tokens=usage.get("prompt_tokens") or 0,
            completion_tokens=usage.get("completion_tokens") or 0,
            finish_reason=ch.get("finish_reason") or "",
            raw=data,
        )

    def list_models(self) -> list[str]:
        """Elenco modeli, se il provider lo espone. Utile per il discovery."""
        return [m.get("id", "") for m in self._list_models_raw() if m.get("id")]

    def _list_models_raw(self) -> list[dict[str, Any]]:
        """JSON grezzo di /models: prezzi, contesto, parametri supportati.

        `list_models` tiene solo gli id, ma il catalogo ha bisogno del
        resto per stimare i costi e filtrare chi supporta i tool.
        """
        try:
            r = urllib.request.Request(
                f"{self.base_url}/models",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "Mozilla/5.0 (compatible; orchestra/0.1)",
                },
            )
            with urllib.request.urlopen(r, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            out = data.get("data")
            return out if isinstance(out, list) else []
        except Exception:
            return []


# --------------------------------------------------------------------------
# Configurazione provider da .env
# --------------------------------------------------------------------------

# name -> (base_url, env var della chiave, modello di default)
#
# Una env var CHIAVE VUOTA significa "questo provider non vuole una
# chiave". E' il caso dei modelli locali: Ollama, LM Studio, llama.cpp,
# vLLM espongono tutti un'API OpenAI-compatible su localhost e chiedono
# nessuna autenticazione. Senza questo, l'unico modo di usarli sarebbe
# inventare una chiave finta — e la chiave finta in un prodotto e' una
# bug che aspetta di essere scoperta da un cliente.
#
# I modelli locali sono l'unica risposta vera alla domanda "gratis senza
# API key": il free tier dei provider cloud funziona, ma chiede un
# account, e un account non e' gratis per tutti. Un modello sul proprio
# computer non chiede nulla, non ha limiti di rate e funziona offline.
KNOWN_PROVIDERS: dict[str, tuple[str, str, str]] = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", ""),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", ""),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", ""),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY", ""),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", ""),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY", ""),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
    # --- locali, senza chiave ---
    "ollama": ("http://127.0.0.1:11434/v1", "", "llama3.2"),
    "lmstudio": ("http://127.0.0.1:1234/v1", "", "local-model"),
}

# Provider che non chiedono autenticazione: la chiave vuota e' corretta,
# non un errore di configurazione.
NO_KEY_PROVIDERS: frozenset[str] = frozenset(
    name for name, (_, key_env, _) in KNOWN_PROVIDERS.items() if not key_env
)


def base_url_for(name: str, env: dict[str, str] | None = None) -> str:
    """L'indirizzo del provider, con override possibile.

    Serve per i motori locali che girano su una porta diversa dalla
    solita (vLLM su 8000, un Ollama remoto su un'altra macchina). Senza
    override si dovrebbe modificare il codice, e un utente non tecnico
    non puo' farlo.
    """
    env = env if env is not None else os.environ
    if name not in KNOWN_PROVIDERS:
        raise KeyError(f"provider sconosciuto: {name}")
    override = env.get(f"ORCHESTRA_{name.upper()}_URL", "").strip()
    return (override or KNOWN_PROVIDERS[name][0]).rstrip("/")


def local_models(name: str, env: dict[str, str] | None = None,
                 timeout: float = 3.0) -> list[dict[str, Any]]:
    """Elenco dei modelli gia' scaricati su un motore locale.

    Non solleva: se il motore non e' in ascolto torna una lista vuota, e
    il chiamante può dire "nessun modello locale" invece di crashare.
    """
    import json as _json
    import urllib.request as _req

    base = base_url_for(name, env).rstrip("/")
    url = base + "/models"
    req = _req.Request(url, headers={"Accept": "application/json"})
    try:
        with _req.urlopen(req, timeout=timeout) as r:
            dati = _json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for m in (dati.get("data") or []):
        mid = m.get("id")
        if mid:
            out.append({"id": mid, "free": True, "context": 0,
                        "prompt_price": 0.0, "scores": {}})
    return sorted(out, key=lambda m: m["id"])


def local_models_multi(names: list[str], env: dict[str, str] | None = None,
                       timeout: float = 1.5) -> dict[str, list[dict[str, Any]]]:
    """Interroga piu' motori locali IN PARALLELA.

    In sequenza, due motori assenti costano 2 timeout: il pannello Opzioni
    impiegava tre secondi ad aprirsi, e sembrava rotto. Un timeout qui e'
    un'attesa, non un errore: se non arriva entro, quel motore non c'e' e
    va detto in un secondo momento, non bloccando la pagina.
    """
    from concurrent.futures import ThreadPoolExecutor

    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(names))) as ex:
        risultati = list(ex.map(
            lambda n: local_models(n, env, timeout=timeout), names))
    return {n: r for n, r in zip(names, risultati)}


def load_env(path: str) -> dict[str, str]:
    """Legge un .env minimale (KEY=VALUE, # commenti, export ammesso)."""
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            out[k.strip()] = v
    return out


def build_provider(
    name: str,
    *,
    model: str,
    env: dict[str, str] | None = None,
) -> OpenAICompatAdapter:
    env = env if env is not None else os.environ
    if name not in KNOWN_PROVIDERS:
        raise KeyError(f"provider sconosciuto: {name}. Disponibili: {list(KNOWN_PROVIDERS)}")
    _, key_env, default_model = KNOWN_PROVIDERS[name]
    api_key = env.get(key_env, "") if key_env else ""
    # chiave vuota in un provider SENZA chiave e' normale: e' un motore
    # locale. Su un provider cloud significa configurazione mancante, e
    # li' conviene dirlo adesso invece di mandare una richiesta che
    # torna 401.
    if not api_key and name not in NO_KEY_PROVIDERS:
        raise ProviderError(
            f"manca la chiave {key_env} per il provider '{name}'. "
            f"Mettila nel .env o nell'ambiente."
        )
    return OpenAICompatAdapter(
        base_url=base_url_for(name, env),
        api_key=api_key or "local",  # alcuni motori rifiutano un header vuoto
        model=model or default_model,
        name=name,
    )
