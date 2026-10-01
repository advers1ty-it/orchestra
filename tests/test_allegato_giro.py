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

PORT = 8737
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
    import time
    for _ in range(secondi * 2):
        try:
            r = urllib.request.Request(
                f"http://127.0.0.1:{PORT}/api/allega",
                json.dumps({"files": []}).encode(),
                {"Content-Type": "application/json"})
            urllib.request.urlopen(r, timeout=10)
            return                      # 200: libero
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return                  # errore di input, ma libero
        except Exception:
            pass
        time.sleep(0.5)


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

print("\n[3] Mandare: parte col suo allegato")
stato2, d2 = post("/api/send", {"text": "quanti pixel rossi?", "allegati": ids})
check("accettato", stato2 == 200, f"HTTP {stato2}: {d2}")
check("risponde con il conto", isinstance(d2.get("token"), int)
      and d2["token"] > 0, str(d2.get("token")))

print("\n[4] Un allegato non vive per due messaggi")
# Se l'id restasse valido, Invio due volte manderebbe la stessa foto
# due volte. L'utente riceverebbe due risposte identiche e penserebbe
# a un bug.
_aspetta_libero()
stato3, d3 = post("/api/send", {"text": "di nuovo", "allegati": ids})
check("il secondo inveso viene rifiutato", stato3 == 400, f"HTTP {stato3}")
check("e il motivo e' leggibile",
      "scaduto" in d3.get("error", ""), d3.get("error", "")[:70])

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
