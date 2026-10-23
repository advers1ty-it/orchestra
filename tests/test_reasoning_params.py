"""Il ragionamento si regola dove il modello lo accetta, e solo la'.

Due regole:

1. `preserve_thinking` e' un parametro Qwen-specifico. Va mandato solo
   ai modelli Qwen: un gateway che non lo conosce risponde 400, e lo
   manderebbe a Claude o a Beam per sbaglio.

2. Beam su Nous ragiona sempre, quindi ha i livelli di reasoning_effort:
   prima `nous` non era nella mappa e non si poteva regolarlo.
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
from orchestra.reasoning import (
    build_preserve_payload,
    build_reasoning_payload,
    get_model_levels,
    wants_preserve_thinking,
)


def test_preserve_thinking_solo_qwen():
    """Solo i modelli Qwen lo vogliono; gli altri non devono averlo."""
    for m in ("qwen/qwen3.8-27b:free", "qwen/qwen3-235b-a22b",
              "qwen/qwen3-coder"):
        assert wants_preserve_thinking(m), f"{m} deve averlo"
        assert build_preserve_payload(m) == {"preserve_thinking": True}

    for m in ("reflection/beam-1.0-501b-a23b", "Beam-1.0-501B-A23B",
              "anthropic/claude-sonnet-4", "gpt-4o-mini",
              "deepseek/deepseek-v4"):
        assert not wants_preserve_thinking(m), f"{m} non deve averlo"
        assert build_preserve_payload(m) == {}


def test_preserve_thinking_case_insensitive():
    """Il nome del modello arriva con prefissi e suffissi vari."""
    assert wants_preserve_thinking("Qwen/Qwen3-32B")
    assert wants_preserve_thinking("qwen3.8-27b")


def test_nous_ha_i_livelli_di_reasoning():
    """Beam su Nous: prima non c'era, quindi il livello non si poteva regolare."""
    livelli = get_model_levels("nous", "Beam-1.0-501B-A23B")
    assert livelli, "nous deve avere i livelli di reasoning"
    assert "medium" in livelli
    # Beam non ha un livello "none": ragiona sempre.
    assert "none" not in livelli, "Beam non puo' spegnere il ragionamento"


def test_nous_reasoning_payload():
    """Il payload di reasoning su nous e' quello che Beam aspetta."""
    assert build_reasoning_payload("nous", "Beam-1.0-501B-A23B", "medium") == {
        "reasoning_effort": "medium"
    }
    # "none" non esiste: non si manda nulla, invece di un parametro che
    # Beam rifiuterebbe con 400.
    assert build_reasoning_payload("nous", "Beam-1.0-501B-A23B", "none") == {}


def test_payload_qwen_non_rompe_gli_altri():
    """Un gateway severo che rifiuta parametri sconosciuti: solo Qwen li prende."""
    severi = {
        "reflection/beam-1.0-501b-a23b": {},
        "anthropic/claude-sonnet-4": {},
        "gpt-4o-mini": {},
    }
    for modello, atteso in severi.items():
        assert build_preserve_payload(modello) == atteso, modello


# --- End-to-end: il parametro arriva solo dove serve ---



def _gateway(porta, modello):
    """Un gateway che rifiuta `preserve_thinking` se il modello non e' Qwen."""
    viste = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_POST(self):
            corpo = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length") or 0)))
            viste.append(corpo)
            if corpo.get("preserve_thinking") and "qwen" not in corpo.get("model", "").lower():
                out = json.dumps({"error": {"message":
                    "preserve_thinking not supported for this model"}}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers(); self.wfile.write(out)
                return
            msg = {"role": "assistant", "content": "fatto",
                   "reasoning_content": "ok"}
            out = json.dumps({"choices": [
                {"message": msg, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers(); self.wfile.write(out)

    srv = HTTPServer(("127.0.0.1", porta), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, viste


def _esegui(porta, modello):
    prov = OpenAICompatAdapter(base_url=f"http://127.0.0.1:{porta}",
                               api_key="x", model=modello, name="openrouter")
    ag = Agent(prov, default_registry(), "test", LoopConfig(max_iterations=3))
    return ag.run("ciao")


def test_beam_non_prende_preserve_thinking():
    """Beam su OpenRouter: niente `preserve_thinking`, altrimenti 400."""
    _gateway(8788, "reflection/beam-1.0-501b-a23b")
    st = _esegui(8788, "reflection/beam-1.0-501b-a23b")
    assert st.stopped_because == "risposta_finale", (
        f"fermato: {st.stopped_because}"
    )


def test_qwen_prende_preserve_thinking():
    """Qwen lo prende: senza, il ragionamento si perde tra i turni."""
    srv, viste = _gateway(8787, "qwen/qwen3.8-27b:free")
    st = _esegui(8787, "qwen/qwen3.8-27b:free")
    assert st.stopped_because == "risposta_finale", (
        f"fermato: {st.stopped_because}"
    )
    assert viste, "nessuna richiesta"
    assert any(v.get("preserve_thinking") for v in viste), (
        "Qwen deve ricevere preserve_thinking"
    )
