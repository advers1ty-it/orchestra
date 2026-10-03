"""Ogni provider che Orchestra supporta deve comparire nella lista.

La lista dei servizi gratuiti era scritta a mano e non coincideva piu'
con quella vera: consigliava Google e Hugging Face, che Orchestra NON
supporta — la chiave che mettevi non sarebbe mai stata usata — e non
citava NVIDIA e Together, che sono due dei servizi che funzionano.

Nove supportati, sette citati, due inventati. E il difetto peggiore è
la prima direzione, non la seconda: un servizio consigliato che
Orchestra non supporta è peggio di un servizio non citato. Si fa una
chiave, la si mette, e non capita niente — senza che nessuno dica
perché.

Questo test è la parte che mancava: non controlla che la lista sia
bella, controlla che coincida con `KNOWN_PROVIDERS`. Le due liste non
possono divergere senza che qualcosa diventi rosso.

E controlla anche l'altra direzione, quella che sembra innocua: un
provider supportato e non citato è un servizio che funziona e che
nessuno ti fa scoprire.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.keys import FREE_SERVICES  # noqa: E402
from orchestra.providers import KNOWN_PROVIDERS  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


citati = {x["id"] for x in FREE_SERVICES}
supportati = set(KNOWN_PROVIDERS)

print("[1] Nulla di consigliato che Orchestra non supporti")
fantasmi = sorted(citati - supportati)
check("nessun provider immaginario", not fantasmi,
      f"non supportati: {fantasmi} — la chiave non verrebbe mai usata")

print("\n[2] Nessun provider supportato che non compaia")
nascosti = sorted(supportati - citati)
check("nessun provider senza voce", not nascosti,
      f"funzionano ma nessuno li fa scoprire: {nascosti}")

print("\n[3] Le due liste coincidono")
check("stesso numero", len(citati) == len(supportati),
      f"citati {len(citati)}, supportati {len(supportati)}")
check("stessi nomi", citati == supportati,
      f"solo nella lista: {sorted(citati - supportati)}; "
      f"solo nel codice: {sorted(supportati - citati)}")

print("\n[4] Ogni voce ha i campi che il pannello usa")
CAMPI = ("id", "nome", "costo", "cosa", "requisiti", "come")
for v in FREE_SERVICES:
    mancanti = [c for c in CAMPI if not v.get(c)]
    check(f"{v['id']}: ha tutti i campi", not mancanti,
          f"mancano: {mancanti}")

print("\n[5] E dice la verita' su cosa serve")
# Un servizio con `chiave: True` deve dirlo, e la nota finale deve
# spiegare che 'gratis' vuol dire 'un piano gratis con limiti'.
for v in FREE_SERVICES:
    if v.get("chiave"):
        check(f"{v['id']}: dichiara che serve la chiave",
              "chiave" in v.get("requisiti", "").lower()
              or "serve" in v.get("requisiti", "").lower(),
              v.get("requisiti", "")[:60])
    else:
        check(f"{v['id']}: non dice 'serve una chiave'",
              "serve una chiave" not in v.get("requisiti", "").lower(),
              v.get("requisiti", "")[:60])

print("\n[6] Nessuno si dichiara gratis senza condizione")
for v in FREE_SERVICES:
    c = v.get("costo", "").lower()
    if "computer" in c:
        continue
    check(v['id'] + ': il gratis ha una condizione',
          any(w in c for w in ("limiti", "con chiave", "quasi", "a pagamento")),
          v.get("costo", ""))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)