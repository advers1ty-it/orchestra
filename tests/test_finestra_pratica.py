"""La compattazione deve AVVENIRE, e al punto giusto.

Il difetto visto in uso: "non l'ho mai vista funzionare, con nessun
modello" — e dopo qualche ora sulla stessa conversazione l'agente
cominciava a rispondere fuori bersaglio o a chiudere il turno senza
usare un tool.

Non era rotta: era irraggiungibile. Il limite veniva dal 75% della
finestra del modello, quindi su un modello da 1M di token la soglia
stava a 786.432. Misurato sulla sessione viva dell'app: 317 messaggi,
~145.000 token, `compactions: 0`. La compattazione non scattava mai, e
il contesto cresceva senza fine — che e' esattamente la condizione in
cui un modello smette di usare i tool e risponde a caso.

Qui si verifica:
  1. la regola della soglia (`limite_compattazione`);
  2. che una conversazione come quella vera venga davvero compattata
     col tetto pratico, e NON col vecchio limite (il difetto);
  3. che compattare piu' volte non accumuli riepiloghi su riepiloghi;
  4. il PUNTO IN CUI LA REGOLA VIENE APPLICATA: `allinea_finestra`
     sull'app vera, con un catalogo finto. La regola pura non basta —
     il difetto stava in quella riga, che sovrascriveva il limite con il
     75% della finestra senza che nessun test la guardasse.

Nessuna rete, nessuna API: si guida `fit_context` sui messaggi e
l'app si costruisce senza `__init__`, con catalogo e sessione finti.
"""

import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from orchestra.context import (  # noqa: E402
    RIEPILOGO_TAG, TETTO_PRATICO, count_tokens, fit_context,
    limite_compattazione,
)
from orchestra.types import Message, ToolCall  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# ---------------------------------------------------------------------------
# [1] La regola della soglia
# ---------------------------------------------------------------------------
print("\n[1] La soglia di compattazione")

check("finestra da 1M: si compatta a 60k",
      limite_compattazione(1_048_576) == TETTO_PRATICO,
      f"{limite_compattazione(1_048_576)}")
check("786.432 non e' piu' il limite (era il difetto)",
      limite_compattazione(1_048_576) != 786_432)
check("finestra da 200k: sempre 60k",
      limite_compattazione(200_000) == TETTO_PRATICO,
      f"{limite_compattazione(200_000)}")
check("finestra da 32k: 24k (75% della finestra)",
      limite_compattazione(32_000) == 24_000,
      f"{limite_compattazione(32_000)}")
check("finestra da 8k: 6k", limite_compattazione(8_000) == 6_000,
      f"{limite_compattazione(8_000)}")
check("finestra sconosciuta: 60k, non 120k",
      limite_compattazione(0) == TETTO_PRATICO,
      f"{limite_compattazione(0)}")
check("scelta dell'utente rispettata",
      limite_compattazione(1_048_576, tetto=120_000) == 120_000,
      f"{limite_compattazione(1_048_576, tetto=120_000)}")
check("ma mai oltre la finestra del modello",
      limite_compattazione(32_000, tetto=200_000) == 24_000,
      f"{limite_compattazione(32_000, tetto=200_000)}")
check("su un modello minuscolo il minimo sta dentro la finestra",
      limite_compattazione(2_000) == 2_000,
      f"{limite_compattazione(2_000)}")


# ---------------------------------------------------------------------------
# Una conversazione come quella vera: tanti turni, risultati tool grossi E
# testo lungo (un agente che spiega, non solo che legge file). Serve il
# testo perche' la fase 1 non lo tocca: cosi' si arriva davvero alla fase 2.
# ~220k token: piu' o meno una sessione dopo qualche ora di lavoro.
# ---------------------------------------------------------------------------
GIRI = 120


def conversazione(giri: int = GIRI, risultato: int = 3000) -> list[Message]:
    msgs = [
        Message(role="system", content="SYS " + "regole di lavoro. " * 40),
        Message(role="user", content="sistema il sito sentrya: parte dal restyling"),
    ]
    for i in range(giri):
        msgs.append(Message(role="user", content=f"passo {i}: " + "u" * 400))
        msgs.append(Message(
            role="assistant", content="",
            tool_calls=[ToolCall(id=f"c{i}", name="read_file",
                                 arguments='{"path":"index.html"}')]))
        msgs.append(Message(role="tool", content="x" * risultato,
                            name="read_file", tool_call_id=f"c{i}"))
        msgs.append(Message(role="assistant", content=f"fatto {i}: " + "y" * 3000))
    return msgs


def orfani(msgs: list[Message]) -> list[str]:
    attesi: set[str] = set()
    fuori: list[str] = []
    for m in msgs:
        if m.role == "assistant":
            attesi |= {tc.id for tc in m.tool_calls}
        elif m.role == "tool":
            if m.tool_call_id in attesi:
                attesi.discard(m.tool_call_id)
            else:
                fuori.append(str(m.tool_call_id))
    return fuori


print("\n[2] La conversazione vera: col vecchio limite non succede niente")
msgs = conversazione()
prima = count_tokens(msgs)
check("la conversazione supera i 100k token", prima > 100_000, f"{prima}")
vecchio = fit_context(msgs, limit=786_432, keep_recent=8)
check("col limite al 75% di 1M non pota niente",
      vecchio["tools_pruned"] == 0, f"potati={vecchio['tools_pruned']}")
check("...e non fonde niente",
      vecchio["history_merged"] == 0, f"fusi={vecchio['history_merged']}")
check("...e i token restano identici",
      count_tokens(msgs) == prima, f"{count_tokens(msgs)} vs {prima}")

print("\n[3] Col tetto pratico la compattazione avviene")
msgs2 = conversazione()
report = fit_context(msgs2, limit=TETTO_PRATICO, keep_recent=8)
check("pota i risultati tool vecchi", report["tools_pruned"] > 0,
      f"potati={report['tools_pruned']}")
check("fonde la storia vecchia", report["history_merged"] > 0,
      f"fusi={report['history_merged']}")
check("scende sotto il limite", report["tokens_after"] <= TETTO_PRATICO,
      f"{report['tokens_after']} > {TETTO_PRATICO}")
check("il system prompt resta in testa", msgs2[0].role == "system")
check("il riepilogo apre la storia",
      (msgs2[1].content or "").startswith(RIEPILOGO_TAG),
      repr((msgs2[1].content or "")[:40]))
check("gli ultimi messaggi sono intatti",
      msgs2[-1].content.startswith(f"fatto {GIRI - 1}"),
      repr(msgs2[-1].content[:30]))
check("nessun tool result orfano", not orfani(msgs2), f"{orfani(msgs2)[:5]}")
check("una conversazione corta non si tocca",
      fit_context(conversazione(giri=2), limit=TETTO_PRATICO,
                  keep_recent=8)["history_merged"] == 0)

print("\n[4] Compattare piu' volte non accumula riepiloghi")
msgs3 = conversazione()
for giro in range(3):
    fit_context(msgs3, limit=TETTO_PRATICO, keep_recent=8)
    # la sessione continua: altri turni dopo la compattazione
    for i in range(40):
        msgs3.append(Message(role="user", content=f"ancora {giro}-{i}"))
        msgs3.append(Message(role="assistant", content="z" * 1200))
    fit_context(msgs3, limit=TETTO_PRATICO, keep_recent=8)

riepiloghi = [m for m in msgs3 if (m.content or "").startswith(RIEPILOGO_TAG)]
check("un solo riepilogo, non uno per compattazione",
      len(riepiloghi) == 1, f"{len(riepiloghi)}")
check("il riepilogo e' in testa",
      (msgs3[1].content or "").startswith(RIEPILOGO_TAG))
check("un solo system prompt",
      sum(1 for m in msgs3 if m.role == "system") == 1)
check("nessun tool result orfano dopo tre compattazioni",
      not orfani(msgs3), f"{orfani(msgs3)[:5]}")
check("il contesto resta sotto il limite",
      count_tokens(msgs3) <= TETTO_PRATICO, f"{count_tokens(msgs3)}")

# ---------------------------------------------------------------------------
# [5] Il percorso vero: la soglia applicata alla sessione
#
# `limite_compattazione` puo' essere giusta e non essere usata: prima di
# questa correzione `allinea_finestra` calcolava il limite per conto suo
# (75% della finestra) e nessun test guardava quella riga. Qui si chiama
# il metodo vero di `OrchestraApp` su un'app costruita senza `__init__`,
# con un catalogo finto (niente rete) e una sessione che parte dal
# vecchio default di 120k — cosi' "non e' cambiato niente" si vede.
# ---------------------------------------------------------------------------
print("\n[5] allinea_finestra sull'app (catalogo finto)")

from orchestra import webapp as webapp_mod  # noqa: E402
from orchestra.catalog import Catalog, ModelInfo, ModelProfile  # noqa: E402

MODELLO_1M = "vendor/modello-1m"
MODELLO_32K = "vendor/modello-32k"


def catalogo(*modelli: tuple[str, int]) -> Catalog:
    cat = Catalog("finto")
    for mid, finestra in modelli:
        cat.models[mid] = ModelProfile(
            info=ModelInfo(id=mid, context_length=finestra))
    return cat


class AppFinta(webapp_mod.OrchestraApp):
    """L'app vera, senza rete e senza dati dell'utente.

    Non si chiama `__init__`: servono solo `env`, `catalog` e la sessione,
    e costruire un'app intera leggerebbe `.env`, chiavi e cronologia. Il
    METODO pero' e' quello di produzione, non una copia.
    """

    def __init__(self, env: dict, cataloghi: dict, limit: int = 120_000):
        self.env = dict(env)
        self._cataloghi = cataloghi
        self.session = SimpleNamespace(
            agent=SimpleNamespace(
                config=SimpleNamespace(context_limit=limit)))

    @property
    def catalog(self):
        return self._cataloghi.get("principale")

    def _catalogo_scelto(self, provider):
        return self._cataloghi.get(provider)


cat_1m = catalogo((MODELLO_1M, 1_048_576))
cat_32k = catalogo((MODELLO_32K, 32_000))

app = AppFinta({"ORCHESTRA_MODEL": MODELLO_1M}, {"principale": cat_1m})
check("si passa dal metodo vero dell'app",
      app.allinea_finestra.__func__ is webapp_mod.OrchestraApp.allinea_finestra)
valore = app.allinea_finestra()
check("finestra da 1M: applica 60k alla sessione",
      app.session.agent.config.context_limit == TETTO_PRATICO,
      f"context_limit={app.session.agent.config.context_limit}")
check("...e restituisce lo stesso valore",
      valore == app.session.agent.config.context_limit, f"{valore}")
check("...e non torna a 786.432", valore != 786_432, f"{valore}")

app_env = AppFinta({"ORCHESTRA_MODEL": MODELLO_1M,
                    "ORCHESTRA_CONTEXT_LIMIT": "120000"},
                   {"principale": cat_1m})
check("ORCHESTRA_CONTEXT_LIMIT rispettata (e applicata)",
      app_env.allinea_finestra() == 120_000
      and app_env.session.agent.config.context_limit == 120_000,
      f"{app_env.session.agent.config.context_limit}")

app_piccolo = AppFinta({"ORCHESTRA_MODEL": MODELLO_32K},
                       {"principale": cat_32k})
check("modello da 32k: 24k, applicato",
      app_piccolo.allinea_finestra() == 24_000
      and app_piccolo.session.agent.config.context_limit == 24_000,
      f"{app_piccolo.session.agent.config.context_limit}")

app_stretta = AppFinta({"ORCHESTRA_MODEL": MODELLO_32K,
                        "ORCHESTRA_CONTEXT_LIMIT": "200000"},
                       {"principale": cat_32k})
check("scelta utente oltre la finestra: resta dentro (24k)",
      app_stretta.allinea_finestra() == 24_000,
      f"{app_stretta.allinea_finestra()}")

# La sessione parte dal vecchio default: se il metodo non facesse niente,
# questo controllo sarebbe rosso.
app_ignoto = AppFinta({"ORCHESTRA_MODEL": "non/esiste"},
                      {"principale": cat_1m})
check("modello fuori catalogo: 60k, non il vecchio 120k",
      app_ignoto.allinea_finestra() == TETTO_PRATICO
      and app_ignoto.session.agent.config.context_limit == TETTO_PRATICO,
      f"{app_ignoto.session.agent.config.context_limit}")

app_altro = AppFinta(
    {"ORCHESTRA_MODEL": "vendor/modello-2",
     "ORCHESTRA_PROVIDER": "altro"},
    {"principale": cat_1m,
     "altro": catalogo(("vendor/modello-2", 200_000))})
check("modello nel catalogo del servizio scelto: 60k",
      app_altro.allinea_finestra() == TETTO_PRATICO,
      f"{app_altro.allinea_finestra()}")

app_rotta = AppFinta({"ORCHESTRA_MODEL": MODELLO_1M,
                      "ORCHESTRA_CONTEXT_LIMIT": "tanti"},
                     {"principale": cat_1m})
check("valore non numerico: si ignora, vale 60k",
      app_rotta.allinea_finestra() == TETTO_PRATICO,
      f"{app_rotta.allinea_finestra()}")

app_senza_cat = AppFinta({"ORCHESTRA_MODEL": MODELLO_1M},
                         {"principale": None})
check("catalogo che non si apre: 60k, non un crash",
      app_senza_cat.allinea_finestra() == TETTO_PRATICO,
      f"{app_senza_cat.allinea_finestra()}")

app_senza_sess = AppFinta({"ORCHESTRA_MODEL": MODELLO_1M},
                          {"principale": cat_1m})
app_senza_sess.session = None
check("senza sessione non solleva", app_senza_sess.allinea_finestra() == TETTO_PRATICO)

# L'argomento esplicito e' la strada del cambio modello: deve vincere
# sulla variabile d'ambiente del modello attuale.
app_cambio = AppFinta({"ORCHESTRA_MODEL": MODELLO_1M},
                      {"principale": catalogo((MODELLO_1M, 1_048_576),
                                              (MODELLO_32K, 32_000))})
check("allinea_finestra(nuovo_modello) usa la finestra di quello",
      app_cambio.allinea_finestra(MODELLO_32K) == 24_000
      and app_cambio.session.agent.config.context_limit == 24_000,
      f"{app_cambio.session.agent.config.context_limit}")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
