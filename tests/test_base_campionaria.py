"""La base campionaria deve sopravvivere al salvataggio.

Il punteggio veniva salvato senza la frazione e senza la base: si
scriveva `scores` e basta. Il risultato era che il 100% di un modesso
misurato su una categoria sola e il 100% di un altro misurato su otto
finivano identici — e la tabella promette che la frazione sia
confrontabile, cosa che senza il denominatore non e' vera.

Il dato non mancava: lo scriveva `salva_punteggi` e veniva buttato
tre righe piu' in giu', nel dizionario passato a `json.dump`.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.catalog import Catalog, ModelInfo, ModelProfile  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


D = tempfile.mkdtemp()
path = os.path.join(D, "catalog.json")
MID = "esempio/modello:free"

print("[1] Il giro completo: scrivo, chiudo, riapro")
cat = Catalog("openrouter")
cat._path = path
cat.models[MID] = ModelProfile(info=ModelInfo(id=MID))
p = cat.models[MID]
p.scores = {"code": 0.67, "js": 1.0}
p.frazioni = {"code": 2, "js": 2}
p.task_per_cat = {"code": 3, "js": 2}
cat.save()

su_disco = json.load(open(path, encoding="utf-8"))["models"][MID]
check("il punteggio c'e'", su_disco.get("scores") == p.scores, str(su_disco.get("scores")))
check("la frazione pure — non si butta piu'",
      su_disco.get("frazioni") == {"code": 2, "js": 2}, str(su_disco.get("frazioni")))
check("e la base campionaria",
      su_disco.get("task_per_cat") == {"code": 3, "js": 2}, str(su_disco.get("task_per_cat")))

# riapro: il percorso che fa il server a ogni avvio
cat2 = Catalog("openrouter")
cat2._path = path
cat2.models[MID] = ModelProfile(info=ModelInfo(id=MID))
n = cat2.load_measurements()
p2 = cat2.models[MID]
check("il ricaricamento li ha presi", n >= 1, str(n))
check("e la frazione e' tornata", p2.frazioni == {"code": 2, "js": 2}, str(p2.frazioni))
check("e la base e' tornata", p2.task_per_cat == {"code": 3, "js": 2}, str(p2.task_per_cat))

print("\n[2] Due modelli con lo stesso 100% restano distinguibili")
# E' il punto per cui tutto questo serve. Un 100% su un task e un
# 100% su venti non sono la stessa misura, e senza la base la tabella
# li metteva sulla stessa riga.
a = Catalog("openrouter")
a._path = path
a.models["a"] = ModelProfile(info=ModelInfo(id="a"))
a.models["a"].scores = {"code": 1.0}
a.models["a"].frazioni = {"code": 1}
a.models["a"].task_per_cat = {"code": 1}
a.models["b"] = ModelProfile(info=ModelInfo(id="b"))
a.models["b"].scores = {"code": 1.0, "js": 1.0, "web": 1.0}
a.models["b"].frazioni = {"code": 7, "js": 6, "web": 7}
a.models["b"].task_per_cat = {"code": 7, "js": 6, "web": 7}
a.save()
b = Catalog("openrouter")
b._path = path
b.models["a"] = ModelProfile(info=ModelInfo(id="a"))
b.models["b"] = ModelProfile(info=ModelInfo(id="b"))
b.load_measurements()
ta = sum(b.models["a"].task_per_cat.values())
tb = sum(b.models["b"].task_per_cat.values())
check("le due basi sono diverse", ta == 1 and tb == 20, f"{ta} e {tb}")
ma = sum(b.models["a"].scores.values()) / len(b.models["a"].scores)
mb = sum(b.models["b"].scores.values()) / len(b.models["b"].scores)
check("le due MEDIE sono identiche", ma == mb == 1.0, f"{ma} e {mb}")
check("quindi la base e' l'unica cosa che distingue", ta != tb,
      "stesse medie, stessa base: la tabella mostrerebbe due righe "
      "identiche per due misure diverse")

print("\n[3] Un archivio vecchio non deve mentire")
# Prima di questa correzione i file gia' scritti non hanno i campi. Se
# il caricamento li riempisse con zeri, la tabella mostrerebbe 0/0 e
# "0/0" sembrerebbe una misura. Meglio niente: la frazione assente
# vuol dire "non lo so".
vecchio = {"provider": "openrouter", "models": {MID: {"scores": {"code": 0.5},
                                                       "last_measured": 1.0}}}
json.dump(vecchio, open(path, "w", encoding="utf-8"))
c = Catalog("openrouter")
c._path = path
c.models[MID] = ModelProfile(info=ModelInfo(id=MID))
c.load_measurements()
check("il punteggio c'e' comunque", c.models[MID].scores == {"code": 0.5})
check("la frazione e' vuota, non zero",
      not c.models[MID].frazioni, str(c.models[MID].frazioni))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)