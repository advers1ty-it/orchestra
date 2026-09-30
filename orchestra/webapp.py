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

    def __init__(self, env: dict[str, str], session: Session | None = None) -> None:
        self.env = env
        # la sessione può arrivare già costruita (dal create, che deve poter
        # catturare l'errore del provider) o essere costruita qui. Il punto
        # è che TUTTE le istanze passano da qui: prima `create()` usava
        # __new__ e saltava __init__, e gli attributi mancavano a runtime
        # con un AttributeError che emergeva solo al primo /api/models.
        self.session = session if session is not None else self._make_session(
            env.get("ORCHESTRA_PROVIDER", "openrouter"),
            env.get("ORCHESTRA_MODEL", ""),
        )
        self.ready = True
        self.error = ""
        # il catalogo viene caricato pigramente: `/models` lo chiede, la
        # chat no. Caricarlo all'avvio aggiungerebbe una chiamata di rete a
        # ogni start, anche quando l'utente vuole solo chattare.
        self._catalog: Any = None
        self._catalog_tried = False
        self._catalog_error: str = ""
        # stato del benchmark lanciato dalla UI
        self._bench: dict[str, Any] = {"running": False, "log": [], "result": None}

    @property
    def catalog(self) -> Any:
        """Catalogo dei modelli, caricato alla prima richiesta."""
        if not self._catalog_tried:
            self._catalog_tried = True
            try:
                from .catalog import Catalog

                self._catalog = Catalog.fetch(self.env.get("ORCHESTRA_PROVIDER", "openrouter"))
            except Exception as e:  # noqa: BLE001 - l'UI mostra l'errore
                self._catalog = None
                self._catalog_error = str(e)
        return self._catalog

    def switch_model(self, model_id: str) -> None:
        """Cambia il modello dell'agent in uso.

        Solleva RuntimeError se l'agente sta lavorando: cambiarlo a metà
        turno lascerebbe la conversazione con messaggi di due modelli
        diversi e un contesto che non ha senso.

        Valida contro il catalogo. `build_provider` accetterebbe QUALSIASI
        stringa — costruisce un client valido che fallisce solo alla
        prima chiamata, con un errore che sembra un problema di rete. Un
        id sbagliato in una select non è un errore plausibile da accettare
        in silenzio.
        """
        if self.session.busy:
            raise RuntimeError("l'agente sta lavorando: attendi o annulla prima")

        cat = self.catalog
        if cat is not None and cat.models and model_id not in cat.models:
            raise ValueError(
                f"modello sconosciuto: {model_id}. "
                f"Disponibili: {', '.join(sorted(cat.models)[:5])}…"
            )

        from .providers import build_provider

        provider_name = self.env.get("ORCHESTRA_PROVIDER", "openrouter")
        env = dict(os.environ)
        env.update(load_env(ENV_PATH))
        prov = build_provider(provider_name, model=model_id, env=env)
        self.session.agent.provider = prov
        self.env["ORCHESTRA_MODEL"] = model_id

    def start_benchmark(self, *, sample: int = 3, category: str | None = None,
                        throttle: float = 3.0) -> dict[str, Any]:
        """Lancia il benchmark in background e restituisce subito.

        Non blocca: l'UI mostra l'avanzamento via /api/bench/status. Un
        benchmark dura minuti e un server che aspetta è un server morto.
        """
        if self._bench["running"]:
            raise RuntimeError("un benchmark è già in corso")

        cat = self.catalog
        if cat is None or not cat.models:
            raise RuntimeError("catalogo non disponibile")

        # il campione viene dai modelli gratuiti con tool-calling, sparsi
        # sulla finestra di contesto: primo, uno medio, uno con contesto
        # grande. Non e' casuale perche' il confronto deve essere leggibile.
        free = sorted(cat.free(), key=lambda p: p.info.id)
        if not free:
            raise RuntimeError("nessun modello gratuito con tool-calling")
        free.sort(key=lambda p: -(p.info.context_length or 0))
        step = max(1, len(free) // max(1, sample))
        ids = [m.info.id for m in free[::step]][:sample]

        self._bench = {"running": True, "log": [], "result": None,
                       "started": time.time(), "models": ids}

        def worker() -> None:
            from .benchmark import render_table, run_task, summarize, tasks_for

            tasks = tasks_for(category)
            if not tasks:
                self._bench["log"].append(f"categoria sconosciuta: {category}")
                self._bench["running"] = False
                return
            results = []
            stop = False
            try:
                for mid in ids:
                    if stop:
                        break
                    name = cat.models[mid].info.short if mid in cat.models else mid
                    self._bench["log"].append(f"== {name} ==")
                    for t in tasks:
                        r = run_task(t, provider_name=self.env.get("ORCHESTRA_PROVIDER", "openrouter"),
                                     model=mid, env=dict(os.environ, **self.env),
                                     max_iterations=10)
                        results.append(r)
                        if r.unusable:
                            # il provider lo riserva ad altri client: inutile
                            # continuare e tenerlo nel confronto
                            self._bench["log"].append(f"  {t.id}: non raggiungibile")
                            stop = True
                            break
                        state = "ok" if r.passed else ("errore" if r.error else "fail")
                        self._bench["log"].append(
                            f"  {t.id}: {state}"
                            + (f" — {(r.detail or r.error)[:80]}" if not r.passed else "")
                        )
                        if throttle:
                            time.sleep(throttle)
                summary = summarize(results)
                for mid, data in summary["per_model"].items():
                    prof = cat.models.get(mid)
                    if prof:
                        prof.scores = {c: v for c, v in data["by_category"].items() if v > 0}
                        prof.last_measured = time.time()
                try:
                    cat.save()
                except Exception:
                    pass
                self._bench["result"] = {
                    "table": render_table(summary, cat),
                    "per_model": summary["per_model"],
                    "unusable": summary.get("unusable_models", []),
                }
            except Exception as e:  # noqa: BLE001
                self._bench["log"].append(f"ERRORE: {type(e).__name__}: {e}")
            finally:
                self._bench["running"] = False

        threading.Thread(target=worker, daemon=True, name="orchestra-bench").start()
        return {"ok": True, "models": ids, "tasks": len(tasks_for(category))}

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
            return cls(
                env,
                session=cls._make_session(
                    env.get("ORCHESTRA_PROVIDER", "openrouter"),
                    env.get("ORCHESTRA_MODEL", ""),
                ),
            )
        except (ProviderError, KeyError) as e:
            # l'app esiste anche senza sessione: /api/state deve poter
            # rispondere con l'errore, e la UI lo mostra
            app = cls(env, session=None)
            app.ready = False
            app.error = str(e)
            return app
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

    def _static(self, name: str, content_type: str) -> None:
        """Serve un file statico dalla cartella web/.

        Il nome viene controllato: solo [A-Za-z0-9._-], niente percorsi.
        Un parametro che arrivasse da fuori (`../webapp.py`) deve poter
        solo ottenere file della web/, mai altri.
        """
        if not all(c.isalnum() or c in "._-" for c in name):
            self._json({"error": "nome file non valido"}, 400)
            return
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", name)
        # doppia barriera: anche senza percorsi, il risultato deve stare
        # dentro web/
        if not os.path.abspath(path).startswith(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        ):
            self._json({"error": "non trovato"}, 404)
            return
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._json({"error": "non trovato"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # come per l'HTML: obbliga a riverificare. Senza, correggere un .js
        # e ricaricare non produceva nulla, e sembrava che le modifiche
        # non arrivassero al browser.
        self.send_header("Cache-Control", "no-cache, must-revalidate")
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
        # Senza questi il browser puo' servire una copia vecchia dalla
        # memoria e non lo dice: si vedeva una UI senza selettore modello
        # mentre il server era gia' aggiornato, e sembrava un bug del
        # codice. `no-cache` non impedisce di salvare, obbliga a
        # riverificare; `must-revalidate` chiude la porta al limbo.
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
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
        elif path == "/app.js":
            self._bundle()
        elif path.endswith(".js"):
            self._static(path[1:], "text/javascript; charset=utf-8")
        elif path.endswith(".css"):
            self._static(path[1:], "text/css; charset=utf-8")
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
        elif path == "/api/models":
            self._models()
        elif path == "/api/bench/status":
            self._json({
                "running": self.app._bench["running"],
                "log": self.app._bench["log"][-60:],
                "result": self.app._bench["result"],
                "models": self.app._bench.get("models", []),
            })
        elif path == "/api/capabilities":
            cat = self.app.catalog
            if cat is None:
                self._json({"error": getattr(self.app, "_catalog_error", "catalogo non disponibile")}, 503)
                return
            # solo i punteggi misurati: "non lo so" non si trasforma in uno
            # zero, altrimenti la UI mostrerebbe una tabella piena di
            # modelli con 0.00 che non sono misurati ma sconosciuti
            self._json({"measured": {mid: p.scores for mid, p in cat.models.items() if p.scores}})
        else:
            self._json({"error": "non trovato"}, 404)

    def _models(self) -> None:
        """Elenco modelli con i punteggi misurati, per il selettore."""
        cat = self.app.catalog
        if cat is None:
            self._json({"error": getattr(self.app, "_catalog_error", "catalogo non disponibile")}, 503)
            return
        current = self.app.env.get("ORCHESTRA_MODEL", "")
        out = []
        for p in sorted(cat.with_tools(), key=lambda x: x.info.id):
            out.append({
                "id": p.info.id,
                "short": p.info.short,
                "free": p.info.is_free,
                "context": p.info.context_length,
                "prompt_price": p.info.prompt_price,
                "scores": p.scores,
                "current": p.info.id == current,
            })
        self._json({"models": out, "current": current, "provider": self.app.env.get("ORCHESTRA_PROVIDER")})

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
        elif path == "/api/model":
            model_id = (body.get("model") or "").strip()
            if not model_id:
                self._json({"error": "modello vuoto"}, 400)
                return
            try:
                self.app.switch_model(model_id)
            except RuntimeError as e:
                self._json({"error": str(e)}, 409)
                return
            except Exception as e:  # noqa: BLE001 - chiave o provider
                self._json({"error": f"{type(e).__name__}: {e}"}, 400)
                return
            self._json({"ok": True, "model": model_id})
        elif path == "/api/bench":
            sample = body.get("sample", 3)
            try:
                sample = max(1, min(8, int(sample)))
            except (TypeError, ValueError):
                sample = 3
            category = body.get("category") or None
            if category == "all":
                category = None
            try:
                res = self.app.start_benchmark(sample=sample, category=category)
            except RuntimeError as e:
                self._json({"error": str(e)}, 409)
                return
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
                return
            self._json(res)
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
