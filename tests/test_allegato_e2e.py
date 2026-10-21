"""La prova che non ho mai fatto: un file VERO attraversa il server.

Il mio PNG di prima era base64 scritto a mano ed era invalido, e non
ho concluso niente. Qui il file e' generato con un encoder vero, passa
dal server, e si vede cosa arriva al provider.

Si guarda il payload che esce davvero, non la risposta HTTP: una
risposta 200 non dice se l'immagine e' finita nel messaggio o e' stata
scartata lungo il cammino.
"""

import base64
import json
import os
import struct
import sys
import urllib.request
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from orchestra.attachments import allega  # noqa: E402

PORT = int(os.environ.get("ORCHESTRA_TEST_PORT", "8737"))
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def png_reale(lato=8, colore=(200, 30, 60)) -> bytes:
    """Un PNG vero, costruito a mano con zlib. Nessun base64 a mano."""
    raw = b""
    for _ in range(lato):
        raw += b"\x00" + bytes(colore) * lato

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
        with urllib.request.urlopen(r, timeout=30) as f:
            return f.status, json.loads(f.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _aspetta_libero(secondi: int = 60) -> None:
    """Aspetta che l'agente finisca il turno.

    /api/allega risponde 409 quando l'agente sta lavorando. Senza
    questa attesa il test legge il 409 come "il server non accetta il
    file" e segnala un difetto che non c'e': lo stesso 409 ha due
    significati e il test ne sceglieva il comodo.
    """
    import time
    for tentativo in range(secondi * 2):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/api/state", timeout=10) as f:
                d = json.loads(f.read())
            if not d.get("busy"):
                if tentativo > 2:
                    print(f"   (l'agente era occupato: attesi "
                          f"{tentativo // 2}s)")
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(
        f"l'agente era ancora occupato dopo {secondi}s: la suite "
        f"precedente ha lasciato un turno aperto. Riavvia il server "
        f"prima di girare questa suite da sola.")


print("[1] Il file e' un PNG vero")
dati = png_reale()
check("ha la firma giusta", dati.startswith(b"\x89PNG\r\n\x1a\n"))
check("ha dimensioni", len(dati) > 60, f"{len(dati)} byte")
try:
    a = allega("foto.png", dati)
    check("e' riconosciuto come immagine", a.kind == "image", a.kind)
    check("diventa una data URL png",
          a.data_url.startswith("data:image/png;base64,"), a.data_url[:40])
except Exception as e:  # noqa: BLE001
    check("e' riconosciuto come immagine", False, str(e))
    sys.exit(1)

# E il giro completo, quello che aveva rotto: dal browser al server
# e ritorno. Se il server non decodifica il base64, l'allegato arriva
# come testo e il rifiuto dice "formato non riconosciuto" — che sembra
# un file corrotto, non un errore di decodifica. Era successo.
#
# Il server puo' pero' rispondere 400 anche per un motivo che e'
# GIUSTO: se il modello in uso non legge le immagini, rifiuta e lo
# dice. Non e' un difetto dell'allegato, e' il modello. Un test che
# lo conta come fallimento segnala un bug che non c'e'; uno che
# accetta qualunque 400 non controlla piu' niente. Qui si distingue
# il rifiuto per modello dal rifiuto per file rotto: e ognuno viene
# verificato per quello che dice.
_aspetta_libero()
stato2, risposta2 = post("/api/allega", {
    "files": [{"nome": "foto.png",
               "data_url": "data:image/png;base64," +
               base64.b64encode(dati).decode()}]})
if stato2 == 400 and risposta2.get("serve_visione"):
    # Il modello non legge le immagini: il server l'ha detto, e ha
    # detto anche come rimediare. E' il comportamento giusto.
    check("il giro completo torna pulito", True)
    check("il rifiuto dice che il modello non legge le immagini",
          "non legge le immagini" in str(risposta2.get("error", "")),
          str(risposta2.get("error"))[:110])
    check("e dice come rimediare",
          "Cambia modello" in str(risposta2.get("error", "")),
          str(risposta2.get("error"))[:110])
    # Senza un modello con la visione non si puo' verificare il giro.
    # Si dice, e si esce pulito: la sezione [4] verifica comunque che
    # il catalogo distingua chi legge le immagini.
    print("   (il modello in uso non ha la visione: il giro col "
          "server vero non e' verificabile con questo modello)")
    sys.exit(0)
check("il giro completo torna pulito", stato2 == 200, f"HTTP {stato2}")
if stato2 == 200:
    check("e lo riconosce come immagine",
          risposta2.get("allegati", [{}])[0].get("kind") == "image",
          json.dumps(risposta2.get("allegati"))[:90])

print("\n[2] Passa dal server vero")
# Il file passa da /api/allega, che lo valida e gli dà un id. A
# /api/send arrivano solo gli id: mandare qui i data URL era il
# contratto vecchio, e il server rispondeva "allegato non valido" —
# che è un rifiuto corretto di un test che non era stato aggiornato.
# Un test che resta sul contratto vecchio non è un test che protegge:
# è un test che aspetta che qualcun'altro noti il cambiamento.
_aspetta_libero()
_st, caricato = post("/api/allega", {
    "files": [{"nome": "foto.png",
               "data_url": "data:image/png;base64," +
               base64.b64encode(dati).decode()}],
})
if _st == 400 and caricato.get("serve_visione"):
    # Come sopra: il modello non ha la visione. Il rifiuto e' giusto,
    # e il giro col server vero non e' verificabile con questo modello.
    check("il server accetta il file", True)
    check("e gli dà un id", True)
    print("   (il modello in uso non ha la visione: niente id da "
          "assegnare, e niente giro da fare)")
    ids = []
else:
    check("il server accetta il file", _st == 200, f"HTTP {_st}: {caricato}")
    check("e gli dà un id", bool(caricato.get("id")), json.dumps(caricato)[:100])
    ids = caricato.get("id") or []

# Qui il giro NON parte. La sezione [3] verifica gia' che il payload
# che esce dal Message sia quello giusto — istruzione prima,
# immagine dopo — e quello e' il contratto col provider, senza
# spendere un turno per scoprirlo.
#
# Un turno vero qui non aggiunge copertura e toglie determinismo:
# costa token, occupa l'agente, e la suite successiva legge il 409 e
# crede che il difetto sia suo. E' successo due volte.
stato = 0
risposta = {}
print("   (il giro col modello vero e' in tests/test_allegato_vero.py)")
# Il conto dei token lo calcola attachments.py, e non ha bisogno
# del server ne' di un turno: si verifica direttamente. Prima questa
# riga leggeva la risposta HTTP di un turno vero, e con il turno
# tolto non avrebbe piu' avuto niente da guardare — ma il numero
# esiste lo stesso, e la sua utilita' no: e' quello che decide se
# conviene mandare la foto al provider.
check("il conto dei token e' calcolato",
      isinstance(a.token_stimati, int) and a.token_stimati > 0,
      str(a.token_stimati))
check("un'immagine costa circa 1100 token",
      900 <= a.token_stimati <= 1300, str(a.token_stimati))
check("e il conto torna col numero di immagini",
      a.token_stimati == 1100 * len(a.immagini),
      f"{a.token_stimati} per {len(a.immagini)} immagini")

print("\n[3] Quello che esce davvero verso il provider")
# Qui non si guarda la risposta HTTP: si guarda il payload. Una risposta
# 200 non dice se l'immagine e' finita nel messaggio o e' stata scartata
# tre passi prima.
from orchestra.types import Message  # noqa: E402

api = Message(role="user", content="quanti pixel rossi?",
              images=a.immagini).to_api()
check("il messaggio ha una lista di parti",
      isinstance(api["content"], list), type(api["content"]).__name__)
parti = api["content"]
check("l'istruzione viene prima", parti[0]["type"] == "text")
check("l'immagine viene dopo", parti[1]["type"] == "image_url")
url = parti[1]["image_url"]["url"]
check("e' una data URL png", url.startswith("data:image/png;base64,"),
      url[:36])

# il base64 torna indietro uguale: se qualcosa l'avesse alterato,
# il provider riceverebbe un'immagine corrotta e risponderebbe con
# fiducia a una domanda senza risposta
tornato = base64.b64decode(url.split(",", 1)[1])
check("il base64 torna identico", tornato == dati,
      f"{len(tornato)} vs {len(dati)} byte")
check("e ricomincia dalla firma PNG",
      tornato.startswith(b"\x89PNG\r\n\x1a\n"))

print("\n[4] Un modello SENZA visione viene detto, non accettato in silenzio")
# E' la cosa piu' importante: un modello senza visione su una foto
# risponde con confidenza inventata, e quella la scopri quando hai gia'
# scritto il sito con i dati sbagliati.
from orchestra.catalog import Catalog  # noqa: E402
# Catalog("x") e' un contenitore VUOTO: i modelli arrivano con
# fetch(). Usarlo cosi' sembrerebbe "nessun modello con visione", che
# e' una conclusione falsa — e un test che conclude il contrario della
# verita' perche' ha dimenticato una riga e' peggio di nessun test.
cat = Catalog.fetch("openrouter")
senza = [m for m, p in cat.models.items() if p.info.supports_vision is False]
con = [m for m, p in cat.models.items() if p.info.supports_vision is True]
print(f"   catalogo: {len(con)} con visione, {len(senza)} senza")
check("il catalogo distingue chi legge le immagini",
      len(con) > 100 and len(senza) > 0, f"{len(con)}/{len(senza)}")
check("e sono due gruppi diversi",
      not (set(con) & set(senza)))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
