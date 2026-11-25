"""I tool browser e la rete locale: la stessa guardia di `web_leggi`.

`web_leggi` blocca localhost, la rete privata e il DNS rebinding. I tool
browser no: `browser_render` e `browser_screenshot` potevano leggere un
servizio locale e riportarne il contenuto al modello. Qui si prova che la
guardia e' condivisa, che il ripiego fetch valida redirect e peer, e che
`browser_apri` resta l'eccezione per il server locale dell'utente.

La pagina locale e' un caso di lavoro vero (il server del progetto), non
solo un attacco: per questo il test verifica anche che il gate possa
concederla esplicitamente, invece di pretendere un blocco che romperebbe
la skill `local-web-ui`.
"""

from __future__ import annotations

import os
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

from orchestra import cdp as cdp_mod  # noqa: E402
from orchestra.tools import browser as b  # noqa: E402
from orchestra.tools import set_permission_gate  # noqa: E402
from orchestra.tools.web import _rete_locale  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class _Gate:
    """Un gate finto: risponde sempre `esito` e registra le domande."""

    def __init__(self, esito: bool = True) -> None:
        self.esito = esito
        self.chiamate: list[tuple[str, str, str]] = []

    def chiedi_all_utente(self, soggetto: str, azione: str,
                          dettaglio: str = "") -> bool:
        self.chiamate.append((soggetto, azione, dettaglio))
        return self.esito


print("\n[1] La rete locale si riconosce dagli indirizzi, non dal nome")
for host in ("127.0.0.1", "localhost", "10.0.0.1", "192.168.1.1",
             "169.254.169.254", "100.64.0.1"):
    check(f"{host} e' rete locale", _rete_locale(host))
check("un IP pubblico non e' rete locale", not _rete_locale("93.184.216.34"))


print("\n[2] Senza gate i tool che riportano contenuto rifiutano la rete locale")
set_permission_gate(None)
casi = [
    ("browser_render", b.tool_browser_render().handler,
     {"url": "http://127.0.0.1:9/"}),
    ("browser_screenshot", b.tool_browser_screenshot().handler,
     {"url": "http://localhost:9/"}),
    ("browser_click", b.tool_browser_click().handler,
     {"selettore": "#x", "url": "http://10.0.0.1/"}),
    ("browser_digita", b.tool_browser_digita().handler,
     {"selettore": "#x", "testo": "ciao", "url": "http://192.168.1.1/"}),
    ("browser_attendi", b.tool_browser_attendi().handler,
     {"selettore": "#x", "url": "http://169.254.169.254/"}),
]
for nome, funzione, argomenti in casi:
    esito = funzione(**argomenti)
    check(f"{nome} blocca la rete locale",
          "Rete locale bloccata" in esito, esito[:200])


print("\n[3] Con il permesso esplicito la pagina locale si apre")
gate = _Gate(True)
set_permission_gate(gate)
motivo = b._accesso_locale("http://127.0.0.1:3000/")
check("il gate viene interrogato", len(gate.chiamate) == 1, str(gate.chiamate))
check("e il permesso concede l'accesso", motivo == "", motivo)
set_permission_gate(_Gate(False))
check("un permesso negato lascia il blocco",
      "Rete locale bloccata" in b._accesso_locale("http://127.0.0.1:3000/"))
set_permission_gate(None)


print("\n[4] Il ripiego di browser_render usa redirect e peer di web_leggi")
vecchio_exe = b._browser_exe
vecchio_build = urllib.request.build_opener
vecchio_peer = b._peer_pubblico
visti: dict = {}


class _Headers:
    def get_content_charset(self):
        return "utf-8"


class _Risposta:
    headers = _Headers()

    def read(self, n=-1):
        return (b"<html><head><title>Prova</title></head><body>"
                b"<p>contenuto pubblico</p></body></html>")

    def geturl(self):
        return "http://93.184.216.34/"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def open(self, req, timeout=0):
        return _Risposta()


def _build(*gestori):
    visti["gestori"] = gestori
    return _Opener()


b._browser_exe = lambda: None
urllib.request.build_opener = _build
b._peer_pubblico = lambda resp: True
try:
    esito = b.tool_browser_render().handler(url="http://93.184.216.34/")
finally:
    b._browser_exe = vecchio_exe
    urllib.request.build_opener = vecchio_build
    b._peer_pubblico = vecchio_peer

check("la pagina pubblica viene letta", "contenuto pubblico" in esito,
      esito[:200])
check("il testo e' nel recinto non fidato",
      "CONTENUTO NON FIDATO" in esito, esito[:120])
check("il ripiego valida i redirect",
      b._RedirectPubblico in visti.get("gestori", ()),
      str(visti.get("gestori")))


print("\n[5] Un peer locale dopo la connessione viene fermato")
b._browser_exe = lambda: None
urllib.request.build_opener = _build
b._peer_pubblico = lambda resp: False
try:
    esito = b.tool_browser_render().handler(url="http://93.184.216.34/")
finally:
    b._browser_exe = vecchio_exe
    urllib.request.build_opener = vecchio_build
    b._peer_pubblico = vecchio_peer
check("il DNS rebinding non restituisce il corpo",
      "rete locale" in esito.lower() and "contenuto pubblico" not in esito,
      esito[:200])


print("\n[6] Un redirect pubblico->locale non viene letto nemmeno da Chrome")


class _SessioneFinta:
    """Simula un Chrome/CDP che e' finito su un altro URL."""

    def __init__(self, finale: str) -> None:
        self.finale = finale
        self.html_letto = False
        self.screenshot_fatto = False

    def url_corrente(self) -> str:
        return self.finale

    def html(self) -> str:
        self.html_letto = True
        return "<html><body>SEGRETO LOCALE</body></html>"

    def screenshot(self, larghezza: int = 0, altezza: int = 0) -> bytes:
        self.screenshot_fatto = True
        return b"\x89PNG\r\n\x1a\n"


vecchio_exe = b._browser_exe
vecchio_sessione = b._sessione_cdp
vecchio_chiudi = b.chiudi_sessione_cdp
finta = _SessioneFinta("http://127.0.0.1:9/segreto")
b._browser_exe = lambda: "chrome-finto"
b._sessione_cdp = lambda url: finta
b.chiudi_sessione_cdp = lambda: None
try:
    esito = b.tool_browser_render().handler(url="http://93.184.216.34/")
    check("il redirect non restituisce il contenuto locale",
          "rete locale" in esito.lower() and "SEGRETO" not in esito,
          esito[:260])
    check("e il DOM non viene nemmeno letto", not finta.html_letto)

    finta2 = _SessioneFinta("http://127.0.0.1:9/segreto")
    b._sessione_cdp = lambda url: finta2
    esito2 = b.tool_browser_screenshot().handler(
        url="http://93.184.216.34/", nome_file="redirect_browser_test.png")
    check("lo screenshot non cattura la pagina locale",
          "rete locale" in esito2.lower()
          and "Screenshot salvato" not in esito2, esito2[:260])
    check("e la cattura non viene eseguita", not finta2.screenshot_fatto)
finally:
    b._browser_exe = vecchio_exe
    b._sessione_cdp = vecchio_sessione
    b.chiudi_sessione_cdp = vecchio_chiudi

check("il controllo riconosce il redirect pubblico->locale",
      "rete locale" in b._motivo_redirect("http://93.184.216.34/",
                                          "http://127.0.0.1/"))
check("un locale gia' autorizzato non viene bloccato due volte",
      b._motivo_redirect("http://127.0.0.1:3000/",
                         "http://127.0.0.1:3000/" ) == "")

print("\n[6b] Anche la sessione CDP condivisa controlla l'URL finale")


class _ProcFinto:
    def poll(self):
        return None


class _BrowserFinto:
    """Un SessioneBrowser che, dopo il navigate, e' su localhost."""

    def __init__(self, *args, **kwargs):
        self.cdp = object()
        self.proc = _ProcFinto()
        self.chiuso = False

    def apri(self):
        pass

    def vai(self, url):
        return {"url": "http://127.0.0.1:9/segreto"}

    def url_corrente(self):
        return "http://127.0.0.1:9/segreto"

    def chiudi(self):
        self.chiuso = True


vecchio_classe = cdp_mod.SessioneBrowser
vecchio_exe = b._browser_exe
b._browser_exe = lambda: "chrome-finto"
cdp_mod.SessioneBrowser = _BrowserFinto
b.chiudi_sessione_cdp()
try:
    try:
        b._sessione_cdp("http://93.184.216.34/")
        check("la sessione rifiuta il redirect", False, "nessuna eccezione")
    except b._RedirectLocaleBloccato as e:
        check("la sessione rifiuta il redirect",
              "rete locale" in str(e).lower(), str(e))
finally:
    cdp_mod.SessioneBrowser = vecchio_classe
    b._browser_exe = vecchio_exe
    b.chiudi_sessione_cdp()

print("\n[6c] Un redirect HTTP vero: CDP legge l'URL finale")


class _RedirectHTTP(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/segreto")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        corpo = (b"<html><body>SEGRETO LOCALE</body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


if not b._browser_exe():
    print("  SALTA: nessun Chrome/Edge per il redirect HTTP reale")
else:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHTTP)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        b.chiudi_sessione_cdp()
        sessione = b._sessione_cdp(
            f"http://127.0.0.1:{server.server_address[1]}/")
        finale = sessione.url_corrente()
        check("CDP vede la destinazione del 302",
              finale.endswith("/segreto"), finale)
        check("e il controllo pubblico->locale la ferma",
              "rete locale" in b._motivo_redirect(
                  "http://93.184.216.34/", finale), finale)
    finally:
        b.chiudi_sessione_cdp()
        server.shutdown()
        server.server_close()

print("\n[7] browser_apri resta l'eccezione per il server locale")
import webbrowser

vecchio_open = webbrowser.open_new_tab
webbrowser.open_new_tab = lambda u: True
try:
    esito = b.tool_browser_apri().handler(url="http://127.0.0.1:3000/")
finally:
    webbrowser.open_new_tab = vecchio_open
check("apre il server locale nel browser dell'utente",
      "Browser aperto" in esito, esito[:200])


print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
