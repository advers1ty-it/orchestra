"""Verifica nel browser vero: caricare un file e guardare cosa succede.

Non chiama funzioni interne del server: simula quello che fa l'utente.
Il motivo e' che il difetto che mi hai segnalato era gia' coperto dai
test in Python — a ogni giro tornava 14/14 — e non si vedeva. Il
"carico..." che non finiva e il "Failed to fetch" stavano nel passaggio
fra il file picker e la rete, e quel passaggio non esiste in un test
che chiama /api/allega con urllib.

Qui il file lo produce il browser e la richiesta la fa fetch, che ha
regole sue sui corpi grandi e sulle connessioni persistenti.

Va lanciato con Chrome in ascolto:
    chrome --headless --remote-debugging-port=9333 --user-data-dir=<tmp>
"""

import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request
from urllib.parse import urlparse

CDP = "http://127.0.0.1:9333"
PORT = int(os.environ.get("ORCHESTRA_TEST_PORT", "8737"))
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


class WS:
    """Websocket quanto basta: handshake e frame di testo."""

    def __init__(self, url: str) -> None:
        u = urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=90)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((
            f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        dati = b""
        while b"\r\n\r\n" not in dati:
            dati += self.s.recv(4096)

    def _leggi(self, n: int) -> bytes:
        b = b""
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c:
                raise EOFError
            b += c
        return b

    def invia(self, msg: dict) -> None:
        p = json.dumps(msg).encode()
        mask = os.urandom(4)
        n = len(p)
        hdr = (struct.pack("!BB", 0x81, 0x80 | n) if n < 126
               else struct.pack("!BBH", 0x81, 0x80 | 126, n))
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(p)))

    def ricevi(self) -> dict:
        h = self._leggi(2)
        ln = h[1] & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", self._leggi(2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", self._leggi(8))[0]
        return json.loads(self._leggi(ln).decode())


WS_ = None
_id = [1000]   # si parte da 1000: gli id bassi sono del debugger
# (Runtime.enable e' 1) e una risposta in ritardo con quell'id puo'
# essere scambiata per il risultato di una valuta(). Il sintomo e'
# un None che non dipende dalla pagina: e' una risposta arrivata
# fuori posto.


def apri() -> None:
    """Una tab sola, tenuta aperta per tutto il test.

    Aprirne una per ogni valutazione scarterebbe lo stato a ogni passo:
    si controllerebbe sempre una pagina appena caricata, dove non e'
    ancora successo niente. Il test passerebbe guardando il nulla.
    """
    global WS_
    r = urllib.request.Request(CDP + f"/json/new?http://127.0.0.1:{PORT}", method="PUT")
    tab = json.loads(urllib.request.urlopen(r, timeout=20).read())
    WS_ = WS(tab["webSocketDebuggerUrl"])
    WS_.invia({"id": 1, "method": "Runtime.enable"})
    # Si aspetta che il bundle sia eseguito, non solo che la pagina
    # esista. Senza, la prima valuta() legge una pagina a meta'
    # caricamento: il title c'e' gia' (lo mette l'HTML) ma gli id
    # aggiunti dal JS no. Il sintomo e' una pagina "vuota" che in
    # realta e' solo non ancora pronta — e sembra un bug della UI.
    for _ in range(40):
        time.sleep(0.25)
        _id[0] += 1
        mio = _id[0]
        WS_.invia({"id": mio, "method": "Runtime.evaluate", "params": {
            "expression": "typeof aggiungiFile === 'function' && "
                          "document.querySelectorAll('[id]').length > 40",
            "returnByValue": True}})
        scaduto = time.time() + 20
        while time.time() < scaduto:
            m = WS_.ricevi()
            if m.get("id") == mio:
                if (m.get("result", {}).get("result", {}).get("value")):
                    return
                break
    # Non ha aspettato: si prosegue e i fallimenti diranno perche'.


def valuta(expr: str):
    _id[0] += 1
    mio = _id[0]
    WS_.invia({"id": mio, "method": "Runtime.evaluate", "params": {
        "expression": expr, "awaitPromise": True, "returnByValue": True}})
    scaduto = time.time() + 60
    while time.time() < scaduto:
        try:
            m = WS_.ricevi()
        except (EOFError, OSError):
            return {"errore": "connessione caduta"}
        if m.get("id") == mio:
            res = m.get("result", {}).get("result", {})
            if res.get("subtype") == "error":
                return {"errore": str(res.get("description", "?"))[:150]}
            return res.get("value")
    return {"errore": "timeout"}


print("[1] La pagina parte e il bundle e' eseguito")
apri()
r = valuta("document.title")
check("la pagina e' quella di Orchestra", "orchestra" in str(r).lower(), str(r))
print("   ", r)
for cosa, expr in [("readyState", "document.readyState"),
                   ("href", "location.href"),
                   ("titolo", "document.title"),
                   ("allegati-lista", "!!document.getElementById('allegati-lista')"),
                   ("btn-send", "!!document.getElementById('btn-send')"),
                   ("input", "!!document.querySelector('#input')"),
                   ("quanti id", "document.querySelectorAll('[id]').length")]:
    print(f"    {cosa:<16}", valuta(expr))
check("aggiungiFile esiste", valuta("typeof aggiungiFile") == "function",
      str(valuta("typeof aggiungiFile")))

print("\n[2] Il file picker accetta un file e la riga appare")
r = valuta("""
(async () => {
  const b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
  const bin = atob(b64);
  const arr = Uint8Array.from(bin, c => c.charCodeAt(0));
  const file = new File([arr], "rosso.png", { type: "image/png" });
  if (typeof aggiungiFile !== "function") return { errore: "aggiungiFile assente" };
  await aggiungiFile([file]);
  return { righe: allegatiInAttesa.length,
           nome: allegatiInAttesa[0] && allegatiInAttesa[0].nome };
})()
""")
check("il file e' stato accettato",
      isinstance(r, dict) and r.get("righe") == 1, json.dumps(r)[:120])

print("\n[3] La riga passa da 'carico...' a un conto")
# Il difetto che hai visto: il flag restava True perche' nessuno lo
# toglieva. Ora lo toglie la risposta del server.
stato = []
for _ in range(40):
    stato = valuta("""
    (typeof allegatiInAttesa !== 'undefined' ? allegatiInAttesa : []).map(a => ({
      nome: a.nome, caricamento: !!a.in_caricamento,
      id: a.id || null, errore: a.errore || null,
    }))
    """) or []
    if stato and all(not a["caricamento"] for a in stato):
        break
    time.sleep(0.5)
print("   ", json.dumps(stato)[:170])
check("nessuna riga resta in caricamento",
      bool(stato) and all(not a["caricamento"] for a in stato), json.dumps(stato)[:120])
check("nessun errore sul caricamento",
      bool(stato) and all(not a["errore"] for a in stato), json.dumps(stato)[:120])
check("la riga ha un id", bool(stato) and all(a["id"] for a in stato), json.dumps(stato)[:120])
# L'id deve essere una STRINGA. Era una lista dentro la lista, e
# falliva solo all'invio: la riga si riempiva, il conto c'era, e il
# server respingeva "allegato non valido" quando premevi Invia.
tipi = valuta("allegatiInAttesa.map(a => typeof a.id)") or []
check("l'id e' una stringa, non una lista", tipi == ["string"], json.dumps(tipi))

print("\n[4] Cosa si vede a schermo")
righe = valuta("""
(() => { const c = document.querySelector('#allegati');
         return c ? c.innerText.trim() : '(nessun #allegati-lista)'; })()
""")
print("   ", repr(str(righe)[:160]))
check("il nome del file e' visibile", "rosso.png" in str(righe), str(righe)[:90])
check("il conto e' visibile", "1100" in str(righe), str(righe)[:90])
check("NON resta scritto 'carico'", "carico" not in str(righe).lower(), str(righe)[:90])

print("\n[5] Il corpo che il browser manderebbe all'invio")
r = valuta("""
(() => {
  const a = (typeof allegatiInAttesa !== 'undefined' ? allegatiInAttesa : [])[0];
  const corpo = JSON.stringify({ text: "quanti pixel rossi?",
                                 allegati: [a && a.id].filter(Boolean) });
  return { byte: corpo.length, ha_base64: corpo.includes("base64") };
})()
""")
print("   ", json.dumps(r)[:150])
check("il corpo non contiene il file", not r.get("ha_base64"), str(r)[:100])
check("ed e' piccolo", r.get("byte", 9999) < 200, str(r.get("byte")))

print("\n[6] Il tasto Invia e' cliccabile")
stato_invio = valuta("""
(() => { const b = document.querySelector('#send');
         return b ? { esiste: true, disabilitato: !!b.disabled } : { esiste: false }; })()
""")
print("   ", json.dumps(stato_invio))
check("il tasto c'e'", bool(stato_invio.get("esiste")), json.dumps(stato_invio))
check("e non e' disabilitato", not stato_invio.get("disabilitato"), json.dumps(stato_invio))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
