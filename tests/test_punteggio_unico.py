"""Il numero unico deve mettere sullo stesso piano due prove diverse.

Il caso che l'ha motivato: un modello con 2 test perfetti ha 100%
esattamente come uno con 40 all'85%. Il primo porta una prova
incomparabilmente minore, ma senza correzione vince lui — e basta
misurare due modelli a caso perché il meno testato vinca. La
correzione lo tira verso la media degli altri, e con molte prove il
peso torna a essere suo.

Una nota su questi test, che ho rifatto: la prima versione passava
`media_di_insieme=0.0` "per isolare il numero". Ma è proprio la media a
zero che tira il punteggio verso il basso, ed è il caso peggiore. Il
numero che si voleva verificare non era più il numero. Qui la media si
lascia calcolare da sola.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.punteggio import (  # noqa: E402
    PRIOR_PROVE, PESO_LIVELLO, livello_di, punteggio_unico,
)

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


class R:
    """Il minimo che serve: un risultato di benchmark."""

    def __init__(self, model, task_id, category, passed, unusable=False):
        self.model = model
        self.task_id = task_id
        self.category = category
        self.passed = passed
        self.unusable = unusable


print("[1] Il livello si legge dall'id, e i pesi sono quelli scelti")
check("code_l1 -> l1", livello_di("code_l1") == "l1", livello_di("code_l1"))
check("code_l3 -> l3", livello_di("code_l3") == "l3", livello_di("code_l3"))
check("un task vecchio -> senza livello", livello_di("code_fib") == "senza")
check("pesi: 1 / 1.5 / 2",
      PESO_LIVELLO == {"l1": 1.0, "l2": 1.5, "l3": 2.0}, str(PESO_LIVELLO))
check("il prior vale 4 prove", PRIOR_PROVE == 4.0, str(PRIOR_PROVE))

print("\n[2] Il caso che hai descritto: 5 perfetti contro 40 all'85")
pochi = [R("pochi", f"code_l{n}", "code", True) for n in (1, 1, 1, 2, 2)]
molti = [R("molti", f"code_l{n}", "code", i < 34)
         for i, n in enumerate([1] * 20 + [2] * 10 + [3] * 10)]
ris = punteggio_unico(pochi + molti)["modelli"]

# NonPretendo che il modello con 5 prove perda. 5 successi sono prova,
# e la correzione li attenua (100 -> 95.6) senza cancellarli: non deve.
# Pretendere il contrario sarebbe un'altra versione del difetto di cui
# questo modulo è fatto — decidere al posto del dato quale verità sia.
check("il 100% di cinque prove è stato tirato verso il basso",
      ris["pochi"]["punteggio"] < ris["pochi"]["grezzo"],
      f"{ris['pochi']['punteggio']} contro grezzo {ris['pochi']['grezzo']}")
check("ma non è stato cancellato: cinque successi sono prova",
      ris["pochi"]["punteggio"] > 90, str(ris["pochi"]["punteggio"]))
check("e il contrasto dichiara di quanto", ris["pochi"]["contrasto"] > 0,
      str(ris["pochi"]["contrasto"]))
check("la base dichiarata è 5 e 40",
      ris["pochi"]["task"] == 5 and ris["molti"]["task"] == 40,
      f"{ris['pochi']['task']} e {ris['molti']['task']}")

print("\n[3] Con molte prove la correzione sparisce")
# È la regola che rende la correzione onesta: se penalizzasse anche chi
# è stato misurato tanto, sarebbe una tassa sulla misura.
tanti = [R("tanti", f"code_l{n}", "code", i < 170)
         for i, n in enumerate([1] * 100 + [2] * 50 + [3] * 50)]
solo = punteggio_unico(tanti)["modelli"]["tanti"]
check("con 200 prove il numero è suo",
      abs(solo["punteggio"] - solo["grezzo"]) < 0.5,
      f"grezzo {solo['grezzo']}, ridotto {solo['punteggio']}")
check("il contrasto è trascurabile", abs(solo["contrasto"]) < 0.5,
      str(solo["contrasto"]))
check("e le prove sono contate col peso del livello",
      solo["prove"] == 100 + 75 + 100, str(solo["prove"]))

print("\n[4] Ogni categoria pesa uguale")
# code ha 6 task e web 2: con un peso per singolo test la categoria con
# più compiti farebbe la parte dominante di un numero che dovrebbe
# dire "quanto vale in generale".
misto = ([R("m", "code_l1", "code", True) for _ in range(6)]
         + [R("m", "web_pagina", "web", True),
            R("m", "web_layout", "web", False)])
s = punteggio_unico(misto)["modelli"]["m"]
check("code 100% e web 50% danno 75%", s["punteggio"] == 75.0, str(s["punteggio"]))
check("e le due categorie sono entrambe contate", s["categorie"] == 2,
      str(s["categorie"]))
check("il peso per categoria batte il peso per singolo test",
      s["punteggio"] != 83.3,
      f"{s['punteggio']}: con 6 test su 8 il peso per test darebbe 83")

print("\n[5] Il livello pesa dentro la categoria")
# Stessa percentuale, livelli diversi: il numero è uguale — il livello
# cambia QUANTO, non quanto hai risposto bene.
mezzo_facile = [R("f", "code_l1", "code", True), R("f", "code_l1", "code", False)]
mezzo_duro = [R("d", "code_l3", "code", True), R("d", "code_l3", "code", False)]
altro = [R("altro", "code_l1", "code", False)]
sf = punteggio_unico(mezzo_facile + altro)["modelli"]
sd = punteggio_unico(mezzo_duro + altro)["modelli"]
check("la percentuale grezza è la stessa",
      sf["f"]["grezzo"] == sd["d"]["grezzo"] == 50.0,
      f"{sf['f']['grezzo']} e {sd['d']['grezzo']}")
check("ma il difficile porta più prove",
      sf["f"]["prove"] < sd["d"]["prove"],
      f"prove facili {sf['f']['prove']}, difficili {sd['d']['prove']}")
check("e quindi subisce meno correzione",
      sd["d"]["punteggio"] > sf["f"]["punteggio"],
      f"facile {sf['f']['punteggio']}, difficile {sd['d']['punteggio']}")

print("\n[6] Un modello che il provider riserva non compete")
riservato = [R("normale", "code_l1", "code", True) for _ in range(3)]
riservato += [R("riservato", "code_l1", "code", False, unusable=True) for _ in range(5)]
s6 = punteggio_unico(riservato)["modelli"]
check("il riservato non c'è fra i modelli", "riservato" not in s6, str(list(s6)))
check("e il normale non è stato abbassato dalla sua sfortuna",
      s6["normale"]["grezzo"] == 100.0, str(s6["normale"]["grezzo"]))

print("\n[7] Il risultato porta tutto quello che serve a dubitarne")
due = punteggio_unico([R("a", "code_l1", "code", True),
                       R("b", "code_l1", "code", False)])
check("la media di insieme è dichiarata",
      "media_di_insieme" in due, str(list(due)))
check("e con due modelli non coincide con nessuno dei due",
      due["media_di_insieme"] == 50.0, str(due["media_di_insieme"]))
check("ogni modello dichiara base, prove e categorie",
      all({"punteggio", "grezzo", "prove", "task", "categorie", "contrasto",
           "per_categoria"} <= set(m) for m in due["modelli"].values()),
      str(sorted(due["modelli"]["a"])))
check("e i punteggi per categoria ci sono",
      due["modelli"]["a"]["per_categoria"] == {"code": 100.0},
      str(due["modelli"]["a"]["per_categoria"]))

print("\n[8] Vuoto e casi limite")
# il caso vuoto: nessun modello, nessun compito, e soprattutto nessun
# "misurati su insiemi diversi" — con zero modelli non c'è nessun
# confronto da dichiarare non valido
_vuoto = punteggio_unico([])
check("nessun risultato non esplode", _vuoto["modelli"] == {}, str(_vuoto))
check("e non inventa un confronto da dichiarare",
      _vuoto["confrontabili"] is True and _vuoto["motivo"] == "",
      str(_vuoto["motivo"]))
solo_m = punteggio_unico([R("solo", "code_l1", "code", True)])
check("un solo modello ha la media uguale a lui",
      solo_m["media_di_insieme"] == 100.0, str(solo_m["media_di_insieme"]))
check("e il suo numero non è tirato verso se stesso",
      solo_m["modelli"]["solo"]["punteggio"] == 100.0,
      str(solo_m["modelli"]["solo"]["punteggio"]))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)


print("\n[9] Il confronto vale solo sugli stessi task")
# Il caso che la media pesata nascondeva: due modelli con 5 e 40 test
# non hanno risposto alle stesse domande. Nessuna formula li rende
# confrontabili — ma il numero puo' dire che non lo sono.
pochi = [R("pochi", f"code_l{n}", "code", True) for n in (1, 1, 1, 2, 2)]
molti = [R("molti", f"code_l{n}", "code", i < 34)
         for i, n in enumerate([1] * 20 + [2] * 10 + [3] * 10)]
r = punteggio_unico(pochi + molti)
check("su insiemi diversi il confronto e' dichiarato non valido",
      r["confrontabili"] is False, str(r["confrontabili"]))
check("e il motivo dice quanti task hanno in comune",
      "insiemi diversi" in r["motivo"], r["motivo"])
check("i numeri ci sono comunque, nascosti no",
      set(r["modelli"]) == {"pochi", "molti"} and
      r["modelli"]["pochi"]["punteggio"] > 0, str(r["modelli"].keys()))

# sugli stessi task il confronto torna e distingue
a = [R("a", f"t{i}", "code", True) for i in range(20)]
b = [R("b", f"t{i}", "code", i < 17) for i in range(20)]
r2 = punteggio_unico(a + b)
check("sugli stessi task e' confrontabile", r2["confrontabili"] is True,
      r2["motivo"])
check("e i due punteggi sono distinguibili",
      r2["modelli"]["a"]["punteggio"] > r2["modelli"]["b"]["punteggio"],
      f"{r2['modelli']['a']['punteggio']} contro {r2['modelli']['b']['punteggio']}")
check("20 e 17 su 20: i numeri non sono 100 e 85",
      r2["modelli"]["a"]["punteggio"] != 100.0,
      f"{r2['modelli']['a']['punteggio']}: con 20 prove la media degli altri pesa ancora")
check("e ogni modello dichiara su quali task e' stato misurato",
      len(r2["modelli"]["a"]["task_id"]) == 20,
      str(len(r2["modelli"]["a"]["task_id"])))

