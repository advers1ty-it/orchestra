"""Le domande dell'agente all'utente: canale, attesa, risposta.

Il difetto che questi controlli prevengono: un agente che si ferma ad
aspettare una risposta che nessuno puo' dare. Senza canale deve dirlo
subito, non bloccare il turno per cinque minuti.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import pathlib

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)
os.environ.setdefault("ORCHESTRA_HOME", tempfile.mkdtemp(prefix="orchestra_domande_"))

from orchestra import domande  # noqa: E402
from orchestra.tools.ask_user import NESSUN_CANALE, tool_ask_user  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def reset() -> None:
    domande.imposta_canale(None)
    for d in domande.in_attesa():
        domande.annulla(d["id"])


print("\n[1] Senza canale il tool lo dice e non aspetta")
reset()
inizio = time.monotonic()
esito = tool_ask_user().handler(domanda="Come si chiama il campo?")
durata = time.monotonic() - inizio
check("il tool non aspetta", durata < 1.0, f"{durata:.2f}s")
check("e lo dice chiaramente", esito == NESSUN_CANALE, esito)


print("\n[2] Con un canale la domanda arriva e la risposta torna al tool")
ricevute: list[dict] = []
domande.imposta_canale(ricevute.append)


def rispondi_dopo(domanda_id: str, testo: str) -> None:
    time.sleep(0.2)
    domande.rispondi(domanda_id, testo)


def avvia_risposta() -> None:
    # l'id lo scopriamo dall'evento emesso, come farebbe la UI
    fine = time.monotonic() + 2
    while not ricevute and time.monotonic() < fine:
        time.sleep(0.02)
    if ricevute:
        threading.Thread(target=rispondi_dopo,
                         args=(ricevute[0]["id"], "si chiama nome"),
                         daemon=True).start()


threading.Thread(target=avvia_risposta, daemon=True).start()
esito = tool_ask_user().handler(
    domanda="  Il campo   si chiama   nome o name? ",
    opzioni=["nome", "name", "  "])
check("la domanda e' stata emessa", len(ricevute) == 1, str(len(ricevute)))
check("il testo e' normalizzato",
      ricevute and ricevute[0]["testo"] == "Il campo si chiama nome o name?")
check("le opzioni vuote cadono", ricevute and ricevute[0]["opzioni"] == ["nome", "name"])
check("la risposta arriva al tool", "nome" in esito and "Risposta dell'utente" in esito,
      esito)
check("la domanda non resta in attesa", domande.in_attesa() == [])


print("\n[3] Una seconda risposta non sovrascrive la prima")
d = domande.crea("quale file?")
check("la domanda e' in attesa", len(domande.in_attesa()) == 1)
check("la prima risposta passa", domande.rispondi(d["id"], "a.txt"))
check("la seconda viene rifiutata", not domande.rispondi(d["id"], "b.txt"))
check("vince la prima", domande.attendi(d["id"], timeout=0.5) == "a.txt")


print("\n[4] La scadenza libera il turno")
d = domande.crea("ci sei?")
inizio = time.monotonic()
check("nessuna risposta = None", domande.attendi(d["id"], timeout=0.3) is None)
check("non ha aspettato troppo", time.monotonic() - inizio < 2)
check("la domanda scaduta sparisce", domande.in_attesa() == [])
check("rispondere dopo la scadenza non ha effetto",
      not domande.rispondi(d["id"], "tardi"))


print("\n[5] Limiti: domanda vuota, testo e opzioni")
try:
    domande.crea("   ")
    errore = ""
except ValueError as e:
    errore = str(e)
check("una domanda vuota e' un errore", "vuota" in errore, errore)
lunga = domande.crea("x" * 5000, [str(i) for i in range(20)])
check("il testo e' tagliato", len(lunga["testo"]) <= domande.MAX_TESTO + 1,
      str(len(lunga["testo"])))
check("le opzioni sono al massimo sei", len(lunga["opzioni"]) == domande.MAX_OPZIONI,
      str(len(lunga["opzioni"])))
domande.annulla(lunga["id"])
check("annullare toglie dall'attesa", domande.in_attesa() == [])


print("\n[6] Il filo e' collegato in tutti e tre i pezzi")
web = pathlib.Path(RADICE) / "orchestra" / "web"
tool_src = (pathlib.Path(RADICE) / "orchestra" / "tools" / "__init__.py").read_text(encoding="utf-8")
webapp_src = (pathlib.Path(RADICE) / "orchestra" / "webapp.py").read_text(encoding="utf-8")
core_src = (web / "core.js").read_text(encoding="utf-8")
html_src = (web / "index.html").read_text(encoding="utf-8")
check("il tool e' nel registro", "tool_ask_user()" in tool_src)
check("il tool e' in ogni profilo", "\"ask_user\"" in tool_src)
check("la rotta risposta esiste", '"/api/risposta"' in webapp_src)
check("la webapp emette l'evento", "domanda_utente" in webapp_src)
check("la UI ascolta l'evento", 'case "domanda_utente"' in core_src)
check("la UI ha il campo di risposta", 'id="domanda-input"' in html_src)
check("la UI ha il bottone", 'id="domanda-invia"' in html_src)

domande.imposta_canale(None)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
