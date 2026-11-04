"""Il riepilogo di fine turno: la riga che dice cosa è successo.

Il difetto che previene: un turno finisce, la risposta è sopra lo
schermo, e nessuno sa se è finito davvero, cosa ha toccato e quanto è
costato. `traccia.py` lo sa, ma va aperta a mano.

I casi che contano: l'esito tradotto (un codice interno non deve
diventare "finito"), i file accorpati (lo stesso file toccato due volte
non è due file), e il costo che non mente (sotto un centesimo non è
zero).
"""

from __future__ import annotations

import os
import sys
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

os.environ.setdefault("ORCHESTRA_HOME",
                      tempfile.mkdtemp(prefix="orchestra_riep_"))

from orchestra import riepilogo  # noqa: E402


PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class Stato:
    def __init__(self, **kw):
        self.stopped_because = kw.get("stopped_because", "")
        self.total_tokens = kw.get("total_tokens", 0)
        self.total_cost_usd = kw.get("total_cost_usd", 0.0)
        self.tool_calls_made = kw.get("tool_calls_made", 0)
        self.tool_errors = kw.get("tool_errors", 0)
        self.iterations = kw.get("iterations", 0)


print("\n== un turno finito bene ==")

r = riepilogo.costruisci(
    stato=Stato(total_tokens=12000, total_cost_usd=0.034,
                tool_calls_made=4, iterations=3),
    modifiche=[{"percorso": "a.py", "stato": "modificato",
                "aggiunte": 10, "tolte": 2}],
    durata_s=42, modello="m")
check("l'esito è finito", r["esito_testo"] == "finito", r["esito_testo"])
check("la gravità è ok", r["gravita"] == "ok", r["gravita"])
check("un file solo", r["n_file"] == 1, str(r["n_file"]))
check("i token ci sono", r["token"] == 12000)
check("il costo in dollari", abs(r["costo_usd"] - 0.034) < 1e-9,
      str(r["costo_usd"]))
check("il costo leggibile", r["costo"] == "$0.03", r["costo"])
check("la riga contiene l'esito", "finito" in r["riga"], r["riga"])
check("la riga contiene i file", "1 file" in r["riga"], r["riga"])
check("la riga contiene i token", "12.000 token" in r["riga"], r["riga"])

print("\n== lo stesso file toccato due volte è un file ==")

r = riepilogo.costruisci(
    stato=Stato(),
    modifiche=[
        {"percorso": "a.py", "stato": "modificato",
         "aggiunte": 3, "tolte": 1},
        {"percorso": "b.py", "stato": "nuovo", "aggiunte": 5, "tolte": 0},
        {"percorso": "a.py", "stato": "modificato",
         "aggiunte": 2, "tolte": 4},
    ])
per = {f["percorso"]: f for f in r["file"]}
check("due file, non tre", r["n_file"] == 2, str(r["n_file"]))
check("le aggiunte si sommano", per["a.py"]["aggiunte"] == 5,
      str(per["a.py"]))
check("le tolte si sommano", per["a.py"]["tolte"] == 5, str(per["a.py"]))

print("\n== un annullamento non è un successo ==")

r = riepilogo.costruisci(stato=Stato(stopped_because="canceled_da_should_continue"))
check("l'annullamento si legge", "annullato" in r["esito_testo"],
      r["esito_testo"])
check("la gravità è annullato", r["gravita"] == "annullato", r["gravita"])

print("\n== gli esiti che contano si leggono in italiano ==")

for codice, atteso in (
    ("troppi_errori_consecutivi", "troppi errori"),
    ("gira_a_vuoto", "ripetendo"),
    ("budget_exceeded", "budget"),
    ("solo_parole", "annunciato"),
):
    testo, gravita = riepilogo.esito_leggibile(codice)
    check(f"{codice} -> {atteso}", atteso in testo and gravita != "ok",
          f"{testo} ({gravita})")

testo, gravita = riepilogo.esito_leggibile("qualcosa_di_nuovo")
check("un codice sconosciuto non diventa 'finito'",
      "qualcosa" in testo and gravita == "avviso", f"{testo} ({gravita})")

print("\n== il costo piccolo non è zero ==")

r = riepilogo.costruisci(stato=Stato(total_tokens=100, total_cost_usd=0.0004))
check("sotto un centesimo si dice", r["costo"] == "< $0,01", r["costo"])
r = riepilogo.costruisci(stato=Stato(total_tokens=100, total_cost_usd=0))
check("senza costo stimato si dice n/d", r["costo"] == "n/d", r["costo"])

print("\n== la durata si legge ==")

r = riepilogo.costruisci(stato=Stato(), durata_s=125)
check("due minuti e cinque", r["durata"] == "2m 05s", r["durata"])

print("\n== l'ultimo riepilogo resta disponibile ==")

check("ultimo() lo restituisce", riepilogo.ultimo().get("durata") == "2m 05s",
      str(riepilogo.ultimo()))
prima = riepilogo.ultimo()
r = riepilogo.costruisci(stato=Stato(), durata_s=3)
check("un nuovo turno lo sostituisce",
      riepilogo.ultimo()["durata"] == "3s" and prima["durata"] == "2m 05s")

print("\n== l'Agent accumula il costo anche senza budget ==")

from orchestra.agent import AgentState  # noqa: E402

check("lo stato ha il costo", hasattr(AgentState(), "total_cost_usd"))
check("parte da zero", AgentState().total_cost_usd == 0.0)

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
