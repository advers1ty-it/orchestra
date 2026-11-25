"""`scarica`: stesso web, stesso tetto, stesso confine.

Il punto del tool e' togliere `curl` dalla shell senza aprire un secondo
buco: un host locale, un redirect verso localhost, un peer privato o un
file oltre 1.200.000 byte devono fermarsi prima della scrittura. Il
percorso passa da `_safe_path`, come `write_file`: fuori dalla root non
si scrive senza permesso, e `.env` resta vietato anche dentro.

Il server HTTP e' finto. Nessuna richiesta esce dal test, e ogni caso
controlla anche che il file di destinazione NON sia stato creato.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

WORK = tempfile.mkdtemp(prefix="orch-scarica-")
HOME = tempfile.mkdtemp(prefix="orch-scarica-home-")
os.environ["ORCHESTRA_ROOT"] = WORK
os.environ["ORCHESTRA_HOME"] = HOME

from orchestra import piano as piano_mod  # noqa: E402
from orchestra.tools import (  # noqa: E402
    _PROFILI,
    default_registry,
    set_permission_gate,
)
from orchestra.tools import scarica as s  # noqa: E402
from orchestra.tools import web as web_mod  # noqa: E402
from orchestra.tools.web import _RedirectPubblico  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def percorso(rel: str) -> str:
    return os.path.join(WORK, rel)


def esiste(rel: str) -> bool:
    return os.path.exists(percorso(rel))


class _Headers:
    def __init__(self, valori=None) -> None:
        self._v = {str(k).lower(): str(v)
                   for k, v in (valori or {}).items()}

    def get(self, nome: str, default=None):
        return self._v.get(str(nome).lower(), default)


class _Risposta:
    def __init__(self, dati: bytes = b"", *,
                 url: str = "https://example.com/file.bin",
                 tipo: str = "application/octet-stream",
                 lunghezza: int | None = None) -> None:
        self.dati = dati
        self.url = url
        self.pos = 0
        self.letta = 0
        valori = {"Content-Type": tipo}
        if lunghezza is not None:
            valori["Content-Length"] = str(lunghezza)
        self.headers = _Headers(valori)

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = len(self.dati) - self.pos
        out = self.dati[self.pos:self.pos + n]
        self.pos += len(out)
        self.letta += len(out)
        return out

    def geturl(self) -> str:
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, risposta: _Risposta) -> None:
        self.risposta = risposta

    def open(self, req, timeout=0):
        return self.risposta


@contextlib.contextmanager
def finto(risposta: _Risposta, *, rete=None, peer: bool = True):
    """Sostituisce rete, peer e opener per la durata del blocco."""
    visti: dict = {}
    vecchio_rete = s._rete_locale
    vecchio_peer = s._peer_pubblico
    vecchio_build = urllib.request.build_opener

    s._rete_locale = rete or (lambda host: False)
    s._peer_pubblico = lambda resp: peer

    def build(*gestori):
        visti["gestori"] = gestori
        return _Opener(risposta)

    urllib.request.build_opener = build
    try:
        yield visti
    finally:
        s._rete_locale = vecchio_rete
        s._peer_pubblico = vecchio_peer
        urllib.request.build_opener = vecchio_build


set_permission_gate(None)
r = default_registry()
t = r.get("scarica")
h = t.handler

print("\n[1] Il tool e' registrato, e il tetto e' quello di web_leggi")
check("scarica e' registrato", "scarica" in r)
check("e' attivo", t in r.active)
check("lo schema richiede url e path",
      set(t.schema["required"]) == {"url", "path"},
      str(t.schema["required"]))
check("il tetto e' condiviso con web_leggi",
      s.TETTO_RISPOSTA_BYTE == web_mod.TETTO_RISPOSTA_BYTE == 1_200_000,
      f"{s.TETTO_RISPOSTA_BYTE} / {web_mod.TETTO_RISPOSTA_BYTE}")
check("e' in tutti i profili",
      all("scarica" in p for p in _PROFILI.values()),
      str({k: "scarica" in v for k, v in _PROFILI.items()}))
check("e' bloccato in modalita' piano",
      "scarica" in piano_mod.TOOL_CHE_CAMBIANO)

print("\n[2] La rete locale resta chiusa, come in web_leggi")
for url in ("http://127.0.0.1:9/file.bin",
            "http://localhost:9/file.bin",
            "http://10.0.0.1/file.bin",
            "http://192.168.1.1/file.bin",
            "http://169.254.169.254/file.bin"):
    esito = h(url=url, path="locale.bin")
    check(f"blocca {url.split('/')[2]}", "rete locale bloccato" in esito,
          esito[:160])
check("non ha creato il file locale", not esiste("locale.bin"))

esito = h(url="file:///etc/passwd", path="schema.bin")
check("blocca gli schemi non http", "Schema non ammesso" in esito, esito[:160])
check("e non crea niente", not esiste("schema.bin"))

try:
    _RedirectPubblico().redirect_request(
        None, None, 302, "Found", {}, "http://127.0.0.1/file.bin")
    check("un redirect verso localhost viene fermato", False, "nessuna eccezione")
except urllib.error.HTTPError as e:
    check("un redirect verso localhost viene fermato", e.code == 302, str(e))

print("\n[3] Il peer e l'URL finale vengono guardati dopo la connessione")
with finto(_Risposta(b"contenuto pubblico"), peer=False):
    esito = h(url="https://example.com/file.bin", path="peer.bin")
check("un peer locale non restituisce il corpo",
      "rete locale" in esito.lower() and not esiste("peer.bin"),
      esito[:200])

with finto(_Risposta(b"contenuto pubblico", url="http://127.0.0.1/finale"),
           rete=lambda host: host == "127.0.0.1"):
    esito = h(url="https://example.com/file.bin", path="finale.bin")
check("un URL finale locale viene fermato",
      "rete locale" in esito.lower() and not esiste("finale.bin"),
      esito[:200])

print("\n[4] Il confine dei percorsi e' quello di write_file")
fuori = tempfile.mkdtemp(prefix="orch-scarica-fuori-")
try:
    with finto(_Risposta(b"x")):
        try:
            h(url="https://example.com/file.bin",
              path=os.path.join(fuori, "fuori.bin"))
            check("fuori dalla root non scrive", False, "nessuna eccezione")
        except ValueError as e:
            check("fuori dalla root non scrive", "fuori dal root" in str(e),
                  str(e))
    check("e non ha creato il file fuori", not os.path.exists(
        os.path.join(fuori, "fuori.bin")))

    with finto(_Risposta(b"x")):
        try:
            h(url="https://example.com/file.bin", path=".env")
            check(".env resta vietato", False, "nessuna eccezione")
        except PermissionError as e:
            check(".env resta vietato", "protetto" in str(e), str(e))
    check("e non ha creato .env", not esiste(".env"))
finally:
    shutil.rmtree(fuori, ignore_errors=True)

os.makedirs(percorso("cartella"), exist_ok=True)
with finto(_Risposta(b"x")):
    esito = h(url="https://example.com/file.bin", path="cartella")
check("una directory non viene usata come file",
      "DIRECTORY" in esito and os.path.isdir(percorso("cartella")), esito[:160])

print("\n[5] Il tetto byte vale prima e dopo la lettura")
risposta = _Risposta(b"", lunghezza=s.TETTO_RISPOSTA_BYTE + 1)
with finto(risposta):
    esito = h(url="https://example.com/grande.bin", path="grande-dichiarato.bin")
check("un Content-Length oltre il tetto ferma subito",
      "TROPPO GRANDE" in esito and risposta.letta == 0,
      f"{esito[:160]} letto={risposta.letta}")
check("e non scrive il file", not esiste("grande-dichiarato.bin"))

risposta = _Risposta(b"x" * (s.TETTO_RISPOSTA_BYTE + 1))
with finto(risposta):
    esito = h(url="https://example.com/grande.bin", path="grande-letto.bin")
check("un corpo oltre il tetto viene fermato",
      "TROPPO GRANDE" in esito and not esiste("grande-letto.bin"),
      esito[:160])
check("e non legge oltre un byte dal tetto",
      risposta.letta <= s.TETTO_RISPOSTA_BYTE + 1, str(risposta.letta))

print("\n[6] Un download pubblico viene scritto davvero")
dati = b"\x89PNG\r\n\x1a\ncontenuto-del-file"
with finto(_Risposta(dati, tipo="image/png")) as visti:
    esito = h(url="https://example.com/logo.png",
              path="media/logo.png")
check("il file esiste", esiste("media/logo.png"))
with open(percorso("media/logo.png"), "rb") as f:
    scritto = f.read()
check("i byte sono quelli, non una decodifica", scritto == dati, repr(scritto[:40]))
check("la cartella e' stata creata", os.path.isdir(percorso("media")))
check("il risultato dice byte e tipo",
      f"{len(dati)} byte" in esito and "image/png" in esito, esito)
check("il download usa il guardiano dei redirect",
      _RedirectPubblico in visti.get("gestori", ()),
      str(visti.get("gestori")))

esito = h(url="", path="vuoto.bin")
check("un URL vuoto lo dice", "URL" in esito, esito)
esito = h(url="https://example.com/x", path="")
check("un percorso vuoto lo dice", "Dove salvo" in esito, esito)

shutil.rmtree(WORK, ignore_errors=True)
shutil.rmtree(HOME, ignore_errors=True)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
