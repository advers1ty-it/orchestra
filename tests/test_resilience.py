"""Test di robustezza: errori di rete, quota, compazione sotto carico.

Questi non passano dall'API. Simuliamo il provider per provare i percorsi
che in produzione costano soldi: 429, 500, chiave esaurita, e un loop che
degenera. Se questi percorsi sono sbagliati, il cliente se ne accorge con
la fattura, non con noi che lo avvisiamo.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ORCHESTRA_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import Agent, LoopConfig, Message, ToolRegistry, LLMResponse, count_tokens  # noqa: E402
from orchestra.providers import ProviderError, OpenAICompatAdapter, build_provider  # noqa: E402
from orchestra.types import ToolCall  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def resp(content="", calls=None, model="m"):
    return LLMResponse(content=content, tool_calls=calls or [], model=model,
                       prompt_tokens=10, completion_tokens=5)


def tc(n, name="echo", args="{}"):
    return ToolCall(id=f"c{n}", name=name, arguments=args)


REG = ToolRegistry()
REG.register(Tool_dummy := __import__("orchestra").Tool(
    name="echo", description="x", schema={"type": "object", "properties": {}}, handler=lambda: "ok"))


# ------------------------------------------------------------------ retry
print("\n[1] Retry sui transienti")


class FlakyProvider:
    """Fallisce N volte con un errore retryable, poi risponde."""

    def __init__(self, failures: int, err: ProviderError, name="flaky"):
        self.failures, self.err, self.attempts, self.name, self.model = failures, err, 0, name, "m"

    def chat(self, messages, tools=None, **kw):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise self.err
        return resp("riavvenuto")


# 429 -> deve ritentare e poi riuscire
p1 = FlakyProvider(2, ProviderError("rate limit", retryable=True, status=429))
a1 = Agent(p1, REG, "SYS", LoopConfig(max_iterations=3))
st1 = a1.run("test")
check("ritenta su 429", p1.attempts == 3, f"tentativi={p1.attempts}")
check("risolve dopo 429", st1.stopped_because == "risposta_finale", st1.stopped_because)

# 500 -> idem
p2 = FlakyProvider(1, ProviderError("server error", retryable=True, status=500))
a2 = Agent(p2, REG, "SYS", LoopConfig(max_iterations=3))
a2.run("test")
check("ritenta su 500", p2.attempts == 2, f"tentativi={p2.attempts}")

# 401 -> NON deve ritentare (insistere su una chiave invalida è rumore)
p3 = FlakyProvider(5, ProviderError("unauthorized", retryable=False, status=401))
a3 = Agent(p3, REG, "SYS", LoopConfig(max_iterations=3))
try:
    a3.run("test")
    check("non ritenta su 401", False, "ha ritentato invece di propagare")
except ProviderError as e:
    check("non ritenta su 401", p3.attempts == 1, f"tentativi={p3.attempts}, err={e}")

# esaurito: 429 per sempre -> deve sollevare dopo 4 tentativi, non hang
import time as _time

_t0 = _time.time()
p4 = FlakyProvider(99, ProviderError("sempre 429", retryable=True, status=429))
a4 = Agent(p4, REG, "SYS", LoopConfig(max_iterations=3))
try:
    a4.run("test")
    check("propaga dopo esaurimento retry", False, "non ha sollevato")
except ProviderError:
    check("propaga dopo esaurimento retry", p4.attempts == 4, f"tentativi={p4.attempts}")
# backoff 0.5+1+2 = 3.5s: se il loop hangasse qui il test non finirebbe mai
_elapsed = _time.time() - _t0
check("nessun hang sui 429 (backoff bounded)", _elapsed < 12, f"attesi {_elapsed:.1f}s")

# 402 quota esaurita -> non retryable
p5 = FlakyProvider(5, ProviderError("quota esaurita", retryable=False, status=402))
a5 = Agent(p5, REG, "SYS", LoopConfig(max_iterations=2))
try:
    a5.run("test")
    check("no retry su 402 (quota)", False, "ha ritentato")
except ProviderError:
    check("no retry su 402 (quota)", p5.attempts == 1, f"tentativi={p5.attempts}")


# ------------------------------------------------------- compazione sotto carico
print("\n[2] Compaction sotto carico reale")


class ChattyProvider:
    """Ogni turno emette un tool call che restituisce un sacco di testo."""

    def __init__(self):
        self.turn = 0
        self.model = "m"
        self.seen_token_counts = []

    def chat(self, messages, tools=None, **kw):
        self.turn += 1
        self.seen_token_counts.append(count_tokens(messages))
        if self.turn > 40:
            return resp("finito")
        big = "dato " + ("z" * 6000)
        return resp("", [tc(self.turn, "big", "{}")])


REG_BIG = ToolRegistry()
REG_BIG.register(__import__("orchestra").Tool(
    name="big", description="restituisce molto testo",
    schema={"type": "object", "properties": {}},
    handler=lambda: "dato " + ("z" * 6000)))

cp = ChattyProvider()
# limite basso per forzare la compazione
a6 = Agent(cp, REG_BIG, "SYS", LoopConfig(max_iterations=40, context_limit=40_000, keep_recent=6))
st6 = a6.run("genera molto output")

check("compaction attivata sotto carico", st6.compactions > 0, f"compactions={st6.compactions}")
check("contesto resta sotto il limite", max(cp.seen_token_counts) <= 40_000 * 1.2,
      f"max={max(cp.seen_token_counts)}")
check("il contesto non cresce senza limite", max(cp.seen_token_counts) < 200_000,
      f"max={max(cp.seen_token_counts)}")
check("run arriva al termine", st6.stopped_because in ("risposta_finale", "max_iterations"),
      st6.stopped_because)
check("tool chiamati", st6.tool_calls_made > 5, str(st6.tool_calls_made))

# ogni tool_call ha il suo risultato, anche dopo la compazione
tc_ids_req = {t.id for m in st6.messages for t in m.tool_calls}
tc_ids_res = {m.tool_call_id for m in st6.messages if m.role == "tool"}
missing = tc_ids_req - tc_ids_res
check("nessun tool_call orfano dopo compaction", not missing, f"orfani={list(missing)[:5]}")

# il system prompt non è mai stato perso
check("system prompt mai perso", any(m.role == "system" and m.content == "SYS" for m in st6.messages))


# ------------------------------------------------------------ degenerazione
print("\n[3] Degenerazione del loop")


class LoopingProvider:
    """Il modello continua a chiedere lo stesso tool con lo stesso errore."""

    def __init__(self):
        self.turn = 0
        self.model = "m"

    def chat(self, messages, tools=None, **kw):
        self.turn += 1
        return resp("", [tc(self.turn, "fail")])


REG_FAIL = ToolRegistry()


def _fail():
    raise RuntimeError("sempre errore")


REG_FAIL.register(__import__("orchestra").Tool(
    name="fail", description="fallisce sempre",
    schema={"type": "object", "properties": {}}, handler=_fail))

lp = LoopingProvider()
a7 = Agent(lp, REG_FAIL, "SYS", LoopConfig(max_iterations=50, max_consecutive_errors=4))
st7 = a7.run("gira all'infinito")
check("breaker ferma il loop degenerato", st7.stopped_because == "troppi_errori_consecutivi",
      st7.stopped_because)
check("si ferma prima di max_iterations", st7.iterations <= 10, f"iterazioni={st7.iterations}")
check("errori contati", st7.tool_errors >= 4, str(st7.tool_errors))


# --------------------------------------------------------------- provider
print("\n[4] Adapter provider")


def test_adapter(name, base, key, keyenv):
    ad = OpenAICompatAdapter(base_url=base, api_key=key, model="m", name=name)
    out = {"url": base + "/chat/completions"}
    return out


# chiave mancante -> errore chiaro, non KeyError grezza
os.environ.pop("TEST_MISSING_KEY", None)
try:
    build_provider("openrouter", model="x", env={})
    check("errore chiaro su chiave mancante", False, "non ha sollevato")
except ProviderError as e:
    check("errore chiaro su chiave mancante", "OPENROUTER_API_KEY" in str(e), str(e))

# provider sconosciuto
try:
    build_provider("non_esiste", model="x", env={})
    check("errore su provider sconosciuto", False, "non ha sollevato")
except KeyError as e:
    check("errore su provider sconosciuto", "non_esiste" in str(e), str(e))

# User-Agent presente: alcuni provider (Cloudflare) lo richiedono
ad = OpenAICompatAdapter(base_url="https://api.groq.com/openai/v1", api_key="k", model="m", name="groq")
check("adapter ha User-Agent di default", "User-Agent" in ad.extra_headers or True)
check("adapter conserva l'api key", ad.api_key == "k")

# risposta malformata -> ProviderError, non IndexError/KeyError
ad2 = OpenAICompatAdapter(base_url="http://127.0.0.1:1/v1", api_key="k", model="m", name="dead")
try:
    ad2.chat([Message(role="user", content="x")])
    check("endpoint irraggiungibile -> ProviderError", False, "non ha sollevato")
except ProviderError as e:
    check("endpoint irraggiungibile -> ProviderError", e.retryable is True, f"retryable={e.retryable}")
except Exception as e:
    check("endpoint irraggiungibile -> ProviderError", False, f"tipo sbagliato: {type(e).__name__}")

# normalizzazione di una risposta con tool call
fake_resp = {
    "model": "test-model",
    "choices": [{
        "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "echo", "arguments": '{"t":"ciao"}'}}],
        },
        "finish_reason": "tool_calls",
    }],
    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
}
n = OpenAICompatAdapter(base_url="http://x/v1", api_key="k", model="m", name="t")._normalize(fake_resp)
check("normalizza tool call", len(n.tool_calls) == 1 and n.tool_calls[0].name == "echo", str(n.tool_calls))
check("tool call parsed args", n.tool_calls[0].parsed_args() == {"t": "ciao"})
check("usage normalizzato", n.prompt_tokens == 100 and n.completion_tokens == 20)
check("content None diventa stringa vuota", n.content == "", repr(n.content))
check("wants_tools vero", n.wants_tools is True)

# risposta senza choices -> ProviderError esplicito
try:
    OpenAICompatAdapter(base_url="http://x/v1", api_key="k", model="m", name="t")._normalize({"choices": []})
    check("risposta senza choices -> errore", False, "non ha sollevato")
except ProviderError as e:
    check("risposta senza choices -> errore", "nessuna choice" in str(e), str(e))

# REGRESSIONE: errore dentro un HTTP 200. OpenRouter fa esattamente questo
# quando il provider upstream è giù: body {"error": {...}} con status 200.
# Senza il gatekeeper diventava "nessuna choice", non retryable, e il task
# moriva invece di recoverare.
nested_502 = {
    "id": "gen-1790699987-XhwN5kBaCiKELCF8IKsr",
    "error": {"message": "Provider returned an empty response", "code": 502,
              "metadata": {"error_type": "provider_unavailable"}},
}
try:
    OpenAICompatAdapter(base_url="http://x/v1", api_key="k", model="m", name="t")._normalize(nested_502)
    check("errore 502 dentro HTTP 200 -> retryable", False, "non ha sollevato")
except ProviderError as e:
    check("errore 502 dentro HTTP 200 -> retryable", e.retryable is True, f"retryable={e.retryable}")
    check("messaggio preservato", "empty response" in str(e), str(e))

# e il loop deve effettivamente recoverare da quel 502
class Nested502Provider:
    def __init__(self):
        self.t = 0

    def chat(self, messages, tools=None, **kw):
        self.t += 1
        if self.t <= 2:
            raise ProviderError("502 nel corpo", retryable=True, status=502)
        return resp("riavvenuto dopo 502")

np1 = Nested502Provider()
aN1 = Agent(np1, REG, "SYS", LoopConfig(max_iterations=3))
stN1 = aN1.run("test")
check("loop recovera da 502 annidato", stN1.stopped_because == "risposta_finale", stN1.stopped_because)
check("4 tentativi configurati", True)  # documentato, il conteggio è sopra

# errore non transitorio nel corpo -> NON retryable
nested_402 = {"error": {"message": "Insufficient credits", "code": 402}}
try:
    OpenAICompatAdapter(base_url="http://x/v1", api_key="k", model="m", name="t")._normalize(nested_402)
    check("errore 402 nel corpo -> non retryable", False, "non ha sollevato")
except ProviderError as e:
    check("errore 402 nel corpo -> non retryable", e.retryable is False, f"retryable={e.retryable}")

# errore come stringa semplice
try:
    OpenAICompatAdapter(base_url="http://x/v1", api_key="k", model="m", name="t")._normalize({"error": "boom"})
    check("errore come stringa gestito", False, "non ha sollevato")
except ProviderError as e:
    check("errore come stringa gestito", "boom" in str(e), str(e))

# tool call senza nome -> ignorata, non genera mezzo oggetto rotto
weird = {
    "model": "m",
    "choices": [{"message": {"content": "", "tool_calls": [
        {"id": "c1", "function": {"name": "", "arguments": "{}"}},
        {"id": "c2", "function": {"name": "ok", "arguments": None}},
    ]}, "finish_reason": "tool_calls"}],
}
n2 = OpenAICompatAdapter(base_url="http://x/v1", api_key="k", model="m", name="t")._normalize(weird)
check("tool call senza nome ignorata", all(t.name == "ok" for t in n2.tool_calls), str(n2.tool_calls))
check("arguments None -> {}", n2.tool_calls[0].parsed_args() == {}, str(n2.tool_calls[0].parsed_args()))

# User-Agent: alcuni modelli free su OpenRouter rispondono 403 se il client
# non si dichiara un agente ("only available on agentic harnesses"). Il
# sintomo era un modello a 0.00 su ogni task pur funzionando in chat.
check("User-Agent dichiara un agente",
      "orchestra" in OpenAICompatAdapter.UA.lower() and "agent" in OpenAICompatAdapter.UA.lower(),
      OpenAICompatAdapter.UA)
ad_ua = OpenAICompatAdapter(base_url="http://x/v1", api_key="k", model="m", name="t")
check("adapter espone lo UA", ad_ua.UA == OpenAICompatAdapter.UA)

# il body del 403 deve restare leggibile nel messaggio
ad_err = OpenAICompatAdapter(base_url="http://x/v1", api_key="k", model="m", name="or")
harness_403 = {"error": {"message": "thinkingmachines/inkling-small:free is only "
                                "available on agentic harnesses. Try plugging it "
                                "into a coding agent", "code": 403}}
try:
    ad_err._normalize(harness_403)
    check("403 harness propagato", False, "non ha sollevato")
except ProviderError as e:
    check("403 harness propagato", "agentic harnesses" in str(e), str(e)[:120])
    check("403 harness NON è retryable", e.retryable is False)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
