"""Ogni task della curva cinque deve avere una risposta giusta e una sbagliata.

È la prova che ha trovato i quattro difetti sui primi dieci task: due
verificatori che accettavano qualunque cosa, due soluzioni "sbagliate"
che erano giuste, e un quesito con la risposta scritta due righe sopra
la domanda. Qui si eseguono quindici task due volte.

Le soluzioni sbagliate sono scritte a mano e il motivo è commentato:
una soluzione sbagliata generata da uno script sbaglierebbe insieme
alla verifica, e il test passerebbe senza dire niente.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.tasks_curva5 import TASK_CURVA  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


GIUSTE = {
    "js_l1": {"media.js":
              "function media(xs) { return xs.reduce((a, b) => a + b, 0) / xs.length; }\n"},
    # il caso limite: lista vuota e solo null, entrambe null e non 0
    "js_l2": {"media.js":
              "function media(xs) {\n"
              "  const n = xs.filter(x => x !== null && x !== undefined);\n"
              "  if (n.length === 0) return null;\n"
              "  return n.reduce((a, b) => a + b, 0) / n.length;\n}\n"},
    "js_l3": {"ordina.js":
              "function ordina(xs) {\n"
              "  const n = xs.filter(x => x !== null && x !== undefined);\n"
              "  n.sort((a, b) => a - b);\n"
              "  return n.concat(xs.filter(x => x === null || x === undefined));\n}\n"},
    "web_l1": {"pagina.html":
               "<!DOCTYPE html>\n<html>\n<head>\n<title>Benvenuto</title>\n"
               "</head>\n<body>\n<h1>Ciao</h1>\n</body>\n</html>\n"},
    "web_l2": {"link.html":
               "<p>Vedi il <a href=\"manuale.html\">docs</a>.</p>\n"},
    "web_l3": {"elenco.html":
               "<ul>\n<li>1</li>\n<li>2</li>\n<li>3</li>\n</ul>\n"},
    "app_l1": {"Contatore.jsx":
               "import React from 'react';\n"
               "export default function Contatore({ iniziale }) {\n"
               "  return <span>{iniziale}</span>;\n}\n"},
    "app_l2": {"Contatore.jsx":
               "import React, { useState } from 'react';\n"
               "export default function Contatore({ iniziale }) {\n"
               "  const [valore, setValore] = useState(iniziale);\n"
               "  return (<div><span>{valore}</span>"
               "<button onClick={() => setValore(valore + 1)}>+</button></div>);\n}\n"},
    "app_l3": {"Timer.jsx":
               "import React, { useState, useEffect } from 'react';\n"
               "export default function Timer() {\n"
               "  const [secondi, setSecondi] = useState(0);\n"
               "  useEffect(() => {\n"
               "    const t = setInterval(() => setSecondi(s => s + 1), 1000);\n"
               "    return () => clearInterval(t);\n"
               "  }, []);\n"
               "  return <span>{secondi}</span>;\n}\n"},
    "instr_l1": {"tre.txt": "uno\ndue\ntre\n"},
    "instr_l2": {"tre.txt": "prima riga\nseconda riga\nterza riga.\n"},
    "instr_l3": {"scelta.txt": "casa tre\n"},
    "reason_l1": {"risposta.txt": "5\n"},
    "write_l3": {"bozza.txt": "primo punto che arriva\nsecondo punto da mettere\n"
                             "terzo punto in chiusura\n",
                 "due.txt": "- primo punto che arriva\n- secondo punto da mettere\n"
                            "- terzo punto in chiusura\n"},
}

SBAGLIATE = {
    "js_l1": {"media.js": "function media(xs) { return 0; }\n"},
    # NaN invece di null: la divisione senza controllo
    "js_l2": {"media.js":
              "function media(xs) {\n"
              "  const n = xs.filter(x => x !== null);\n"
              "  return n.reduce((a, b) => a + b, 0) / n.length;\n}\n"},
    # i null davanti: l'errore che si fa col sort senza pensarci
    "js_l3": {"ordina.js":
              "function ordina(xs) { return xs.slice().sort((a, b) => (a > b ? 1 : -1)); }\n"},
    "web_l1": {"pagina.html":
               "<html><body><h1>Ciao</h1></body></html>\n"},
    # l'& codificato dentro l'attributo, che è il contrario di giusto
    "web_l2": {"link.html":
               "<p><a href=\"manuale&amp;html\">docs</a></p>\n"},
    # il terzo <li> fuori dall'elenco: conta tre, ma solo due sono dentro
    "web_l3": {"elenco.html": "<ul>\n<li>1</li>\n<li>2</li>\n</ul>\n<li>3</li>\n"},
    # non mostra la prop: il compito chiede un numero, e questo non ne
    # mostra nessuno. La verifica di questo task e' strutturale — React
    # non si esegue qui — quindi la sbagliata deve essere strutturalmente
    # sbagliata, non semantica
    "app_l1": {"Contatore.jsx":
               "import React from 'react';\n"
               "export default function Contatore({ iniziale }) {\n"
               "  return <div>contatore</div>;\n}\n"},
    # il pulsante c'è ma niente stato
    "app_l2": {"Contatore.jsx":
               "import React from 'react';\n"
               "export default function Contatore({ iniziale }) {\n"
               "  return (<div><span>{iniziale}</span>"
               "<button>+</button></div>);\n}\n"},
    # l'effetto che non si ferma
    "app_l3": {"Timer.jsx":
               "import React, { useState, useEffect } from 'react';\n"
               "export default function Timer() {\n"
               "  const [secondi, setSecondi] = useState(0);\n"
               "  useEffect(() => {\n"
               "    setInterval(() => setSecondi(s => s + 1), 1000);\n"
               "  }, []);\n"
               "  return <span>{secondi}</span>;\n}\n"},
    # quattro righe invece di tre
    "instr_l1": {"tre.txt": "uno\ndue\ntre\nquattro\n"},
    # l'ultima riga senza il punto fermo
    "instr_l2": {"tre.txt": "prima riga\nseconda riga\nterza riga\n"},
    # la parola esentata manca
    "instr_l3": {"scelta.txt": "casa bella\n"},
    "reason_l1": {"risposta.txt": "3\n"},
    # riassunto invece che riportato: un file ben scritto, non quello chiesto
    "write_l3": {"bozza.txt": "primo punto che arriva\nsecondo punto da mettere\n"
                             "terzo punto in chiusura\n",
                 "due.txt": "- primo\n- secondo\n- terzo\n"},
}


def scenario(task, file: dict) -> tuple[bool, str]:
    d = tempfile.mkdtemp()
    if task.setup:
        task.setup(d)
    for nome, contenuto in file.items():
        p = os.path.join(d, nome)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(contenuto)
    return task.verify(d)


print(f"[1] La curva cinque: {len(TASK_CURVA)} task")
ids = [t.id for t in TASK_CURVA]
check("gli id sono unici", len(set(ids)) == len(ids), str(ids))
check("ognuno ha il livello nell'id",
      all(t.id.rsplit("_", 1)[-1] in ("l1", "l2", "l3") for t in TASK_CURVA),
      str([t.id for t in TASK_CURVA if t.id.rsplit("_", 1)[-1] not in ("l1", "l2", "l3")]))
cat = {}
for t in TASK_CURVA:
    cat.setdefault(t.category, []).append(t.id)
for c, ts in sorted(cat.items()):
    liv = ", ".join(x.rsplit("_", 1)[-1] for x in ts)
    print(f"   {c:12} {len(ts)} task  ({liv})")

print("\n[2] Ogni task ha una soluzione giusta, e passa")
for t in TASK_CURVA:
    g = GIUSTE.get(t.id)
    if g is None:
        check(f"{t.id}: soluzione giusta presente", False, "manca nel test")
        continue
    ok, det = scenario(t, g)
    check(f"{t.id}: la giusta passa", ok, det)

print("\n[3] Ogni task ha una soluzione sbagliata, e viene bocciata")
for t in TASK_CURVA:
    k = SBAGLIATE.get(t.id)
    if k is None:
        check(f"{t.id}: soluzione sbagliata presente", False, "manca nel test")
        continue
    ok, det = scenario(t, k)
    check(f"{t.id}: la sbagliata fallisce", not ok,
          f"PASSATA — il task non misura niente ({det[:70]})")

print("\n[4] Le soluzioni non coincidono")
for tid in SBAGLIATE:
    if tid not in GIUSTE:
        continue
    # i file che scrive il setup sono gli stessi per costruzione e non
    # sono la risposta del modello: confrontarli diceva che le due
    # soluzioni erano uguali quando non lo sono
    setup_files = set()
    t = next((x for x in TASK_CURVA if x.id == tid), None)
    if t and t.setup:
        d = tempfile.mkdtemp()
        t.setup(d)
        setup_files = set(os.listdir(d))
    identiche = [n for n in set(SBAGLIATE[tid]) & set(GIUSTE[tid])
                 if SBAGLIATE[tid][n] == GIUSTE[tid][n] and n not in setup_files]
    check(f"{tid}: giusta e sbagliata diverse", not identiche, str(identiche))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)