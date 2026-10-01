"""Il punteggio del benchmark: percentuale, frazione, e niente liste scritte a mano.

Tre difetti che questo file chiude:

1. il menu categorie aveva cinque voci scritte nell'HTML mentre il
   server ne manda nove — estrazione, scrittura, js, web e app non
   erano raggiungibili da nessuna parte
2. il punteggio era una frazione 0..1 con due decimali: con 2-3 test
   per categoria i valori possibili sono cinque, e 0.67 e 0.66
   arrotondano allo stesso numero sul display
3. la percentuale senza la base nasconde che 2/3 e 13/20 non sono
   confrontabili
"""

import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("[1] Il menu categorie non e' scritto a mano")
html = io.open(os.path.join(ROOT, "orchestra", "web", "index.html"),
               encoding="utf-8").read()
i = html.index('id="bench-cat"')
j = html.index("</select>", i)
menu = html[i:j]
opzioni = [l.strip() for l in menu.splitlines() if "<option" in l]
check("il menu ha una sola opzione scritta",
      len(opzioni) == 1, f"{len(opzioni)}: {opzioni}")
check("ed e' 'tutte', che e' una scelta e non una categoria",
      'value="all"' in opzioni[0], opzioni[0][:70])
# Nessuna delle vecchie cinque deve essere rimasta scritta a mano:
# sono quello che invecchiava da solo.
for cat in ("code", "reasoning", "instruction", "tool_use"):
    check(f"'{cat}' non e' scritto nel menu",
          f'value="{cat}"' not in menu,
          "una categoria scritta qui non esiste se il backend ne aggiunge una")

print("\n[2] Il menu si riempie col server")
js = io.open(os.path.join(ROOT, "orchestra", "web", "panels.js"),
             encoding="utf-8").read()
check("qualcuno riempie benchCat", "benchCat" in js and "replaceChildren" in js)
k = js.find("benchCat.replaceChildren")
check("e lo fa dentro la routine delle categorie", k > 0)
# l'elenco scritto a mano delle 9: e' la stessa malattia in un altro
# posto, e nessuno se ne sarebbe accorto
for vecchia in ('["js", "web", "app", "code"', '["code", "reasoning"'):
    check(f"l'elenco scritto a mano {vecchia[:20]} non c'e' piu'",
          vecchia not in js)
check("l'ordine viene dal server",
      "categorieServer.map" in js,
      "senza questo, la decima categoria non appare")
check("e accanto al nome dice quanti test ha",
      "test" in js[js.find("benchCat.replaceChildren"):][:600],
      "senza il numero, 'estrazione' sembra una categoria minore")

print("\n[3] Il punteggio e' una percentuale")
i = js.find("function punteggioDi")
check("la funzione c'e'", i > 0)
corpo = js[i:i + 2200] if i > 0 else ""
check("calcola una percentuale", "Math.round(v * 100)" in corpo,
      "0.50 non e' leggibile come capacita'")
check("non stampa piu' due decimali di una frazione",
      "v.toFixed(2)" not in corpo,
      "0.67 e 0.66 diventano lo stesso numero sul display")
check("e accanto c'e' la frazione", "passati" in corpo and "quanti" in corpo,
      "la percentuale senza la base nasconde la base")
check("il titolo avverte che non e' confrontabile",
      "STESSA" in corpo or "confrontabile" in corpo,
      "due punteggi di categorie diverse non si confrontano")

print("\n[4] Su 'tutte' non c'e' un punteggio unico")
check("mostra le categorie misurate, non una media",
      "CATEGORIE_TOTALE" in corpo and 'cat === "all"' in corpo,
      "la media di percentuali su categorie diverse non significa niente")

print("\n[5] Il backend porta la base")
import orchestra.benchmark as B  # noqa: E402
import orchestra.catalog as C  # noqa: E402
# RunResult ha nove campi obbligatori. Si costruisce una volta sola e
# si cambia solo quello che conta: indovinare la firma a ogni tentativo
# fa perdere un giro per un errore che il traceback gia' diceva.
base = dict(task_id="t", detail="", seconds=1.0, prompt_tokens=10,
            completion_tokens=10, cost_usd=0.0, tool_calls=0,
            tool_errors=[], stopped_because="fine", unusable=False)


def res(cat, ok):
    return B.RunResult(model="m", category=cat, passed=ok, **base)


s = B.summarize([res("code", True), res("code", False),
                 res("reasoning", True), res("reasoning", False)])
bc = s["per_model"]["m"]["by_category"]
check("by_category e' un dizionario per categoria",
      isinstance(bc["code"], dict), str(bc)[:90])
check("e porta il punteggio", bc["code"].get("score") == 0.5,
      str(bc["code"]))
check("e i passati", bc["code"].get("passati") == 1, str(bc["code"]))
check("e quanti ne erano", bc["code"].get("quanti") == 2, str(bc["code"]))
check("una categoria diversa ha base diversa",
      bc["reasoning"]["quanti"] == 2)

print("\n[6] Il profilo conserva tutto")
p = C.ModelProfile(info=C.ModelInfo(id="x"))
p.scores = {"code": 0.5}
p.frazioni = {"code": 1}
p.task_per_cat = {"code": 2}
blob = p.to_dict() if hasattr(p, "to_dict") else None
check("scores va nel dizionario", blob and "scores" in blob)
check("e anche le frazioni", blob and "frazioni" in blob,
      "senza, la frazione si perde al riavvio")
check("e quanti test per categoria", blob and "task_per_cat" in blob)

print("\n[7] Il riepilogo testuale non mente")
# Il nome e' render_table, non report: il test lo indovinava e senza
# hasattr tornava None, e "il riepilogo si genera" falliva senza dire
# che il codice sotto non era mai stato eseguito. Un test che non
# gira e' verde quanto a fallito.
import inspect  # noqa: E402
nome_tab = [n for n, _ in inspect.getmembers(B, inspect.isfunction)
            if not n.startswith("_") and ("table" in n or "report" in n)]
check("la funzione che stampa la tabella c'e'",
      bool(nome_tab), str([n for n in dir(B) if "tab" in n]))
if nome_tab:
    out = getattr(B, nome_tab[0])(s)
    check("il riepilogo si genera", out is not None)
    testo = out if isinstance(out, str) else "\n".join(map(str, out))
    check("non stampa un dizionario al posto di un numero",
          "{'score'" not in testo and "{'passati'" not in testo,
          "by_category era un numero, ora e' un dizionario")
    check("mostra la percentuale", "%" in testo)
    check("e la frazione", "/" in testo)
    check("e dice che va letto per categoria",
          "categoria" in testo.lower())
    check("e che la media non serve per scegliere",
          "non per scegliere" in testo or "media" in testo.lower())

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)