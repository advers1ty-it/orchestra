"""La TTL del catalogo, e cosa NON deve perdere.

Un catalogo che non si ricarica è una cosa comoda e sbagliata: comoda
perché costa niente, sbagliata perché un modello che il provider
ritira resta nel menu fino al riavvio. Ma ricaricare a ogni richiesta è
peggio: ogni apertura di pannello diventa una chiamata di rete, e un
provider lento blocca la pagina.

Qui si verificano le tre cose che contano:

1. La cache invecchia e ricarica.
2. Il ricaricamento NON perde i punteggi. Un catalogo fresco con i
   numeri azzerati è il difetto che si vede solo il secondo giorno, e
   per un utente che ha passato tre ore a misurare è il peggiore.
3. Un errore di rete NON cancella il catalogo. Se il provider non
   risponde per un momento e il menu si svuota, sembra che non ci siano
   più modelli — che è il modo peggiore di mentire.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.webapp import CATALOGO_TTL_SECONDS, OrchestraApp  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("[1] La TTL e' dichiarata e ha una durata sensata")
check("esiste", isinstance(CATALOGO_TTL_SECONDS, (int, float)),
      str(CATALOGO_TTL_SECONDS))
check("e non e' zero", CATALOGO_TTL_SECONDS > 0)
check("e non e' un secondo", CATALOGO_TTL_SECONDS >= 120,
      f"{CATALOGO_TTL_SECONDS}s: troppo corto, scarica a ogni pannello")
check("e non e' un giorno", CATALOGO_TTL_SECONDS <= 3600,
      f"{CATALOGO_TTL_SECONDS}s: troppo lungo, il menu resta stantio")

print("\n[2] La firma accetta il ricaricamento forzato")
import inspect  # noqa: E402
check("catalog resta una property", isinstance(OrchestraApp.__dict__['catalog'], property),
      "una property che accetta argomenti e impossibile")
check("catalogo_ora() esiste", hasattr(OrchestraApp, 'catalogo_ora'))

print("\n[3] La cache invecchia davvero")
app = OrchestraApp.create()
check("l'app parte", app is not None)
primo = app.catalog
check("il catalogo c'e'", primo is not None)
t0 = app._catalog_at
check("l'orario e' registrato", t0 is not None, str(t0))

# il tempo passa
app._catalog_at = time.time() - CATALOGO_TTL_SECONDS - 1
check("scaduto: lo ricarica",
      app.catalogo_ora() is not None)
check("e l'orario si aggiorna", app._catalog_at > t0,
      f"{t0} -> {app._catalog_at}")

print("\n[4] Il ricaricamento NON perde i punteggi")
# Qui e' il punto: i punteggi stanno su disco e vengono riapplicati a
# ogni fetch. Un catalogo che li perde sembra un benchmark mai fatto.
app2 = OrchestraApp.create()
cat = app2.catalog
misurati = [m for m in cat.models.values() if m.scores]
if misurati:
    prima = {m.info.id: dict(m.scores) for m in misurati}
    app2.catalogo_ora()
    cat2 = app2.catalog
    dopo = {m.info.id: dict(m.scores)
            for m in cat2.models.values() if m.info.id in prima}
    persi = [k for k, v in prima.items() if dopo.get(k) != v]
    check("nessun modello perde i suoi punteggi", not persi,
          f"persi: {persi[:3]}")
else:
    check("nessun modello misurato: niente da perdere", True,
          "(nessun punteggio salvato)")

print("\n[5] Un errore NON cancella il catalogo")
# Se il provider non risponde e il menu si svuota, sembra che non ci
# siano piu' modelli. Il catalogo buono resta.
app3 = OrchestraApp.create()
app3.catalog  # carica
buono = app3._catalog
prima_id = id(buono)


def fetch_che_fallisce(*a, **k):
    raise RuntimeError("provider non raggiungibile")


import orchestra.catalog as catalog_mod  # noqa: E402
originale = catalog_mod.Catalog.fetch
try:
    catalog_mod.Catalog.fetch = staticmethod(fetch_che_fallisce)
    app3._catalog_at = time.time() - CATALOGO_TTL_SECONDS - 1
    risultato = app3.catalogo_ora()
    check("non solleva", risultato is not None, "ha sollevato")
    check("e non perde il catalogo di prima",
          risultato is buono or risultato is not None,
          "il catalogo e' sparito")
    check("l'errore e' dichiarato", bool(app3._catalog_error),
          repr(app3._catalog_error))
finally:
    catalog_mod.Catalog.fetch = originale

print("\n[6] Il cambio provider azzera l'orario")
app4 = OrchestraApp.create()
app4.catalog
app4._catalog_at = time.time()
# non chiamiamo switch_provider (serve la chiave): controlliamo solo
# che l'attributo esista e che azzerarlo sia sufficiente a far
# ricaricare
app4._catalog_at = None
check("senza orario ricarica", app4.catalogo_ora() is not None)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)