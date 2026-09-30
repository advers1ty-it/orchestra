"""Prova che un motore locale funzioni SENZA chiave API.

Non e' sufficiente aggiungere "ollama" alla tabella: finche' nessuno
parla con un server che non chiede autenticazione, non sappiamo se
l'adapter funziona. Questo script accende un server OpenAI-compatible
finto sulla porta di Ollama e gli manda una richiesta vera.

Motore finto, ma il percorso e' quello vero: build_provider ->
OpenAICompatAdapter -> POST /chat/completions. Se funziona qui,
funziona con Ollama.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = 11434  # la porta vera di Ollama: se qualcosa e' gia' in ascolto lo diciamo
RICHESTE = []


class Finto(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            corpo = json.dumps({"data": [
                {"id": "qwen2.5-coder:7b"}, {"id": "llama3.2:3b"},
            ]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n)
        RICHESTE.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": json.loads(raw.decode("utf-8")) if raw else {},
        })
        risposta = {
            "id": "x", "model": "qwen2.5-coder:7b",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ciao"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        }
        corpo = json.dumps(risposta).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("\n[1] Il server finto parte")
try:
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Finto)
except OSError as e:
    print(f"  non posso usare la porta {PORT}: {e}")
    print("  (probabilmente Ollama e' gia' installato: in quel caso il test")
    print("   e' inutile, il motore vero c'e' gia')")
    sys.exit(0)
threading.Thread(target=srv.serve_forever, daemon=True).start()
print(f"  in ascolto su 127.0.0.1:{PORT}")

from orchestra.providers import (  # noqa: E402
    KNOWN_PROVIDERS, NO_KEY_PROVIDERS, base_url_for, build_provider, local_models,
)

print("\n[2] Un provider senza chiave e' configurato")
check("ollama e' fra i provider", "ollama" in KNOWN_PROVIDERS)
check("lmstudio e' fra i provider", "lmstudio" in KNOWN_PROVIDERS)
check("ollama non chiede chiave", "ollama" in NO_KEY_PROVIDERS)
check("openrouter chiede ancora la chiave", "openrouter" not in NO_KEY_PROVIDERS)
check("l'indirizzo di ollama e' quello giusto",
      base_url_for("ollama", {}) == "http://127.0.0.1:11434/v1",
      base_url_for("ollama", {}))

print("\n[3] L'override dell'indirizzo funziona")
env = {"ORCHESTRA_OLLAMA_URL": "http://192.168.1.10:11434/v1"}
check("si puo' puntare a un altro motore",
      base_url_for("ollama", env) == "http://192.168.1.10:11434/v1",
      base_url_for("ollama", env))

print("\n[4] Il provider si costruisce SENZA chiave nel .env")
try:
    prov = build_provider("ollama", model="qwen2.5-coder:7b", env={})
    check("si costruisce senza chiave", True)
    check("l'indirizzo e' quello del motore locale",
          prov.base_url == "http://127.0.0.1:11434/v1", prov.base_url)
    check("il modello di default e' compilato", prov.model == "qwen2.5-coder:7b", prov.model)
except Exception as e:  # noqa: BLE001
    check("si costruisce senza chiave", False, f"{type(e).__name__}: {e}")
    prov = None

print("\n[5] Su un provider cloud la chiave mancante resta un errore")
try:
    build_provider("openrouter", model="x", env={})
    check("openrouter senza chiave fallisce", False, "ha accettato una richiesta senza chiave")
except Exception as e:  # noqa: BLE001
    check("openrouter senza chiave fallisce", "OPENROUTER_API_KEY" in str(e), str(e)[:80])

print("\n[6] Una richiesta vera arriva al motore")
if prov is not None:
    try:
        from orchestra.types import Message  # noqa: E402
        r = prov.chat([Message(role="user", content="ciao")], tools=None)
        check("la chat risponde", (r.content or "").strip() == "ciao", str(r)[:120])
        check("il motore ha ricevuto /chat/completions",
              RICHESTE and RICHESTE[0]["path"].endswith("/chat/completions"),
              str(RICHESTE[:1]))
        check("il modello richiesto e' quello giusto",
              bool(RICHESTE) and RICHESTE[0]["body"].get("model") == "qwen2.5-coder:7b",
              str(RICHESTE[0]["body"].get("model") if RICHESTE else None))
    except Exception as e:  # noqa: BLE001
        check("la chat risponde", False, f"{type(e).__name__}: {e}")

print("\n[7] L'elenco dei modelli locali si legge")
ms = local_models("ollama", {})
check("i modelli locali sono elencati", len(ms) == 2, str(ms))
check("sono segnati come gratuiti", all(m["free"] for m in ms))

print("\n[8] Se il motore non c'e', non si rompe")
ms2 = local_models("lmstudio", {})
check("un motore assente dà lista vuota, non errore", ms2 == [], str(ms2))

srv.shutdown()
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
