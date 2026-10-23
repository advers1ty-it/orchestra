"""Layer provider: normalizzazione delle differenze reali tra API.

Obiettivo dichiarato: NON fingere che le API siano identiche. Ogni adapter
espone le differenze che cambiano il comportamento del loop, invece di
appiattirle in un'interfaccia che mente.

Ad oggi: OpenAI-compatibili (OpenRouter, Groq, NVIDIA, Together, vLLM...).
Il punto di innesto per Anthropic nativo è `AnthropicAdapter`.
"""

from __future__ import annotations

import json
import re
import os
import shutil
import sys
import urllib.request
import urllib.error
from collections.abc import Callable
from typing import Any

from .types import LLMResponse, Message, ToolCall, new_id
from .reasoning import build_reasoning_payload
from . import nous_auth


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
        retry_after: float = 0.0,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.unusable = unusable
        # Quanto il server chiede di aspettare, in secondi. Su un 429
        # OpenRouter scrive "Please try again in 8.13s" nel corpo e
        # rimette anche l'header: noi lo leggevamo e non lo usiavamo,
        # e il backoff di mezzo secondo faceva quattro tentativi
        # dentro la finestra che il provider aveva chiesto di non
        # toccare. Il server dice quanto aspettare e noi indoviniamo
        # di meno.
        self.retry_after = retry_after


# Status che valgono la pena ritentare: rete intasata o quota esaurita.
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class _StreamNonSupportato(Exception):
    """Il provider non fa lo streaming su questo modello.

    Non è un errore: è una capacità che non c'è. Distinguerla serve a
    tornare alla richiesta in blocco invece di propagare un'eccezione che
    sembra un guasto di rete.
    """

def _retry_after(corpo: str, headers=None) -> float:
    """Quanti secondi chiede il server di aspettare. Zero se non lo dice.

    OpenRouter scrive la richiesta in due modi: l'header
    `Retry-After` e, dentro il corpo, frasi come "Please try again in
    8.13s". Li leggevamo entrambi senza usarne nessuno, e il backoff
    di mezzo secondo faceva quattro tentativi dentro la finestra che
    il provider aveva chiesto di lasciare stare.

    Si guardano entrambi perche' non tutti i gateway mandano l'header,
    e alcuni non scrivono niente. Zero significa "non lo ha detto" e il
    chiamante usa il suo backoff: nessun numero inventato.
    """
    try:
        if headers is not None:
            v = headers.get("Retry-After") or headers.get("retry-after")
            if v:
                return max(0.0, min(float(str(v).strip()), 300.0))
    except (TypeError, ValueError, AttributeError):
        pass
    m = re.search(r"try again in\s+([\d.]+)\s*s", corpo or "", re.I)
    if m:
        try:
            return max(0.0, min(float(m.group(1)), 300.0))
        except ValueError:
            pass
    m = re.search(r"retry[_ ]after[^\d]{0,12}(\d+)", corpo or "", re.I)
    if m:
        try:
            return max(0.0, min(float(m.group(1)), 300.0))
        except ValueError:
            pass
    return 0.0



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
        refresh_key: Callable[[], str | None] | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        # Chiave di scorta: su 401 la si prova una volta prima di
        # arrendersi (token Nous scaduto a server acceso, vedi sotto).
        self.refresh_key = refresh_key

    def _chiave_fresca(self) -> bool:
        """Chiede una chiave nuova e la installa. True se e' cambiata.

        Solo per provider con rinnovo (Nous): gli altri non passano
        refresh_key e qui non si fa niente. Non solleva mai: se il
        rinnovo fallisce, il chiamante segnala il 401 originale.
        """
        if self.refresh_key is None:
            return False
        try:
            nuova = self.refresh_key()
        except Exception:
            return False
        if nuova and nuova != self.api_key:
            self.api_key = nuova
            return True
        return False

    # -- trasporto ---------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any],
              _retry: bool = True) -> dict[str, Any]:
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
            # 401 con rinnovo: il token e' scaduto mentre il server era
            # acceso (l'adapter nasce col token di allora). Una sola
            # seconda chance con la chiave fresca, poi l'errore vero.
            if e.code == 401 and _retry and self._chiave_fresca():
                return self._post(path, payload, _retry=False)
            # "only available on agentic harnesses": il provider riserva il
            # modello a un elenco chiuso di client. Non e' un errore da
            # ritentare e non dice niente sulla qualita' del modello, quindi
            # lo marchiamo a parte (vedi ProviderError.unusable).
            harness_locked = "agentic harnesses" in (detail or "").lower()
            # quanto aspettare: l'header e la frase dentro il corpo. Su
            # un 429 il provider scrive "try again in 8.13s" e noi
            # ripartivamo dopo mezzo secondo — quattro tentativi dentro
            # la sua finestra, e poi un rate limit finiva nel
            # benchmark come un modello scarso.
            attesa = _retry_after(
                detail or "",
                getattr(e, "headers", None))
            raise ProviderError(
                f"{self.name}: HTTP {e.code} — {detail or e.reason}",
                retryable=e.code in RETRYABLE_STATUS,
                status=e.code,
                unusable=harness_locked,
                retry_after=attesa,
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
            reasoning_level: str | None = None,
        ) -> LLMResponse:
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": [m.to_api() for m in messages],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            # Provider-specific reasoning payload (no-op if unsupported)
            reasoning_payload = build_reasoning_payload(self.name, self.model, reasoning_level)
            if reasoning_payload:
                payload.update(reasoning_payload)
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            if stop:
                payload["stop"] = stop

            data = self._post("/chat/completions", payload)
            return self._normalize(data)

    def chat_stream(
            self,
            messages: list[Message],
            tools: list[dict[str, Any]] | None = None,
            *,
            temperature: float = 0.7,
            max_tokens: int = 4096,
            stop: list[str] | None = None,
            reasoning_level: str | None = None,
            on_event=None,
    ) -> LLMResponse:
        """Come `chat`, ma i pezzi arrivano man mano che il modello li scrive.

        Metodo SEPARATO, e non un flag su `chat`: l'agent loop, il
        benchmark e la delega ragionano su `LLMResponse` completo — token
        totali, durata, `finish_reason`. Aggiungere lo streaming lì
        significava toccare tutti quelli, e un rialzo di costo in cambio
        di niente.

        Qui serve una cosa sola: mostrare il ragionamento mentre accade.
        Verificato su un modello gratuito con `reasoning: high` — 328
        chunk, 2044 caratteri, tutti prima del primo carattere di
        contenuto. È quel vuoto che l'utente guardava senza sapere se
        fosse rotto.

        `on_event(kind, data)` riceve `ragionamento` e `contenuto`. Se
        manca, lo streaming degrada a `chat` con una richiesta in blocco.
        """
        def emetti(kind: str, data: dict) -> None:
            if on_event is None:
                return
            try:
                on_event(kind, data)
            except Exception:
                # La UI non deve poter far cadere una risposta già pagata.
                pass

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_api() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        # Con lo streaming si chiedono anche gli usage: senza, i token
        # totali non arrivano nei chunk e il budget di spesa non li vede.
        payload["stream_options"] = {"include_usage": True}
        reasoning_payload = build_reasoning_payload(self.name, self.model,
                                                    reasoning_level)
        if reasoning_payload:
            payload.update(reasoning_payload)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if stop:
            payload["stop"] = stop

        # Se il provider rifiuta lo streaming si torna al blocco: la
        # risposta giusta conta più del modo in cui arriva.
        try:
            return self._post_stream("/chat/completions", payload, emetti)
        except _StreamNonSupportato:
            payload.pop("stream", None)
            payload.pop("stream_options", None)
            data = self._post("/chat/completions", payload)
            risposta = self._normalize(data)
            if risposta.reasoning:
                emetti("ragionamento", {"testo": risposta.reasoning})
            if risposta.content:
                emetti("contenuto", {"testo": risposta.content})
            return risposta

    def _post_stream(self, path: str, payload: dict[str, Any],
                     emetti, _retry: bool = True) -> LLMResponse:
        """Fa la chiamata in streaming e ricompone la risposta.

        I chunk arrivano come `data: {...}` e finiscono con `data: [DONE]`.
        I tool call arrivano a pezzi, per indice: vanno accumulati e non
        presi uno per uno, o una chiamata con tre argomenti diventa tre
        chiamate con un argomento ciascuna.
        """
        import urllib.request
        url = self.base_url.rstrip("/") + path
        corpo = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=corpo, headers=headers,
                                     method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:500]
            except Exception:
                pass
            # Un 400 che parla di `stream` vuol dire "non lo faccio": si
            # torna al blocco invece di morire su una capacità che il
            # provider non ha.
            if e.code == 400 and "stream" in (detail or "").lower():
                raise _StreamNonSupportato(detail)
            # Come in _post: un 401 puo' essere il token scaduto a server
            # acceso. Nessun chunk e' ancora partito, quindi si puo'
            # riaprire lo stream da capo con la chiave fresca, una volta.
            if e.code == 401 and _retry and self._chiave_fresca():
                return self._post_stream(path, payload, emetti, _retry=False)
            raise ProviderError(
                f"{self.name}: HTTP {e.code} — {detail or e.reason}",
                retryable=e.code in RETRYABLE_STATUS,
                status=e.code,
                retry_after=_retry_after(detail or "", getattr(e, "headers", None)),
            )

        contenuto: list[str] = []
        ragionamento: list[str] = []
        tool_per_indice: dict[int, dict[str, Any]] = {}
        modello = payload.get("model", "")
        finish = ""
        uso: dict[str, Any] = {}

        with resp:
            grezzo = resp.readline()
            while grezzo:
                riga = grezzo.decode("utf-8", "replace").strip()
                grezzo = resp.readline()
                if not riga or not riga.startswith("data:"):
                    continue
                dati = riga[5:].strip()
                if dati == "[DONE]":
                    break
                try:
                    d = json.loads(dati)
                except Exception:
                    continue
                if d.get("error"):
                    msg = d["error"]
                    if isinstance(msg, dict):
                        msg = msg.get("message") or json.dumps(msg)[:300]
                    raise ProviderError(f"{self.name}: {msg}", retryable=True)
                if d.get("model"):
                    modello = d["model"]
                if d.get("usage"):
                    uso = d["usage"]
                scelte = d.get("choices") or []
                if not scelte:
                    continue
                delta = scelte[0].get("delta") or {}
                # Il ragionamento arriva in `reasoning` (OpenRouter), in
                # `reasoning_content` (Reflection/DeepSeek) oppure in
                # `reasoning_details` (altri gateway): si guardano tutti, o
                # su metà dei provider il vuoto resta.
                pezzo = delta.get("reasoning") or delta.get("reasoning_content")
                if not pezzo:
                    dettagli = delta.get("reasoning_details")
                    if isinstance(dettagli, list):
                        pezzo = "".join(
                            str(x.get("text") or x.get("summary") or "")
                            for x in dettagli if isinstance(x, dict))
                if pezzo:
                    ragionamento.append(pezzo)
                    emetti("ragionamento", {"testo": pezzo})
                testo = delta.get("content")
                if testo:
                    contenuto.append(testo)
                    emetti("contenuto", {"testo": testo})
                for tc in (delta.get("tool_calls") or []):
                    i = tc.get("index", 0)
                    acc = tool_per_indice.setdefault(
                        i, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fun = tc.get("function") or {}
                    if fun.get("name"):
                        acc["name"] += fun["name"]
                    if fun.get("arguments"):
                        acc["arguments"] += fun["arguments"]
                if scelte[0].get("finish_reason"):
                    finish = scelte[0]["finish_reason"]

        tool_calls = []
        for i in sorted(tool_per_indice):
            t = tool_per_indice[i]
            if t["name"]:
                tool_calls.append(ToolCall(
                    id=t["id"] or f"call_{i}",
                    name=t["name"],
                    arguments=t["arguments"] or "{}",
                ))

        return LLMResponse(
            content="".join(contenuto),
            tool_calls=tool_calls,
            model=modello,
            prompt_tokens=int(uso.get("prompt_tokens") or 0),
            completion_tokens=int(uso.get("completion_tokens") or 0),
            finish_reason=finish,
            reasoning="".join(ragionamento),
            raw={"streamed": True},
        )

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
        # Il ragionamento: `reasoning` (OpenRouter), `reasoning_content`
        # (Reflection/DeepSeek/altri) oppure `reasoning_details` (gateway
        # che lo mandano come lista). Non si puo' fidarsi del primo solo:
        # su Beam 1.0 arriva `reasoning_content` e senza leggerlo il campo
        # resta vuoto, e i turni successivi non hanno piu' il ragionamento
        # da rimandare.
        ragionamento = msg.get("reasoning") or msg.get("reasoning_content") or ""
        if not ragionamento:
            dettagli = msg.get("reasoning_details")
            if isinstance(dettagli, list):
                ragionamento = "".join(
                    str(x.get("text") or x.get("summary") or "")
                    for x in dettagli if isinstance(x, dict))
        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=calls,
            model=data.get("model") or self.model,
            prompt_tokens=usage.get("prompt_tokens") or 0,
            completion_tokens=usage.get("completion_tokens") or 0,
            finish_reason=ch.get("finish_reason") or "",
            reasoning=ragionamento,
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


class AnthropicAdapter:
    """Adapter nativo per l'API Messages di Anthropic.

    Differenza fondamentale rispetto all'OpenAI-compat: i tool vengono
    mandati in un formato proprio (`input_schema` invece di
    `function.parameters`), il system prompt va nel campo top-level e non
    dentro i messaggi, e le risposte separano `text` blocks da `tool_use`
    blocks dentro l'array `content`.

    Non implementiamo lo streaming: `chat_stream` resta assente e l'agent
    cade su `chat`, che è il caso corretto per i provider-memo (reasoning)
    non è disponibile qui.
    """

    UA = "Orchestra/0.2 (agentic CLI; +https://github.com/local/orchestra)"

    def __init__(self, *, base_url: str, api_key: str, model: str,
                timeout: int = 120, extra_headers: dict[str, str] | None = None) -> None:
        self.name = "anthropic"
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/messages"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.UA,
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        headers.update(self.extra_headers)
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
            raise ProviderError(
                f"anthropic: HTTP {e.code} — {detail or e.reason}",
                retryable=e.code in RETRYABLE_STATUS,
                status=e.code,
            ) from e
        except urllib.error.URLError as e:
            raise ProviderError(f"anthropic: errore di rete — {e.reason}",
                               retryable=True) from e
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"anthropic: risposta non-JSON: {raw[:200]}") from e

    def _convert_messages(self, messages: list[Message]):
        system: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                if m.content:
                    system.append(m.content)
                continue
            if m.role == "assistant":
                content: list[dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    try:
                        inp = json.loads(tc.arguments or "{}")
                    except json.JSONDecodeError:
                        inp = {"_raw": tc.arguments}
                    if not isinstance(inp, dict):
                        inp = {"_raw": inp}
                    content.append({"type": "tool_use",
                                   "id": tc.id, "name": tc.name, "input": inp})
                if not content:
                    content.append({"type": "text", "text": ""})
                out.append({"role": "assistant", "content": content})
            elif m.role == "tool":
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": m.tool_call_id,
                     "content": m.content}]})
            else:
                content = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                # immagini data URL -> base64 source
                for url in getattr(m, "images", []) or []:
                    if not isinstance(url, str) or not url.startswith("data:"):
                        continue
                    try:
                        head, b64 = url.split(",", 1)
                        media = head.split(";")[0].split(":")[1] if ";" in head else head.split(":")[1]
                    except (ValueError, IndexError):
                        continue
                    content.append({"type": "image", "source": {
                        "type": "base64", "media_type": media, "data": b64}})
                if not content:
                    content.append({"type": "text", "text": ""})
                out.append({"role": "user", "content": content})
        return ("\n\n".join(system).strip(), out)

    def _convert_tools(self, tools):
        out = []
        for t in tools or []:
            f = t.get("function", t) if isinstance(t, dict) else t
            if not isinstance(f, dict):
                continue
            out.append({
                "name": f["name"],
                "description": f.get("description", ""),
                "input_schema": f.get("parameters", {"type": "object"}),
            })
        return out

    def chat(self, messages, tools=None, *, temperature=0.7, max_tokens=4096,
             stop=None, reasoning_level=None) -> LLMResponse:
        system, converted = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": converted,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        converted_tools = self._convert_tools(tools) if tools else []
        if converted_tools:
            payload["tools"] = converted_tools
        try:
            data = self._post(payload)
        except Exception:
            raise

        blocks = data.get("content") or []
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                text_parts.append(b.get("text") or "")
            elif bt == "tool_use":
                calls.append(ToolCall(
                    id=b.get("id") or new_id(),
                    name=b.get("name") or "",
                    arguments=json.dumps(b.get("input") or {}),
                ))
        usage = data.get("usage") or {}
        return LLMResponse(
            content="".join(text_parts),
            tool_calls=calls,
            model=data.get("model") or self.model,
            prompt_tokens=usage.get("input_tokens") or 0,
            completion_tokens=usage.get("output_tokens") or 0,
            finish_reason=data.get("stop_reason") or "",
            raw=data,
        )

    def list_models(self) -> list[str]:
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
    # Hugging Face: l'Inference API e' OpenAI-compatible e il free tier
    # con token e' il piu' generoso in numero di richieste fra i
    # provider che accettano una carta. Funziona anche senza account
    # con crediti, quindi resta raggiungibile quando gli altri no.
    "huggingface": ("https://router.huggingface.co/v1", "HF_TOKEN", ""),
    # Google AI Studio: Gemini su un endpoint OpenAI-compatible.
    # Non confonderlo con Vertex AI, che e' un'altra cosa e ha bisogno
    # di un progetto GCP. Qui si parla solo di aistudio.
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai",
               "GEMINI_API_KEY", "gemini-2.0-flash"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY", ""),
    "anthropic": ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-latest"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
    # Nous Research: accesso diretto all'inference API tramite il
    # device code OAuth Nous (JWT), oppure NOUS_API_KEY.
    "nous": ("https://inference-api.nousresearch.com/v1", "NOUS_API_KEY", ""),
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
    env = env if env is not None else os.environ
    if name == "nous":
        _, base = nous_auth.get_nous_credentials(env)
        if base:
            return base.rstrip("/")
        override = str(env.get("ORCHESTRA_NOUS_URL") or env.get("NOUS_INFERENCE_BASE_URL") or "").strip()
        return (override or "https://inference-api.nousresearch.com/v1").rstrip("/")
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
) -> Any:
    env = env if env is not None else os.environ
    if name == "anthropic":
        api_key = (env.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            raise ProviderError("manca la chiave ANTHROPIC_API_KEY per il provider 'anthropic'.")
        _, _, default_model = KNOWN_PROVIDERS[name]
        return AnthropicAdapter(
            base_url=base_url_for(name, env),
            api_key=api_key,
            model=model or default_model,
        )
    if name == "nous":
        token, base_url_override = nous_auth.get_nous_credentials(env)
        if not token:
            raise ProviderError(
                "nous: collegamento non disponibile. Esegui "
                "`python -m orchestra.cli auth nous` (oppure imposta NOUS_API_KEY), "
                "poi riprova."
            )
        _, _, default_model = KNOWN_PROVIDERS[name]
        return OpenAICompatAdapter(
            base_url=base_url_override or base_url_for(name, env),
            api_key=token,
            model=model or default_model,
            name=name,
            # Il token scade a server acceso: su 401 si rinnova e si
            # riprova una volta, invece di chiedere un riavvio.
            refresh_key=lambda: nous_auth.refresh_forzato(env),
        )
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
            f"Inseriscila dal pannello Opzioni (icona in alto) o in .env."
        )
    return OpenAICompatAdapter(
        base_url=base_url_for(name, env),
        api_key=api_key or "local",  # alcuni motori rifiutano un header vuoto
        model=model or default_model,
        name=name,
    )

def ambiente(path: str) -> dict[str, str]:
    """Le chiavi per costruire un provider: .env + ambiente di sistema.

    Il .env riempie quello che manca; l'ambiente esplicito vince.
    Prima era il contrario — `dict(os.environ)` seguito da
    `update(load_env(...))` — e rendeva impossibile cambiare provider o
    modello dalla riga di comando senza editare il file. E' utile solo
    finche' non serve esattamente quello: e' servito a un test che
    voleva provare la delega su un provider diverso e non c'e' riuscito
    perche' il .env decideva al suo posto.

    Nota che le chiavi dei provider NON sono un caso speciale. Se
    qualcuno esporta una chiave volutamente, quella e' quella giusta:
    un .env con dentro una chiave scaduta non deve vincere su una
    chiave messa a posto per questa esecuzione.
    """
    # Primo avvio: se il .env non esiste ma c'e' l'esempio accanto, lo
    # si crea da soli. Cosi' l'installazione per i non esperti non puo'
    # restare senza file di configurazione: resta solo da riempire le
    # chiavi (dalla UI in Opzioni, o editando il file).
    if not os.path.exists(path):
        esempio = os.path.join(os.path.dirname(path), ".env.example")
        if os.path.exists(esempio):
            try:
                shutil.copy(esempio, path)
                print(f"creato {path} da .env.example: inserisci le chiavi API",
                      file=sys.stderr)
            except OSError:
                pass
    merged = dict(load_env(path))
    merged.update(os.environ)
    return merged
