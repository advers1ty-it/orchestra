"""Il ragionamento deve fare il giro intero: arriva, si conserva, torna.

Beam 1.0 ragiona SEMPRE e richiede `reasoning_content` indietro nei turni
successivi: senza quel campo risponde 400 missing_required_parameter e i
tool call si fermano al secondo giro. Il ragionamento arriva in tre forme
distinte a seconda del gateway:

  - `reasoning`          (OpenRouter)
  - `reasoning_content`  (Reflection/DeepSeek)
  - `reasoning_details`  (gateway che lo mandano come lista)

Questo test non parla con nessun provider: costruisce le risposte a mano e
controlla che il campo sopravviva dalla risposta grezza al payload che
l'agente reinvoca.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["ORCHESTRA_ROOT"] = ROOT

from orchestra.agent import Agent, LoopConfig
from orchestra.providers import OpenAICompatAdapter
from orchestra.tools import default_registry
from orchestra.types import LLMResponse, Message, ToolCall


def _risposta_grezza(reasoning_key, ragionamento, con_tool=False):
    """Una risposta grezza come la manda un gateway.

    `reasoning_key` dice in quale campo viaggia il ragionamento, così si
    possono provare tutti e tre i formati senza un provider vero.
    """
    msg = {"role": "assistant", "content": "fatto"}
    if ragionamento:
        msg[reasoning_key] = ragionamento
    calls = []
    if con_tool:
        msg["tool_calls"] = [{
            "id": "call_1", "type": "function",
            "function": {"name": "leggi_file", "arguments": '{"path": "a.txt"}'},
        }]
        calls.append(ToolCall(id="call_1", name="leggi_file",
                              arguments='{"path": "a.txt"}'))
    return {
        "choices": [{"message": msg, "finish_reason": "tool_calls" if con_tool else "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }, calls


def _adapter():
    """Un adapter senza rete: serve solo per chiamare `_normalize`."""
    return OpenAICompatAdapter(base_url="http://127.0.0.1:1",
                               api_key="", model="fake/modello", name="fake")


def test_reasoning_content_letto():
    """`reasoning_content` (Reflection/Beam) viene letto e non perso."""
    dati, _ = _risposta_grezza("reasoning_content", "Penso: chiamo il tool.")
    risp = _adapter()._normalize(dati)
    assert risp.reasoning == "Penso: chiamo il tool.", (
        f"reasoning_content non letto: {risp.reasoning!r}"
    )


def test_reasoning_tre_formati():
    """Tutti e tre i campi in cui un gateway puo' mandarlo."""
    for chiave, valore in (
        ("reasoning", "A"),
        ("reasoning_content", "B"),
        ("reasoning_details", [{"text": "C", "summary": ""}]),
    ):
        dati, _ = _risposta_grezza(chiave, valore)
        risp = _adapter()._normalize(dati)
        assert risp.reasoning, f"formato {chiave} non riconosciuto"


def test_message_rimanda_reasoning_solo_assistant():
    """`reasoning_content` va rimandato solo negli assistant non vuoti.

    Un `reasoning_content: ""` manda in 400 i gateway che non lo
    conoscono, e nei messaggi tool/user non ha senso: ci sta solo dove il
    modello ha ragionato.
    """
    con = Message(role="assistant", content="x", reasoning="pensato")
    assert con.to_api()["reasoning_content"] == "pensato"

    vuoto = Message(role="assistant", content="x", reasoning="")
    assert "reasoning_content" not in vuoto.to_api(), (
        "un campo vuoto non va mai inviato"
    )

    tool = Message(role="tool", content="x", tool_call_id="t1",
                   reasoning="pensato")
    assert "reasoning_content" not in tool.to_api(), (
        "il ragionamento non appartiene ai messaggi tool"
    )


def test_giro_agente_conserva_reasoning():
    """Il ragionamento sopravvive al giro: la richiesta successiva lo ha."""
    reg = default_registry()

    class Provider:
        name = "fake"
        model = "fake/modello"

        def __init__(self):
            self.chiamate = 0

        def chat(self, messages, tools=None, **kw):
            self.chiamate += 1
            if self.chiamate == 1:
                return LLMResponse(
                    content="Chiamo il tool.",
                    tool_calls=[ToolCall(id="call_1", name="leggi_file",
                                         arguments='{"path": "a.txt"}')],
                    reasoning="Prima ragiono, poi chiamo.",
                    model=self.model,
                )
            return LLMResponse(content="fatto", model=self.model,
                               reasoning="Ora concludo.")

    ag = Agent(Provider(), reg, "test", LoopConfig(max_iterations=4))
    ag.run("leggi a.txt")

    payload = [m.to_api() for m in ag.state.messages]
    assistant = [m for m in payload if m.get("role") == "assistant"]
    assert assistant, "manca il messaggio assistant"
    assert any(m.get("reasoning_content") for m in assistant), (
        f"il ragionamento non torna nella richiesta successiva: {payload!r}"
    )


# --------------------------------------------------------------------------
# End-to-end: un gateway che si comporta come Beam 1.0
# --------------------------------------------------------------------------

class _Beam:
    """Un gateway che ragiona sempre e richiede il ragionamento indietro.

    Risponde in STREAMING (l'agente usa `chat_stream`), manda il
    ragionamento in `reasoning_content` e al secondo turno risponde 400 se
    l'assistant non lo rimanda. E' il comportamento documentato di Beam.
    """

    porta = 8795
    viste: list = []

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_POST(self):
            corpo = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length") or 0)))
            _Beam.viste.append(corpo)
            ultimo_con_tool = None
            for m in corpo.get("messages") or []:
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    ultimo_con_tool = m

            if len(_Beam.viste) == 1:
                pezzi = [
                    {"choices": [{"delta": {"reasoning_content": "Devo "}}]},
                    {"choices": [{"delta": {"reasoning_content": "guardare."}}]},
                    {"choices": [{"delta": {"content": "Chiamo il tool."}}]},
                    {"choices": [{"delta": {"tool_calls": [
                        {"index": 0, "id": "call_1", "type": "function",
                         "function": {"name": "calculate",
                                      "arguments": "{\"expression\": "}}]}}]},
                    {"choices": [{"delta": {"tool_calls": [
                        {"index": 0, "function": {"arguments": "\"2+2\"}"}}]}}]},
                    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
                ]
            else:
                if not (ultimo_con_tool or {}).get("reasoning_content"):
                    out = json.dumps({"error": {"message":
                        "Missing required parameter: "
                        "messages[].reasoning_content"}}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(out)))
                    self.end_headers(); self.wfile.write(out)
                    return
                pezzi = [
                    {"choices": [{"delta": {"reasoning_content": "Concludo."}}]},
                    {"choices": [{"delta": {"content": "Il risultato e' 4."}}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                ]

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for p in pezzi:
                self.wfile.write(b"data: " + json.dumps(p).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

    @classmethod
    def avvia(cls):
        cls.viste = []
        srv = HTTPServer(("127.0.0.1", cls.porta), cls._Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv


def test_beam_roundtrip_end_to_end():
    """Beam 1.0: ragiona, chiama il tool, torna a casa.

    Senza la rimandazione del ragionamento questo test muore con 400 al
    secondo turno: e' esattamente il guasto che si vedeva — il modello
    sembrava non usare mai gli strumenti.
    """
    _Beam.avvia()
    prov = OpenAICompatAdapter(
        base_url=f"http://127.0.0.1:{_Beam.porta}", api_key="x",
        model="reflection/beam-1.0-501b-a23b", name="beam-sim")
    ag = Agent(prov, default_registry(), "test", LoopConfig(max_iterations=5))
    st = ag.run("quanto fa 2+2")

    assert len(_Beam.viste) >= 2, (
        f"il ciclo si e' fermato dopo {len(_Beam.viste)} chiamate: "
        f"{st.stopped_because}"
    )
    assert st.stopped_because == "risposta_finale", st.stopped_because
    assistant = [m for m in st.messages if m.role == "assistant"]
    con_ragionamento = [m for m in assistant if m.reasoning]
    assert con_ragionamento, "il ragionamento non e' stato conservato"
    assert any(m.tool_calls for m in assistant), "nessun tool call"
    # La richiesta successiva porta il ragionamento indietro.
    seconda = [m.to_api() for m in st.messages]
    assert any(m.get("reasoning_content") for m in seconda), (
        "il ragionamento non torna nella richiesta successiva"
    )
