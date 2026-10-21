"""La prova col modello VERO, da lanciare a mano.

Non e' nella suite perche' costa un turno di inferenza e risponde a
una domanda che solo tu puoi fare: "quanti pixel rossi ci sono?"
richiede un modello che guardi davvero le immagini, e quello lo
scegli tu.

    python3 tests/test_allegato_vero.py

Se il modello non ha visione lo dice, e il test fallisce — che e' il
motivo per cui va lanciato a mano: e' l'unica verifica che dicono se
il passaggio delle immagini funziona davvero, e non si puo' fare con
un modello qualsiasi perche' il risultato dipende dal modello.

Prima scegli il modello. Con uno senza visione fallisce sempre, e
sembra un difetto dell'allegato.
"""

import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import urllib.error
import urllib.request

BASE = f"http://127.0.0.1:{os.environ.get('ORCHESTRA_TEST_PORT', '8737')}"
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def png(lato=64, colore=(200, 30, 60)) -> bytes:
    """Un quadrato di un solo colore, generato: niente base64 a mano.

    Il base64 scritto a mano ha rotto due test in questa sessione e
    ogni volta sembrava un difetto del codice.
    """
    raw = b"".join(b"\x00" + bytes(colore) * lato for _ in range(lato))

    def pezzo(tipo: bytes, dati: bytes) -> bytes:
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + pezzo(b"IHDR", struct.pack(">IIBBBBB", lato, lato, 8, 2, 0, 0, 0))
            + pezzo(b"IDAT", zlib.compress(raw))
            + pezzo(b"IEND", b""))


def post(body):
    r = urllib.request.Request(BASE + "/api/send" if False else BASE + "/api/allega",
                               json.dumps(body).encode(),
                               {"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as f:
        return json.loads(f.read())


print("Verifica col modello vero")
print("=" * 60)

try:
    with urllib.request.urlopen(BASE + "/api/state", timeout=10) as f:
        stato = json.loads(f.read())
except Exception as e:
    print(f"  Server non raggiungibile ({e}).")
    print("  Avvialo con:  python3 -m orchestra.cli web --no-browser")
    sys.exit(1)

modello = stato.get("modello") or "(non dichiarato)"
print(f"\n  Modello in uso: {modello}")

try:
    from orchestra.catalog import Catalog
    cat = Catalog.fetch(stato.get("provider") or "openrouter")
    info = cat.models.get(modello)
    if info is not None and info.info.supports_vision is False:
        print(f"  ATTENZIONE: {modello} NON ha visione.")
        print("  Il test fallira' e il motivo sara' il modello, non l'allegato.")
        print("  Cambia modello dal menu in alto e rilancia.\n")
except Exception as e:
    print(f"  (catalogo non raggiungibile: {e})")

print("\n[1] Carico l'immagine")
import base64
url = "data:image/png;base64," + base64.b64encode(png()).decode()
d = post({"files": [{"nome": "rosso.png", "data_url": url}]})
check("accettata", d.get("ok"), str(d)[:100])
check("ha un id", bool(d.get("id")), str(d.get("id")))
ids = d.get("id") or []
check("il conto e' vicino a 1100 token",
      900 <= d.get("token", 0) <= 1300, str(d.get("token")))

print("\n[2] Chiedo al modello")
print(f"  mando: «quanti pixel rossi ci sono?» su un quadrato {64}x{64} di RGB(200,30,60)")
r = urllib.request.Request(
    BASE + "/api/send",
    json.dumps({"text": "quanti pixel rossi ci sono? "
                        "Rispondi solo con il numero.",
                "allegati": ids}).encode(),
    {"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(r, timeout=120) as f:
        invio = json.loads(f.read())
    check("il messaggio e' partito", invio.get("ok"), str(invio)[:100])
except urllib.error.HTTPError as e:
    check("il messaggio e' partito", False, f"HTTP {e.code}: {e.read()[:100]}")

print("\n  Aspetto la risposta (puo' mettere qualche minuto)…")
risposta = ""
for _ in range(120):
    time.sleep(2)
    try:
        with urllib.request.urlopen(BASE + "/api/state", timeout=10) as f:
            st = json.loads(f.read())
        if not st.get("busy"):
            break
    except Exception:
        pass
else:
    check("la risposta arriva", False, "timeout: l'agente lavora ancora")

# l'ultimo messaggio dell'assistente
try:
    with urllib.request.urlopen(BASE + "/api/state", timeout=10) as f:
        st = json.loads(f.read())
    log = st.get("log") or []
    for evento in reversed(log):
        testo = (evento.get("text") or "") if isinstance(evento, dict) else ""
        if evento.get("kind") == "assistant" and testo:
            risposta = testo
            break
except Exception as e:
    print(f"  (non riesco a leggere la risposta: {e})")

print(f"\n  Cosa ha risposto:\n  {risposta or '(nessuna risposta trovata)'}\n")

if risposta:
    # Non si giudica la risposta: quello che conta e' che il modello
    # abbia guardato l'immagine e non abbia detto di non poterla vedere.
    non_vede = any(parola in risposta.lower() for parola in
                   ("non posso vedere", "non posso leggere", "non sono in grado",
                    "non ho accesso", "non posso analizzare", "no posso",
                    "can't see", "cannot see"))
    check("il modello non dice di non poterla vedere", not non_vede,
          "il modello non ha visione: cambia modello")
    ha_numero = any(ch.isdigit() for ch in risposta)
    check("ha risposto con un numero", ha_numero, risposta[:80])
else:
    check("il modello non dice di non poterla vedere", False,
          "nessuna risposta: guarda la chat")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
    print("\nSe il fallimento e' 'il modello non ha visione', non e' un")
    print("difetto dell'allegato: cambia modello e rilancia.")
sys.exit(1 if FAIL else 0)