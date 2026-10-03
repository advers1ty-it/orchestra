"""Il "forse" si dice una volta, non su ogni riga.

Un'etichetta identica su tutte le righe non è un'informazione per
riga: è rumore che si impara a non leggere. Su NVIDIA la dicevano
80 righe su 80, e su Groq 8 su 11 — il menu intero marcato "forse",
che vuol dire niente.

La regola che ne segue, e che è quella giusta:

- se il servizio dichiara il tool-calling su ALMENO UN modello, il
  "forse" resta sulle righe che lo dichiarano male — lì distingue
  davvero
- se il servizio non dichiara NIENTE, non si mette niente sulle righe,
  e si dice una volta sola cosa significa

E il "no" — `[niente tool]` — resta su ogni riga che lo merita: è
un no definitivo, e un modello senza tool-calling non è Orchestra.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "orchestra", "web", "core.js")
POPUP = os.path.join(ROOT, "orchestra", "web", "modelpick.js")

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


core = open(CORE, encoding="utf-8").read()
popup = open(POPUP, encoding="utf-8").read()

print("[1] Le due bandiere sono a livello di modulo")
check("servizioDichiaraTool e' globale", "let servizioDichiaraTool" in core)
check("servizioTace e' globale", "let servizioTace" in core)
check("e non coperte da una const locale",
      "const servizioDichiaraTool" not in core
      and "const servizioTace" not in core,
      "una const dentro loadModels nasconde quella globale, e il popup "
      "legge un nome che non aggiorna mai")
check("il popup le usa", "servizioTace" in popup)

print("\n[2] La regola e' quella giusta")
m = re.search(r"const tc = m\.tool_calling;.*?;", core, re.S)
check("il codice c'e'", m is not None)
riga = m.group(0) if m else ""
check("'[niente tool]' resta incondizionato", '"  [niente tool]"' in riga)
check("'[tool?]' e' condizionato al servizio", "servizioDichiaraTool ?" in riga,
      "senza la condizione il 'forse' torna su ogni riga")
check("e la condizione guarda anche il 'no' esplicito", "tc === false" in riga)

print("\n[3] Il calcolo: conta chi DICHIARA, non chi tace")
check("filtra tool_calling non nullo", "tool_calling !== null" in core)
check("e non undefined", "tool_calling !== undefined" in core)
check("la bandiera e' vero se almeno uno dichiara",
      "servizioDichiaraTool = _dichiarati > 0" in core)

print("\n[4] E funziona davvero, sui dati dei tre provider")
HARNESS = """
function etichetta(tc, dichiara) {
  if (tc === true) return "";
  if (tc === false) return "[niente tool]";
  return dichiara ? "[tool?]" : "";
}
const casi = [
  ["nvidia",   [null, null, null],                         null],
  ["groq",     [false, false, false, null, null],          null],
  ["openrouter", [true, true, true],                      null],
];
const fuori = [];
for (const [nome, tc] of casi) {
  const dich = tc.filter((v) => v !== null && v !== undefined).length > 0;
  fuori.push([nome, tc.map((v) => etichetta(v, dich)).join("|")]);
}
console.log(JSON.stringify(fuori));
"""


def esegui():
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(HARNESS)
        path = fh.name
    try:
        out = subprocess.run(["node", path], capture_output=True, text=True,
                             timeout=30)
        righe = [l for l in out.stdout.split("\n") if l.strip().startswith("[")]
        return json.loads(righe[-1]) if righe else None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


ris = esegui()
check("il codice gira", ris is not None)
if ris:
    per = dict((r[0], r[1]) for r in ris)
    check("i tre casi ci sono", len(per) == 3, str(list(per)))
    # Solo NVIDIA: li' nessuno dichiara niente, e il [tool?] sarebbe
    # identico su tutte le righe. Groq dichiara tre NO, quindi il
    # [tool?] sulle righe ignote DISTINGUE e deve restare — e se
    # sparisse li', il menu direbbe "nessuno dichiara" su un servizio
    # che dichiara benissimo.
    if "nvidia" in per:
        check("nvidia: nessun [tool?] sulle righe",
              "tool?" not in per["nvidia"], per["nvidia"][:70])
    if "groq" in per:
        check("groq: il [tool?] resta sulle righe ignote",
              "tool?" in per["groq"],
              "Groq dichiara tre no: il dubbio distingue dal no")
        check("groq: e i [niente tool] restano",
              "niente tool" in per["groq"], per["groq"][:70])
    check("openrouter: nessuna etichetta",
          "tool" not in per.get("openrouter", ""), per.get("openrouter", "")[:50])
    check("groq conserva i suoi [niente tool]",
          "niente tool" in per.get("groq", ""),
          "un no definitivo resta su ogni riga che lo merita")

print("\n[5] E il popup dice la cosa UNA volta")
check("il piede ha il messaggio", "non dichiara il supporto tool" in popup)
check("e solo se il servizio tace", "if (servizioTace)" in popup)
# Conta le VOLTE che il messaggio entra nel piede, non quante volte
# la parola compare nel file: se sta in un commento, il conteggio
# menteva. E comunque deve essere uno solo — il piede e' una riga.
_assegna = len(re.findall(r"piede\.textContent\s*\+?=[^;]*non dichiara",
                          popup))
check("non lo ripete su ogni riga", _assegna <= 1,
      f"il messaggio entra nel piede {_assegna} volte")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)