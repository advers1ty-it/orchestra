"""Il cestino e la griglia delle skill.

Tre cose che l'utente chiede e che devono funzionare davvero:

1. cancellare una skill e poterla vedere nel cestino — prima si
   cancellava e non si sapeva dove fosse andata
2. poterla rimettere
3. poterla cancellare per davvero, con una conferma che non si clicca
   per sbaglio

E le skill come schede in griglia, non come lista: con cento righe si
scorreva per metri.
"""

import io
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = f"http://127.0.0.1:{os.environ.get('ORCHESTRA_TEST_PORT', '8737')}"
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def post(body):
    r = urllib.request.Request(BASE + "/api/skill", json.dumps(body).encode(),
                               {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return f.status, json.loads(f.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


print("[1] Il server e' in piedi")
try:
    with urllib.request.urlopen(BASE + "/api/state", timeout=10):
        check("risponde", True)
except Exception as e:
    check("risponde", False, f"{type(e).__name__} — avvia il server")
    sys.exit(1)

print("\n[2] Il cestino e' visibile")
# Prima esisteva solo come cartella sul disco: si cancellava e non si
# sapeva dove fosse andata. Ora l'elenco torna con ogni risposta.
stato, d = post({"azione": "cestino"})
check("l'azione esiste", stato == 200, f"HTTP {stato}: {str(d)[:80]}")
check("e porta il cestino", "cestino" in d, str(list(d))[:90])
check("e anche l'elenco", "elenco" in d)
check("l'elenco torna con ogni risposta",
      "cestino" in post({"azione": "elenca"})[1],
      "il primo caricamento del pannello non saprebbe cosa mostrare")

print("\n[3] Il giro completo: cancella, vedi, rimetti")
import shutil
import tempfile
store = tempfile.mkdtemp(prefix="store-c-")
for n in ("giro-una", "giro-due"):
    p = os.path.join(store, n)
    os.makedirs(p, exist_ok=True)
    open(os.path.join(p, "SKILL.md"), "w", encoding="utf-8").write(
        f"---\nname: {n}\ndescription: Skill di prova {n}.\n---\n\n"
        "Procedura di prova. " * 30)

stato, d = post({"azione": "importa", "cartella": store, "categoria": "prova"})
check("importa", d.get("importate") == 2, str(d.get("importate")))

stato, d = post({"azione": "cancella", "nome": "giro-due"})
check("cancella", d.get("ok"), str(d)[:90])
nel_cestino = [v["nome"] for v in (d.get("cestino") or [])]
check("e la si vede nel cestino", "giro-due" in nel_cestino, str(nel_cestino))
check("con la data", any(v.get("data") for v in d["cestino"]),
      str(d["cestino"][:1])[:90])
check("non e' piu' nell'elenco attivo",
      not any(s["nome"] == "giro-due"
              for s in d["elenco"]["lista_scaricate"]))

stato, d = post({"azione": "ripristina", "nome": "giro-due"})
check("si rimette", d.get("ok"), str(d)[:90])
check("e torna nell'elenco attivo",
      any(s["nome"] == "giro-due"
          for s in d["elenco"]["lista_scaricate"]))
check("torna nella sua categoria",
      any(s["nome"] == "giro-due" and "prova" in s["categoria"]
          for s in d["elenco"]["lista_scaricate"]),
      str([(s["nome"], s["categoria"]) for s in d["elenco"]["lista_scaricate"]
           if s["nome"] == "giro-due"]))
check("il cestino si svuota", not d.get("cestino"), str(d.get("cestino")))

print("\n[4] La cancellazione definitiva")
stato, d = post({"azione": "cancella", "nome": "giro-una"})
nel_cestino = [v["nome"] for v in (d.get("cestino") or [])]
check("nel cestino", "giro-una" in nel_cestino, str(nel_cestino))

stato, d = post({"azione": "cancella_definitivo", "nome": "giro-una"})
check("cancella per sempre", d.get("ok"), str(d)[:90])
check("non e' piu' nel cestino",
      not any(v["nome"] == "giro-una" for v in (d.get("cestino") or [])),
      str(d.get("cestino")))
stato, d = post({"azione": "ripristina", "nome": "giro-una"})
check("e non si recupera", not d.get("ok"), str(d)[:80])
check("con un motivo leggibile", "cestino" in d.get("error", ""),
      str(d.get("error"))[:80])

# una voce che non c'e'
stato, d = post({"azione": "cancella_definitivo", "nome": "mai-esistita"})
check("una inesistente e' rifiutata", stato == 400, f"HTTP {stato}")

print("\n[5] Svuotare il cestino")
post({"azione": "importa", "cartella": store, "categoria": "prova"})
post({"azione": "cancella", "nome": "giro-una"})
post({"azione": "cancella", "nome": "giro-due"})
stato, prima = post({"azione": "cestino"})
check("il cestino ha due voci", len(prima.get("cestino") or []) == 2,
      str(len(prima.get("cestino") or [])))
stato, d = post({"azione": "svuota_cestino"})
check("svuota", d.get("ok"), str(d)[:90])
check("e non rimane niente", not d.get("cestino"), str(d.get("cestino")))
check("dice quante", d.get("rimosse", 0) >= 2, str(d.get("rimosse")))

print("\n[6] Le skill sono schede in griglia, non righe")
html = io.open(os.path.join(ROOT, "orchestra", "web", "index.html"),
               encoding="utf-8").read()
css = io.open(os.path.join(ROOT, "orchestra", "web", "app.css"),
              encoding="utf-8").read()
js = io.open(os.path.join(ROOT, "orchestra", "web", "panels.js"),
             encoding="utf-8").read()
check("le liste sono griglie", 'class="skill-griglia"' in html,
      "manca la griglia")
check("non c'e' piu' skill-lista nell'HTML", "skill-lista" not in html)
check("la griglia e' una griglia", ".skill-griglia" in css and "display: grid" in css)
# tre o quattro per riga: con auto-fill e minimo 190px su 900px di
# pannello ne stanno quattro
check("le colonne si adattano alla larghezza",
      "auto-fill" in css and "minmax" in css,
      "senza auto-fit la griglia resta a una colonza stretta")
check("la scheda esiste come classe", ".skill-carta" in css)
check("e il JS costruisce schede", "function skillCarta(" in js)
check("e non piu' righe", "function skillRiga(" not in js)
check("la descrizione sta su due righe", "line-clamp" in css,
      "senza, le schede hanno altezze diverse")

print("\n[7] Il cestino e' una sezione, e si arriva")
check("la tab esiste", 'id="opz-tab-cestino"' in html)
check("la sezione esiste", 'id="opz-sez-cestino"' in html)
check("il pulsante svuota c'e'", 'id="skill-svuota"' in html)
check("il contenitore del cestino c'e'", 'id="skill-cestino"' in html)
check("la funzione che costruisce la scheda esiste",
      "function skillCartaCestino" in js)
# Il punto, e il difetto che questo test non aveva visto: la funzione
# esisteva e il pannello mostrava lo stesso il cestino vuoto. Il
# blocco che lo disegna dentro disegnaSkill MANCAVA, perche' la mia
# guardia chiedeva "questa stringa e' gia' nel file?" e la stringa
# c'era gia' altrove.
#
# Invisibile dal lato server: /api/skill rispondeva correttamente, il
# backend era a posto, e il test passava controllando che il nome
# della funzione fosse nel sorgente. Il pannello vuoto non lo
# distingueva dal pannello funzionante.
i = js.find("function disegnaSkill")
corpo = js[i:i + 6000] if i > 0 else ""
check("disegnaSkill legge il contenitore del cestino",
      "$(" + chr(34) + "skill-cestino" + chr(34) + ")" in corpo,
      "il cestino non viene mai letto: resta vuoto per sempre")
check("e riempie il contenitore",
      "skillCartaCestino" in corpo,
      "il contenitore si svuota ma non si riempie")
check("e il vuoto spiega, non tace",
      "da recuperare" in corpo and "rimetterle" in corpo,
      "il vuoto e' uno spazio bianco, non un messaggio")

print("\n[8] La conferma chiede una parola, non un si'")
# La cancellazione definitiva non ha ritorno. Un bottone "Cancella"
# che si clicca per sbaglio e' il modo migliore per perdere roba.
check("si scrive CANCELLA", "CANCELLA" in js)
check("e la risposta viene confrontata",
      'toUpperCase() === "CANCELLA"' in js)
check("la cancellazione definitiva e' un'azione separata dallo svuota",
      "cancella_definitivo" in js and "svuota_cestino" in js,
      "stessa azione per una voce e per tutto: perde piu' di quanto chiedi")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
shutil.rmtree(store, ignore_errors=True)
sys.exit(1 if FAIL else 0)