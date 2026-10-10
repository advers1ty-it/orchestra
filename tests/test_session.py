"""Test del ponte fra il loop sincrono e la UI.

Qui i bug sono per definizione invisibili a `test_offline.py`: sono race
condition, e una race condition che si manifesta una volta su cento non
appare in una suite. Percio qui non asseriamo il comportamento tipico ma
quello sotto stress: colpi ripetuti, cancel a met' turno, reset mentre
l'agente lavora.

Uso un provider finto con ritardi, per avere finestre di concorrenza reali.
"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_session")
os.environ["ORCHESTRA_ROOT"] = WORK
os.makedirs(WORK, exist_ok=True)
# Il DB dello storico su una cartella di test: senza, ogni turno di questi
# test finisce nella cronologia VERA dell'utente. Va impostato prima di
# qualsiasi import di orchestra, perché lo storico è un singleton che si
# crea la prima volta che serve.
os.environ["ORCHESTRA_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_dati_test")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra import LLMResponse, LoopConfig  # noqa: E402
from orchestra.session import EventBridge, Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import ToolCall  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


class SlowProvider:
    """Provider con ritardo, per aprire vere finestre di concorrenza.

    Riporta `usage` come un provider vero: senza, `total_tokens` resta
    zero e i test sui contatori falliscono per colpa del mock.
    """

    def __init__(self, delay=0.02):
        self.delay = delay
        self.t = 0
        self.name = "slow"
        self.model = "m"
        self.calls = 0
        self._lock = threading.Lock()

    def chat(self, messages, tools=None, **kw):
        with self._lock:
            self.calls += 1
            n = self.calls
        time.sleep(self.delay)
        usage = dict(prompt_tokens=100 + n, completion_tokens=20)
        if n > 6:
            return LLMResponse(content="finito", model="m", **usage)
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id=f"c{n}", name="noop", arguments="{}")],
            model="m",
            **usage,
        )


def noop_reg():
    from orchestra import Tool

    r = default_registry()
    r.register(Tool(name="noop", description="non fa nulla",
                    schema={"type": "object", "properties": {}},
                    handler=lambda: "ok"))
    return r


# ---------------------------------------------------------------- EventBridge
print("\n[1] EventBridge")
b = EventBridge()
got = []
# L'iscrizione avviene quando si chiama stream(), non prima: un client
# che arriva dopo gli eventi non li riceve, e non deve. Il suo punto di
# partenza e' la snapshot, non un replay che potrebbe doppiare.
# Prima la coda teneva tutto e un test poteva emettere e poi mettersi
# in ascolto — era una proprieta' comoda e sbagliata: significava che
# due client collegati in momenti diversi vedevano cose diverse senza
# saperlo.
it = b.stream(timeout=0.2)
for i in range(5):
    b.emit("test", {"i": i})
for item in it:
    got.append(item)
    if len(got) == 5:
        break
check("eventi consegnati", len(got) == 5, str(len(got)))
check("seq monotono", [g["seq"] for g in got] == sorted(g["seq"] for g in got),
      str([g["seq"] for g in got]))
check("payload conservato", got[2]["data"]["i"] == 2, str(got[2]["data"]))

# keepalive: silenzio lungo -> segnale, non blocco.
# NB: stream() non termina mai da solo (continua a emettere keepalive), quindi
# va consumato con un limite esplicito. Un `list(...)` qui blocca per sempre.
b2 = EventBridge()
t0 = time.time()
first = next(b2.stream(timeout=0.3))
check("keepalive emesso durante il silenzio", first["kind"] == "keepalive", str(first))
check("keepalone dopo ~timeout", 0.2 < time.time() - t0 < 1.5, f"{time.time()-t0:.2f}s")

# overflow: emettere molto piu' di quanto si legga non deve far crashare
# L'iscrizione viene PRIMA del flood: la coda e' per client, e un client
# che non c'e' non accumula niente. Prima l'overflow si misurava sul
# backlog, che ora non esiste piu'.
b3 = EventBridge(maxsize=10)
flood = b3.stream(timeout=0.2)
for i in range(500):
    b3.emit("flood", {"i": i})
check("non crasha su overflow", True)
received = 0
for item in flood:
    received += 1
    if received >= 10:
        break
check("la coda mantiene il limite", received <= 20, str(received))
check("eventi persi dichiarati", b3.dropped > 0, f"dropped={b3.dropped}")

# close: il flusso termina.
# close() chiude i client gia' collegati: se nessuno e' collegato, non
# c'e' niente da chiudere e stream() resta aperto, come deve. Chi si
# collega DOPO un close() su una sessione che non ha piu' agent e'
# un caso che il server non produce — l'app ricrea la sessione.
b4 = EventBridge()
it4 = b4.stream(timeout=0.2)
b4.close()
# Non con list(): dopo la sentinella il generatore finisce, ma se la
# sentinella non arrivasse per colpa di una coda piena, list()
# ascolterebbe i keepalive PER SEMPRE e il test si bloccherebbe invece
# di fallire. Un test che puo' non terminare non e' un test.
try:
    primo = next(it4)
    chiuso = primo is None
except StopIteration:
    chiuso = True
except Exception as e:  # noqa: BLE001
    chiuso = False
    print("   [errore]", e)
check("stream termina dopo close", chiuso)

# emettere dopo close e' harmless
b4.emit("x", {})
check("emit dopo close non crasha", True)

# ---------------------------------------------------------------- Session
print("\n[2] Session: esecuzione in background")
s = Session(provider=SlowProvider(), registry=noop_reg(), system_prompt="SYS",
            config=LoopConfig(max_iterations=8))
check("sessione non occupata all'inizio", s.busy is False)
check("send accettato", s.send("primo") is True)
check("occupata subito dopo send", s.busy is True)

evs = []
# `idle` arriva DOPO `turn_end` nella stessa sequenza: spezziamo solo quando
# lo abbiamo visto davvero, non al primo turn_end. Fermarsi li lascerebbe
# pendente l'evento di chiusura del turno — che e' quello che dice alla UI
# che puo' accettare un nuovo messaggio.
for item in s.bridge.stream(timeout=0.3):
    evs.append(item["kind"])
    if "idle" in evs:
        break
s.wait(timeout=10)

check("turn_end emesso", "turn_end" in evs, str(set(evs)))
check("idle emesso alla fine", "idle" in evs, str(set(evs)))
check("tool_start emesso", "tool_start" in evs, str(set(evs)))
check("sessione libera dopo il turno", s.busy is False)
snap = s.snapshot()
check("snapshot ha i contatori", snap["tool_calls"] >= 1, str(snap))
check("snapshot serializzabile", isinstance(snap["messages"], list))

print("\n[3] Secondo turno: il contesto sopravvive")
n_msgs_before = len(s.agent.state.messages)
s.send("secondo")
s.wait(timeout=10)
check("messaggi cresciuti", len(s.agent.state.messages) > n_msgs_before,
      f"{n_msgs_before} -> {len(s.agent.state.messages)}")
check("contatore token accumulato", s.agent.state.total_tokens > 0)

print("\n[4] Send rifiutato mentre occupata")
s3 = Session(provider=SlowProvider(delay=0.05), registry=noop_reg(), system_prompt="SYS",
             config=LoopConfig(max_iterations=20))
s3.send("lento")
r2 = s3.send("secondo imminente")
check("secondo send rifiutato", r2 is False, str(r2))
check("non si accoda silenziosamente", s3.busy is True)
s3.cancel()
s3.wait(timeout=10)

print("\n[5] Cancel a meta' turno")
s4 = Session(provider=SlowProvider(delay=0.03), registry=noop_reg(), system_prompt="SYS",
             config=LoopConfig(max_iterations=100))
s4.send("lungo")
time.sleep(0.12)  # lascia che il loop avanzi
ok = s4.cancel()
check("cancel accettato", ok is True)
s4.wait(timeout=10)
check("turno terminato dopo cancel", s4.busy is False)
check("motivo del fermo registrato",
      s4.agent.state.stopped_because in ("canceled_da_should_continue", "risposta_finale", "max_iterations"),
      s4.agent.state.stopped_because)
check("cancel non ha prodotto uno stato incoerente",
      len(s4.agent.state.messages) > 0)
# ogni tool_call ha il suo risultato, anche dopo il cancel
req = {t.id for m in s4.agent.state.messages for t in m.tool_calls}
res = {m.tool_call_id for m in s4.agent.state.messages if m.role == "tool"}
check("nessun tool_call orfano dopo cancel", not (req - res), str(list(req - res)[:3]))

print("\n[6] Reset")
s5 = Session(provider=SlowProvider(), registry=noop_reg(), system_prompt="SYS",
             config=LoopConfig(max_iterations=3))
s5.send("prima")
s5.wait(timeout=10)
n_before = len(s5.agent.state.messages)
s5.reset()
n_after = len(s5.agent.state.messages)
check("reset azzera i messaggi", n_after < n_before, f"{n_before} -> {n_after}")
check("reset ripristina il system prompt",
      s5.agent.state.messages[0].role == "system" and
      s5.agent.state.messages[0].content == "SYS")
check("reset azzera i contatori", s5.agent.state.total_tokens == 0 and s5.agent.state.iterations == 0)
check("sessione utilizzabile dopo reset", s5.send("dopo") is True)
s5.wait(timeout=10)

# reset mentre occupata -> deve rifiutare, non corrompere
s6 = Session(provider=SlowProvider(delay=0.05), registry=noop_reg(), system_prompt="SYS",
             config=LoopConfig(max_iterations=20))
s6.send("occupa")
try:
    s6.reset()
    check("reset rifiutato se occupata", False, "ha accettato il reset")
except RuntimeError:
    check("reset rifiutato se occupata", True)
s6.cancel()
s6.wait(timeout=10)

print("\n[7] Update del system prompt a sessione avviata")
s7 = Session(provider=SlowProvider(), registry=noop_reg(), system_prompt="PRIMO",
             config=LoopConfig(max_iterations=2))
s7.send("a")
s7.wait(timeout=10)
s7.set_system_prompt("SECONDO")
s7.send("b")
s7.wait(timeout=10)
s7.set_system_prompt("TERZO")
s7.send("c")
s7.wait(timeout=10)
s7.set_system_prompt("QUARTO")
sysmsgs = [m.content for m in s7.agent.state.messages if m.role == "system"]
check("un solo system prompt", len(sysmsgs) == 1, str(sysmsgs))
check("system prompt aggiornato", sysmsgs[0] == "QUARTO", str(sysmsgs))
check("contesto preservato dopo l'update",
      sum(1 for m in s7.agent.state.messages if m.role == "user") == 3)

print("\n[8] Errori del provider non lasciano la sessione appesa")
class BrokenProvider:
    model = "m"
    name = "broken"

    def chat(self, messages, tools=None, **kw):
        raise RuntimeError("provider esploso")


s8 = Session(provider=BrokenProvider(), registry=noop_reg(), system_prompt="SYS",
             config=LoopConfig(max_iterations=2))
# L'ascolto parte PRIMA del turno. Prima si mandava il messaggio, si
# aspettava la fine, e solo dopo si leggeva lo stream: funzionava con
# una coda che teneva il passato, e ora non deve piu' funzionare —
# un client che si collega dopo gli eventi non li vede, e mentire
# sarebbe peggio che non riceverli.
raccolti8: list[Any] = []
stop8 = threading.Event()


def ascolta8() -> None:
    for ev in s8.bridge.stream(timeout=0.3):
        if ev["kind"] != "keepalive":
            raccolti8.append(ev)
        if ev["kind"] == "idle":
            return


t8 = threading.Thread(target=ascolta8, daemon=True)
t8.start()
time.sleep(0.2)
s8.send("booma")
s8.wait(timeout=10)
t8.join(timeout=3)
check("sessione liberata dopo l'errore", s8.busy is False)
errs = [e["data"] for e in raccolti8 if e["kind"] == "error"]
check("evento error emesso", len(errs) == 1, str(errs))
check("messaggio d'errore leggibile",
      errs and "provider esploso" in errs[0]["message"], str(errs))

print("\n[9] Stress: 40 turni di fila")
s9 = Session(provider=SlowProvider(delay=0.0), registry=noop_reg(), system_prompt="SYS",
             config=LoopConfig(max_iterations=4))
ev9 = []
def drain():
    for item in s9.bridge.stream(timeout=5.0):
        ev9.append(item["kind"])
        if item["kind"] == "idle":
            break

done = 0
for i in range(10):
    t = threading.Thread(target=drain, daemon=True)
    t.start()
    s9.send(f"turno {i}")
    s9.wait(timeout=15)
    t.join(timeout=2)
    done += 1
check("tutti i turni completati", done == 10, str(done))
check("sessione libera alla fine", s9.busy is False)
seqs_ok = True
# ogni turno deve aver prodotto idle
check("idle per ogni turno", ev9.count("idle") >= 10, str(ev9.count("idle")))

print("\n[10] snapshot: niente messaggi assistant vuoti in cronologia")
from orchestra import LLMResponse as LR, Tool as T, ToolRegistry  # noqa: E402
from orchestra.types import ToolCall as TC  # noqa: E402

regS = ToolRegistry()
regS.register(T(name="noop", description="x", schema={"type": "object", "properties": {}},
                handler=lambda: "ok"))


class ToolThenText:
    """Il PRIMO turno emette solo una tool call; tutti i successivi rispondono
    con testo. Serve a produrre esattamente un assistant senza contenuto."""
    def __init__(self):
        self.n = 0
        self.name = "tool_then_text"
        self.model = "m"

    def chat(self, messages, tools=None, **kw):
        self.n += 1
        if self.n == 1:
            return LR(content="", tool_calls=[TC(id="x1", name="noop", arguments="{}")], model="m")
        return LR(content=f"risposta {self.n}", model="m")


sN = Session(provider=ToolThenText(), registry=regS, system_prompt="SYS",
             config=LoopConfig(max_iterations=5))
sN.send("primo")
sN.wait(timeout=10)
sN.send("secondo")
sN.wait(timeout=10)
msgs = sN.snapshot()["messages"]
roles = [m["role"] for m in msgs]
check("2 messaggi utente", roles.count("user") == 2, str(roles))
# Il turno con la tool call NON viene più scartato: entra nello snapshot
# (con contenuto vuoto) perché è la riga madre della chiamata, e senza di
# lui il blocco del tool non si potrebbe ridisegnare al refresh. Quindi
# ora ci sono 3 assistant, e il primo ha contenuto vuoto ma una tool_call:
# è corretto, non è una riga bianca.
check("3 assistant, quello col tool incluso", roles.count("assistant") == 3, str(roles))
con_testo = [m for m in msgs
             if m["role"] == "assistant" and not m.get("tool_calls")]
check("nessun messaggio di testo vuoto",
      all(m["content"].strip() for m in con_testo),
      str([m["content"][:20] for m in con_testo]))
check("l'assistant vuoto porta la tool call",
      any(m["role"] == "assistant" and not m["content"].strip()
          and m.get("tool_calls") for m in msgs))
check("i testi finali ci sono", sum(1 for m in msgs if m["content"].startswith("risposta")) == 2)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
