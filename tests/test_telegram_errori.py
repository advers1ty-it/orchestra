"""Telegram: un turno fallito deve dire perche', non ripetere la risposta.

Difetto visto in uso (tre screenshot, stessa chat): esaurite le richieste
gratuite del giorno di OpenRouter, ogni messaggio riceveva come risposta
lo STESSO testo del turno precedente ("Fatto. Monitoraggio attivo: ..."),
all'infinito. Dal telefono non si capiva niente: sembrava che il bot
avesse smesso di leggere, invece stava fallendo con un 429.

La catena era questa:

  - il turno cade su `ProviderError` -> nella conversazione non entra
    nessun messaggio `assistant` nuovo;
  - `telegram_turno` chiude con `_telegram_ultima_risposta(sess)`, che
    scorre TUTTA la storia all'indietro: trova la risposta del turno
    prima e la rimanda;
  - l'evento `error` (dove il server scrive "ProviderError: ... 429 ...")
    non veniva nemmeno raccolto da `_telegram_segui`.

Qui si verificano i tre pezzi della correzione: la risposta si legge solo
dal turno in corso, l'errore viene raccolto, e quando non c'e' risposta si
spiega cos'e' successo. Nessuna rete: sessioni e bridge finti.
"""

import inspect
import os
import sys
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from orchestra import webapp as webapp_mod  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


ERRORE_429 = (
    'ProviderError: openrouter: HTTP 429 — {"error":{"message":"Rate limit '
    'exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model '
    'requests per day: https://openrouter.ai/settings/credits?utm_source=api",'
    '"code":429,"metadata":{"headers":{"X-RateLimit-Limit":"50",'
    '"X-RateLimit-Remaining":"0"},"limit_source":"openrouter_free_tier_daily",'
    '"remedy_hint":"Wait for the daily reset"}}}'
)
PRIMA = "Fatto. Monitoraggio attivo: ogni 15 minuti controllo la posta."


def messaggio(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content)


def sessione(messaggi: list, fermato: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        agent=SimpleNamespace(state=SimpleNamespace(
            messages=list(messaggi), stopped_because=fermato)),
        busy=False,
    )


app = webapp_mod.OrchestraApp.__new__(webapp_mod.OrchestraApp)

# ---------------------------------------------------------------------------
print("\n[1] La risposta si legge solo dal turno in corso")

vecchia = sessione([
    messaggio("user", "Ok allora aggiornami se arrivano mail degne di nota"),
    messaggio("assistant", PRIMA),
])
check("senza indice si trova la risposta di prima (com'era il difetto)",
      app._telegram_ultima_risposta(vecchia) == PRIMA)
check("dal turno in corso non c'e' nessuna risposta",
      app._telegram_ultima_risposta(vecchia, da_indice=2) == "")

dopo = sessione([
    messaggio("user", PRIMA and "Ricordami domani alle 11"),
    messaggio("assistant", PRIMA),
    messaggio("user", "e anche dopodomani"),
    messaggio("assistant", "Fatto: due promemoria."),
])
check("con un turno che scrive, si prende la risposta nuova",
      app._telegram_ultima_risposta(dopo, da_indice=3) == "Fatto: due promemoria.")
check("e non quella vecchia",
      app._telegram_ultima_risposta(dopo, da_indice=3) != PRIMA)

sorgente = inspect.getsource(webapp_mod.OrchestraApp.telegram_turno)
check("telegram_turno passa l'indice del turno",
      "da_indice=prima" in sorgente)
check("e spiega il turno muto invece di ripetere",
      "_telegram_spiega_turno_muto" in sorgente)

# ---------------------------------------------------------------------------
print("\n[2] L'errore viene raccolto dagli eventi")


class BridgeFinto:
    def __init__(self, eventi):
        self._eventi = eventi

    def stream(self, timeout=0.0):
        return iter(self._eventi)


sess_eventi = sessione([messaggio("assistant", PRIMA)])
sess_eventi.bridge = BridgeFinto([
    {"kind": "turn_start", "data": {"input": "ciao"}},
    {"kind": "error", "data": {"message": ERRORE_429}},
    {"kind": "idle", "data": {"busy": False}},
])
stato = app._telegram_segui(sess_eventi, sess_eventi.bridge.stream(), None,
                            {"id": 1})
check("l'evento error finisce nello stato",
      "429" in stato.get("errore", ""), str(stato.get("errore"))[:80])
check("il turno risulta finito", stato.get("finito") is True)
check("lo stato ha sempre il campo errore", "errore" in stato)

# ---------------------------------------------------------------------------
print("\n[3] Il 429 delle richieste gratuite si spiega")

spiegato = app._telegram_spiega_turno_muto(sess_eventi, stato)
check("non e' il messaggio di prima", PRIMA not in spiegato)
check("dice che sono finite le richieste gratuite di oggi",
      "gratuite" in spiegato and "oggi" in spiegato, spiegato[:120])
check("dice cosa si puo' fare (/modello o credito)",
      "/modello" in spiegato and "credito" in spiegato)
check("porta il dettaglio tecnico",
      spiegato.startswith("Ho esaurito") and "Dettaglio:" in spiegato)
check("ma resta leggibile (non un muro)", len(spiegato) < 900, str(len(spiegato)))

print("\n[4] Gli altri errori hanno una spiegazione loro")
casi = {
    "ProviderError: openrouter: HTTP 401 — invalid api key":
        ("chiave", "Opzioni"),
    "ProviderError: openrouter: errore di rete — timed out":
        ("raggiungere il servizio", "Riprova"),
    "ProviderError: groq: HTTP 500 — internal":
        ("errore del servizio", "Diagnosi"),
    "ProviderError: anthropic: HTTP 429 — rate limit reached":
        ("rate limit", "Riprova"),
}
for errore, (atteso_motivo, atteso_come) in casi.items():
    testo = app._telegram_spiega_errore(errore)
    check(f"{errore[:42]}... -> spiegato",
          atteso_motivo in testo and atteso_come in testo, testo[:120])

# ---------------------------------------------------------------------------
print("\n[5] Turno muto senza errore: si dice cosa ha fermato il turno")

budget = sessione([messaggio("assistant", PRIMA)], fermato="budget_exceeded")
testo_budget = app._telegram_spiega_turno_muto(budget, {})
check("il budget esaurito si dice",
      "budget esaurito" in testo_budget, testo_budget)
check("e si dice dove alzarlo", "Opzioni" in testo_budget)

vuoto = sessione([messaggio("assistant", PRIMA)])
testo_vuoto = app._telegram_spiega_turno_muto(vuoto, {})
check("senza errore e senza esito lo si dice lo stesso",
      "senza scrivere una risposta" in testo_vuoto, testo_vuoto)
check("e si chiarisce che non e' la risposta di prima",
      "non era la risposta" in testo_vuoto)
check("mai vuoto, mai il testo vecchio",
      bool(testo_vuoto.strip()) and PRIMA not in testo_vuoto)

# ---------------------------------------------------------------------------
print("\n[6] Il recapito a turno finito usa la stessa regola")


class PonteFinto:
    def __init__(self):
        self.testi = []

    def recapita(self, testo, file=None):
        self.testi.append(testo)


sorgente_recapito = inspect.getsource(
    webapp_mod.OrchestraApp._telegram_recapita_dopo)
check("il recapito chiede la risposta con l'indice del turno",
      "_telegram_ultima_risposta(sess, da_indice=da_indice)" in sorgente_recapito)
check("e non riscorre la conversazione con un ciclo suo",
      "reversed(" not in sorgente_recapito)

lunghi = sessione([
    messaggio("user", "controlla le mail"),
    messaggio("assistant", PRIMA),
    messaggio("user", "e fammi un riepilogo lungo"),
    messaggio("assistant", "Ecco il riepilogo lungo."),
])
ponte = PonteFinto()
app._telegram_ponti = {7: ponte}
app._telegram_recapita_dopo(7, lunghi, 0.0, 3)
for _ in range(40):
    if ponte.testi:
        break
    time.sleep(0.1)
check("a turno finito arriva la risposta del turno",
      ponte.testi == ["Ecco il riepilogo lungo."], str(ponte.testi))
check("e non quella di prima",
      PRIMA not in "".join(ponte.testi)
      and all("non era la risposta" not in t for t in ponte.testi))

muto = sessione([
    messaggio("assistant", PRIMA),
    messaggio("user", "controlla ancora"),
])
ponte_muto = PonteFinto()
app._telegram_ponti = {8: ponte_muto}
app._telegram_recapita_dopo(8, muto, 0.0, 2)
for _ in range(40):
    if ponte_muto.testi:
        break
    time.sleep(0.1)
check("un turno lungo caduto si spiega, non si ripete",
      len(ponte_muto.testi) == 1
      and PRIMA not in ponte_muto.testi[0]
      and "senza scrivere una risposta" in ponte_muto.testi[0],
      str(ponte_muto.testi)[:160])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
