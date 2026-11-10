"""Il tunnel e il DNS rebinding non devono passare per traffico locale.

Il caso che ha motivato il file: cloudflared inoltra a `127.0.0.1`, e il
gate considerava locale ogni richiesta da loopback. La URL pubblica
`trycloudflare.com` aveva quindi accesso completo senza token. Lo stesso
gate lasciava passare una pagina su un dominio qualsiasi che, dopo il
primo caricamento, risolveva a `127.0.0.1` (DNS rebinding): `Origin` e
`Host` coincidono, l'IP e' loopback, e il token non veniva mai chiesto.

Qui si usa un server HTTP vero e si mandano Host e header di proxy
diversi da quelli che `urllib` sceglierebbe da solo.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time

_TMP = tempfile.mkdtemp(prefix="webapp-remoto-")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.environ["ORCHESTRA_ROOT"] = os.path.join(_TMP, "root")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)
os.makedirs(os.environ["ORCHESTRA_ROOT"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import LLMResponse, webapp  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class Provider:
    name = "remoto-demo"
    model = "m"

    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="ok", model="m")


app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app.env = {"ORCHESTRA_MODEL": "m", "ORCHESTRA_PROVIDER": "remoto-demo"}
app.ready = True
app.error = ""
app.remoto_attivo = True
app.token_remoto = "token-di-prova-remoto"
app.session = Session(provider=Provider(), registry=default_registry(),
                      system_prompt="SYS",
                      config=webapp.LoopConfig(max_iterations=2))
webapp.Handler.app = app

httpd = webapp.OrchestraServer(("127.0.0.1", 0), webapp.Handler)
PORT = httpd.server_address[1]
app.porta = PORT
threading.Thread(target=httpd.serve_forever, daemon=True).start()

HOST_LOCALE = f"127.0.0.1:{PORT}"
HOST_TUNNEL = "abc.trycloudflare.com"


def richiesta(metodo, percorso, host, *, intestazioni=None, dati=None):
    """Una richiesta con Host scelto da noi (urllib non lo permette)."""
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    conn.putrequest(metodo, percorso, skip_host=True, skip_accept_encoding=True)
    conn.putheader("Host", host)
    conn.putheader("Connection", "close")
    for k, v in (intestazioni or {}).items():
        conn.putheader(k, v)
    corpo = None
    if dati is not None:
        corpo = json.dumps(dati).encode("utf-8")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(len(corpo)))
    conn.endheaders(corpo)
    r = conn.getresponse()
    letto = r.read()
    esito = (r.status, letto, dict(r.getheaders()))
    conn.close()
    return esito


def attendi(secondi=10.0):
    fine = time.time() + secondi
    while time.time() < fine:
        try:
            stato, _, _ = richiesta("GET", "/api/state", HOST_LOCALE)
            if stato == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.05)
    return False


try:
    check("il server di prova risponde", attendi())

    print("\n[1] Il loopback vero passa, il resto no")
    stato, _, _ = richiesta("GET", "/api/state", HOST_LOCALE)
    check("Host loopback senza token: 200", stato == 200, str(stato))

    stato, _, _ = richiesta("GET", "/api/state", f"evil.example:{PORT}")
    check("Host estraneo senza token: 401", stato == 401, str(stato))

    stato, _, _ = richiesta(
        "GET", "/api/state", HOST_TUNNEL,
        intestazioni={"CF-Connecting-IP": "203.0.113.9",
                      "Cf-Ray": "8f0-test", "X-Forwarded-Proto": "https"})
    check("tunnel senza token: 401", stato == 401, str(stato))

    stato, _, _ = richiesta(
        "GET", "/api/state", HOST_TUNNEL,
        intestazioni={"CF-Connecting-IP": "203.0.113.9",
                      "Authorization": "Bearer token-di-prova-remoto"})
    check("tunnel con Bearer: 200", stato == 200, str(stato))

    # Un header di inoltro da loopback toglie la fiducia anche se Host e'
    # loopback: e' il caso cloudflared, che parla al server da 127.0.0.1.
    stato, _, _ = richiesta(
        "GET", "/api/state", HOST_LOCALE,
        intestazioni={"CF-Connecting-IP": "203.0.113.9"})
    check("header di proxy da loopback: 401", stato == 401, str(stato))

    print("\n[2] Il login via tunnel funziona, e il cookie e' Secure")
    stato, corpo, hdr = richiesta(
        "POST", "/api/login", HOST_TUNNEL,
        intestazioni={"Origin": f"https://{HOST_TUNNEL}",
                      "X-Forwarded-Proto": "https"},
        dati={"token": "token-di-prova-remoto"})
    cookie = hdr.get("Set-Cookie", "")
    check("login via tunnel: 200", stato == 200, f"{stato} {corpo[:80]}")
    check("il cookie e' HttpOnly", "HttpOnly" in cookie, cookie)
    check("il cookie e' SameSite=Lax", "SameSite=Lax" in cookie, cookie)
    check("il cookie e' Secure in HTTPS", "Secure" in cookie, cookie)

    stato, _, hdr = richiesta(
        "POST", "/api/login", HOST_LOCALE,
        intestazioni={"Origin": f"http://{HOST_LOCALE}"},
        dati={"token": "token-di-prova-remoto"})
    cookie = hdr.get("Set-Cookie", "")
    check("login locale: 200", stato == 200, str(stato))
    check("in HTTP il cookie non e' Secure", "Secure" not in cookie, cookie)

    print("\n[3] La stessa-origine resta necessaria")
    stato, _, _ = richiesta(
        "POST", "/api/system", HOST_TUNNEL,
        intestazioni={"Origin": "https://sito-malevolo.example",
                      "Authorization": "Bearer token-di-prova-remoto"},
        dati={"prompt": "CATTIVO"})
    check("Origin estraneo: 403", stato == 403, str(stato))
finally:
    httpd.shutdown()
    httpd.server_close()
    shutil.rmtree(_TMP, ignore_errors=True)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
