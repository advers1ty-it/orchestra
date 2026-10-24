"""Test offline: tool, compaction, invarianti. Non chiamano l'API.

Un mock provider per provare il loop deterministico — se il loop funziona
qui, quando funziona con un provider vero è il provider che decide.
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ORCHESTRA_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import (  # noqa: E402
    Agent, LoopConfig, Message, ToolRegistry, ToolCall, LLMResponse,
    count_tokens, fit_context, compact_tools, default_registry,
)
from orchestra.types import Tool  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------------------------------------------------------------- TOOL
print("\n[1] Tool e sicurezza")
r = default_registry()
# Non un numero: "5 tool" era giusto fino a quando ho aggiunto le
# skill, e allora il test ha iniziato a segnalare come difetto una
# cosa che era un miglioramento. Il punto che voleva verificare e'
# un altro — che ci sia la base, non quanta ce n'e'.
BASE = {"read_file", "write_file", "list_dir", "run_shell", "calculate"}
check("la base dei tool c'e' tutta", BASE.issubset(set(r.all_names())),
      f"mancano: {sorted(BASE - set(r.all_names()))}")
check("ogni tool ha una descrizione",
      all(len(t.description) > 20 for t in r.active),
      "una descrizione vuota o troppo corta non dice al modello quando usarlo")
check("read_file dichiara path required",
      r.get("read_file").schema["required"] == ["path"])

# path traversal: la guardia solleva (fail loud) invece di leggere fuori dal root
try:
    r.get("read_file").handler(path="../../../Windows/System32/drivers/etc/hosts")
    check("read_file blocca il traversal", False, "NON ha sollevato: ha letto fuori dal root!")
except ValueError as e:
    check("read_file blocca il traversal", "root consentito" in str(e), str(e))

# calculate: solo aritmetica
calc = r.get("calculate").handler
check("calcola (3+4)*2", calc(expression="(3+4)*2") == "14", calc(expression="(3+4)*2"))
check("rifiuta __import__", "ERRORE" in calc(expression="__import__('os').system('dir')"))
check("rifiuta attributi", "ERRORE" in calc(expression="().__class__"))

# scrittura e rilettura
res = r.get("write_file").handler(path="_test_probe.txt", content="riga1\nriga2\n")
check("write_file scrive", "creato" in res, res)
back = r.get("read_file").handler(path="_test_probe.txt")
check("read_file rilegge", "riga1" in back and "riga2" in back)
r.get("write_file").handler(path="_test_err.txt", content="x")
check("read_file su file esistente segnala aggiornato",
      "aggiornato" in r.get("write_file").handler(path="_test_err.txt", content="y"))

# ---------------------------------------------------------------- COMPACTION
print("\n[2] Compaction")
msgs = [Message(role="system", content="SYSTEM")]
msgs.append(Message(role="user", content="obiettivo: costruisci X"))
for i in range(20):
    msgs.append(Message(role="assistant", content=f"risposta lunga numero {i} " + "x" * 400))
    msgs.append(Message(role="tool", content=f"risultato tool {i} " + "y" * 2000))

before = count_tokens(msgs)
pruned = compact_tools(msgs, keep_recent=6)
after = count_tokens(msgs)
check("compact_tools pota qualcosa", pruned > 0, f"pruned={pruned}")
check("compaction riduce i token", after < before, f"{before} -> {after}")

# keep_recent è in MESSI, non in turni: gli ultimi 6 messaggi devono
# conservare il contenuto pieno, i precedenti devono essere potati.
recent = msgs[-6:]
old = msgs[:-6]
check("ultimi 6 messaggi non potati",
      all("y" * 2000 in m.content for m in recent if m.role == "tool"),
      "un tool recente è stato potato per errore")
check("messaggi vecchi potati",
      all("y" * 2000 not in m.content for m in old if m.role == "tool"),
      "un tool vecchio non è stato potato")
check("il segnaposto conserva l'inizio del risultato",
      any("potato" in m.content and m.content.count("\n") >= 1
          for m in old if m.role == "tool"),
      "il potatura ha perso anche la testa del risultato")

# invariant 3: gli ultimi keep_recent non si toccano MAI
msgs2 = [Message(role="system", content="S"), Message(role="user", content="primo")]
for i in range(15):
    msgs2.append(Message(role="tool", content="POTATO" if i < 9 else "GIOVANE-" + str(i)))
compact_tools(msgs2, keep_recent=4)
check("ultimi messaggi intatti", all(m.content.startswith("GIOVANE") for m in msgs2[-4:]))

# il system prompt non viene mai perso
from orchestra.context import compact_history
msgs3 = [Message(role="system", content="SYS-PROTECT")]
msgs3.append(Message(role="user", content="PRIMO-OBIETTIVO"))
for i in range(15):
    msgs3.append(Message(role="user", content=f"u{i} " + "z" * 300))
    msgs3.append(Message(role="assistant", content=f"a{i} " + "z" * 300))
n = compact_history(msgs3, keep_recent=4)
check("compact_history unisce turni", n > 0, f"merged={n}")
check("system prompt preservato", any(m.role == "system" and m.content == "SYS-PROTECT" for m in msgs3))
check("primo obiettivo preservato", any("PRIMO-OBIETTIVO" in m.content for m in msgs3))
check("riepilogo presente", any("RIEPILOGO" in m.content for m in msgs3))

# report di fit_context
rep = fit_context(msgs, limit=1000, keep_recent=6)
check("fit_context ritorna un report", set(rep) >= {"tokens_before", "tools_pruned", "history_merged"}, str(rep))
check("fit_context scende sotto il limite", rep["tokens_after"] <= 1000 or rep["history_merged"] > 0, str(rep))

# ---------------------------------------------------------------- MOCK PROVIDER
print("\n[3] Loop con provider finto")

class FakeProvider:
    """Provider a script: restituisce risposte in sequenza e registra le richieste."""

    def __init__(self, script: list[LLMResponse], name: str = "fake"):
        self.script, self.i, self.calls, self.name = script, 0, [], name
        self.model = "fake-1"

    def chat(self, messages, tools=None, **kw):
        self.calls.append({"messages": [m.to_api() for m in messages], "tools": tools})
        if self.i >= len(self.script):
            return self.script[-1]
        r = self.script[self.i]; self.i += 1; return r

def resp(content="", calls=None, model="fake-1", pt=10, ct=5):
    return LLMResponse(content=content, tool_calls=calls or [], model=model,
                       prompt_tokens=pt, completion_tokens=ct)

def tcid(n): return f"call_{n}"

# caso A: una tool call poi risposta finale
reg = ToolRegistry()
reg.register(Tool(name="echo", description="ripete", schema={"type": "object", "properties": {"t": {"type": "string"}}, "required": ["t"]}, handler=lambda t: f"ECHO:{t}"))
prov = FakeProvider([
    resp("Provo lo strumento", [ToolCall(id=tcid(1), name="echo", arguments='{"t":"ciao"}')]),
    resp("Ho detto ciao"),
])
a = Agent(prov, reg, "SYS", LoopConfig(max_iterations=5))
st = a.run("saluta")
check("loop termina con risposta finale", st.stopped_because == "risposta_finale", st.stopped_because)
check("risposta finale corretta", a.final_text() == "Ho detto ciao", a.final_text())
check("tool chiamato una volta", st.tool_calls_made == 1)
tool_msgs = [m for m in st.messages if m.role == "tool"]
check("risultato tool presente", len(tool_msgs) == 1 and "ECHO:ciao" in tool_msgs[0].content)
check("risultato tool ha tool_call_id", bool(tool_msgs[0].tool_call_id))
check("2 iterazioni", st.iterations == 2, str(st.iterations))
check("schema tool passato al provider", prov.calls[0]["tools"][0]["function"]["name"] == "echo")

# caso B: tool che solleva -> il loop deve RECUPERARE, non morire
def boom():
    raise RuntimeError("esplosione controllata")
reg2 = ToolRegistry()
reg2.register(Tool(name="boom", description="fallisce", schema={"type": "object", "properties": {}}, handler=boom))
prov2 = FakeProvider([
    resp("", [ToolCall(id=tcid(2), name="boom", arguments="{}")]),
    resp("Ho gestito l'errore"),
])
a2 = Agent(prov2, reg2, "SYS", LoopConfig(max_iterations=5))
st2 = a2.run("prova")
check("loop sopravvive a un tool che crasha", st2.stopped_because == "risposta_finale", st2.stopped_because)
err_msg = [m for m in st2.messages if m.role == "tool"][0].content
check("errore riportato come contenuto", "esplosione controllata" in err_msg, err_msg[:100])
check("conteggio errori aggiornato", st2.tool_errors == 1)
check("modello ha potuto recuperare", a2.final_text() == "Ho gestito l'errore")

# caso C: invariant 2 — ogni tool_call riceve SEMPRE un risultato
reg3 = ToolRegistry()
reg3.register(Tool(name="e1", description="x", schema={"type": "object", "properties": {}}, handler=lambda: "1"))
reg3.register(Tool(name="e2", description="x", schema={"type": "object", "properties": {}}, handler=lambda: "2"))
prov3 = FakeProvider([
    resp("", [ToolCall(id=tcid(3), name="e1", arguments="{}"), ToolCall(id=tcid(4), name="e2", arguments="{}")]),
    resp("fatto"),
])
a3 = Agent(prov3, reg3, "SYS", LoopConfig(max_iterations=4))
st3 = a3.run("due tool in parallelo")
results = [m for m in st3.messages if m.role == "tool"]
check("2 tool call -> 2 risultati", len(results) == 2, str(len(results)))
ids = {m.tool_call_id for m in results}
check("ogni tool_call_id coperto", ids == {tcid(3), tcid(4)}, str(ids))

# caso D: invariant 1 — tool inesistente
prov4 = FakeProvider([
    resp("", [ToolCall(id=tcid(5), name="fantasma", arguments="{}")]),
    resp("ok"),
])
a4 = Agent(prov4, reg3, "SYS", LoopConfig(max_iterations=4))
st4 = a4.run("tool inesistente")
r4 = [m for m in st4.messages if m.role == "tool"][0].content
check("tool inesistente non crasha", "inesistente" in r4, r4[:120])

# caso E: argomenti malformati
prov5 = FakeProvider([
    resp("", [ToolCall(id=tcid(6), name="echo2", arguments="{non json")]),
    resp("ok"),
])
reg5 = ToolRegistry()
reg5.register(Tool(name="echo2", description="x", schema={"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}, handler=lambda a: f"got {a}"))
a5 = Agent(prov5, reg5, "SYS", LoopConfig(max_iterations=4))
st5 = a5.run("json rotto")
check("JSON malformato non crasha", st5.stopped_because == "risposta_finale", st5.stopped_because)
r5 = [m for m in st5.messages if m.role == "tool"][0].content
check("JSON malformato: errore chiaro e tool non eseguito",
      "JSON" in r5 and "non e' valido" in r5 and "_raw" not in r5, r5)

# caso F: max_iterations
class LoopForever(FakeProvider):
    def chat(self, messages, tools=None, **kw):
        return resp("", [ToolCall(id=tcid(99), name="echo", arguments='{"t":"x"}')])
a6 = Agent(LoopForever([]), reg, "SYS", LoopConfig(max_iterations=3))
st6 = a6.run("infinito")
check("max_iterations rispetta", st6.stopped_because == "max_iterations" and st6.iterations == 3, f"{st6.stopped_because}/{st6.iterations}")

# caso G: cancel esterno
calls = {"n": 0}
def stopper(state):
    calls["n"] += 1
    return state.iterations < 2
prov7 = FakeProvider([resp("", [ToolCall(id=tcid(7), name="echo", arguments='{"t":"y"}')]), resp("finale")])
a7 = Agent(prov7, reg, "SYS", LoopConfig(max_iterations=10))
st7 = a7.run("task lungo", should_continue=stopper)
check("cancel esterno funziona", st7.stopped_because == "canceled_da_should_continue", st7.stopped_because)

# caso H: max_consecutive_errors
def always_fail(): raise RuntimeError("sempre")
reg8 = ToolRegistry()
reg8.register(Tool(name="af", description="x", schema={"type": "object", "properties": {}}, handler=always_fail))
class RetryForever(FakeProvider):
    def chat(self, messages, tools=None, **kw):
        return resp("", [ToolCall(id=tcid(8), name="af", arguments="{}")])
a8 = Agent(RetryForever([]), reg8, "SYS", LoopConfig(max_iterations=10, max_consecutive_errors=3))
st8 = a8.run("fallisce sempre")
check("si ferma dopo N errori consecutivi", st8.stopped_because == "troppi_errori_consecutivi", st8.stopped_because)

# caso I: conteggio token
check("conta token su testo", count_tokens([Message(role="user", content="a"*360)]) > 90)
check("contesto vuoto = 0 token", count_tokens([]) == 0)

# caso J: la guardia di sicurezza vista dal loop deve tornare al modello
# come contenuto recuperabile, non come crash. E' la catena completa.
reg9 = default_registry()
prov9 = FakeProvider([
    resp("", [ToolCall(id=tcid(10), name="read_file", arguments='{"path":"../../../Windows/System32/drivers/etc/hosts"}')]),
    resp("Ho capito che sono fuori dal root."),
])
a9 = Agent(prov9, reg9, "SYS", LoopConfig(max_iterations=4))
st9 = a9.run("leggi un file di sistema")
res9 = [m for m in st9.messages if m.role == "tool"]
check("traversal gestito senza crash dal loop", st9.stopped_because == "risposta_finale", st9.stopped_because)
check("errore di sicurezza riportato al modello",
      len(res9) == 1 and "root consentito" in res9[0].content, res9[0].content[:150] if res9 else "nessun risultato")
check("nessun contenuto di sistema trapelato",
      len(res9) == 1 and "127.0.0.1" not in res9[0].content)

# caso K: il callback on_event non deve mai crashare il loop.
# Regressione: `_emit("compaction", report)` passava il dict come argomento
# posizionale e rompeva con TypeError appena la compazione scattava — i test
# offline non lo prendevano perché usavano il callback di default (no-op).
print("\n[4] Callback eventi")
EVENTS = []


def collect(kind, data):
    EVENTS.append((kind, data))


provK = FakeProvider([resp("prima"), resp("dopo")])
aK = Agent(provK, reg, "SYS", LoopConfig(max_iterations=3), on_event=collect)
stK = aK.run("test callback")
check("on_event riceve gli eventi", len(EVENTS) > 0, str(len(EVENTS)))
check("tutti gli eventi hanno un dict", all(isinstance(d, dict) for _, d in EVENTS))
check("chiavi attese presenti", any(k == "user_message" for k, _ in EVENTS), str({k for k, _ in EVENTS}))
check("loop non crasha con callback attivo", stK.stopped_because == "risposta_finale", stK.stopped_because)

# e specificamente sulla compazione, che era il path rotto
EVENTS.clear()
big_reg = ToolRegistry()
# args diverse ("n": turno) per non innescare l'anti-gira-a-vuoto, che
# becca la stessa identica chiamata; l'handler accetta **kw e ignora n.
big_reg.register(Tool(name="big", description="x", schema={"type": "object", "properties": {"n": {"type": "integer"}}},
                      handler=lambda **kw: "dato " + ("z" * 6000)))


class Chatty2(FakeProvider):
    def __init__(self):
        super().__init__([], name="chatty2")
        self.t = 0

    def chat(self, messages, tools=None, **kw):
        self.t += 1
        if self.t > 30:
            return resp("finito")
        return resp("", [ToolCall(id=tcid(self.t), name="big", arguments='{"n": %d}' % self.t)])


aK2 = Agent(Chatty2(), big_reg, "SYS", LoopConfig(max_iterations=30, context_limit=30_000, keep_recent=6),
            on_event=collect)
stK2 = aK2.run("carico")
check("compaction emette l'evento", any(k == "compaction" for k, _ in EVENTS),
      str({k for k, _ in EVENTS}))
check("compaction: evento col suo dizionario",
      any(k == "compaction" and "tokens_before" in d for k, d in EVENTS))

# pulizia
for f in ["_test_probe.txt", "_test_err.txt"]:
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f)
    if os.path.exists(p): os.remove(p)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
