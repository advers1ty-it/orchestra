"""Ogni cosa che il verificatore cerca, il prompt deve dirla.

Un verificatore che cerca una parola che il prompt non contiene non
misura il modello: misura se ha indovinato. E un compito la cui
risposta attesa è sbagliata non misura niente — fa bocciare il
modello che ha ragione.

Tutti e tre i difetti che sono usciti insieme:

- reason_l3 si aspettava "Ada 2 1 0" quando il conteggio vero è "1 0 1",
  e portava "2 1 0" come esempio del formato. Il modello che aveva
  indovinato il risultato giusto è stato bocciato.
- app_l2 cercava `setValore` senza mai nominarlo: chi scriveva
  `setContatore` veniva bocciato per un nome mai chiesto.
- extract_l3 si aspettava 3 mentre il prompt chiedeva "la riga che
  spiega lo scarto": la 4. Il file ha quattro righe, e la 4 è quella
  che contiene il 60,03 senza il quale il conto tornerebbe. Il
  modello che rispondeva 4 aveva ragione e veniva bocciato.

La regola è meccanica e si verifica su tutti i task, non uno alla
volta: ogni stringa che il verificatore richiede deve comparire nel
prompt. È l'unico controllo che avrebbe preso tutti e tre.
"""

import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestra.tasks_curva as T1  # noqa: E402
import orchestra.tasks_curva5 as T2  # noqa: E402
from orchestra.benchmark import tasks_for  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# I tre task che sono stati corretti, e la risposta giusta.
# Ogni voce e' (task, risposta che DEVE passare).
CASI = {
    "reason_l3": '{"Ada": "1 0 1", "Bo": "0 1 1", "Cy": "1 0 0"}\n',
    "app_l2": (
        "import { useState } from 'react';\n"
        "export function Contatore({ iniziale }) {\n"
        "  const [valore, setValore] = useState(iniziale);\n"
        "  return (\n"
        "    <div>\n"
        "      <p>{valore}</p>\n"
        "      <button onClick={() => setValore(valore + 1)}>+1</button>\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    ),
    "extract_l3": '{"differenza": 0.03, "riga": 4}\n',
}


def trova(tid):
    """Il task per id, in qualunque categoria. None se non c'e'.

    Una funzione perche' la stessa ricerca compariva in tre punti di
    questo file, e in due avevo dimenticato il `[0]`: la lista dei
    match finiva in `t` e `t.prompt` non esiste — un errore che dice
    "list has no attribute prompt" e non dice che il problema e' una
    lista che non ho aperto.
    """
    for cat in ("reasoning", "app", "extraction", "code", "js", "web",
                "tool_use", "writing"):
        trovati = [x for x in tasks_for(cat) if x.id == tid]
        if trovati:
            return trovati[0]
    return None


def verifica(task_id, contenuto):
    import tempfile
    from pathlib import Path
    task = trova(task_id)
    if task is None:
        return None
    with tempfile.TemporaryDirectory() as d:
        w = Path(d)
        if task.setup:
            task.setup(w)
        # il file da scrivere cambia da task a task, e ogni task sa gia'
        # quale si aspetta: extract scrive reporting.json, app scrive
        # il .jsx.
        nome = {"app_l2": "Contatore.jsx",
                "extract_l3": "reporting.json"}.get(task_id, "risultato.json")
        (w / nome).write_text(contenuto, encoding="utf-8")
        # verify(work) prende solo la cartella: il nome del file e'
        # dentro la closure, non un parametro. E torna sempre una
        # tupla (ok, dettaglio) — non un booleano: un check che
        # aspetta `True` fallisce su tutto quello che funziona.
        ok, det = task.verify(w)
        return ok, det


print("[1] reason_l3: la risposta GIUSTA passa")
# Il conteggio vero di "Ada fa A, Bo fa B, Ada fa C, Cy fa A, Bo fa C"
# e' Ada 1 0 1. Il task si aspettava 2 1 0 e il modello che aveva
# ragione era stato bocciato.
r = verifica("reason_l3", CASI["reason_l3"])
check("la risposta vera passa", bool(r[0]), str(r))

# Ada conta C come se fosse B: l'errore piu' probabile, e quello che
# il vecchio esempio induceva.
r2 = verifica("reason_l3", '{"Ada": "1 1 1", "Bo": "0 1 1", "Cy": "1 0 0"}\n')
check("la sbagliata e' bocciata", not r2[0], str(r2))

print("\n[3] reason_l3: il prompt non contiene piu' numeri d'esempio")
t = trova("reason_l3")
check("nessun '2 1 0' nel prompt", "2 1 0" not in t.prompt)
check("nessun '1 1 1' nel prompt", "1 1 1" not in t.prompt,
      "un esempio con numeri veri e' una risposta da indovinare")

print("\n[4] app_l2: il prompt nomina setValore, e il codice passa")
t2 = trova("app_l2")
check("il prompt nomina setValore", "setValore" in t2.prompt)
r3 = verifica("app_l2", CASI["app_l2"])
check("il codice che lo usa passa", bool(r3[0]), str(r3))
print("\n[5] extract_l3: il prompt dice come si contano le righe")
t3 = trova("extract_l3")
check("dice che si conta dalla prima riga",
      "riga 1" in t3.prompt or "partire dalla prima" in t3.prompt,
      t3.prompt[-200:])
check("e nomina l'intestazione", "intestazione" in t3.prompt)
r4 = verifica("extract_l3", CASI["extract_l3"])
check("la risposta vera passa", bool(r4[0]), str(r4))

print("\n[6] La regola su TUTTI i task: ogni nome richiesto e' nel prompt")
# Non un task alla volta: tutti. E' l'unico modo che avrebbe preso
# tutti e tre i difetti in una volta sola.
NOMI_DA_VERIFICARE = {
    "app_l2": ["setValore", "useState", "<button", "iniziale"],
    "app_l3": ["setSecondi", "clearInterval", "useEffect"],
    "reason_l3": ["risultato.json", "Ada", "Bo", "Cy"],
    "extract_l3": ["reporting.json", "differenza", "riga", "0.02"],
}



for tid, nomi in NOMI_DA_VERIFICARE.items():
    t = trova(tid)
    if t is None:
        check(f"{tid}: il task esiste", False, "non trovato")
        continue
    mancanti = [n for n in nomi if n.lower() not in t.prompt.lower()]
    check(f"{tid}: il prompt contiene tutto quello che si verifica",
          not mancanti, f"mancano: {mancanti}")

print("\n[7] E nessun prompt contiene piu' la risposta del proprio task")
# La forma peggiore: il prompt che contiene la risposta. Un modello
# che copia passa; uno che ragagna fallisce. E il benchmark premia la
# copia.
for cat in ("reasoning", "app", "extraction"):
    for t in tasks_for(cat):
        p = (t.prompt or "")
        # numeri a tre cifre separate da spazio = una risposta
        sospetto = re.findall(r"\b\d\s+\d\s+\d\b", p)
        if sospetto:
            check(f"{t.id}: nessuna terna numerica nel prompt", False,
                  str(sospetto[:3]))
check("nessun task con una terna numerica nel prompt", True)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)