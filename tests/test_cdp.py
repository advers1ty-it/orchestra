"""Il canale CDP: WebSocket fatto in casa, e un browser vero se c'è.

Due livelli, perché si rompono in due modi diversi:

1. Il WebSocket. Se sbaglia la maschera o la lunghezza estesa, Chrome
   chiude il canale e sembra "CDP rotto". Qui c'è un server WebSocket
   minimo che risponde in locale, quindi il framing si prova SEMPRE,
   anche su una macchina senza Chrome.
2. L'interazione. Se c'è un Chrome/Edge, si apre una pagina vera con un
   pulsante e un campo, si clicca, si scrive, si aspetta, e si leggono
   console e rete. Se il browser non c'è, il test lo dice e non finge di
   aver verificato.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import socketserver
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

os.environ.setdefault("ORCHESTRA_HOME",
                      os.path.join(RADICE, "tests", "_dati_test"))

from orchestra.cdp import WS_MAGIC, WebSocket  # noqa: E402

PASS, FAIL, SKIP = [], [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def salta(nome: str, motivo: str) -> None:
    SKIP.append(nome)
    print(f"  SALTA {nome} — {motivo}")


# ---------------------------------------------------------------------------
# Un server WebSocket minimo: handshake, frame, eco
# ---------------------------------------------------------------------------

def _leggi(conn: socket.socket, n: int) -> bytes:
    out = b""
    while len(out) < n:
        pezzo = conn.recv(n - len(out))
        if not pezzo:
            raise EOFError
        out += pezzo
    return out


def _frame_server(dati: bytes, opcode: int = 0x1) -> bytes:
    n = len(dati)
    if n < 126:
        testa = bytes([0x80 | opcode, n])
    elif n < 65536:
        testa = bytes([0x80 | opcode, 126]) + struct.pack(">H", n)
    else:
        testa = bytes([0x80 | opcode, 127]) + struct.pack(">Q", n)
    return testa + dati


class EchoWS(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        testa = b""
        while b"\r\n\r\n" not in testa:
            testa += conn.recv(4096)
        righe = testa.split(b"\r\n\r\n")[0].decode("latin-1").split("\r\n")
        chiave = ""
        for r in righe[1:]:
            if r.lower().startswith("sec-websocket-key:"):
                chiave = r.split(":", 1)[1].strip()
        accept = base64.b64encode(
            hashlib.sha1((chiave + WS_MAGIC).encode()).digest()).decode()
        conn.sendall((
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        # Un ping prima di tutto: il client deve rispondere pong e non
        # scambiarlo per un messaggio.
        conn.sendall(_frame_server(b"ping", 0x9))
        while True:
            try:
                b1, b2 = _leggi(conn, 2)
            except EOFError:
                return
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", _leggi(conn, 2))[0]
            elif n == 127:
                n = struct.unpack(">Q", _leggi(conn, 8))[0]
            maschera = _leggi(conn, 4) if b2 & 0x80 else b""
            dati = _leggi(conn, n) if n else b""
            if maschera:
                dati = bytes(b ^ maschera[i % 4] for i, b in enumerate(dati))
            opcode = b1 & 0x0F
            if opcode == 0x8:
                conn.sendall(_frame_server(b"", 0x8))
                return
            if opcode == 0xA:
                continue  # pong: niente da fare
            conn.sendall(_frame_server(dati))


class ServerWS(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


ws_server = ServerWS(("127.0.0.1", 0), EchoWS)
PORTA_WS = ws_server.server_address[1]
threading.Thread(target=ws_server.serve_forever, daemon=True).start()

print("\n== il WebSocket: handshake, maschera, lunghezza estesa ==")

ws = WebSocket(f"ws://127.0.0.1:{PORTA_WS}/devtools/page/x")
ws.connect(timeout=5)
check("l'handshake passa", ws.sock is not None)
ws.send_text("ciao")
check("un messaggio piccolo torna", ws.recv_text(timeout=5) == "ciao")
lungo = "à" * 400  # multi-byte e oltre i 125 byte: lunghezza estesa
ws.send_text(lungo)
check("un messaggio lungo torna intero", ws.recv_text(timeout=5) == lungo)
ws.close()

print("\n== CDP: comandi numerati ed eventi ==")

from orchestra.cdp import CDP, ErroreCDP  # noqa: E402

cdp = CDP(f"ws://127.0.0.1:{PORTA_WS}/x", timeout=5)
# Il server d'eco risponde con lo stesso JSON: simuliamo una risposta CDP
# mandando un comando e leggendo l'eco con l'id giusto.
cdp.ws.send_text(json.dumps({"id": 99, "method": "Browser.getVersion",
                             "params": {}}))
eco = json.loads(cdp.ws.recv_text(timeout=5))
check("il comando conserva il suo id", eco.get("id") == 99, str(eco))
cdp.close()


# ---------------------------------------------------------------------------
# Un browser vero, se c'è
# ---------------------------------------------------------------------------

PAGINA = """<!doctype html><html><head><title>Prova CDP</title></head><body>
<h1 id="titolo">Pagina di prova</h1>
<button id="btn" onclick="document.getElementById('esito').textContent='cliccato'; console.log('cliccato dal test')">Premi</button>
<input id="nome" />
<button id="saluta" onclick="document.getElementById('saluto').textContent='Ciao '+document.getElementById('nome').value">Saluta</button>
<div id="esito"></div><div id="saluto"></div>
<script>console.log('pagina pronta')</script>
</body></html>"""


class Pagina(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        corpo = PAGINA.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


web = ThreadingHTTPServer(("127.0.0.1", 0), Pagina)
PORTA_WEB = web.server_address[1]
threading.Thread(target=web.serve_forever, daemon=True).start()

from orchestra.tools import browser as b  # noqa: E402

exe = b._browser_exe()
if not exe:
    salta("browser CDP", "nessun Chrome/Edge su questa macchina")
else:
    try:
        b.chiudi_sessione_cdp()
        s = b._sessione_cdp(f"http://127.0.0.1:{PORTA_WEB}/")
    except Exception as e:  # noqa: BLE001
        salta("browser CDP", f"il browser non parte: {type(e).__name__}: {e}")
    else:
        print("\n== browser: click, digitazione, attesa, console, rete ==")
        check("la pagina si apre", "127.0.0.1" in s.url_corrente(),
              s.url_corrente())
        esito = b.tool_browser_click().handler(selettore="#btn")
        check("il click riesce", "cliccato" in esito, esito)
        att = b.tool_browser_attendi().handler(selettore="#esito",
                                               testo="cliccato", timeout_s=5)
        check("il testo compare dopo il click", "comparso" in att, att)
        val = s.eval("document.getElementById('esito').textContent")
        check("il DOM è cambiato davvero", val == "cliccato", str(val))

        out = b.tool_browser_digita().handler(selettore="#nome", testo="Ada")
        check("la digitazione riesce", "scritto" in out, out)
        check("il campo contiene il testo",
              s.eval("document.getElementById('nome').value") == "Ada",
              str(s.eval("document.getElementById('nome').value")))
        b.tool_browser_click().handler(selettore="#saluta")
        att = b.tool_browser_attendi().handler(testo="Ciao Ada", timeout_s=5)
        check("l'evento input è stato registrato",
              "comparso" in att, att)

        cons = b.tool_browser_console().handler(limite=20)
        check("la console contiene il log della pagina",
              "pagina pronta" in cons, cons)
        check("la console contiene il log del click",
              "cliccato dal test" in cons, cons)

        rete = b.tool_browser_rete().handler(limite=20)
        check("la rete mostra la richiesta della pagina",
              "127.0.0.1" in rete and "200" in rete, rete)

        mancante = b.tool_browser_click().handler(selettore="#non-esiste")
        check("un selettore assente lo dice", "nessun elemento" in mancante,
              mancante)
        b.chiudi_sessione_cdp()
        web.shutdown()

ws_server.shutdown()

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}  SKIP {len(SKIP)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
