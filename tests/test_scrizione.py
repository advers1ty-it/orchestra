"""I verificatori devono RESPINGERE, non solo accettare.

Il test piu' importante di tutti. Un verificatore che passa sempre e'
peggio di nessun verificatore: non solo non serve, e' peggio perche'
produce un punteggio alto che non significa niente, e tu lo usi per
scegliere il modello.

Ogni verificatore viene provato con la risposta GIUSTA (deve passare) e
con almeno una sbagliata (deve fallire). Le risposte sbagliate sono
quelle che i modelli fanno davvero: il numero inventato, la data nel
formato italiano, il campo che manca, il file che non e' JSON.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.benchmark import tasks_for  # noqa: E402
from orchestra.tasks_scrizione import (  # noqa: E402
    BOZZA, CLIENTI, LISTINO, TASK_EXTRACTION, TASK_WRITING,
)

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    if cond:
        print(f"  OK   {nome}")
    else:
        # Il dettaglio si stampa solo quando qualcosa e' andato storto:
        # un "OK" con il perche' accanto e' rumore che costringe a
        # leggere due righe per ogni riga verde.
        print(f"  FAIL {nome} — {dettaglio}")


def cartella() -> str:
    return tempfile.mkdtemp(prefix="ver-")


def scrive(work: str, nome: str, testo: str) -> None:
    with open(os.path.join(work, nome), "w", encoding="utf-8") as f:
        f.write(testo)


GIUSTO = {
    "preventivi.json": json.dumps({
        "cliente": "Rossi S.r.l.", "codice": "R-1043",
        "preventivo": "2026/1847", "data": "2026-06-14", "totale": 5200,
    }, indent=2),
    "clienti.json": json.dumps([
        {"id": 1, "nome": "Ferrari", "importo": 1200},
        {"id": 2, "nome": "Bianchi", "importo": 800},
        {"id": 3, "nome": "Romano", "importo": 650},
        {"id": 4, "nome": "Gallo", "importo": 300},
        {"id": 5, "nome": "Neri", "importo": 200},
    ], indent=2),
    "scheda.md": "# Scheda\n\n## Luogo\nReggio Emilia\n\n## Data\n3 settembre 1947\n\n"
                 "## Rilevatore\nAria Dossena\n\n## Circostanze\nassente\n\n"
                 "## Ipotesi\nnon registrato\n\n## Conclusione\naperto\n",
    "scheda-finale.md": BOZZA.replace("via Mazzini 8", "via Emilia 12")
                          .replace("1042", "1142").replace("dal 1945", "dal 1946"),
    "allarme.txt": "Serrande giù, impianto in demolizione: non entrare "
                   "e non toccare nulla. Chiude il cantiere domani.",
}

# Le risposte sbagliate che i modelli fanno davvero. Non inventate a
# caso: sono i tre errori ricorrenti — il numero plausible ma falso,
# il formato italiano, e il wrapper di prosa che spacca il JSON.
SBAGLIATE = {
    "extract_campi": [
        ("totale inventato",
         '{"cliente":"Rossi S.r.l.","codice":"R-1043","preventivo":"2026/1847",'
         '"data":"2026-06-14","totale":5000}'),
        ("data in formato italiano",
         '{"cliente":"Rossi S.r.l.","codice":"R-1043","preventivo":"2026/1847",'
         '"data":"14/06/2026","totale":5200}'),
        ("campo che manca",
         '{"cliente":"Rossi S.r.l.","codice":"R-1043","totale":5200}'),
        ("non e' JSON",
         "Ecco il preventivo:\ncliente: Rossi\ntotale: 5200"),
        ("JSON avvolto in prosa",
         "Ho estratto i dati:\n" + chr(96) * 3 + "json\n"
         + GIUSTO["preventivi.json"] + "\n" + chr(96) * 3),
    ],
    "extract_tabella": [
        ("somma sbagliata (una riga inventata)",
         '[{"id":1,"nome":"Ferrari","importo":1200},{"id":2,"nome":"Bianchi","importo":800},'
         '{"id":3,"nome":"Romano","importo":650},{"id":4,"nome":"Gallo","importo":900},'
         '{"id":5,"nome":"Neri","importo":200}]'),
        ("virgola decimale invece del punto",
         '[{"id":1,"nome":"Ferrari","importo":"1200,00"},{"id":2,"nome":"Bianchi","importo":800},'
         '{"id":3,"nome":"Romano","importo":650},{"id":4,"nome":"Gallo","importo":300},'
         '{"id":5,"nome":"Neri","importo":200}]'),
    ],
    "write_struttura": [
        ("sezioni mancanti",
         "# Scheda\n\n## Luogo\nReggio Emilia\n\n## Data\n1947\n"),
        ("sezioni fuori ordine",
         "# Scheda\n\n## Data\n1947\n\n## Luogo\nReggio\n\n"
         "## Rilevatore\nDossena\n\n## Circostanze\nassente\n\n"
         "## Ipotesi\nnon noto\n\n## Conclusione\naperto\n"),
    ],
    "write_dati_giusti": [
        ("solo la prima occorrenza corretta",
         BOZZA.replace("via Mazzini 8", "via Emilia 12")),
        ("tutti i dati lasciati come erano", BOZZA),
    ],
    "write_senza_filler": [
        ("troppo lungo", "Serrande giù. " * 40),
        ("riempitivo", "Ecco qui l'avviso:\nSerrande giù, non entrare."),
    ],
}

print("[1] Ogni task ha una risposta giusta che passa")
# Ogni task scrive UN file, e si sa quale: la mappa evita una
# cascata di if che continua a crescere ogni volta che aggiungi un
# task, ed e' il posto dove si sbaglia: un `if` dimenticato scrive
# il file sbagliato e il test verifica un'altra cosa.
FILE_DEL_TASK = {
    "extract_campi": "preventivi.json",
    "extract_tabella": "clienti.json",
    "write_struttura": "scheda.md",
    "write_dati_giusti": "scheda-finale.md",
    "write_senza_filler": "allarme.txt",
}

for task in TASK_EXTRACTION + TASK_WRITING:
    work = cartella()
    if task.setup:
        task.setup(work)
    nome_file = FILE_DEL_TASK[task.id]
    scrive(work, nome_file, GIUSTO[nome_file])
    ok, dettaglio = task.verify(work)
    check(f"{task.id}: la risposta giusta passa", ok, dettaglio)
    shutil.rmtree(work, ignore_errors=True)

print("\n[2] Ogni risposta sbagliata viene respinta")
# Il punto dell'intero file. Se un verificatore accetta una risposta
# sbagliata, il punteggio che produce non distingue niente.
respinte = 0
accettate = []
for task in TASK_EXTRACTION + TASK_WRITING:
    for etichetta, testo in SBAGLIATE.get(task.id, []):
        work = cartella()
        if task.setup:
            task.setup(work)
        nome_file = {"extract_campi": "preventivi.json",
                     "extract_tabella": "clienti.json",
                     "write_struttura": "scheda.md",
                     "write_dati_giusti": "scheda-finale.md",
                     "write_senza_filler": "allarme.txt"}[task.id]
        scrive(work, nome_file, testo)
        ok, dettaglio = task.verify(work)
        if ok:
            accettate.append(f"{task.id}/{etichetta}")
        else:
            respinte += 1
        shutil.rmtree(work, ignore_errors=True)
check("nessuna risposta sbagliata passa", not accettate,
      "accettate: " + ", ".join(accettate))
print(f"   respinte {respinte} su {respinte + len(accettate)}")

print("\n[3] I file di partenza esistono e sono credibili")
# Un setup che scrive un file vuoto rende il task impossibile, e
# resterebbe "non misurabile" per sempre senza che nessuno lo dica.
work = cartella()
for task in TASK_EXTRACTION + TASK_WRITING:
    if not task.setup:
        continue
    w2 = cartella()
    task.setup(w2)
    file_ = os.listdir(w2)
    check(f"{task.id}: il setup crea i file", bool(file_), str(file_))
    for nome in file_:
        contenuto = open(os.path.join(w2, nome), encoding="utf-8").read()
        check(f"{task.id}/{nome}: non e' vuoto", len(contenuto) > 40,
              f"{len(contenuto)} caratteri")
    shutil.rmtree(w2, ignore_errors=True)
shutil.rmtree(work, ignore_errors=True)

print("\n[4] Il prompt contiene abbastanza informazione")
# Un prompt che non dice il formato richiesto fallisce sempre, e il
# modello sembra incapace quando il compito era ambiguo. Non e' un
# difetto del modello: e' del test, ed e' peggio perche' non si vede.
for task in TASK_EXTRACTION + TASK_WRITING:
    check(f"{task.id}: il prompt dice il formato",
          any(k in task.prompt.lower() for k in
              ("json", "##", "md", "txt")),
          task.prompt[:70])
    check(f"{task.id}: il prompt nomina il file",
          ".json" in task.prompt or ".md" in task.prompt or ".txt" in task.prompt,
          task.prompt[:70])

print("\n[5] Le categorie sono misurabili, e dichiarate")
tutte = tasks_for()
for cat in ("extraction", "writing"):
    n = len(tasks_for(cat))
    check(f"{cat} ha almeno 2 task", n >= 2, f"{n} task")
    check(f"{cat} non e' piu' vuota", n > 0)
check("il totale dei task e' cresciuto", len(tutte) >= 20, f"{len(tutte)} task")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
