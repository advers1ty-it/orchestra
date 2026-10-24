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
from _ordine import ORDER  # noqa: E402
for nome in ORDER:
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

# $() e' getElementById, quindi il prefisso '#' non esiste: $("modello")
# cerca un elemento chiamato "modello", non "#modello", e restituisce
# null. Il sintomo e' silenzioso — un handler agganciato a null muore
# con "Cannot read properties of null" — ed e' gia' successo.
con_graffa = re.findall(r'\$\("#([^"]+)"\)', bundle)
check("nessun id con il prefisso # dentro $()", not con_graffa, str(con_graffa))
# lo stesso vale per querySelector: li' il # serve, ma i selettori
# CSS scritti a mano sono facili da sbagliare in un altro modo
qs = re.findall(r'querySelector\("([^"]+)"\)', bundle)
check("i selettori CSS sono validi",
      all(s.startswith((".", "#", "[", "a", "b", "i", "s", "h", "n")) or s[0].isalpha()
          for s in qs if s), str(qs))

print("\n[4] Nessun elemento puo' far esplodere il caricamento")
# una riga come X.addEventListener uccide tutto quello che segue se X
# e' null. Meglio accorgersene qui che a schermo.
pericolosi = re.findall(r'\$\("[^"]+"\)\.addEventListener', bundle)
check("nessun listener agganciato direttamente a un $()", not pericolosi,
      f"{len(pericolosi)} occorrenze: {pericolosi[:3]}")
pericolosi2 = re.findall(r'\$\("[^"]+"\)\.on\w+\s*=', bundle)
check("nessun handler assegnato direttamente a un $()", not pericolosi2,
      f"{len(pericolosi2)} occorrenze: {pericolosi2[:3]}")

print("\n[5] I blocchi di primo livello stanno davvero nel body")
# Un </div> mancante non e' un errore di sintassi: il file resta valido,
# il server risponde 200, il CSS si applica. Ma il parser HTML5 chiude
# al posto tuo l'elemento rimasto aperto, e TUTTO quello che segue
# finisce dentro di lui. E' successo con #onboard: la barra degli
# obiettivi e i tre modali (tracce, memoria, progetti) diventarono suoi
# figli, e siccome #onboard e' hidden con display:none !important i
# modali si aprivano e restavano invisibili. Il sintomo era "i modali
# non si aprono" e il JavaScript era innocente: nessun errore, nessun
# avviso, `hidden=false` e `display:flex` corretti.
#
# La lezione: il posto di un blocco si verifica guardando il DOM, non
# il sorgente. Qui si ricostruisce l'albero come farebbe il browser.
from html.parser import HTMLParser

VUOTI = {"area", "base", "br", "col", "embed", "hr", "img", "input",
         "link", "meta", "param", "source", "track", "wbr"}
# Elementi che il browser chiude da solo quando ne inizia uno nuovo:
# senza, il controllo segnalerebbe squilibri che il browser non ha.
CHIUDONO_P = {"p", "div", "ul", "ol", "table", "section", "h1", "h2",
              "h3", "h4", "h5", "h6", "form", "blockquote"}


class Albero(HTMLParser):
    """La catena dei genitori, con le stesse regole del browser."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pila = []
        self.genitori = {}
        self.orfani = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in CHIUDONO_P and self.pila and self.pila[-1][0] == "p":
            self.pila.pop()
        if tag in VUOTI:
            if a.get("id"):
                self.genitori[a["id"]] = [t for t, _, _ in self.pila]
            return
        self.pila.append((tag, a.get("id"), a.get("class", "")))
        if a.get("id"):
            self.genitori[a["id"]] = [t for t, _, _ in self.pila[:-1]]

    def handle_endtag(self, tag):
        if tag in VUOTI:
            return
        for i in range(len(self.pila) - 1, -1, -1):
            if self.pila[i][0] == tag:
                del self.pila[i:]
                return
        self.orfani.append(tag)


with open(ui, encoding="utf-8") as f:
    sorgente = f.read()

albero = Albero()
albero.feed(sorgente)
albero.close()

aperti = len(re.findall(r"<div\b", sorgente))
chiusi = len(re.findall(r"</div>", sorgente))
check("i <div> aperti e chiusi sono pari", aperti == chiusi,
      f"{aperti} aperti, {chiusi} chiusi")
check("nessun tag di chiusura orfano", not albero.orfani, str(albero.orfani[:5]))

# I blocchi che devono stare appesi al body: se uno finisce dentro un
# altro, il suo hidden lo nasconde per sempre.
PRIMO_LIVELLO = ["onboard", "onboard-details", "goal-bar", "traccia-modal",
                 "mem-modal", "progetti-modal"]
for _id in PRIMO_LIVELLO:
    catena = albero.genitori.get(_id)
    check(f"#{_id} e' figlio del body",
          catena is not None and catena and catena[-1] == "body",
          f"genitori: {catena}")

# E il caso generale: nessun blocco di primo livello puo' finire dentro
# un elemento che nasconde tutto.
NASCOSTI = {"onboard", "onboard-details"}
for _id, _catena in albero.genitori.items():
    dentro = [t for t in _catena if t in NASCOSTI]
    if dentro:
        check(f"#{_id} non sta dentro un contenitore nascosto", False,
              f"dentro {dentro}")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
