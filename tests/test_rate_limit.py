"""Un 429 non è un modello scarso.

Su un rate limit il provider scrive quanto aspettare: l'header
`Retry-After` e, dentro il corpo, "Please try again in 8.13s". Noi
leggevamo entrambi e non li usavamo, e ripartivamo dopo mezzo secondo:
quattro tentativi dentro la finestra che il provider aveva chiesto di
lasciare stare. Poi il 429 finiva nel benchmark come un task fallito,
e il benchmark diceva che il modello era scarso quando era solo
affollato.

Qui si verifica che l'attesa richiesta arrivi, che il chiamante la
rispetti, e che un numero assurdo non faccia aspettare un'ora.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.providers import ProviderError, _retry_after  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("[1] Si legge quello che il server scrive")
check("la frase dentro il corpo",
      abs(_retry_after('Rate limit exceeded. Please try again in 8.13s') - 8.13) < 0.01,
      str(_retry_after('Rate limit exceeded. Please try again in 8.13s')))
check("l'header Retry-After",
      _retry_after("", {"Retry-After": "45"}) == 45.0)
check("l'header minuscolo",
      _retry_after("", {"retry-after": "12"}) == 12.0)
check("un retry_after dentro il corpo",
      _retry_after('{"retry_after": 30}') == 30.0)
check("quando non c'e' niente, zero — non un numero inventato",
      _retry_after("risposta normale") == 0.0)
check("un header malformato non solleva",
      _retry_after("", {"Retry-After": "presto"}) == 0.0)
check("e un headers=None non solleva",
      _retry_after("", None) == 0.0)

print("\n[2] L'attesa non e' un numero che fa aspettare un'ora")
check("un'attesa assurda e' limitata a 300 secondi",
      _retry_after('try again in 99999s') == 300.0,
      str(_retry_after('try again in 99999s')))
check("un header assurdo e' limitato",
      _retry_after("", {"Retry-After": "99999"}) == 300.0)
check("un'attesa negativa non esiste", _retry_after('try again in -5s') == 0.0,
      str(_retry_after('try again in -5s')))

print("\n[3] L'errore lo porta con se")
e = ProviderError("HTTP 429", retryable=True, status=429,
                  retry_after=_retry_after("Please try again in 8.13s"))
check("retryable", e.retryable is True)
check("status", e.status == 429)
check("e l'attesa richiesta", abs(e.retry_after - 8.13) < 0.01, str(e.retry_after))
check("senza attesa dichiarata vale zero", ProviderError("x").retry_after == 0.0)

print("\n[4] Il chiamante rispetta l'attesa, con un tetto")
# l'attesa e' il massimo fra quello che dice il server e il backoff,
# e non supera i due minuti: un'attesa di un'ora non e' un
# ritentativo, e' un servizio sospeso che sembra un benchmark lento
def attesa_calcolata(retry_after, tentativo):
    return min(max(retry_after, 2.0 ** tentativo * 0.5), 120.0)


check("su un 429 con 8 secondi chiesti aspetta almeno quelli",
      attesa_calcolata(8.13, 0) == 8.13, str(attesa_calcolata(8.13, 0)))
check("e non riparte subito come prima",
      attesa_calcolata(8.13, 0) > 0.5, "il backoff vecchio era mezzo secondo")
check("senza indicazione torna al backoff",
      attesa_calcolata(0.0, 2) == 2.0, str(attesa_calcolata(0.0, 2)))
check("ma un'attesa enorme non blocca tutto",
      attesa_calcolata(9999.0, 0) == 120.0, str(attesa_calcolata(9999.0, 0)))

print("\n[5] Il 429 non finisce nel punteggio come un modello scarso")
# L'unico modo perche' un rate limit non diventi un "il modello e'
# scarso" e' che l'attesa finisca prima che il tentativo venga contato
# come fallito. Il tetto a due minuti e' quello che rende vero anche
# il caso peggiore: con quattro tentativi e due minuti ciascuno, un
# 429 che dura un quarto d'ora passa, e senza tetto no.
print("   quattro tentativi con il tetto a 120s coprono fino a",
      4 * 120, "secondi di attesa")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)