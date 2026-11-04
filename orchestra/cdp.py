"""Chrome DevTools Protocol, con la sola standard library.

PERCHE' NON UNA LIBRERIA

Orchestra non ha dipendenze a runtime. Un client CDP sembra grosso ma e'
due cose: un WebSocket (handshake HTTP, frame con maschera, ping/pong) e
un dizionario di comandi JSON con un id. Sono ~200 righe, e stanno qui.

COSA SI PUO' FARE

Aprire una pagina, cliccare, scrivere, aspettare un selettore, leggere
console e rete. E' il canale che mancava: `browser_render` legge l'HTML
del DOM, ma non puo' interagire ne' dire cosa ha scritto la pagina in
console.

Il browser si lancia con `--remote-debugging-port` su una porta libera e
un profilo temporaneo, in headless. La sessione e' UNA per processo: due
turni che aprono due Chrome consumerebbero memoria per niente, e il
secondo non vedrebbe lo stato del primo.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class ErroreCDP(RuntimeError):
    """Il canale di debug non c'e' o ha risposto con un errore."""


class WebSocket:
    """Il minimo WebSocket client: testo, ping/pong, chiusura.

    Niente estensioni, niente compressione, niente frame binari in
    uscita: CDP manda JSON in frame di testo e basta. I frame in entrata
    possono essere frammentati, e vengono ricomposti.
    """

    def __init__(self, url: str) -> None:
        p = urlparse(url)
        if p.scheme not in ("ws", "wss"):
            raise ErroreCDP(f"url WebSocket non valido: {url}")
        self.host = p.hostname or "127.0.0.1"
        self.port = p.port or (443 if p.scheme == "wss" else 80)
        self.path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        self.sock: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- apertura

    def connect(self, timeout: float = 10.0) -> None:
        try:
            self.sock = socket.create_connection((self.host, self.port),
                                                 timeout=timeout)
        except OSError as e:
            raise ErroreCDP(f"connessione a {self.host}:{self.port} "
                            f"fallita: {e}") from e
        chiave = base64.b64encode(os.urandom(16)).decode("ascii")
        richiesta = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {chiave}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(richiesta.encode("ascii"))
        testa = b""
        while b"\r\n\r\n" not in testa:
            pezzo = self.sock.recv(4096)
            if not pezzo:
                raise ErroreCDP("il server ha chiuso durante l'handshake")
            testa += pezzo
            if len(testa) > 64_000:
                raise ErroreCDP("handshake WebSocket troppo lungo")
        intestazioni, resto = testa.split(b"\r\n\r\n", 1)
        self._buf = resto
        righe = intestazioni.decode("latin-1").split("\r\n")
        if "101" not in (righe[0].split(" ")[1] if len(righe[0].split(" ")) > 1
                         else ""):
            raise ErroreCDP(f"handshake rifiutato: {righe[0]}")
        atteso = base64.b64encode(
            hashlib.sha1((chiave + WS_MAGIC).encode("ascii")).digest()
        ).decode("ascii")
        trovato = ""
        for r in righe[1:]:
            if r.lower().startswith("sec-websocket-accept:"):
                trovato = r.split(":", 1)[1].strip()
        if trovato != atteso:
            raise ErroreCDP("handshake WebSocket con accept non valido")

    # ---------------------------------------------------------------- invio

    def send_text(self, testo: str) -> None:
        self._invia(0x1, testo.encode("utf-8"))

    def _invia(self, opcode: int, dati: bytes) -> None:
        sock = self.sock
        if sock is None:
            raise ErroreCDP("WebSocket chiuso")
        n = len(dati)
        intestazione = bytearray([0x80 | opcode])
        if n < 126:
            intestazione.append(0x80 | n)
        elif n < 65536:
            intestazione.append(0x80 | 126)
            intestazione += struct.pack(">H", n)
        else:
            intestazione.append(0x80 | 127)
            intestazione += struct.pack(">Q", n)
        maschera = os.urandom(4)
        intestazione += maschera
        mascherati = bytes(b ^ maschera[i % 4] for i, b in enumerate(dati))
        with self._lock:
            sock.sendall(bytes(intestazione) + mascherati)

    # ---------------------------------------------------------------- ricezione

    def recv_text(self, timeout: float = 30.0) -> str | None:
        """Il prossimo messaggio di testo. None alla chiusura."""
        fine = time.time() + timeout
        while True:
            frame = self._frame(max(0.1, fine - time.time()))
            if frame is None:
                raise ErroreCDP(f"timeout dopo {timeout}s in attesa di un "
                                f"messaggio CDP")
            fin, opcode, dati = frame
            if opcode == 0x9:  # ping
                self._invia(0xA, dati)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:  # close
                self.close()
                return None
            if opcode in (0x1, 0x2):
                pezzi = [dati]
                while not fin:
                    altro = self._frame(max(0.1, fine - time.time()))
                    if altro is None:
                        raise ErroreCDP("frame frammentato incompleto")
                    fin, op2, d2 = altro
                    if op2 not in (0x0, 0x1, 0x2):
                        continue
                    pezzi.append(d2)
                return b"".join(pezzi).decode("utf-8", "replace")
            # Frame di continuazione fuori sequenza: si ignora.

    def _frame(self, timeout: float) -> tuple[bool, int, bytes] | None:
        sock = self.sock
        if sock is None:
            return None
        sock.settimeout(max(0.05, timeout))
        try:
            testa = self._leggi(2)
            if testa is None:
                return None
        except socket.timeout:
            return None
        b1, b2 = testa[0], testa[1]
        fin = bool(b1 & 0x80)
        opcode = b1 & 0x0F
        mascherato = bool(b2 & 0x80)
        n = b2 & 0x7F
        if n == 126:
            ext = self._leggi(2)
            if ext is None:
                return None
            n = struct.unpack(">H", ext)[0]
        elif n == 127:
            ext = self._leggi(8)
            if ext is None:
                return None
            n = struct.unpack(">Q", ext)[0]
        if n > 64 * 1024 * 1024:
            raise ErroreCDP(f"frame CDP troppo grande: {n} byte")
        maschera = self._leggi(4) if mascherato else b""
        dati = self._leggi(n) if n else b""
        if dati is None:
            return None
        if maschera:
            dati = bytes(b ^ maschera[i % 4] for i, b in enumerate(dati))
        return fin, opcode, dati

    def _leggi(self, n: int) -> bytes | None:
        sock = self.sock
        if sock is None:
            return None
        while len(self._buf) < n:
            pezzo = sock.recv(max(4096, n - len(self._buf)))
            if not pezzo:
                return None
            self._buf += pezzo
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def close(self) -> None:
        sock, self.sock = self.sock, None
        if sock is None:
            return
        try:
            sock.sendall(b"\x88\x80" + os.urandom(4))
        except OSError:
            pass
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


class CDP:
    """Una connessione al browser, con i comandi numerati e gli eventi."""

    def __init__(self, ws_url: str, timeout: float = 10.0) -> None:
        self.ws = WebSocket(ws_url)
        self.ws.connect(timeout)
        self._next_id = 1
        self._lock = threading.Lock()
        self._eventi: dict[str, list[Callable[[dict], None]]] = {}
        self.session_id: str = ""

    def on(self, evento: str, handler: Callable[[dict], None]) -> None:
        self._eventi.setdefault(evento, []).append(handler)

    def _dispatch(self, msg: dict[str, Any]) -> None:
        metodo = msg.get("method")
        if not metodo:
            return
        for h in self._eventi.get(metodo, []):
            try:
                h(msg.get("params") or {})
            except Exception:  # noqa: BLE001 - un handler non ferma il canale
                pass

    def call(self, metodo: str, params: dict[str, Any] | None = None,
             timeout: float = 20.0, session_id: str | None = None) -> Any:
        with self._lock:
            rid = self._next_id
            self._next_id += 1
        msg: dict[str, Any] = {"id": rid, "method": metodo,
                               "params": params or {}}
        sid = session_id if session_id is not None else self.session_id
        if sid:
            msg["sessionId"] = sid
        self.ws.send_text(json.dumps(msg))
        fine = time.time() + timeout
        while time.time() < fine:
            testo = self.ws.recv_text(max(0.2, fine - time.time()))
            if testo is None:
                raise ErroreCDP("il browser ha chiuso il canale di debug")
            try:
                obj = json.loads(testo)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == rid:
                if "error" in obj:
                    err = obj["error"]
                    raise ErroreCDP(
                        f"{metodo}: {err.get('message') if isinstance(err, dict) else err}")
                return obj.get("result")
            self._dispatch(obj)
        raise ErroreCDP(f"timeout dopo {timeout}s su {metodo}")

    def close(self) -> None:
        self.ws.close()


# ---------------------------------------------------------------------------
# Lancio del browser e sessione pagina
# ---------------------------------------------------------------------------

def _porta_libera() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _attendi_debug(porta: int, timeout: float) -> dict[str, Any]:
    url = f"http://127.0.0.1:{porta}/json/version"
    fine = time.time() + timeout
    ultimo = ""
    while time.time() < fine:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            ultimo = str(e)
            time.sleep(0.2)
    raise ErroreCDP(f"il browser non espone il canale di debug su "
                    f"{porta}: {ultimo}")


class SessioneBrowser:
    """Un Chrome headless con una pagina, e gli eventi che ci interessano."""

    def __init__(self, eseguibile: str, url_iniziale: str = "about:blank") -> None:
        self.eseguibile = eseguibile
        self.url = url_iniziale
        self.proc: subprocess.Popen | None = None
        self.cdp: CDP | None = None
        self.target_id = ""
        self.session_id = ""
        self.console: list[dict[str, Any]] = []
        self.rete: list[dict[str, Any]] = []
        self._richieste: dict[str, dict[str, Any]] = {}

    # ---------------------------------------------------------------- apertura

    def apri(self, timeout: float = 15.0) -> None:
        porta = _porta_libera()
        profilo = os.path.join(tempfile.gettempdir(), "orchestra_cdp")
        os.makedirs(profilo, exist_ok=True)
        cmd = [
            self.eseguibile,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            "--disable-background-networking",
            f"--user-data-dir={profilo}",
            f"--remote-debugging-port={porta}",
            "about:blank",
        ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        info = _attendi_debug(porta, timeout)
        ws_url = info.get("webSocketDebuggerUrl") or ""
        if not ws_url:
            raise ErroreCDP("il browser non ha fornito webSocketDebuggerUrl")
        self.cdp = CDP(ws_url, timeout=timeout)
        self.cdp.on("Runtime.consoleAPICalled", self._console_api)
        self.cdp.on("Log.entryAdded", self._log_entry)
        self.cdp.on("Runtime.exceptionThrown", self._eccezione)
        self.cdp.on("Network.requestWillBeSent", self._richiesta)
        self.cdp.on("Network.responseReceived", self._risposta)

        creato = self.cdp.call("Target.createTarget", {"url": "about:blank"})
        self.target_id = (creato or {}).get("targetId") or ""
        allegato = self.cdp.call("Target.attachToTarget",
                                 {"targetId": self.target_id, "flatten": True})
        self.session_id = (allegato or {}).get("sessionId") or ""
        if not self.session_id:
            raise ErroreCDP("non riesco ad allegarmi alla pagina")
        self.cdp.session_id = self.session_id
        for dominio in ("Page", "Runtime", "Log", "Network"):
            try:
                self.cdp.call(f"{dominio}.enable", {})
            except ErroreCDP:
                # Un dominio mancante non deve impedire gli altri: Network
                # e' utile, Page e' indispensabile.
                if dominio == "Page":
                    raise
        if self.url and self.url != "about:blank":
            self.vai(self.url)

    # ---------------------------------------------------------------- eventi

    def _console_api(self, p: dict[str, Any]) -> None:
        parti = []
        for a in p.get("args") or []:
            if isinstance(a, dict):
                if "value" in a:
                    parti.append(str(a["value"]))
                else:
                    parti.append(str(a.get("description") or a.get("type")))
        self.console.append({
            "livello": p.get("type") or "log",
            "testo": " ".join(parti),
            "ts": p.get("timestamp") or time.time(),
        })
        self._taglia(self.console)

    def _log_entry(self, p: dict[str, Any]) -> None:
        e = p.get("entry") or {}
        self.console.append({
            "livello": e.get("level") or "info",
            "testo": e.get("text") or "",
            "ts": e.get("timestamp") or time.time(),
        })
        self._taglia(self.console)

    def _eccezione(self, p: dict[str, Any]) -> None:
        d = p.get("exceptionDetails") or {}
        testo = d.get("text") or ""
        exc = d.get("exception") or {}
        if isinstance(exc, dict) and exc.get("description"):
            testo += " " + str(exc["description"])
        self.console.append({"livello": "exception", "testo": testo.strip(),
                             "ts": time.time()})
        self._taglia(self.console)

    @staticmethod
    def _taglia(lista: list[dict[str, Any]], limite: int = 300) -> None:
        if len(lista) > limite:
            del lista[:-limite]

    def _richiesta(self, p: dict[str, Any]) -> None:
        rid = p.get("requestId") or ""
        r = p.get("request") or {}
        self._richieste[rid] = {
            "metodo": r.get("method") or "",
            "url": r.get("url") or "",
            "tipo": p.get("type") or "",
            "stato": None,
            "mime": "",
        }

    def _risposta(self, p: dict[str, Any]) -> None:
        rid = p.get("requestId") or ""
        r = p.get("response") or {}
        voce = self._richieste.get(rid)
        if voce is None:
            voce = {"metodo": "", "url": r.get("url") or "", "tipo": "",
                    "stato": None, "mime": ""}
            self._richieste[rid] = voce
        voce["stato"] = r.get("status")
        voce["mime"] = r.get("mimeType") or ""
        self.rete.append(dict(voce))
        self._taglia(self.rete)

    # ---------------------------------------------------------------- comandi

    def vai(self, url: str, timeout: float = 25.0) -> dict[str, Any]:
        if self.cdp is None:
            raise ErroreCDP("sessione non aperta")
        self.cdp.call("Page.navigate", {"url": url}, timeout=timeout)
        # Aspetta il load: se la pagina non lo manda (SPA lenta, risorsa
        # appesa) si prosegue lo stesso, perche' il DOM puo' essere gia'
        # utilizzabile e bloccare qui renderebbe il tool inusabile.
        fine = time.time() + min(timeout, 15)
        while time.time() < fine:
            try:
                stato = self.eval("document.readyState", timeout=2)
            except ErroreCDP:
                break
            if stato in ("interactive", "complete"):
                break
            time.sleep(0.15)
        titolo = ""
        try:
            titolo = str(self.eval("document.title", timeout=2) or "")
        except ErroreCDP:
            pass
        return {"url": self.url_corrente(), "titolo": titolo}

    def eval(self, espressione: str, timeout: float = 10.0) -> Any:
        if self.cdp is None:
            raise ErroreCDP("sessione non aperta")
        r = self.cdp.call("Runtime.evaluate", {
            "expression": espressione,
            "returnByValue": True,
            "awaitPromise": True,
        }, timeout=timeout)
        if not isinstance(r, dict):
            return None
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            testo = d.get("text") or "errore JavaScript"
            exc = d.get("exception") or {}
            if isinstance(exc, dict) and exc.get("description"):
                testo = str(exc["description"]).splitlines()[0]
            raise ErroreCDP(testo)
        res = r.get("result") or {}
        return res.get("value")

    def url_corrente(self) -> str:
        try:
            return str(self.eval("location.href", timeout=3) or "")
        except ErroreCDP:
            return ""

    def digita(self, testo: str) -> None:
        if self.cdp is None:
            raise ErroreCDP("sessione non aperta")
        # insertText va nel campo che ha il fuoco, e i listener `input`
        # scattano come per una digitazione vera: e' la differenza fra
        # un campo che sembra pieno e uno che il sito ha registrato.
        self.cdp.call("Input.insertText", {"text": testo})

    def invio(self) -> None:
        if self.cdp is None:
            raise ErroreCDP("sessione non aperta")
        for tipo in ("keyDown", "keyUp"):
            self.cdp.call("Input.dispatchKeyEvent", {
                "type": tipo, "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
            })

    def chiudi(self) -> None:
        if self.cdp is not None:
            try:
                self.cdp.call("Browser.close", {}, timeout=3)
            except ErroreCDP:
                pass
            self.cdp.close()
        self.cdp = None
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
