"""Beam 1.0: il ragionamento deve fare il giro intero, e basta dove serve.

Beam ragiona SEMPRE e il suo chat template vuole il ragionamento indietro
negli assistant della storia: senza risponde 400 missing_required_parameter
e i tool call sembrano non funzionare mai. Il campo si chiama
`reasoning_content`, e va rimandato solo dove il modello ha ragionato.

Questi test usano gateway simulati che si comportano come il documento
ufficiale ("Beam Harmony format"), non un provider vero.
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
from orchestra.types import Message


def _errore(handler, msg):
    out = json.dumps({"error": {"message": msg}}).encode()
    handler.send_response(400)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(out)))
    handler.end_headers()
    handler.wfile.write(out)


def _gateway(porta, *, esigente=False, rifiuta_fuori_assistant=False):
    """Un gateway Beam-like in streaming. Torna (server, richieste viste).

    `esigente`       — chiede il ragionamento su OGNI assistant, anche i finali
    `rifiuta_fuori_assistant` — rifiuta `reasoning_content` fuori dagli assistant
    """
    viste = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_POST(self):
            corpo = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length") or 0)))
            viste.append(corpo)

            for m in corpo.get("messages") or []:
                if m.get("role") != "assistant" and m.get("reasoning_content"):
                    if rifiuta_fuori_assistant:
                        return _errore(
                            self, "reasoning_content not allowed here")

            if rifiuta_fuori_assistant or esigente:
                ultimo = None
                for m in corpo.get("messages") or []:
                    if m.get("role") == "assistant":
                        ultimo = m
                if ultimo and not ultimo.get("reasoning_content"):
                    return _errore(
                        self, "Missing required parameter: "
                              "messages[].reasoning_content")

            if len(viste) == 1:
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
                pezzi = [
                    {"choices": [{"delta": {"reasoning_content": "Concludo.",
                                           "content": "Il risultato e' 4."}}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                ]

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for p in pezzi:
                self.wfile.write(b"data: " + json.dumps(p).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

    srv = HTTPServer(("127.0.0.1", porta), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, viste


def _esegui(porta, domanda="quanto fa 2+2"):
    prov = OpenAICompatAdapter(base_url=f"http://127.0.0.1:{porta}",
                               api_key="x", model="beam", name="beam-sim")
    ag = Agent(prov, default_registry(), "test", LoopConfig(max_iterations=5))
    return ag.run(domanda)


def test_beam_esigente():
    """Il gateway che vuole il ragionamento su ogni assistant: passa."""
    _gateway(8791, esigente=True)
    st = _esegui(8791)
    assert st.stopped_because == "risposta_finale", (
        f"fermato: {st.stopped_because}"
    )


def test_beam_solo_sui_tool_call():
    """Il gateway che lo chiede solo dove c'e' un tool call: passa."""
    _gateway(8790)
    st = _esegui(8790)
    assert st.stopped_because == "risposta_finale", (
        f"fermato: {st.stopped_because}"
    )


def test_rifiuta_reasoning_fuori_dagli_assistant():
    """Un gateway che rifiuta il campo fuori dagli assistant: passa.

    Orchestra non lo manda mai la': i messaggi tool (nudge, gira-a-vuoto,
    nota di verifica) non hanno ragionamento.
    """
    _gateway(8789, rifiuta_fuori_assistant=True)
    st = _esegui(8789)
    assert st.stopped_because == "risposta_finale", (
        f"fermato: {st.stopped_because}"
    )


# --- Il payload: dove il ragionamento va e dove non deve andare -----------


def test_nudge_non_porta_reasoning():
    """I messaggi di sistema (nudge) non devono avere `reasoning_content`."""
    nudge = Message(
        role="tool",
        tool_call_id="t1",
        name="__nudge__",
        content="NOTA DEL SISTEMA: usa gli strumenti.",
    )
    assert "reasoning_content" not in nudge.to_api(), (
        f"il nudge porta il ragionamento: {nudge.to_api()!r}"
    )


def test_tool_reale_non_porta_reasoning():
    """Un messaggio tool normale (risultato) non deve avere il campo."""
    m = Message(role="tool", tool_call_id="t1", name="calculate", content="4")
    assert "reasoning_content" not in m.to_api()


def test_assistant_senza_ragionamento_non_porta_il_campo():
    """Un assistant che non ha ragionato non deve avere il campo."""
    m = Message(role="assistant", content="fatto")
    assert "reasoning_content" not in m.to_api()


def test_assistant_con_ragionamento_lo_rimanda():
    """E uno che ha ragionato lo rimanda, come Beam chiede."""
    m = Message(role="assistant", content="fatto", reasoning="pensato")
    assert m.to_api()["reasoning_content"] == "pensato"
