"""Ogni campo che il frontend legge, il backend deve esporlo.

Un campo che non esiste in JavaScript non da errore: da `undefined`,
e `undefined.punteggio` e' `undefined`, e un `if` sul undefined e'
falsamente vero quanto "non c'e' niente da mostrare". Il menu resta
muto e sembra una decisione, non un difetto.

E' successo: il menu non mostrava punteggi, il backend li inviava in
un campo chiamato `punteggio_unico`, e il frontend ne cercava uno
chiamato `totale`. Nessun errore da nessuna parte — solo un menu
vuoto, e io che davo la colpa alla logica invece che al nome.

Il test e' meccanico perche' il difetto e' meccanico: non si puo'
verificare "il frontend mostra il punteggio" senza un browser, ma si
puo' verificare che ogni nome che il frontend cerca esista davvero
nella risposta del server. E il resto segue da li'.
"""

import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "orchestra", "web")
BASE = os.environ.get(
    "ORCHESTRA_BASE",
    f"http://127.0.0.1:{os.environ.get('ORCHESTRA_TEST_PORT', '8737')}")

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def api(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------
print("[1] Ogni campo che punteggioPerScope legge, il server lo manda")

try:
    modelli = api("/api/models")
except Exception as e:  # noqa: BLE001
    print(f"  server non raggiungibile su {BASE}: {e}")
    print("  avvia `orchestra web` e rilancia")
    sys.exit(1)

lista = modelli.get("models") or []
check("il server risponde con i modelli", len(lista) > 100, str(len(lista)))

js = open(os.path.join(WEB, "core.js"), encoding="utf-8").read()
m = re.search(r"function punteggioPerScope\(.*?\n\}", js, re.S)
check("la funzione c'e' nel bundle sorgente", m is not None)
corpo = m.group(0) if m else ""

# i campi che la funzione legge: m.<nome>
letti = sorted(set(re.findall(r"\bm\.([A-Za-z_][A-Za-z0-9_]*)", corpo)))
print(f"     campi letti dalla funzione: {letti}")
esistenti = set(lista[0].keys()) if lista else set()
for campo in letti:
    check(f"il server espone '{campo}'", campo in esistenti,
          f"disponibili: {sorted(esistenti)}")

print("\n[2] E i punteggi ci sono davvero, non solo il campo")
con = [x for x in lista if x.get("punteggio_unico")]
check("qualcuno e' misurato", len(con) > 0, str(len(con)))
if con:
    primo = con[0]
    pu = primo["punteggio_unico"]
    check("e ha un punteggio numerico",
          isinstance(pu.get("punteggio"), (int, float)),
          str(type(pu.get("punteggio"))))
    check("e le prove", "prove" in pu, str(sorted(pu))[:120])
    # Il numero che il menu mostra deve stare fra 0 e 100: sotto 0
    # sembra un errore, sopra 100 e' sbagliato.
    v = pu["punteggio"]
    check("ed e' fra 0 e 100", 0 <= v <= 100, str(v))

print("\n[3] Ogni modello misurato deve poterlo mostrare")
# Se un modello ha i punteggi per categoria ma non il punteggio unico,
# il menu resta muto anche se i numeri ci sono: i due vengono da posti
# diversi e possono non coincidere.
cat_solo = [x for x in lista
            if x.get("scores") and not x.get("punteggio_unico")]
check("nessun modello e' a meta' fra i due",
      len(cat_solo) == 0,
      f"{len(cat_solo)} modelli hanno scores ma non punteggio_unico")

print("\n[4] Il bundle servito contiene il campo giusto")
try:
    with urllib.request.urlopen(BASE + "/app.js", timeout=30) as r:
        bundle = r.read().decode("utf-8")
    check("punteggio_unico nel bundle servito",
          "punteggio_unico" in bundle)
    check("e il nome sbagliato non c'e'", "m.totale" not in bundle,
          "il bundle legge ancora m.totale")
except Exception as e:  # noqa: BLE001
    check("il bundle si scarica", False, str(e)[:80])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)