"""Fallback manuale: la catena contiene solo quello che l'utente ha scelto.

Il difetto che questi test difendono: la catena veniva da `DEFAULT_CHAINS`,
una tabella scritta a mano che nomina servizi che chi usa Orchestra puo'
non avere (Together, Cerebras) e non conosce quelli che ha davvero (nous,
google). Misurato sul campo:

  - con `nous` come primario la catena restava di UN elemento: nessun
    ripiego, mai, e l'errore del modello arrivava dritto all'utente;
  - con OpenRouter come primario i tentativi si spendevano su Groq,
    Together e Cerebras — senza chiave fallisce il `build_provider`, non
    la chiamata — e il turno finiva con "Nessun provider disponibile"
    invece che con l'errore vero.

Da qui la catena e' primario + i ripieghi scelti a mano, al massimo tre, e
spenta la catena e' il solo primario.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "ORCHESTRA_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.fallback import (  # noqa: E402
    MAX_RIPIEGHI, catena_manuale, config_da_env, ripieghi_da_stringa,
    stringa_da_ripieghi,
)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


# --------------------------------------------------------------- la catena
print("\n[1] La catena e' quella scelta, non la tabella")

cat = catena_manuale("nous", "meituan/longcat-2.5:free", [], attivo=False)
check("spento: la catena e' il solo primario", len(cat) == 1,
      f"entry: {[(e.provider, e.model) for e in cat]}")
check("spento: il primario e' quello in uso",
      (cat[0].provider, cat[0].model) == ("nous", "meituan/longcat-2.5:free"),
      f"{cat[0].provider}/{cat[0].model}")

# Questo e' il caso misurato: openrouter sta in DEFAULT_CHAINS, e la catena
# automatica aggiungeva Groq/Together/Cerebras che l'utente non ha.
cat = catena_manuale("openrouter", "cohere/north-mini-code:free", [],
                     attivo=False)
check("spento: nessun servizio altrui entra in catena",
      [e.provider for e in cat] == ["openrouter"],
      f"entry: {[e.provider for e in cat]}")

ripieghi = [("nvidia", "nvidia/llama-3.1-nemotron-70b-instruct"),
            ("openrouter", "cohere/north-mini-code:free")]
cat = catena_manuale("nous", "meituan/longcat-2.5:free", ripieghi, attivo=True)
check("acceso: primario primo, poi i ripieghi in ordine",
      [e.provider for e in cat] == ["nous", "nvidia", "openrouter"],
      f"entry: {[e.provider for e in cat]}")
check("acceso: ogni entry porta il SUO modello",
      [e.model for e in cat] == ["meituan/longcat-2.5:free",
                                 "nvidia/llama-3.1-nemotron-70b-instruct",
                                 "cohere/north-mini-code:free"],
      f"modelli: {[e.model for e in cat]}")

molti = [("nvidia", f"m{i}") for i in range(5)]
check("il quarto ripiego non entra (massimo tre)",
      len(catena_manuale("nous", "a", molti, attivo=True)) == 1 + MAX_RIPIEGHI,
      f"entry: {len(catena_manuale('nous', 'a', molti, attivo=True))}")

check("spento: i ripieghi scelti non vengono usati lo stesso",
      len(catena_manuale("nous", "a", ripieghi, attivo=False)) == 1)

# --------------------------------------------------------------- il formato
print("\n[2] Il formato nel .env")

check("il modello con la barra non diventa un provider",
      ripieghi_da_stringa("openrouter/openai/gpt-oss-120b")
      == [("openrouter", "openai/gpt-oss-120b")],
      str(ripieghi_da_stringa("openrouter/openai/gpt-oss-120b")))
check("le righe vuote e gli spazi non sporcano la lista",
      ripieghi_da_stringa(" nvidia/a , , openrouter/b ") ==
      [("nvidia", "a"), ("openrouter", "b")],
      str(ripieghi_da_stringa(" nvidia/a , , openrouter/b ")))
check("senza barra la voce si scarta, non si indovina",
      ripieghi_da_stringa("soloUnModello") == [])

giro = [("nvidia", "meta/llama"), ("openrouter", "x")]
check("stringa e lista fanno il giro intero",
      ripieghi_da_stringa(stringa_da_ripieghi(giro)) == giro,
      stringa_da_ripieghi(giro))

print("\n[3] Lo stato letto dal .env")
attivo, rip = config_da_env({})
check("senza chiavi: spento e nessun ripiego", attivo is False and rip == [])
attivo, rip = config_da_env({"ORCHESTRA_FALLBACK": "on",
                             "ORCHESTRA_FALLBACK_MODELS": "nvidia/a"})
check("on accende e legge la lista", attivo is True and rip == [("nvidia", "a")])
attivo, _ = config_da_env({"ORCHESTRA_FALLBACK": "off"})
check("off spegne", attivo is False)

# --------------------------------------------------- l'errore che arriva
print("\n[4] Con il fallback spento arriva l'errore VERO")

from orchestra.agent import Agent, LoopConfig  # noqa: E402
from orchestra.providers import ProviderError  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402


class ProviderMorto:
    """Un provider che risponde 401, come il token Nous scaduto."""

    name = "nous"
    model = "meituan/longcat-2.5:free"

    def chat_stream(self, *a, **k):
        raise ProviderError("nous: HTTP 401 — API key is invalid", status=401)

    def chat(self, *a, **k):
        raise ProviderError("nous: HTTP 401 — API key is invalid", status=401)


ag = Agent(ProviderMorto(), default_registry(), "SYS", LoopConfig())
ag.fallback_chain = catena_manuale("nous", "meituan/longcat-2.5:free", [],
                                   attivo=False)
ag._fallback_state = None
eventi = []
ag._emit = lambda kind, **d: eventi.append(kind)  # type: ignore[assignment]

try:
    ag._call_model_with_retry()
    check("un 401 senza ripieghi solleva", False, "non ha sollevato niente")
except ProviderError as e:
    check("un 401 senza ripieghi solleva l'errore del provider",
          "401" in str(e), str(e))
    check("e non lo maschera con 'Nessun provider disponibile'",
          "Nessun provider disponibile" not in str(e), str(e))
except RuntimeError as e:
    check("un 401 senza ripieghi solleva l'errore del provider", False, str(e))
check("nessun provider di ripiego viene tentato",
      "fallback_attempt" not in eventi or eventi.count("fallback_attempt") == 1,
      str(eventi))

# ---------------------------------------- il salvataggio (senza server vero)
print("\n[5] Salvare la scelta: .env e catena viva")

import tempfile  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import orchestra.webapp as webapp_mod  # noqa: E402
from orchestra.providers import load_env  # noqa: E402

cartella = tempfile.mkdtemp()
percorso_env = os.path.join(cartella, ".env")
with open(percorso_env, "w", encoding="utf-8") as f:
    f.write("OPENROUTER_API_KEY=prova\nORCHESTRA_MODEL=vecchio\n")

vecchio_env_path = webapp_mod.ENV_PATH
webapp_mod.ENV_PATH = percorso_env

try:
    # L'app senza __init__: qui si prova il salvataggio, non l'avvio.
    app = object.__new__(webapp_mod.OrchestraApp)
    app.env = {"ORCHESTRA_PROVIDER": "nous", "ORCHESTRA_MODEL": "m"}
    agente = SimpleNamespace(
        provider=SimpleNamespace(name="nous", model="meituan/longcat-2.5:free"),
        fallback_chain=[], _fallback_state="sporca")
    app.session = SimpleNamespace(agent=agente)

    avviso = app.imposta_fallback(True, [("nvidia", "nvidia/x"),
                                         ("openrouter", "cohere/y")])
    scritto = load_env(percorso_env)
    check("acceso: la scelta finisce nel .env",
          scritto.get("ORCHESTRA_FALLBACK") == "on"
          and scritto.get("ORCHESTRA_FALLBACK_MODELS")
          == "nvidia/nvidia/x,openrouter/cohere/y", str(scritto))
    check("acceso: le altre righe restano",
          scritto.get("OPENROUTER_API_KEY") == "prova"
          and scritto.get("ORCHESTRA_MODEL") == "vecchio", str(scritto))
    check("acceso: la catena viva si ricostruisce",
          [e.provider for e in agente.fallback_chain]
          == ["nous", "nvidia", "openrouter"],
          str([e.provider for e in agente.fallback_chain]))
    check("acceso: lo stato vecchio dei tentativi si butta via",
          agente._fallback_state is None)
    check("acceso: nessun avviso di salvataggio", avviso == "", avviso)

    app.imposta_fallback(False, [("nvidia", "nvidia/x")])
    scritto = load_env(percorso_env)
    check("spento: resta scritto spento", scritto.get("ORCHESTRA_FALLBACK") == "off")
    check("spento: la catena torna al solo primario",
          len(agente.fallback_chain) == 1
          and agente.fallback_chain[0].provider == "nous",
          str([e.provider for e in agente.fallback_chain]))
finally:
    webapp_mod.ENV_PATH = vecchio_env_path
    for nome in os.listdir(cartella):
        os.remove(os.path.join(cartella, nome))
    os.rmdir(cartella)

# ------------------------------------------------ le rotte, senza server
print("\n[6] Le rotte /api/fallback: validazione e servizi")

from orchestra.rotte_modelli import RotteModelli  # noqa: E402


class _Rotta:
    """Il minimo che serve a un gestore: `_json` e l'app."""

    def __init__(self, env):
        self.salvati = []
        self.app = SimpleNamespace(
            env=env,
            imposta_fallback=lambda attivo, rip: self.salvati.append(
                (attivo, list(rip))) or "")

    def _json(self, dati, codice=200):
        self.out = (dati, codice)


def _post(env, corpo):
    r = _Rotta(env)
    RotteModelli._r_post_fallback(r, "/api/fallback", corpo, None)
    return r


r = _post({"NVIDIA_API_KEY": "x"},
          {"attivo": True, "ripieghi": [{"provider": "nvidia", "model": "a"},
                                        {"provider": "openrouter", "model": "b"}]})
check("POST accetta due ripieghi",
      r.out[1] == 200 and r.salvati[0][0] is True
      and r.salvati[0][1] == [("nvidia", "a"), ("openrouter", "b")], str(r.out))

r = _post({}, {"attivo": True, "ripieghi": [{"provider": "nvidia", "model": str(i)}
                                            for i in range(4)]})
check("POST rifiuta il quarto ripiego", r.out[1] == 400 and not r.salvati,
      str(r.out))

r = _post({}, {"attivo": True, "ripieghi": [{"provider": "pippo", "model": "a"}]})
check("POST rifiuta un servizio sconosciuto", r.out[1] == 400 and not r.salvati,
      str(r.out))

r = _post({}, {"attivo": True, "ripieghi": [{"provider": "nvidia", "model": ""}]})
check("POST rifiuta una riga senza modello", r.out[1] == 400, str(r.out))

r = _post({}, {"attivo": False, "ripieghi": [{"provider": "", "model": ""}]})
check("POST ignora la riga lasciata vuota",
      r.out[1] == 200 and r.salvati[0] == (False, []), str(r.out))

# I servizi proposti sono SOLO quelli che possono rispondere: una riga di
# fallback su un provider senza chiave fallisce sempre.
r = _Rotta({"NVIDIA_API_KEY": "x", "ORCHESTRA_FALLBACK": "on",
            "ORCHESTRA_FALLBACK_MODELS": "nvidia/a"})
RotteModelli._r_get_fallback(r, "/api/fallback", {}, None)
check("GET: solo i servizi con chiave", r.out[0]["servizi"] == ["nvidia"],
      str(r.out[0]["servizi"]))
check("GET: stato e ripieghi scritti", r.out[0]["attivo"] is True
      and r.out[0]["ripieghi"] == [{"provider": "nvidia", "model": "a"}],
      str(r.out[0]))

# ------------------------------------------------------- la CLI, non solo il web
print("\n[7] Anche `orchestra chat` legge la stessa configurazione")

from orchestra import cli as cli_mod  # noqa: E402

base = {"ORCHESTRA_PROVIDER": "nous",
        "ORCHESTRA_MODEL": "meituan/longcat-2.5:free",
        "NOUS_API_KEY": "chiave-finta-per-costruire-il-provider"}

ag_cli = cli_mod._build_agent(dict(base))
check("CLI spenta: niente tabella automatica",
      [e.provider for e in ag_cli.fallback_chain] == ["nous"],
      str([e.provider for e in ag_cli.fallback_chain]))

ag_cli = cli_mod._build_agent(dict(base, ORCHESTRA_FALLBACK="on",
                                   ORCHESTRA_FALLBACK_MODELS="nvidia/a,openrouter/b"))
check("CLI accesa: primario + i ripieghi scelti",
      [(e.provider, e.model) for e in ag_cli.fallback_chain]
      == [("nous", "meituan/longcat-2.5:free"), ("nvidia", "a"),
          ("openrouter", "b")],
      str([(e.provider, e.model) for e in ag_cli.fallback_chain]))

ag_cli = cli_mod._build_agent(dict(base, ORCHESTRA_FALLBACK="off",
                                   ORCHESTRA_FALLBACK_MODELS="nvidia/a"))
check("CLI spenta: i ripieghi scritti non vengono usati",
      len(ag_cli.fallback_chain) == 1, str([e.provider for e in ag_cli.fallback_chain]))

# ------------------------------------------------- un solo posto che la costruisce
print("\n[8] Goal e CLI passano dallo stesso aiutante")

from orchestra.fallback import catena_per_agente  # noqa: E402

finto = SimpleNamespace(
    provider=SimpleNamespace(name="nous", model="meituan/longcat-2.5:free"))
check("spento: il solo primario dell'agente",
      [(e.provider, e.model) for e in catena_per_agente(finto, {})]
      == [("nous", "meituan/longcat-2.5:free")],
      str([(e.provider, e.model) for e in catena_per_agente(finto, {})]))
check("acceso: primario dell'agente + i ripieghi",
      [e.provider for e in catena_per_agente(
          finto, {"ORCHESTRA_FALLBACK": "on",
                  "ORCHESTRA_FALLBACK_MODELS": "nvidia/a"})]
      == ["nous", "nvidia"])

# Il punto non e' la funzione ma chi la chiama: `goal.py` costruisce i suoi
# agenti per conto suo (il goal e il figlio della delega), e senza questa
# riga tornerebbero alla tabella automatica senza che nessuno se ne accorga.
radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
grezzo_goal = open(os.path.join(radice, "orchestra", "goal.py"),
                   encoding="utf-8").read()
grezzo_cli = open(os.path.join(radice, "orchestra", "cli.py"),
                  encoding="utf-8").read()
check("goal.py usa l'aiutante per il goal e per il figlio",
      grezzo_goal.count("catena_per_agente") >= 2,
      f"occorrenze: {grezzo_goal.count('catena_per_agente')}")
check("cli.py usa l'aiutante", "catena_per_agente" in grezzo_cli)
check("nessuno dei due torna a get_chain_for_provider",
      "get_chain_for_provider" not in grezzo_goal
      and "get_chain_for_provider" not in grezzo_cli)

# -------------------------------------- la tabella non esiste piu'
print("\n[9] Senza tabella: l'agente senza catena usa solo il primario")

import orchestra.fallback as fb_mod  # noqa: E402

check("DEFAULT_CHAINS non esiste piu'",
      not hasattr(fb_mod, "DEFAULT_CHAINS"))
check("get_chain_for_provider non esiste piu'",
      not hasattr(fb_mod, "get_chain_for_provider"))


class ProviderFinto:
    """Un provider minimo: serve solo a far nascere l'agente."""

    name = "nous"
    model = "meituan/longcat-2.5:free"

    def chat(self, *a, **k):
        return None

    def chat_stream(self, *a, **k):
        return None


def _nuovo_agente(**kw):
    return Agent(ProviderFinto(), default_registry(), "SYS", LoopConfig(), **kw)


ag_default = _nuovo_agente()
check("default: una sola entry, il primario",
      [(e.provider, e.model) for e in ag_default.fallback_chain]
      == [("nous", "meituan/longcat-2.5:free")],
      str([(e.provider, e.model) for e in ag_default.fallback_chain]))

class ProviderSenzaNome:
    """Niente `name`: prima la catena restava VUOTA e il turno moriva con
    "Nessun provider disponibile" senza aver mai chiamato il provider."""

    model = "m"

    def chat(self, *a, **k):
        return None


ag_sn = Agent(ProviderSenzaNome(), default_registry(), "SYS", LoopConfig())
check("senza `name` la catena non e' vuota",
      len(ag_sn.fallback_chain) == 1, str(ag_sn.fallback_chain))

check("una catena esplicita resta quella",
      len(_nuovo_agente(fallback_chain=[
          fb_mod.ChainEntry("nous", "m")]).fallback_chain) == 1)
check("una catena esplicita vuota resta vuota",
      _nuovo_agente(fallback_chain=[]).fallback_chain == [])

# Un 401 con la catena di default: nessun altro provider viene provato,
# l'errore vero esce. E' quello che rende onesto il benchmark: il numero
# non puo' essere la risposta di un altro modello.
import orchestra.benchmark as bench_mod  # noqa: E402
import orchestra.council as council_mod  # noqa: E402

for modulo in (bench_mod, council_mod, webapp_mod):
    sorgente = open(modulo.__file__, encoding="utf-8").read()
    check(f"{os.path.basename(modulo.__file__)} non usa la tabella",
          "get_chain_for_provider" not in sorgente
          and "DEFAULT_CHAINS" not in sorgente)

sorgente_webapp = open(webapp_mod.__file__, encoding="utf-8").read()
check("il figlio della delega web prende la catena manuale",
      "figlio.fallback_chain = catena_per_agente(figlio" in sorgente_webapp)

# -------------------------------- temperatura e tetto vengono dalla config
print("\n[10] La chiamata usa la configurazione dell'agente")

from orchestra import LLMResponse  # noqa: E402


class ProviderCheRegistra:
    """Registra i parametri con cui e' stato chiamato."""

    name = "nous"
    model = "meituan/longcat-2.5:free"

    def __init__(self):
        self.visti = []

    def chat_stream(self, messaggi, tool=None, **kw):
        self.visti.append(kw)
        return LLMResponse(content="ok", model=self.model,
                           prompt_tokens=1, completion_tokens=1)


class ProviderSenzaStreaming:
    """Come sopra, ma SENZA `chat_stream`: prende il ramo in blocco.

    Non eredita: `hasattr(provider, "chat_stream")` guarda l'attributo,
    quindi un `chat_stream = None` verrebbe chiamato e esploderebbe.
    """

    name = "nous"
    model = "meituan/longcat-2.5:free"

    def __init__(self):
        self.visti = []

    def chat(self, messaggi, tool=None, **kw):
        self.visti.append(kw)
        return LLMResponse(content="ok", model=self.model,
                           prompt_tokens=1, completion_tokens=1)


prov = ProviderCheRegistra()
ag = Agent(prov, default_registry(), "SYS",
           LoopConfig(max_tokens=12345, temperature=0.25, reasoning_level="max"))
ag._call_model_with_retry()
kw = prov.visti[-1]
check("streaming: il tetto viene dalla config",
      kw.get("max_tokens") == 12345, str(kw.get("max_tokens")))
check("streaming: la temperatura viene dalla config",
      abs(float(kw.get("temperature", -1)) - 0.25) < 1e-9,
      str(kw.get("temperature")))
check("streaming: il default 4096 della entry non arriva piu'",
      kw.get("max_tokens") != 4096, str(kw.get("max_tokens")))
check("streaming: il reasoning level viene dalla config",
      kw.get("reasoning_level") == "max", str(kw.get("reasoning_level")))

prov_blocco = ProviderSenzaStreaming()
ag_blocco = Agent(prov_blocco, default_registry(), "SYS",
                  LoopConfig(max_tokens=9000, temperature=0.1))
ag_blocco._call_model_with_retry()
kw_blocco = prov_blocco.visti[-1]
check("senza streaming: stesso tetto dalla config",
      kw_blocco.get("max_tokens") == 9000, str(kw_blocco.get("max_tokens")))
check("senza streaming: stessa temperatura dalla config",
      abs(float(kw_blocco.get("temperature", -1)) - 0.1) < 1e-9,
      str(kw_blocco.get("temperature")))

# La fonte unica vale solo se l'altra e' sparita: se la entry tornasse a
# portare i suoi parametri, il doppione silenzioso tornerebbe con lei.
voce = fb_mod.ChainEntry("nous", "m")
check("la entry non porta piu' parametri della chiamata",
      not any(hasattr(voce, attr)
              for attr in ("max_tokens", "temperature", "reasoning_level")),
      str(sorted(vars(voce))))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
