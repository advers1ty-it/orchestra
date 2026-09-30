"""Ogni categoria offerta deve avere almeno un task. O viceversa.

Il difetto: il menu scopo elencava nove categorie, il benchmark ne
misurava sette, e le altre due comparivano come "non ancora misurato".
Non e' vero: non esiste nessun test da lanciare. "Non ancora" e "non
possibile" sono la stessa frase detta a un utente che aspetta, e a uno
che sta per fare una domanda a cui nessuno puo' rispondere.

Il pericolo di questo test e' che diventi un elenco di categorie
accettate scritto a mano: sarebbe la stessa divergenza di prima, solo
spostata piu' in basso. Quindi non confronta due liste fisse: confronta
il menu con i task REALMENTE registrati, e segnala le categorie vuote
come un fatto da decidere, non come un errore.
"""

import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.benchmark import tasks_for  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
panels = open(os.path.join(ROOT, "orchestra", "web", "panels.js"), encoding="utf-8").read()
m = re.search(r"const ordine = \[(.*?)\]", panels)
offerte = [x.strip().strip('"') for x in m.group(1).split(",") if x.strip()]

per_cat = collections.Counter(t.category for t in tasks_for())

print("[1] Le due liste sono coerenti")
print("   menu:", len(offerte), "categorie")
print("   benchmark:", len(per_cat), "categorie con almeno un task")
check("il menu non inventa categorie",
      set(offerte) >= set(per_cat),
      str(sorted(set(per_cat) - set(offerte))))
check("non ci sono categorie duplicate nel menu",
      len(offerte) == len(set(offerte)), str(offerte))

print("\n[2] I dati sul server dicono la verita'")
# /api/categorie risponde dai task registrati: e' la stessa fonte che
# usa la UI. Se il contatore tornasse qualcos'altro, la UI direbbe una
# cosa e il server un'altra.
import json  # noqa: E402
import urllib.request  # noqa: E402

try:
    with urllib.request.urlopen("http://127.0.0.1:8737/api/categorie", timeout=20) as f:
        dati = json.load(f)
    server = {c["id"]: c["tasks"] for c in dati["categorie"]}
    check("il conteggio del server coincide con i task registrati",
          all(server.get(c) == per_cat.get(c, 0) for c in set(server) | set(per_cat)),
          str({c: (server.get(c), per_cat.get(c, 0))
               for c in set(server) | set(per_cat)
               if server.get(c) != per_cat.get(c, 0)}))
    check("il totale delle task e' la somma reale",
          dati.get("totale_task") == sum(per_cat.values()),
          f'{dati.get("totale_task")} vs {sum(per_cat.values())}')
    check("il totale delle categorie conta le categorie",
          dati.get("totale_categorie") == len(server),
          str(dati.get("totale_categorie")))
    check("le categorie misurabili sono quelle con task",
          dati.get("categorie_misurabili") == len([c for c in server if server[c] > 0]),
          str(dati.get("categorie_misurabili")))
except Exception as e:  # noqa: BLE001
    check("il server risponde (server acceso?)", False, str(e))
    server = {}

print("\n[3] Le categorie vuote sono dichiarate come vuote")
# Non e' un fallimento: e' il punto. Il test esiste perche' il
# difetto originale non falliva da nessuna parte — era un testo
# mostrato, e un testo non fallisce nessun test.
vuote = [c for c in offerte if per_cat.get(c, 0) == 0]
print("   categorie senza task:", vuote or "nessuna")
check("le categorie vuote sono poche, non la maggior parte",
      len(vuote) < len(offerte) / 2,
      f"{len(vuote)} su {len(offerte)}")

print("\n[4] La UI distingue 'vuota' da 'da misurare'")
# Il punto del fix: due messaggi diversi per due situazioni diverse.
check("la UI chiede le categorie al server",
      "caricaCategorie" in panels and "/api/categorie" in panels)
check("usa il conteggio delle task",
      "taskDi" in panels)
check("distingue i due casi",
      "senza test" in panels and "non ancora misurato" in panels,
      "manca uno dei due messaggi")
check("le categorie senza test hanno un avviso proprio",
      "avviso-grave" in panels)

print("\n[5] Ogni categoria offerta nel menu esiste nel catalogo")
# Il menu scopo e' una promessa: "scegli scrittura" fa pensare che
# qualcuno abbia confrontato i modelli su quello. Se la categoria non
# esiste in CATEGORIES, il menu offre qualcosa che il backend non
# conosce, e il click produce una categoria che nessuno calcola.
from orchestra.catalog import CATEGORIES, CATEGORY_LABEL  # noqa: E402

check("ogni categoria del menu esiste nel catalogo",
      set(offerte) <= set(CATEGORIES),
      str(sorted(set(offerte) - set(CATEGORIES))))
check("ogni categoria ha un'etichetta leggibile",
      all(c in CATEGORY_LABEL and CATEGORY_LABEL[c] for c in CATEGORIES),
      str([c for c in CATEGORIES if not CATEGORY_LABEL.get(c)]))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
