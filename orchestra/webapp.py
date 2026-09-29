"""Server HTTP locale per la UI web.

Server stdlib, nessuna dipendenza. Tre endpoint:

    GET  /               l'interfaccia
    GET  /api/stream     SSE: gli eventi dell'agente in tempo reale
    GET  /api/state      snapshot dello stato
    POST /api/send       {text}       invia un messaggio
    POST /api/cancel     arresta il turno in corso
    POST /api/reset      nuova conversazione
    POST /api/system     {prompt}     cambia le istruzioni di sistema

Perche' SSE e non WebSocket: lo stream e' di sola lettura, va in un senso
solo, e SSE si reconnecta da solo. WebSocket aggiungerebbe una
dipendenza per zero guadagno.

Nota di sicurezza: ascolta su 127.0.0.1 e non ha autenticazione. Va bene
per uso locale, NON va esposto su una rete. C'e' un controllo esplicito
all'avvio perche' sbagliarlo significa esporre le chiavi API.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .agent import LoopConfig
from .providers import ProviderError, build_provider, load_env
from .session import Session
from .tools import SYSTEM_PROMPT, default_registry

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
UI_PATH = os.path.join(HERE, "web", "index.html")

MAX_BODY = 64 * 1024  # un prompt non occupa 64KB: oltre e' un errore


class OrchestraApp:
    """Lo stato del server, condiviso fra i thread.

    ThreadingHTTPServer crea un thread per richiesta, quindi tutto quello
    che tocciamo qui deve essere o immutabile o protetto. La Session ha gia'
    i propri lock; questo oggetto contiene solo la sessione.
    """

    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.session = self._make_session(env.get("ORCHESTRA_PROVIDER", "openrouter"),
                                         env.get("ORCHESTRA_MODEL", ""))
        self.ready = True
        self.error: str = ""

    @staticmethod
    def _make_session(provider_name: str, model: str) -> Session:
        def num(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, default))
            except (TypeError, ValueError):
                return default

        return Session(
            provider=build_provider(provider_name, model=model, env=load_env(ENV_PATH) | os.environ),
            registry=default_registry(),
            system_prompt=SYSTEM_PROMPT,
            config=LoopConfig(max_iterations=12, context_limit=120_000, keep_recent=8),
        )

    @classmethod
    def create(cls) -> "OrchestraApp":
        """Costruisce l'app, o la mette in stato di errore se il provider
        non e' configurato. La UI deve poter mostrare l'errore invece di
        fallire all'avvio."""
        env = dict(os.environ)
        env.update(load_env(ENV_PATH))
        try:
            app = cls.__new__(cls)
            app.env = env
            app.ready = True
            app.error = ""
            app.session = cls._make_session(
                env.get("ORCHESTRA_PROVIDER", "openrouter"),
                env.get("ORCHESTRA_MODEL", ""),
            )
            return app
        except (ProviderError, KeyError) as e:
            app = cls.__new__(cls)
            app.env = env
            app.ready = False
            app.error = str(e)
            app.session = None  # type: ignore[assignment]
            return app


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app: OrchestraApp  # impostato dal server

    # silenzio: il log di ogni richiesta SSE èrumore
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    # -- helper ------------------------------------------------------------

    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, path: str) -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._json({"error": "UI non trovata"}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return {}
        if n <= 0:
            return {}
        if n > MAX_BODY:
            raise ValueError("corpo troppo grande")
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("JSON non valido")

    def _need_session(self) -> Session | None:
        if not self.app.ready or self.app.session is None:
            self._json({"error": self.app.error or "server non pronto"}, 503)
            return None
        return self.app.session

    # -- GET ---------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - firma di BaseHTTPRequestHandler
        path = self.path.split("?")[0]
        if path == "/":
            self._html(UI_PATH)
        elif path == "/api/state":
            s = self._need_session()
            if s is None:
                return
            snap = s.snapshot()
            snap["ready"] = self.app.ready
            snap["error"] = self.app.error
            snap["version"] = __version__
            snap["model"] = self.app.env.get("ORCHESTRA_MODEL", "")
            snap["provider"] = self.app.env.get("ORCHESTRA_PROVIDER", "")
            self._json(snap)
        elif path == "/api/stream":
            self._sse()
        else:
            self._json({"error": "non trovato"}, 404)

    def _sse(self) -> None:
        """Stream degli eventi, formato SSE.

        Formato: `data: <json>\n\n`. Teniamo la connessione aperta e
        mandiamo un commento vuoto come keepalive: senza, il browser chiude
        dopo qualche decina di secondi.
        """
        s = self._need_session()
        if s is None:
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        # assicura che il browser riceva subito gli header
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            # Snapshot iniziale, cosi' la UI non parte vuota dopo un reload.
            # Deve avere un `seq` come tutti gli altri eventi: un client che
            # riconnette e chiede "riprendi dal seq N" altrimenti trova un
            # evento senza seq e non sa dove si era interrotto.
            self._sse_send({
                "seq": 0,
                "kind": "snapshot",
                "data": s.snapshot(),
                "ts": time.time(),
            })
            for item in s.bridge.stream(timeout=10.0):
                if item["kind"] == "keepalive":
                    self.wfile.write(b": ping\n\n")
                else:
                    self._sse_send(item)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            # il browser ha chiuso: normale, non e' un errore da loggare
            pass

    def _sse_send(self, item: dict[str, Any]) -> None:
        payload = json.dumps(item, default=str)
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))

    # -- POST --------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        s = self._need_session()
        if s is None:
            return
        try:
            body = self._body()
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return

        if path == "/api/send":
            text = (body.get("text") or "").strip()
            if not text:
                self._json({"error": "messaggio vuoto"}, 400)
                return
            ok = s.send(text)
            if not ok:
                # l'agente sta lavorando: l'UI deve saperlo e non far partire
                # una richiesta che verrebbe silenziosamente persa
                self._json({"error": "occupato: attendi la fine del turno o annulla",
                            "busy": True}, 409)
                return
            self._json({"ok": True})
        elif path == "/api/cancel":
            self._json({"ok": s.cancel()})
        elif path == "/api/reset":
            try:
                s.reset()
                self._json({"ok": True})
            except RuntimeError as e:
                self._json({"error": str(e)}, 409)
        elif path == "/api/system":
            prompt = (body.get("prompt") or "").strip()
            if not prompt:
                self._json({"error": "prompt vuoto"}, 400)
                return
            s.set_system_prompt(prompt)
            self._json({"ok": True})
        else:
            self._json({"error": "non trovato"}, 404)


def serve(host: str = "127.0.0.1", port: int = 8737, *, open_browser: bool = True) -> None:
    app = OrchestraApp.create()
    Handler.app = app

    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"ATTENZIONE: ascolto su {host}, non su localhost.", file=sys.stderr)
        print("Il server non ha autenticazione: chi lo raggiunge puo' usare le "
              "tue chiavi API. Serve solo per test locali.", file=sys.stderr)
        # senza terminale non c'e' nessuno che possa confermare: rifiutiamo
        if not (sys.stdin and sys.stdin.isatty()):
            raise SystemExit("rifiuto di esporre fuori da localhost in modo non interattivo")
        if input("Continuo? [s/N] ").strip().lower() != "s":
            raise SystemExit("annullato")

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True

    url = f"http://{host}:{port}"
    print(f"\n  Orchestra {__version__}  ->  {url}\n")
    if not app.ready:
        print(f"  ATTENZIONE: {app.error}")
        print(f"  Configura orchestra/.env, poi riavvia.\n")
    else:
        print(f"  modello: {app.env.get('ORCHESTRA_MODEL')} "
              f"({app.env.get('ORCHESTRA_PROVIDER')})")
        print(f"  Ctrl+C per fermare\n")

    if open_browser and app.ready:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  fermo.")
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    serve()
