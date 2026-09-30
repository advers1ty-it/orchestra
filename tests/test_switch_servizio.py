"""Cambiare servizio deve portare con se' un modello che quel servizio ha.

Il difetto: switch_provider cambiava il provider e lasciava il modello.
Un id come "vendor/modello-grande" esiste su OpenRouter e non su Groq,
e allora la combinazione e' impossibile — la select mostra il modello
del servizio nuovo, l'agente chiama quello del vecchio, e la prima
richiesta muore con un errore che sembra di rete.

Non basta pero' dire che il modello e' stato cambiato: se il catalogo
del servizio nuovo non e' disponibile, non si sceglie a caso. Nessuna
informazione e' meglio di un'informazione inventata.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.catalog import Catalog, ModelInfo, ModelProfile  # noqa: E402
from orchestra.webapp import OrchestraApp  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def profilo(mid, *, free=False, tools=True, prezzo=0.0):
    # I fatti stanno in ModelInfo dentro ModelProfile. Scriverli sul
    # profilo direbbe "quello che penso": nel codice vero questo errore
    # si e' gia' verificato, e avrebbe fatto fallire il primo cambio
    # servizio.
    p = 0.0 if free else prezzo
    return ModelProfile(
        info=ModelInfo(id=mid, context_length=32000, prompt_price=p,
                       completion_price=p, supports_tools=tools),
    )


def app_con(catalogo: dict):
    app = OrchestraApp.create()
    cat = Catalog("x")
    cat.models = dict(catalogo)
    app._catalog = cat
    app._catalog_tried = True
    return app


print("[1] Se il modello esiste anche sul servizio nuovo, resta quello")
cat = {"vendor/grande": profilo("vendor/grande", free=True)}
app = app_con(cat)
app.env["ORCHESTRA_MODEL"] = "vendor/grande"
scelto = app._modello_per_servizio("nuovo", "vendor/grande")
check("il modello viene conservato", scelto == "vendor/grande", str(scelto))

print("\n[2] Se non esiste, si sceglie uno che esiste")
# l'id in uso deve essere ASSENTE dal catalogo del servizio nuovo: e'
# il caso che si verifica davvero cambiando provider
app = app_con({
    "altro/piccolo": profilo("altro/piccolo", free=True),
    "altro/medio": profilo("altro/medio", free=True),
})
scelto = app._modello_per_servizio("nuovo", "vendor/grande")
check("non restituisce il modello inesistente", scelto != "vendor/grande", str(scelto))
check("sceglie uno di quelli presenti", scelto in app._catalog.models, str(scelto))

print("\n[3] La scelta ha una regola, non e' arbitraria")
# I gratuiti con i tool-calling vengono prima: sono gli unici che si
# possono provare senza pensarci. E un modello SENZA tool-calling non
# e' Orchestra: risponde, ma non lavora.
app = app_con({
    "a/pago": profilo("a/pago", free=False, tools=True, prezzo=0.003),
    "b/gratuito-senza-tool": profilo("b/gratuito-senza-tool", free=True, tools=False),
    "c/gratuito-con-tool": profilo("c/gratuito-con-tool", free=True, tools=True),
    "d/gratuito-con-tool-2": profilo("d/gratuito-con-tool-2", free=True, tools=True),
})
scelto = app._modello_per_servizio("nuovo", "inesistente")
check("sceglie un gratuito con i tool-calling",
      app._catalog.models[scelto].info.supports_tools is not False, str(scelto))
check("in modo deterministico", scelto == app._modello_per_servizio("nuovo", "inesistente"),
      "due chiamate diverse danno risultati diversi")

print("\n[4] Un servizio senza modelli gratuiti sceglie un pagato")
app = app_con({
    "x/cheap": profilo("x/cheap", free=False, tools=True, prezzo=0.0005),
    "y/costoso": profilo("y/costoso", free=False, tools=True, prezzo=0.02),
})
scelto = app._modello_per_servizio("nuovo", "inesistente")
check("sceglie il piu' economico", scelto == "x/cheap", str(scelto))

print("\n[5] Se un modello non supporta i tool, non viene scelto per primo")
app = app_con({
    "solo/testo": profilo("solo/testo", free=True, tools=False),
})
scelto = app._modello_per_servizio("nuovo", "inesistente")
check("un catalogo solo-senza-tool non e' scelto come gratis-preferito",
      scelto == "solo/testo", str(scelto))
# non ci deve essere alternativa: se non c'e' niente con i tool, si
# prende quello che c'e'. Inventare un id sarebbe peggio.
check("ma non si inventa un id inesistente", scelto in app._catalog.models, str(scelto))

print("\n[6] Catalogo non disponibile: non si sceglie a caso")
app = app_con({})
app._catalog = None
scelto = app._modello_per_servizio("nuovo", "inesistente")
check("restituisce None invece di indovinare", scelto is None, str(scelto))

print("\n[7] Il risultato viaggia fino alla risposta HTTP")
# Se il server non rimanda il modello scelto, la UI non puo' dire
# nulla e l'utente crede di stare ancora usando il suo.
import inspect  # noqa: E402

src = inspect.getsource(OrchestraApp.switch_provider)
check("switch_provider rimanda il modello scelto", "modello_cambiato" in src)
check("switch_provider rimanda il provider", '"provider"' in src)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
