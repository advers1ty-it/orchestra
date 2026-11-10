"""I trasporti MCP: stdio, HTTP streamable, SSE (legacy).

Il protocollo e' lo stesso per tutti e tre — initialize, tools/list,
tools/call, resources/*, prompts/* — e cambia solo come i messaggi
viaggiano. Per questo il trasporto sta qui e il protocollo sta in
`mcp.py`: aggiungere un trasporto non deve voler dire ricopiare
l'handshake, e un difetto nell'handshake non deve esistere in tre
versioni leggermente diverse.

LA DISTINZIONE CHE CONTA

`ErroreTrasporto` = "non c'e' piu' un canale": processo morto, pipe
chiusa, HTTP 404 con sessione scaduta, rete giu'. Solo questo giustifica
una riconnessione, perche' solo questo si risolve riconnettendosi.

`ErroreMCP` = "il server ha risposto che c'e' un errore": metodo
sconosciuto, argomenti sbagliati, tool che fallisce. Riconnettersi qui
non cambierebbe niente: sarebbe solo un secondo errore.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# La versione che annunciamo. 2025-03-26 e' quella che introduce lo
# streamable HTTP; un server piu' vecchio risponde con la sua, e da li'
# in poi si usa quella negoziata.
PROTOCOLLO = "2025-03-26"

USER_AGENT = "Orchestra-MCP/0.5"


class ErroreTrasporto(RuntimeError):
    """Il canale non c'e' piu'. E' il solo caso in cui si riconnette."""


class ErroreMCP(RuntimeError):
    """Il server ha risposto con un errore JSON-RPC."""

    def __init__(self, messaggio: str, codice: int | None = None) -> None:
        super().__init__(messaggio)
        self.codice = codice


def _esito(obj: Any) -> Any:
    """Il `result` di una risposta JSON-RPC, o l'eccezione giusta."""
    if not isinstance(obj, dict):
        return obj
    if "error" in obj:
        err = obj["error"]
        if isinstance(err, dict):
            raise ErroreMCP(str(err.get("message") or err),
                            err.get("code") if isinstance(err.get("code"), int)
                            else None)
        raise ErroreMCP(str(err))
    return obj.get("result")


def _env_minimo() -> dict[str, str]:
    """Ambiente per un server MCP stdio, senza i segreti di Orchestra.

    Prima si passava `dict(os.environ)`: un server MCP — anche uno
    aggiunto per sbaglio dal modello — riceveva chiavi API, token e
    password del processo. Un server MCP ha bisogno di PATH e poco
    altro; quello che gli serve davvero lo dichiara nel suo `env`.
    """
    try:
        from .tools._guard import _sandbox_env
        return _sandbox_env()
    except Exception:  # noqa: BLE001 - meglio un ambiente minimo che uno pieno
        keep = ("PATH", "HOME", "USERPROFILE", "TMP", "TEMP", "LANG",
                "LC_", "SYSTEMROOT", "COMSPEC", "WINDIR", "TERM")
        return {
            k: v for k, v in os.environ.items()
            if k.upper().startswith(keep)
            or k.upper() in {"USER", "LOGNAME", "SHELL", "PWD"}
        }


class Trasporto:
    """Interfaccia comune. `start` apre il canale, non fa l'handshake."""

    initialized = False
    error = ""

    def start(self, timeout: float = 20.0) -> bool:  # pragma: no cover
        raise NotImplementedError

    def request(self, method: str, params: Any = None,
                timeout: float = 20.0, notify: bool = False) -> Any:
        raise NotImplementedError

    def stop(self) -> None:
        pass


# ---------------------------------------------------------------------------
# stdio
# ---------------------------------------------------------------------------

class StdioTrasporto(Trasporto):
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._next_id = 1
        self._reader: threading.Thread | None = None
        # Una riga JSON-RPC e' un messaggio intero: se due thread la
        # scrivono a pezzi, il server riceve due messaggi rotti. Il lock
        # e' sulla scrittura, non sulla richiesta, cosi' due tool MCP in
        # parallelo possono comunque essere in volo insieme.
        self._write_lock = threading.Lock()
        self._chiuso = False
        self.error = ""

    def start(self, timeout: float = 20.0) -> bool:
        self.error = ""
        try:
            cmd = [self.cfg.get("command")] + list(self.cfg.get("args") or [])
            if not cmd[0]:
                raise ValueError("command mancante")
            env = _env_minimo()
            for k, v in (self.cfg.get("env") or {}).items():
                env[str(k)] = str(v)
            cwd = self.cfg.get("cwd") or None
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
                cwd=cwd,
            )
        except Exception as e:  # noqa: BLE001 - un avvio fallito e' un dato
            self.error = f"avvio fallito: {type(e).__name__}: {e}"
            return False
        self._chiuso = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def _read_loop(self) -> None:
        motivo = "il server ha chiuso lo stdout"
        try:
            assert self.proc is not None and self.proc.stdout is not None
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # Rumore su stdout (log, banner): un server MCP che
                    # scrive altro non deve rompere il canale.
                    continue
                rid = obj.get("id") if isinstance(obj, dict) else None
                if rid is None:
                    continue
                with self._lock:
                    q = self._pending.get(rid)
                if q is not None:
                    q.put(obj)
        except Exception as e:  # noqa: BLE001
            motivo = f"lettura fallita: {e}"
        finally:
            # Chi aspetta una risposta deve sapere SUBITO che il canale e'
            # morto. Lasciarlo scadere sul timeout trasforma un processo
            # morto in "il server e' lento", e la riconnessione non parte
            # mai perche' nessuno sa che serviva.
            self._chiuso = True
            with self._lock:
                in_attesa = list(self._pending.values())
            for q in in_attesa:
                q.put({"__trasporto__": motivo})

    def request(self, method: str, params: Any = None, timeout: float = 20.0,
                notify: bool = False) -> Any:
        proc = self.proc
        if proc is None or proc.stdin is None:
            raise ErroreTrasporto("processo non avviato")
        if notify:
            self._scrivi({"jsonrpc": "2.0", "method": method,
                          "params": params or {}})
            return None
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            q: queue.Queue = queue.Queue()
            self._pending[rid] = q
        try:
            self._scrivi({"jsonrpc": "2.0", "id": rid, "method": method,
                          "params": params or {}})
            # Il processo puo' essere morto fra il controllo e la
            # scrittura: senza questo si aspetterebbe il timeout intero
            # per un canale che non c'e' piu'.
            if self._chiuso:
                raise ErroreTrasporto("il server ha chiuso lo stdout")
            obj = q.get(timeout=timeout)
        except queue.Empty:
            raise ErroreTrasporto(
                f"timeout dopo {timeout}s su {method}") from None
        finally:
            with self._lock:
                self._pending.pop(rid, None)
        if isinstance(obj, dict) and "__trasporto__" in obj:
            raise ErroreTrasporto(str(obj["__trasporto__"]))
        return _esito(obj)

    def _scrivi(self, msg: dict[str, Any]) -> None:
        proc = self.proc
        if proc is None or proc.stdin is None:
            raise ErroreTrasporto("processo non avviato")
        try:
            with self._write_lock:
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()
        except Exception as e:  # noqa: BLE001
            raise ErroreTrasporto(f"scrittura fallita: {e}") from e

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# HTTP streamable (2025-03-26)
# ---------------------------------------------------------------------------

class HttpTrasporto(Trasporto):
    """Un POST per richiesta. La risposta e' JSON o un flusso SSE.

    La sessione vive nell'header `Mcp-Session-Id`: il server lo manda al
    primo `initialize` e da li' in poi va rimandato. Se il server risponde
    404 a una richiesta con sessione vuol dire che l'ha scartata: e' un
    errore di trasporto, quindi si riconnette e si rifa' l'handshake.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.url = str(cfg.get("url") or "")
        self.headers = {str(k): str(v)
                        for k, v in (cfg.get("headers") or {}).items()}
        self.session_id = ""
        self.protocol = PROTOCOLLO
        self._next_id = 1
        self._lock = threading.Lock()
        self.error = ""

    def start(self, timeout: float = 20.0) -> bool:
        self.error = ""
        if not self.url.startswith(("http://", "https://")):
            self.error = "url mancante o non http(s)"
            return False
        return True

    def _intestazioni(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol,
            "User-Agent": USER_AGENT,
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        h.update(self.headers)
        return h

    def request(self, method: str, params: Any = None, timeout: float = 20.0,
                notify: bool = False) -> Any:
        with self._lock:
            rid = self._next_id
            self._next_id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method,
                               "params": params or {}}
        if not notify:
            msg["id"] = rid
        dati, ctype = self._post(msg, timeout)
        if notify:
            return None
        if "text/event-stream" in ctype:
            obj = _risposta_da_sse(dati, rid)
            if obj is None:
                raise ErroreTrasporto(
                    f"il flusso SSE non conteneva la risposta a {method}")
            return _esito(obj)
        if not dati.strip():
            raise ErroreTrasporto(f"risposta vuota a {method}")
        try:
            return _esito(json.loads(dati.decode("utf-8", "replace")))
        except json.JSONDecodeError as e:
            raise ErroreTrasporto(
                f"risposta non JSON a {method}: {dati[:200]!r}") from e

    def _post(self, msg: dict[str, Any],
              timeout: float) -> tuple[bytes, str]:
        corpo = json.dumps(msg).encode("utf-8")
        req = urllib.request.Request(self.url, data=corpo,
                                     headers=self._intestazioni(),
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                sid = r.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                proto = r.headers.get("MCP-Protocol-Version")
                if proto:
                    self.protocol = proto
                return r.read(), r.headers.get("Content-Type") or ""
        except urllib.error.HTTPError as e:
            dettaglio = ""
            try:
                dettaglio = e.read()[:300].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            if e.code == 404 and self.session_id:
                raise ErroreTrasporto(
                    "sessione MCP scaduta (HTTP 404): serve un nuovo "
                    "initialize") from e
            # 4xx con una risposta JSON-RPC dentro e' un errore del
            # protocollo (per esempio un parametro sbagliato), non del
            # canale: riconnettersi non lo risolverebbe.
            if dettaglio.strip().startswith("{"):
                try:
                    obj = json.loads(dettaglio)
                    if isinstance(obj, dict) and "error" in obj:
                        return dettaglio.encode("utf-8"), "application/json"
                except json.JSONDecodeError:
                    pass
            raise ErroreTrasporto(
                f"HTTP {e.code} da {self.url}: {dettaglio[:200]}") from e
        except (urllib.error.URLError, OSError) as e:
            raise ErroreTrasporto(f"rete: {e}") from e

    def stop(self) -> None:
        # La sessione si chiude con DELETE, quando il server lo supporta:
        # un server che non lo supporta risponde 405 ed e' lo stesso.
        if not self.session_id:
            return
        try:
            req = urllib.request.Request(
                self.url, headers={"Mcp-Session-Id": self.session_id,
                                   "User-Agent": USER_AGENT},
                method="DELETE")
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:  # noqa: BLE001
            pass
        self.session_id = ""


def _risposta_da_sse(dati: bytes, rid: int) -> dict[str, Any] | None:
    """La risposta con `id` dentro un flusso SSE gia' letto."""
    evento = ""
    for riga in dati.decode("utf-8", "replace").splitlines():
        if riga.startswith("event:"):
            evento = riga[6:].strip()
        elif riga.startswith("data:"):
            testo = riga[5:].strip()
            if evento not in ("", "message"):
                continue
            try:
                obj = json.loads(testo)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("id") == rid:
                return obj
    return None


# ---------------------------------------------------------------------------
# SSE legacy (2024-11-05)
# ---------------------------------------------------------------------------

class SseTrasporto(Trasporto):
    """Il vecchio trasporto: GET per il flusso, POST per i messaggi.

    Il server manda un evento `endpoint` con l'URL su cui mandare le
    richieste, poi le risposte arrivano come eventi `message` sullo
    stesso flusso. Per questo serve un thread che legge, come per stdio.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.url = str(cfg.get("url") or "")
        self.headers = {str(k): str(v)
                        for k, v in (cfg.get("headers") or {}).items()}
        self._pending: dict[int, queue.Queue] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._endpoint = ""
        self._pronto = threading.Event()
        self._resp = None
        self._reader: threading.Thread | None = None
        self.protocol = PROTOCOLLO
        self.error = ""

    def start(self, timeout: float = 20.0) -> bool:
        self.error = ""
        if not self.url.startswith(("http://", "https://")):
            self.error = "url mancante o non http(s)"
            return False
        intestazioni = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "User-Agent": USER_AGENT,
            **self.headers,
        }
        req = urllib.request.Request(self.url, headers=intestazioni,
                                     method="GET")
        try:
            self._resp = urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            self.error = f"connessione SSE fallita: {type(e).__name__}: {e}"
            return False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        if not self._pronto.wait(timeout):
            self.error = "il server non ha mandato l'evento endpoint"
            self.stop()
            return False
        return True

    def _read_loop(self) -> None:
        evento, dati = "", []
        motivo = "il flusso SSE si e' chiuso"
        try:
            resp = self._resp
            assert resp is not None
            for riga in resp:
                riga = riga.decode("utf-8", "replace").rstrip("\r\n")
                if riga == "":
                    self._dispatch(evento, "\n".join(dati))
                    evento, dati = "", []
                elif riga.startswith("event:"):
                    evento = riga[6:].strip()
                elif riga.startswith("data:"):
                    dati.append(riga[5:].lstrip())
        except Exception as e:  # noqa: BLE001
            motivo = f"lettura SSE fallita: {e}"
        finally:
            with self._lock:
                in_attesa = list(self._pending.values())
            for q in in_attesa:
                q.put({"__trasporto__": motivo})

    def _dispatch(self, evento: str, testo: str) -> None:
        if evento == "endpoint":
            self._endpoint = urllib.parse.urljoin(self.url, testo.strip())
            self._pronto.set()
            return
        if evento not in ("", "message"):
            return
        try:
            obj = json.loads(testo)
        except json.JSONDecodeError:
            return
        if not isinstance(obj, dict):
            return
        rid = obj.get("id")
        if rid is None:
            return
        with self._lock:
            q = self._pending.get(rid)
        if q is not None:
            q.put(obj)

    def request(self, method: str, params: Any = None, timeout: float = 20.0,
                notify: bool = False) -> Any:
        if not self._endpoint:
            raise ErroreTrasporto("endpoint SSE non ancora noto")
        with self._lock:
            rid = self._next_id
            self._next_id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method,
                               "params": params or {}}
        if notify:
            self._post(msg, timeout)
            return None
        msg["id"] = rid
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._pending[rid] = q
        try:
            self._post(msg, timeout)
            obj = q.get(timeout=timeout)
        except queue.Empty:
            raise ErroreTrasporto(
                f"timeout dopo {timeout}s su {method}") from None
        finally:
            with self._lock:
                self._pending.pop(rid, None)
        if isinstance(obj, dict) and "__trasporto__" in obj:
            raise ErroreTrasporto(str(obj["__trasporto__"]))
        return _esito(obj)

    def _post(self, msg: dict[str, Any], timeout: float) -> None:
        corpo = json.dumps(msg).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint, data=corpo, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": USER_AGENT, **self.headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()
        except urllib.error.HTTPError as e:
            dettaglio = ""
            try:
                dettaglio = e.read()[:300].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            if e.code >= 500:
                raise ErroreTrasporto(f"HTTP {e.code} su POST SSE") from e
            if dettaglio.strip().startswith("{"):
                try:
                    obj = json.loads(dettaglio)
                    if isinstance(obj, dict) and "error" in obj:
                        return  # l'errore arrivera' sul flusso
                except json.JSONDecodeError:
                    pass
            raise ErroreMCP(f"HTTP {e.code} su POST SSE: {dettaglio[:200]}")
        except (urllib.error.URLError, OSError) as e:
            raise ErroreTrasporto(f"rete: {e}") from e

    def stop(self) -> None:
        resp, self._resp = self._resp, None
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
        self._endpoint = ""
        self._pronto.clear()


def crea(cfg: dict[str, Any]) -> Trasporto:
    """Il trasporto giusto per questa configurazione.

    "http" e "streamable-http" sono lo stesso; "sse" resta per i server
    piu' vecchi. Un valore sconosciuto non viene indovinato: solleva.
    """
    trasporto = str(cfg.get("transport") or "stdio").strip().lower()
    if trasporto in ("stdio", ""):
        return StdioTrasporto(cfg)
    if trasporto in ("http", "streamable-http", "streamable_http"):
        return HttpTrasporto(cfg)
    if trasporto == "sse":
        return SseTrasporto(cfg)
    raise ValueError(f"transport '{trasporto}' non supportato "
                     f"(stdio, http, sse)")
