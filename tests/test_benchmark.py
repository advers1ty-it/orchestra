"""Test del benchmark e del catalogo, senza chiamare l'API.

Qui la cosa che conta di più è che le VERIFICHE funzionino. Un benchmark
con una verifica rotta non misura i modelli: misura sé stesso, e dà
punteggi arbitrari con aria di autorità. Perciò ogni verifica viene
provata contro un file che DOVREBBE passare e uno che NON dovrebbe.

Il resto copre l'aggregazione e la persistenza, che sono le parti dove
un errore produce un routing sbagliato in silenzio.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.benchmark import (  # noqa: E402
    TASKS, RunResult, render_table, score, summarize, tasks_for,
    v_contains, v_file_lines, v_json_field, v_python_prints_exact,
    v_written,
)
from orchestra.catalog import (  # noqa: E402
    CATEGORIES, Catalog, ModelInfo, ModelProfile,
)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def workdir():
    d = tempfile.mkdtemp(prefix="orch_bench_")
    return d


# ------------------------------------------------------------------ verifiche
print("\n[1] Le verifiche distinguono il bene dal male")
# Questo e' il test che conta: se una verifica passa sempre, il benchmark
# non misura niente e restituisce 1.0 a qualunque modello.

d = workdir()
open(os.path.join(d, "ok.py"), "w").write("print(42)\n")
open(os.path.join(d, "bad.py"), "w").write("print(41)\n")
open(os.path.join(d, "crash.py"), "w").write("raise SystemExit(1)\n")
open(os.path.join(d, "loop.py"), "w").write("while True: pass\n")
open(os.path.join(d, "err.py"), "w").write("def f(:\n")

v = v_python_prints_exact("ok.py", ["42"])
check("file corretto passa", v(d)[0] is True, v(d)[1])
check("file sbagliato fallisce", v_python_prints_exact("ok.py", ["43"])(d)[0] is False)
check("file inesistente fallisce", v_python_prints_exact("nope.py", ["42"])(d)[0] is False)

# codice che non termina: deve fallire, non bloccare il benchmark
t0_check = v_python_prints_exact("loop.py", ["1"])
ok, why = t0_check(d)
check("codice infinito non blocca (timeout)", ok is False and "timeout" in why, why)

# codice che solleva
ok, why = v_python_prints_exact("err.py", ["1"])(d)
check("errore di sintassi non blocca", ok is False, why)

# contains
open(os.path.join(d, "c.txt"), "w").write("la risposta e' 18 ore")
check("contains trova", v_contains("c.txt", "18")(d)[0] is True)
check("contains mancante fallisce", v_contains("c.txt", "42")(d)[0] is False)
check("contains su file assente", v_contains("zz.txt", "x")(d)[0] is False)

# json
import json as _json
open(os.path.join(d, "d.json"), "w").write(_json.dumps({"nome": "orchestra", "attivo": True}))
open(os.path.join(d, "bad.json"), "w").write("{non json")
check("json campo corretto", v_json_field("d.json", "nome", "orchestra")(d)[0] is True)
check("json campo diverso", v_json_field("d.json", "nome", "altro")(d)[0] is False)
check("json campo mancante", v_json_field("d.json", "zzz", 1)(d)[0] is False)
ok, why = v_json_field("bad.json", "x", 1)(d)
check("json malformato fallisce pulito", ok is False and "JSON" in why, why)

# linee
open(os.path.join(d, "l.txt"), "w").write("1\n2\n3\n")
check("linee corrette", v_file_lines("l.txt", [(r"^1$", 1), (r"^2$", 1)])(d)[0] is True)
check("linee sbagliate", v_file_lines("l.txt", [(r"^1$", 2)])(d)[0] is False)
# regressione: senza re.M, `$` non matcha prima di \n e il task
# fallirebbe per QUALUNQUE modello
check("$ funziona a fine riga (re.M)",
      len(__import__("re").findall(r"^1$", "1\n2\n3\n", __import__("re").M)) == 1)
check("formattazione esatta passa",
      v_file_lines("l.txt", [(r"^1$", 1), (r"^2$", 1), (r"^3$", 1)])(d)[0] is True)

# written
os.makedirs(os.path.join(d, "s1"), exist_ok=True)
open(os.path.join(d, "s1", "a.txt"), "w").write("x")
check("file esistenti passano", v_written(["s1/a.txt"])(d)[0] is True)
check("file mancanti falliscono", v_written(["s1/zz.txt"])(d)[0] is False)
open(os.path.join(d, "vuoto.txt"), "w").write("")
check("file vuoti falliscono", v_written(["vuoto.txt"])(d)[0] is False)

shutil.rmtree(d, ignore_errors=True)

# ------------------------------------------------------------------ corpus
print("\n[2] Il corpus")
check("ci sono task", len(TASKS) >= 8, str(len(TASKS)))
check("categorie valide", all(t.category in CATEGORIES for t in TASKS),
      str({t.category for t in TASKS} - set(CATEGORIES)))
check("id univoci", len({t.id for t in TASKS}) == len(TASKS))
check("ogni task ha una verifica", all(callable(t.verify) for t in TASKS))
check("ogni task ha un prompt", all(len(t.prompt) > 30 for t in TASKS))
check("tasks_for filtra", len(tasks_for("code")) == 3, str(len(tasks_for("code"))))
check("tasks_for su tutto", len(tasks_for(None)) == len(TASKS))
check("tasks_for categoria ignota vuota", tasks_for("inesistente") == [])

# il ragionamento: verifichiamo che la risposta attesa sia quella giusta.
# Se il task e' sbagliato, il benchmark premia il modello sbagliato.
d = workdir()
open(os.path.join(d, "risposta.txt"), "w").write("18")
ok, why = v_contains("risposta.txt", "18")(d)
check("ragionamento: 18 ore e' la risposta attesa", ok is True, why)
# una risposta sbagliata deve fallire
check("ragionamento: 12 fallisce", v_contains("risposta.txt", "12")(d)[0] is False)
shutil.rmtree(d, ignore_errors=True)

# ------------------------------------------------------------------ scoring
print("\n[3] Aggregazione")


def rr(model, cat, passed, task_id="t", secs=1.0, tok=100):
    return RunResult(model=model, task_id=task_id, category=cat, passed=passed,
                     detail="" if passed else "no", seconds=secs,
                     prompt_tokens=tok, completion_tokens=tok, cost_usd=0.0,
                     tool_calls=1, tool_errors=0, stopped_because="risposta_finale")


check("score tutto passa", score([rr("m", "code", True), rr("m", "code", True)]) == 1.0)
check("score metà", score([rr("m", "code", True), rr("m", "code", False)]) == 0.5)
check("score nulla", score([rr("m", "code", False)]) == 0.0)
check("score su lista vuota", score([]) == 0.0)

s = summarize([
    rr("buono", "code", True), rr("buono", "reasoning", True),
    rr("medio", "code", True), rr("medio", "reasoning", False),
    rr("scarso", "code", False), rr("scarso", "reasoning", False),
])
check("riepilogo per modello", set(s["per_model"]) == {"buono", "medio", "scarso"})
check("punteggio migliore", s["per_model"]["buono"]["score"] == 1.0)
check("punteggio peggiore", s["per_model"]["scarso"]["score"] == 0.0)
check("specializzazione visibile",
      s["per_model"]["medio"]["by_category"]["code"] == 1.0
      and s["per_model"]["medio"]["by_category"]["reasoning"] == 0.0,
      str(s["per_model"]["medio"]["by_category"]))
check("riepilogo per categoria", set(s["by_category"]) == {"code", "reasoning"})

# la cosa che rende il benchmark utile: due modelli con profili diversi
prof_a = summarize([rr("A", "code", True), rr("A", "reasoning", False)])
prof_b = summarize([rr("B", "code", False), rr("B", "reasoning", True)])
check("profili opposti distinguibili",
      prof_a["per_model"]["A"]["by_category"]["code"] == 1.0
      and prof_b["per_model"]["B"]["by_category"]["reasoning"] == 1.0)

tab = render_table(s)
check("tabella ha un header", "modello" in tab, tab[:60])
check("tabella elenca i modelli", "buono" in tab and "scarso" in tab)
check("tabella dichiara n=1", "non è statistico" in tab or "non e' statistico" in tab)
check("tabella gestisce vuoto", "nessun risultato" in render_table({}))

# ------------------------------------------------------------------ catalogo
print("\n[4] Catalogo e capacità")
mi = ModelInfo(id="x/y:free", context_length=256000, prompt_price=0, completion_price=0,
               supports_tools=True)
check("modello free riconosciuto", mi.is_free is True)
check("nome corto", mi.short == "y", mi.short)
paid = ModelInfo(id="a/b", prompt_price=3.0, completion_price=15.0)
check("modello paid non free", paid.is_free is False)
check("costo calcolato", abs(paid.estimate_cost(1_000_000, 1_000_000) - 18.0) < 0.01,
      str(paid.estimate_cost(1_000_000, 1_000_000)))
check("costo zero per free", mi.estimate_cost(1_000_000, 1_000_000) == 0.0)

# da API reale
raw = {"id": "test/model:free", "context_length": 128000,
       "pricing": {"prompt": "0", "completion": "0"},
       "supported_parameters": ["tools", "temperature"]}
mi2 = ModelInfo.from_api(raw)
check("parsing da API", mi2.id == "test/model:free" and mi2.supports_tools is True)
check("prezzi stringa convertiti", mi2.prompt_price == 0.0)
# un modello senza tool non deve entrare nel catalogo
raw_no_tools = {"id": "x", "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["temperature"]}
check("senza tool non è supportato", ModelInfo.from_api(raw_no_tools).supports_tools is False)

# ipotesi vs fatti: e' il punto del modulo
prof = ModelProfile(info=mi)
check("capacità sconosciuta per default",
      prof.confidence("code") == "unknown", prof.confidence("code"))
check("non misurato non è best_for", prof.best_for("code") is False)
prof.scores = {"code": 0.9}
check("misurato ha confidence 'measured'", prof.confidence("code") == "measured")
check("misurato alto è best_for", prof.best_for("code") is True)
prof.scores = {"code": 0.2}
check("misurato basso non è best_for", prof.best_for("code") is False)

# persistenza
store = tempfile.mkdtemp(prefix="orch_cat_")
os.environ["ORCHESTRA_HOME"] = store
cat = Catalog("fake")
p1 = ModelProfile(info=ModelInfo(id="m/uno:free", supports_tools=True))
p1.scores = {"code": 0.75, "reasoning": 0.25}
p2 = ModelProfile(info=ModelInfo(id="m/due:free", supports_tools=True))
cat.models["m/uno:free"] = p1
cat.models["m/due:free"] = p2
cat.save()
check("file scritto", os.path.exists(cat._path))

cat2 = Catalog("fake")
cat2.models["m/uno:free"] = ModelProfile(info=ModelInfo(id="m/uno:free", supports_tools=True))
n_applied = cat2.load_measurements()
check("misurazioni ricaricate",
      cat2.models["m/uno:free"].scores == {"code": 0.75, "reasoning": 0.25},
      str(cat2.models["m/uno:free"].scores))
check("conteggio applicazioni", n_applied == 1, str(n_applied))
# un modello ritirato dal provider non viene perso: resta su disco
check("modello ritirato è stale", "m/due:free" in cat2.stale_measurements(),
      str(cat2.stale_measurements()))
check("modello ritirato non è nel catalogo", "m/due:free" not in cat2.models)
# se torna, le misurazioni sono ancora lì
cat2.models["m/due:free"] = ModelProfile(info=ModelInfo(id="m/due:free", supports_tools=True))
cat2.load_measurements()
check("modello che torna ricarica", "m/due:free" not in cat2.stale_measurements())

# best_for sul catalogo
check("best_for sceglie il migliore misurato",
      cat2.best_for("code").info.id == "m/uno:free")
check("best_for su categoria non misurata", cat2.best_for("writing") is None)
check("leaderboard", cat2.leaderboard("code")[0][0] == "uno",
      str(cat2.leaderboard("code")))
check("by_score ordinato", [p.info.id for p in cat2.by_score("reasoning")] == ["m/uno:free"])
shutil.rmtree(store, ignore_errors=True)

# _run_python con path RELATIVO: era il bug che faceva fallire task con
# codice perfetto. Il cwd di un processo figlio e' diverso, quindi un
# path relativo non si risolve dove pensiamo.
from orchestra.benchmark import _run_python  # noqa: E402

rel_base = tempfile.mkdtemp(prefix="orch_rel_")
old_cwd = os.getcwd()
os.chdir(rel_base)
os.makedirs("sub", exist_ok=True)
with open(os.path.join("sub", "x.py"), "w") as f:
    f.write("print('RELPATH_OK')\n")
try:
    ok, out = _run_python("sub", "print('RELPATH_OK')")
    check("_run_python con path relativo", ok is True and "RELPATH_OK" in out, f"{ok} {out[:80]}")
finally:
    os.chdir(old_cwd)
    shutil.rmtree(rel_base, ignore_errors=True)

# e con path assoluto
abs_w = workdir()
with open(os.path.join(abs_w, "y.py"), "w") as f:
    f.write("print('ABSPATH_OK')\n")
ok, out = _run_python(abs_w, "print('ABSPATH_OK')")
check("_run_python con path assoluto", ok is True and "ABSPATH_OK" in out, out[:60])
shutil.rmtree(abs_w, ignore_errors=True)

# un modello irraggiungibile non è un modello scarso. Se finisce nel
# punteggio a 0.00, il benchmark consiglia il modello sbagliato.
u = RunResult(model="bloccato", task_id="t", category="code", passed=False,
              detail="", seconds=1, prompt_tokens=0, completion_tokens=0,
              cost_usd=0, tool_calls=0, tool_errors=0, stopped_because="",
              error="ProviderError: 403 only available on agentic harnesses",
              unusable=True)
s2 = summarize([rr("buono", "code", True), u])
check("modello unusable escluso dal punteggio",
      "bloccato" not in s2["per_model"], str(list(s2["per_model"])))
check("modello unusable elencato a parte", s2["unusable_models"] == ["bloccato"],
      str(s2["unusable_models"]))
check("il punteggio degli altri resta intatto", s2["per_model"]["buono"]["score"] == 1.0)
check("tabella dichiara i non misurati",
      "NON MISURATI" in render_table(s2), render_table(s2)[-200:])

print("\n[4] La root segue ORCHESTRA_ROOT a runtime")
# Regressione seria: ROOT era congelato all'import, e il benchmark cambia
# la root a ogni task. Sintomo: benchmark intero a 0.00, sembrava che i
# modelli fossimo pessimi quando il codice non scriveva dove credevamo.
from orchestra import tools as T  # noqa: E402

r1 = workdir()
os.environ["ORCHESTRA_ROOT"] = r1
T.ROOT = T._root()
reg_r = T.default_registry()
reg_r.get("write_file").handler(path="uno.txt", content="a")
check("scrive nella root nuova", os.path.exists(os.path.join(r1, "uno.txt")))

r2 = workdir()
os.environ["ORCHESTRA_ROOT"] = r2
T.ROOT = T._root()
reg_r.get("write_file").handler(path="due.txt", content="b")
check("scrive nella root successiva", os.path.exists(os.path.join(r2, "due.txt")))
check("non scrive nella root precedente", not os.path.exists(os.path.join(r1, "due.txt")))

out2 = reg_r.get("list_dir").handler(path=".")
check("list_dir guarda la root nuova", "due.txt" in out2, out2[:120])

shell_out = reg_r.get("run_shell").handler(command="pwd")
# su Windows la root e' tipo C:\Users\...\orch_bench_x, e POSIX la
# traduce in /tmp/...: confrontiamo l'ultimo segmento, che e' univoco
tail_dir = os.path.basename(r2.rstrip("\\/"))
check("run_shell usa la cwd nuova", tail_dir in shell_out.replace("\\", "/"),
      f"atteso {tail_dir!r} in {shell_out[:120]!r}")

# il traversal deve funzionare anche con root nuova
try:
    reg_r.get("read_file").handler(path="../../etc/passwd")
    check("traversal bloccato con root nuova", False, "ha letto!")
except ValueError:
    check("traversal bloccato con root nuova", True)

shutil.rmtree(r1, ignore_errors=True)
shutil.rmtree(r2, ignore_errors=True)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
