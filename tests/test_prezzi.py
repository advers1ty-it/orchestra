"""I prezzi devono essere leggibili, e leggibili sul numero vero.

Il difetto: OpenRouter manda i prezzi per TOKEN (5e-07), il codice li
stampava cosi' com'erano con toFixed(4), e il risultato era che 377
modelli su 379 dicevano "$0.0000/1M". Non un arrotondamento strano: il
99% del menu diceva la stessa cosa, quindi non diceva niente.

Questi test usano i numeri reali del catalogo, non esempi scelti a
mano: se il formato regge sul minimo e sul massimo veri, regge su tutto.
"""

import json
import os
import re
import sys
import urllib.request

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def node_prezzi():
    """Esegue price_label e costo_breve sul catalogo vero."""
    web = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "orchestra", "web")
    src = ""
    for f in ("core.js",):
        src += open(os.path.join(web, f), encoding="utf-8").read() + "\n"
    # le due funzioni, isolate dal resto del file che ha bisogno del DOM
    out = os.path.join(os.environ.get("TEMP", "."), "_prezzi.js")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("""
globalThis.document = {
  getElementById: () => null,
  // serve al pannello a sezioni; senza, collegaSezioni() muore
  querySelectorAll: () => [],
  querySelector: () => null,
};
globalThis.window = globalThis;
""")
        for nome in ("price_label", "costo_stimato", "costo_breve"):
            m = re.search(r"function " + nome + r"\([\s\S]*?\n\}", src)
            if not m:
                print("  non trovo", nome)
                sys.exit(1)
            fh.write(m.group(0) + "\n\n")
        fh.write("""
const cat = JSON.parse(require('fs').readFileSync(process.env.CATALOGO, 'utf8'));
const fuori = [];
for (const m of cat) fuori.push({ short: m.short, free: m.free,
  prezzo: price_label(m), costo: costo_breve(m, 10000) });
console.log(JSON.stringify(fuori));
""")
    import subprocess
    r = subprocess.run(["node", out], capture_output=True, text=True,
                       env=dict(os.environ, CATALOGO=tmp))
    if r.returncode != 0:
        print("  node:", r.stderr[:300])
        sys.exit(1)
    return json.loads(r.stdout)


print("[1] Il catalogo reale, non un esempio")
try:
    with urllib.request.urlopen("http://127.0.0.1:8737/api/models", timeout=20) as f:
        dati = json.load(f)
except Exception as e:  # noqa: BLE001
    print("  server non raggiungibile:", e)
    print("  avvialo con: python3 -m orchestra.cli web --no-browser")
    sys.exit(2)

modelli = dati.get("models") or []
check("il catalogo c'e'", len(modelli) > 100, f"{len(modelli)} modelli")

tmp = os.path.join(os.environ.get("TEMP", "."), "_cat.json")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(modelli, f)
def numero(testo: str) -> float:
    """Il primo numero di una stringa etichettata.

    Non un [^\d.] globale: quello prendeva anche il "10k" finale e il
    punto medio del separatore, e restituiva 0.00801 invece di 0.008.
    Un regex che legge il numero sbagliato fa fallire un test che
    dovrebbe passare, e il risultato e' fermare a guardare numeri che
    non hanno niente a che fare col prezzo.
    """
    m = re.search(r"\d+(?:\.\d+)?", testo)
    return float(m.group(0)) if m else 0.0


risultati = node_prezzi()

pagati = [r for r in risultati if not r["free"]]
check("i modelli a pagamento ci sono", len(pagati) > 100, str(len(pagati)))

print("\n[2] Nessun prezzo deve apparire come zero")
# Il difetto originale. Non basta dire "pochi": se anche uno solo mostra
# 0.0000 e' la stessa bug, solo meno frequente.
zerosi = [r for r in pagati if re.search(r"\$\s*0\.0+(\s|$|/)", r["prezzo"])]
check("nessun prezzo stampato come zero", not zerosi,
      f"{len(zerosi)} su {len(pagati)}; es. {zerosi[:2]}")

print("\n[3] Ogni prezzo e' un numero, non una decorazione")
cattivi = [r for r in risultati
           if r["prezzo"] not in ("free", "prezzo variabile")
           and not re.match(r"^\$\d", r["prezzo"])]
check("il formato e' sempre $ + numero", not cattivi, str(cattivi[:2]))

print("\n[4] Il prezzo per milione e' coerente col prezzo reale")
# Un errore di un milione in una riga si vede subito: un prezzo sotto
# 0.01 $/1M e' improbabile, e sopra 1000 anche.
sospetti = []
for r, m in zip(risultati, modelli):
    if r["free"] or r["prezzo"] == "prezzo variabile":
        continue
    n = numero(r["prezzo"])
    atteso = m["prompt_price"] * 1_000_000
    if abs(n - atteso) > max(0.001, atteso * 0.01):
        sospetti.append((r["short"], r["prezzo"], round(atteso, 4)))
check("il valore corrisponde a prezzo x 1.000.000", not sospetti, str(sospetti[:3]))

print("\n[5] Il costo per 10k token e' derivato dal prezzo, ricalcolato qui")
# Il punto di questo test e' che ricalcola DA SOLO, in Python, senza
# riusare la formula del JavaScript. Prima ricalcolava con la stessa
# divisione per 1000 che aveva il codice, e quindi confermava il
# difetto invece di vederlo: un test che verifica se stesso verifica
# che due errori coincidano.
# 0.8 $/1M = 8e-07 $/token, e 8e-07 * 10000 = 0.008 $. Se qui sotto
# scrivessi /1000, il test passerebbe col codice sbagliato.
sbagliati = []
arrotondati = []
for r, m in zip(risultati, modelli):
    if r["free"] or not r["costo"]:
        continue
    n = numero(r["costo"])
    atteso = m["prompt_price"] * 10000          # $/token * token = $
    # La tolleranza segue la precisione mostrata: sotto 0.01 si vedono
    # 4 decimali, quindi un arrotondamento a 4 cifre non e' un errore.
    # Verificare il numero arrotondato contro quello esatto con la
    # stessa precisione che si stampa e' la definizione di "uguale".
    cifre = 4 if atteso < 0.01 else 2
    arrotondato = float(f"{atteso:.{cifre}f}")
    if abs(n - arrotondato) > 1e-9:
        sbagliati.append((r["short"], r["costo"], round(atteso, 6)))
    elif abs(n - atteso) > max(1e-9, atteso * 0.02):
        arrotondati.append((r["short"], r["costo"], round(atteso, 6)))
check("il costo per 10k segue il prezzo", not sbagliati, str(sbagliati[:3]))
# Non un fallimento: e' un'informazione. Se la lista crescesse, vuol dire
# che la formattazione sta perdendo informazione che serve a decidere.
if arrotondati:
    print(f"   [nota] {len(arrotondati)} costi arrotondati per la visualizzazione, es. {arrotondati[:2]}")

# e la verifica di principio: nessun costo deve stamparsi come zero
# neanche quando e' piccolo ma non nullo
costi_zero = [r for r, m in zip(risultati, modelli)
              if not r["free"] and r["costo"] and m["prompt_price"] > 0
              and numero(r["costo"]) == 0]
check("nessun costo reale stampato come zero", not costi_zero,
      f"{len(costi_zero)} modelli; es. {costi_zero[:2]}")

print("\n[6] 'variabile' non e' un numero")
varia = [m for m in modelli if not m["free"] and m["prompt_price"] < 0]
if varia:
    etichette = [r["prezzo"] for r, m in zip(risultati, modelli)
                 if not m["free"] and m["prompt_price"] < 0]
    check("i prezzi variabili non mostrano un numero negativo",
          all(e == "prezzo variabile" for e in etichette), str(etichette[:3]))
else:
    check("nessun prezzo variabile in questo catalogo (caso non coperto)", True)

print("\n[7] I gratuiti non hanno un costo")
gratis = [r for r in risultati if r["free"]]
check("i gratuiti non hanno costo per richiesta",
      gratis and all(not r["costo"] for r in gratis), str(gratis[:2]))

os.unlink(tmp) if os.path.exists(tmp) else None

print("\n[8] Esempi reali")
for r in risultati[:3] + risultati[len(risultati) // 2:len(risultati) // 2 + 2]:
    print(f"    {r['short'][:26]:28} {r['prezzo']:22} {r['costo']}")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
