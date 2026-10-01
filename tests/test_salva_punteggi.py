"""Il salvataggio dei punteggi dopo un benchmark.

Tre bug vissero qui, tutti con la stessa causa — il formato di
`by_category` e' cambiato da numero a dizionario e nessuno ha cercato
chi lo leggeva:

1. `v > 0` su un dizionario: TypeError DOPO tutti i task, quando il
   lavoro era gia' fatto e il risultato buttato
2. `cat` usato come nome della variabile del ciclo, mentre `cat` e' il
   catalogo: UnboundLocalError su `cat.models`
3. nessun test copriva il blocco, perche' stava dentro un handler

Ora e' una funzione a se' — e questa e' la prova che il percorso
funziona, non un controllo sul sorgente.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestra.benchmark as B  # noqa: E402
import orchestra.catalog as C  # noqa: E402
from orchestra.webapp import salva_punteggi  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def res(cat, ok, modello="m1"):
    return B.RunResult(
        model=modello, category=cat, passed=ok, task_id="t", detail="",
        seconds=1.0, prompt_tokens=10, completion_tokens=10, cost_usd=0.0,
        tool_calls=1, tool_errors=[], stopped_because="fine", unusable=False)


def catalogo_con(*ids):
    cat = C.Catalog("openrouter")
    for i in ids:
        cat.models[i] = C.ModelProfile(info=C.ModelInfo(id=i))
    return cat


print("[1] Il percorso vero: un benchmark finito, i punteggi sul catalogo")
risultati = [res("code", True), res("code", False), res("reasoning", True),
             res("js", False)]
summary = B.summarize(risultati)
cat = catalogo_con("m1")
try:
    n = salva_punteggi(cat, summary)
    check("non crasha", True)
except Exception as e:
    check("non crasha", False, f"{type(e).__name__}: {e}")
    n = 0
check("ha salvato il modello", n == 1, str(n))
prof = cat.models["m1"]
check("il punteggio e' solo delle categorie con test passati",
      prof.scores == {"code": 0.5, "reasoning": 1.0}, str(prof.scores))
# Le frazioni stanno anche per le categorie a zero passati: "js ha
# 0 su 1" e' informazione, e senza la frazione un 0.0 sul display
# non si distingue da "non misurata". Il check le contava tutte e
# si aspettava solo le due con test passati.
check("la frazione e' salvata per ogni categoria misurata",
      prof.frazioni == {"code": 1, "reasoning": 1, "js": 0},
      str(prof.frazioni))
check("la base e' salvata per ogni categoria misurata",
      prof.task_per_cat == {"code": 2, "reasoning": 1, "js": 1},
      str(prof.task_per_cat))
# E la frazione distingue "zero passati" da "non misurata": il primo
# ha una base, il secondo non ce l'ha affatto.
check("una categoria a zero ha lo stesso una base",
      "js" in prof.frazioni and prof.frazioni["js"] == 0,
      "senza questo, 0.0 e 'non misurata' sono la stessa cosa")
check("ed e' stato messo il tempo", prof.last_measured > 0)

print("\n[2] Il caso che crashava")
# Il formato nuovo e' un dizionario: `v > 0` su un dizionario e' il
# TypeError che ha interrotto il benchmark dopo tutti i task.
d = summary["per_model"]["m1"]["by_category"]["code"]
check("by_category e' un dizionario", isinstance(d, dict), type(d).__name__)
check("e ha il punteggio dentro", "score" in d, str(list(d))[:60])
# Il ciclo deve leggere il campo, non il dizionario. Lo si verifica
# dal risultato: se avesse letto il dizionario, scores sarebbe
# pieno di dizionari e qui sarebbe saltato.
check("nessun dizionario e' finito fra i punteggi",
      all(isinstance(v, float) for v in prof.scores.values()),
      str(prof.scores))

print("\n[3] Il caso che diceva 'cat non e' associato'")
# Il nome della variabile del ciclo non puo' essere quello del
# catalogo. Un test che lo esegue lo dimostra meglio di uno che
# guarda il sorgente.
try:
    cat2 = catalogo_con("m1")
    salva_punteggi(cat2, summary)
    check("il catalogo resta raggiungibile dopo il ciclo",
          cat2.models.get("m1") is not None,
          "se il ciclo avesse sovrascritto 'cat', questo would fallire")
except NameError as e:
    check("il catalogo resta raggiungibile dopo il ciclo", False,
          f"{e} — il ciclo ha sovrascritto il catalogo")

print("\n[4] Robustezza: forme che il summary non dovrebbe mai avere")
# Non per fare le scale, ma perche' un formato diverso non deve
# far cadere il benchmark DOPO che ha fatto il lavoro.
provo = {"per_model": {"m1": {"by_category": {
    "code": 0.5,                                  # numero, formato vecchio
    "reasoning": {"score": 0.0},                  # manca la base
}}}}
cat3 = catalogo_con("m1")
try:
    salva_punteggi(cat3, provo)
    check("un formato vecchio non crasha", True)
    check("e il numero viene letto come punteggio",
          cat3.models["m1"].scores == {"code": 0.5},
          str(cat3.models["m1"].scores))
except Exception as e:
    check("un formato vecchio non crasha", False, f"{type(e).__name__}: {e}")

cat4 = catalogo_con("m1")
try:
    salva_punteggi(cat4, {})
    check("un summary vuoto non crasha", True)
except Exception as e:
    check("un summary vuoto non crasha", False, str(e)[:60])

check("un catalogo assente non crasha",
      salva_punteggi(None, summary) == 0)

print("\n[5] Un modello che non e' piu' nel catalogo")
# Il provider puo' togliere un modello fra una misurazione e l'altra.
provo2 = {"per_model": {"modello-scomparso": {
    "by_category": {"code": {"score": 1.0, "passati": 1, "quanti": 1}}}}}
cat5 = catalogo_con("m1")
try:
    salva_punteggi(cat5, provo2)
    check("non crasha e non crea il modello",
          "modello-scomparso" not in cat5.models,
          str(list(cat5.models)))
except Exception as e:
    check("non crasha e non crea il modello", False, f"{type(e).__name__}: {e}")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)