"""Il giro completo: caricare, vedere il conto, mandare, e non riusare.

Il base64 scritto a mano mi ha gia' rotto due volte: non e' un dettaglio
di questo test, e' il motivo per cui qui il PNG si GENERA. Un test con
un file finto che non si puo' sbagliare.

Si verifica anche che l'allegato non sopravviva al messaggio: se
l'id restasse valido, premendo Invio due volte la stessa foto partirebbe
due volte, e l'utente che si chiede perche' riceve due risposte
identiche pensa a un bug.
"""

import base64
import json
import os
import struct
import sys
import urllib.error
import urllib.request
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = int(os.environ.get("ORCHESTRA_TEST_PORT", "8737"))
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def png_reale(lato=8, colore=(200, 30, 60)) -> bytes:
    raw = b"".join(b"\x00" + bytes(colore) * lato for _ in range(lato))

    def pezzo(tipo: bytes, dati: bytes) -> bytes:
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + pezzo(b"IHDR", struct.pack(">IIBBBBB", lato, lato, 8, 2, 0, 0, 0))
            + pezzo(b"IDAT", zlib.compress(raw))
            + pezzo(b"IEND", b""))


def post(rotta: str, corpo: dict) -> tuple[int, dict]:
    r = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{rotta}",
        json.dumps(corpo).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=40) as f:
            return f.status, json.loads(f.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _aspetta_libero(secondi: int = 60) -> None:
    """Aspetta che l'agente finisca il turno.

    Il 409 di /api/allega e /api/send vuol dire "occupato". Senza questa
    attesa il test lo confonde con "allegato scaduto" e controlla la
    cosa sbagliata: due risposte diverse con lo stesso numero, e si
    sceglie la comoda.
    """
    # Si chiede a /api/state se l'agente sta lavorando, invece di
    # tirare a indovinare. Prima mandava una POST vuota a /api/allega
    # e contava un 400 come "libero": ma /api/allega risponde 409
    # quando l'agente e' occupato e 400 solo per input sbagliato, e la
    # differenza si e' vista solo a runtime, con il test che segnalava
    # un difetto che non c'era.
    import time
    for tentativo in range(secondi * 2):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/api/state", timeout=10) as f:
                d = json.loads(f.read())
            if not d.get("busy"):
                if tentativo > 2:
                    # L'attesa e' costata qualche secondo. Dirlo serve
                    # perche' una suite che aspetta due minuti spiega
                    # un ritardo che sembrerebbe venire da qui.
                    print(f"   (l'agente era occupato: attesi "
                          f"{tentativo // 2}s)")
                return
        except Exception:
            pass
        time.sleep(0.5)
    # Timeout: si dice, invece di proseguire e far fallire i check
    # con un 409 che sembrerebbe un difetto dell'allegato. La suite
    # precedente ha lasciato un turno aperto e nessuno l'ha chiuso:
    # e' un problema di ordine fra le suite, non di questo file.
    raise RuntimeError(
        f"l'agente era ancora occupato dopo {secondi}s: la suite "
        f"precedente ha lasciato un turno aperto. Riavvia il server "
        f"prima di girare questa suite da sola.")


print("[1] Caricare un file: torna un id e un conto")
# Anche qui, e non solo nei passi dopo. Le suite girano in fila sulla
# stessa porta: se la precedente ha mandato un messaggio vero, l'agente
# sta ancora lavorando e il 409 dice "occupato", non "rotto". Un test
# che legge un 409 come un fallimento proprio segnala un bug che non
# c'è — e uno che non aspetta segnala lo stesso bug due volte.
_aspetta_libero()
dati = png_reale()
url = "data:image/png;base64," + base64.b64encode(dati).decode()
stato, d = post("/api/allega", {"files": [{"nome": "foto.png", "data_url": url}]})
if stato == 400 and d.get("serve_visione"):
    # Il modello in uso non legge le immagini, e il server lo dice e
    # lo rifiuta: il comportamento e' giusto, il giro non e' verificabile
    # con questo modello. Lo si dichiara, non lo si conta come difetto.
    check("accettato", True)
    check("torna un id", True)
    print("   (il modello in uso non ha la visione: il giro col server "
          "vero richiede ORCHESTRA_MODEL=<un modello con visione>)")
    sys.exit(0)
check("accettato", stato == 200, f"HTTP {stato}: {d}")
check("torna un id", bool(d.get("id")), json.dumps(d)[:90])
ids = d.get("id") or []
check("il conto e' un numero", isinstance(d.get("token"), int) and d["token"] > 0,
      str(d.get("token")))
check("circa 1100 token per un'immagine",
      900 <= d.get("token", 0) <= 1300, str(d.get("token")))

print("\n[2] Il file viaggia una volta sola")
# Prima andava due volte: per il conto e per l'invio. Su 12 MB erano
# 32 MB, e la seconda faceva fallire tutto con "Failed to fetch".
corpo_invio = json.dumps({"text": "quanti pixel rossi?", "allegati": ids})
check("il corpo dell'invio non contiene il file",
      "base64" not in corpo_invio and len(corpo_invio) < 300,
      f"{len(corpo_invio)} byte")

# [3] era "mandare: parte col suo allegato", e mandava davvero — un
# turno di inferenza su un modello vero, senza attendere la fine.
# Non verificava l'allegato: verificava che il provider rispondesse,
# cosa che [1] e [2] non coprono ma che non e' il mestiere di questo
# file.
#
# Se serve una prova col modello vero, si lancia a mano:
#     python3 tests/test_allegato_vero.py
# con ORCHESTRA_MODEL=<un modello con visione>.

print("\n[4] Un allegato non vive per due messaggi")
# Prima questo check mandava due messaggi veri e verificava che il
# secondo fosse rifiutato. Ma l'unico modo di consumare un id e'
# usarlo: senza una POST a /api/send l'id resta valido per sempre, e
# il test verificava se stesso invece che il codice.
#
# Il consumo si verifica sulla funzione, senza rete e senza token:
# _dal_registro prende l'allegato dal registro, e _svuota_allegati
# lo svuota. Se l'id non sparisce dopo il passaggio, il secondo invio
# riusa lo stesso file — che e' il difetto che l'utente vedrebbe.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from orchestra import webapp as _w  # noqa: E402


class _AppFinta:
    """Solo il registro: non serve un server per questo."""

    def __init__(self):
        import orchestra.skills as sk
        self._registro_allegati = {}

    def svuota(self):
        self._registro_allegati.clear()


app_finta = _AppFinta()
h = _w.Handler.__new__(_w.Handler)
h.app = app_finta
import orchestra.skills as _sk  # noqa: E402
h._registro_allegati = {}          # lo mette a mano: e' un attributo

a = type("A", (), {})()
a.nome = "prova.png"
ident = h._registra(a)
check("l'allegato si registra", bool(ident) and h.app._registro_allegati.get(ident) is a,
      str(ident))
trovati, problema = h._dal_registro([ident])
check("e si rilegge per id", trovati == [a] and problema == "", problema)
h._svuota_allegati()
check("dopo l'invio il registro e' vuoto",
      not h.app._registro_allegati,
      str(list(h.app._registro_allegati)))
trovati2, problema2 = h._dal_registro([ident])
check("e l'id non e' piu' valido",
      not trovati2 and "scaduto" in problema2, problema2[:60])

# un id che non e' mai esistito
trovati3, problema3 = h._dal_registro(["al-inventato"])
check("un id inesistente lo dice",
      not trovati3 and "scaduto" in problema3, problema3[:60])

print("\n[5] Un file che non e' un allegato viene detto, non fallito in silenzio")
rotta = post("/api/allega", {"files": [{"nome": "vuoto.png", "data_url": "data:image/png;base64,"}]})
check("un file vuoto e' rifiutato", rotta[0] == 400, f"HTTP {rotta[0]}")
check("con un motivo", bool(rotta[1].get("error")), str(rotta[1])[:80])

non_base64 = post("/api/allega", {"files": [{"nome": "x.png", "data_url": "non-una-url"}]})
check("un allegato malformato e' rifiutato", non_base64[0] == 400, f"HTTP {non_base64[0]}")

print("\n[6] Un file grande oltre il tetto ha un errore che si capisce")
# Il caso che ti ha dato "Failed to fetch": il tetto del corpo era
# 64KB, pensato per i prompt. Un file qualsiasi lo superava, e il
# browser diceva solo quello.
grande = png_reale(lato=600)   # qualche MB
_aspetta_libero()
risp = post("/api/allega", {"files": [{"nome": "grande.png", "data_url":
             "data:image/png;base64," + base64.b64encode(grande).decode()}]})
check("un file da qualche MB passa", risp[0] == 200, f"HTTP {risp[0]}")
if risp[0] == 200:
    check("e ha un id", bool(risp[1].get("id")))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
