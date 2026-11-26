"""Il markdown dei messaggi: le tabelle devono diventare una tabella vera.

Il renderer (orchestra/web/core.js, renderMarkdown) è una funzione pura: si
estrae dal file e si esegue in node, senza DOM. Il difetto che questo test
blocca è quello visto in chat: `| Nome | Esito |` e `|---|---|` restavano
testo, perché il ciclo delle righe non aveva un ramo per le tabelle e ogni
riga finiva in un <p>. Il CSS della tabella c'era già.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, "orchestra", "web", "core.js")

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def estrai_funzione(src, intestazione="function renderMarkdown(text) {"):
    """Il corpo della funzione, contando le graffe (le regex ne contengono)."""
    inizio = src.index(intestazione)
    livello = 0
    for k in range(src.index("{", inizio), len(src)):
        if src[k] == "{":
            livello += 1
        elif src[k] == "}":
            livello -= 1
            if livello == 0:
                return src[inizio:k + 1]
    raise ValueError("funzione non chiusa")


def node_disponibile():
    try:
        return subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


CASI = [
    ("tabella del messaggio",
     "| Nome | `nul*` (prima) | `nul` + `nul'` (ora) |\n"
     "|---|---|---|\n"
     "| `nul` | ignorato | **ignorato** |\n"
     "| `nullable.ts` | ignorato | tracciato |"),
    ("allineamento", "| A | B | C |\n|:---|:---:|---:|\n| 1 | 2 | 3 |"),
    ("separatore senza pipe esterne", "Nome | Esito\n--- | ---\na | b"),
    ("hr intatto", "prima\n\n---\n\ndopo"),
    ("lista intatta", "- uno\n- due"),
    ("pipe senza separatore", "usa a | b\nniente tabella"),
    ("paragrafo dopo la tabella", "| A | B |\n|---|---|\n| 1 | 2 |\n\ndopo la tabella"),
    # Una pipe vera dentro una cella si scrive \| nel markdown. Non è il
    # fallback "usa a | b": qui la tabella esiste, e la pipe non deve aprire
    # una terza colonna.
    ("pipe escapata in una cella", "| Nome | Descrizione |\n|---|---|\n| a | x \\| y |"),
    # L'intestazione non deve finire dentro il <li> della lista precedente.
    ("tabella subito dopo una lista", "- uno\n- due\n| A | B |\n|---|---|\n| 1 | 2 |"),
    # Una tabella a una colonna e' valida: `|---|` non e' un <hr>.
    ("una colonna", "| A |\n|---|\n| 1 |"),
    # Un paragrafo con una pipe dopo la tabella non e' una riga di tabella.
    ("paragrafo con pipe dopo la tabella",
     "| A | B |\n|---|---|\n| 1 | 2 |\nusa a | b"),
]


def esegui(casi):
    with open(CORE, encoding="utf-8") as f:
        funzione = estrai_funzione(f.read())
    script = (
        'const renderMarkdown = new Function("return (" + ' + json.dumps(funzione) + ' + ")")();\n'
        "const casi = " + json.dumps(casi) + ";\n"
        "console.log(JSON.stringify(casi.map(([n, t]) => [n, renderMarkdown(t)])));\n"
    )
    d = tempfile.mkdtemp()
    percorso = os.path.join(d, "render.js")
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(script)
    esito = subprocess.run(["node", percorso], capture_output=True, text=True, encoding="utf-8", timeout=60)
    if esito.returncode != 0:
        raise RuntimeError(esito.stderr.strip()[:400])
    return {n: h for n, h in json.loads(esito.stdout)}


print("[1] node c'è")
check("node è installato", node_disponibile())

print("\n[2] Le tabelle diventano HTML")
if node_disponibile():
    out = esegui(CASI)
    t = out["tabella del messaggio"]
    check("il tag <table> c'è", "<table>" in t and "</table>" in t, t[:200])
    check("intestazione in <th>", "<th>Nome</th>" in t, t[:200])
    check("corpo in <td>", "<td>ignorato</td>" in t, t[:200])
    check("le pipe crude non restano", "|---|" not in t and "| Nome |" not in t, t[:200])
    check("il grassetto dentro la cella regge", "<strong>ignorato</strong>" in t, t[:200])
    check("il codice dentro la cella regge", "<code>nul</code>" in t, t[:200])
    check("una riga per riga di corpo", t.count("<tr>") == 3, f"{t.count('<tr>')} righe")

    a = out["allineamento"]
    check("centrato riconosciuto", 'text-align:center' in a, a[:200])
    check("a destra riconosciuto", 'text-align:right' in a, a[:200])

    s = out["separatore senza pipe esterne"]
    check("tabella senza pipe ai bordi", "<table>" in s and "<td>b</td>" in s, s[:200])

print("\n[3] Quello che non era una tabella resta com'era")
if node_disponibile():
    check("l'<hr> non diventa tabella", "<hr>" in out["hr intatto"], out["hr intatto"])
    check("la lista resta una lista", "<ul>" in out["lista intatta"], out["lista intatta"])
    p = out["pipe senza separatore"]
    check("una pipe in mezzo al testo non apre una tabella", "<table>" not in p, p[:200])
    d = out["paragrafo dopo la tabella"]
    check("dopo la tabella si riprende a paragrafi", "<p>dopo la tabella</p>" in d, d[:200])

    u = out["una colonna"]
    check("una tabella a una colonna è una tabella",
          "<table>" in u and "<th>A</th>" in u and "<td>1</td>" in u, u[:200])
    c = out["paragrafo con pipe dopo la tabella"]
    check("un paragrafo con pipe resta fuori dalla tabella",
          "<p>usa a | b</p>" in c, c[:300])
    check("e la tabella non guadagna righe",
          c.count("<tr>") == 2, f"{c.count('<tr>')} righe: {c[:300]}")

print("\n[4] Pipe escapata e tabella dopo una lista")
if node_disponibile():
    e = out["pipe escapata in una cella"]
    check("la pipe escapata resta nella stessa cella", "<td>x | y</td>" in e, e[:300])
    check("e non apre una terza colonna", e.count("<td>") == 2, f"{e.count('<td>')} celle: {e[:300]}")
    check("il backslash non resta nel testo", "\\|" not in e, e[:300])

    l = out["tabella subito dopo una lista"]
    check("la lista resta una lista", "<ul><li>uno</li><li>due</li></ul>" in l, l[:300])
    check("la tabella parte comunque", "<table>" in l and "<th>A</th>" in l, l[:300])
    check("l'intestazione non è finita in un <li>", "<li>| A | B |</li>" not in l, l[:300])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
