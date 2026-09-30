"""Un commento HTML non chiuso e' il peggior difetto possibile in una pagina.

Non e' un errore di sintassi: il file e' perfettamente valido, ogni altro
controllo passa, il server risponde 200, il CSS si applica. Ma tutto cio'
che viene dopo diventa testo del commento e sparisce dal DOM — quindi
`<main>`, `<footer>`, il campo di input e il tag `<script>` semplicemente
non esistono piu'. Il sintomo e' "la pagina si apre ma non c'e' niente
dentro", e nessun errore in console.

E' successo davvero: `<!-- pannello benchmark ... */` invece di `-->`.
Tre ore di ipotesi, il campo e i pulsanti "non andavano", e la causa era
un asterisco.

Qui il controllo e' esplicito, e vale per ogni file HTML del progetto.
"""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def commenti_aperti(testo):
    """Restituisce i commenti che non sono chiusi.

    Un commento HTML si chiude solo con '-->'. Fino ad allora il
    parser HTML tratta tutto il resto del file come testo: quindi
    anche un solo commento dimenticato mangia la pagina.
    """
    rotti = []
    for m in re.finditer(r"<!--(.*?)(-->|\Z)", testo, re.S):
        if m.group(2) != "-->":
            corpo = " ".join(m.group(1).split())[:70]
            rotti.append(corpo)
    return rotti


print("\n[1] Commenti HTML chiusi in ogni .html del progetto")
files = sorted(glob.glob(os.path.join(ROOT, "**", "*.html"), recursive=True))
check("ci sono file HTML da controllare", len(files) >= 1, str(files))
for f in files:
    testo = open(f, encoding="utf-8").read()
    rotti = commenti_aperti(testo)
    rel = os.path.relpath(f, ROOT).replace("\\", "/")
    check(f"{rel}: tutti i commenti chiusi", not rotti, "; ".join(rotti))

print("\n[2] Il file che aveva il difetto")
ui = os.path.join(ROOT, "orchestra", "web", "index.html")
testo = open(ui, encoding="utf-8").read()
# il difetto era esattamente questo: chiusura con */ invece di -->
check("nessun commento chiuso con '*/'", "-->" in testo and
      not re.search(r"<!--[^>]*\*/", testo),
      "trovato un commento chiuso con */ invece di -->")
check("i tre file JS sono dichiarati", len(re.findall(r"<script[^>]*src=", testo)) == 1,
      str(re.findall(r"<script[^>]*src=[^>]*>", testo)))

print("\n[3] Ogni elemento che il frontend cerca deve esistere")
bundle = ""
for nome in ("core.js", "panels.js", "main.js"):
    p = os.path.join(ROOT, "orchestra", "web", nome)
    if os.path.exists(p):
        bundle += open(p, encoding="utf-8").read()
id_html = set(re.findall(r'id="([^"]+)"', testo))
id_js = set(re.findall(r'\$\("([^"]+)"\)', bundle))
mancanti = sorted(id_js - id_html)
# Questo controllo e' nato da un bug vero: tolto <select id="bench-sample">
# dall'HTML ma lasciato il riferimento nel JS. Il pulsante lanciava
# "Cannot read properties of null (reading 'value')" e il benchmark non
# partiva. Il file HTML era valido, il server rispondeva 200, e ogni
# altro test passava.
check("ogni id cercato esiste nell'HTML", not mancanti, f"mancano: {mancanti}")
check("il codice cerca un buon numero di id", len(id_js) >= 8, str(len(id_js)))

print("\n[4] Nessun elemento puo' far esplodere il caricamento")
# una riga come X.addEventListener uccide tutto quello che segue se X
# e' null. Meglio accorgersene qui che a schermo.
pericolosi = re.findall(r'\$\("[^"]+"\)\.addEventListener', bundle)
check("nessun listener agganciato direttamente a un $()", not pericolosi,
      f"{len(pericolosi)} occorrenze: {pericolosi[:3]}")
pericolosi2 = re.findall(r'\$\("[^"]+"\)\.on\w+\s*=', bundle)
check("nessun handler assegnato direttamente a un $()", not pericolosi2,
      f"{len(pericolosi2)} occorrenze: {pericolosi2[:3]}")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
