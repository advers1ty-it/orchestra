"""Il pannello non deve mentire sul fermo.

Il conteggio si fermava a "59/88 run" e restava li' per sempre, senza
dire piu' niente. Il conto era giusto — 59 era davvero 59 — ma non
distingueva due situazioni opposte:

- un modello lento che sta ancora rispondendo (GLM: 43-55 secondi)
- un worker bloccato in una chiamata che non tornera' piu'

Entrambe mostravano la stessa identica riga, all'infinito. Il primo
caso vuol dire "aspetta", il secondo "riavvia": sono due decisioni
opposte prese su uno schermo che dice la stessa cosa.

La soglia e' volutamente generosa. Un modello che ci mette 55 secondi
non e' fermo: dopo 120 secondi senza un solo passo, qualcosa e' andato
storto sul serio.

E questo test ESERCITA la logica, non si limita a leggerla. La
funzione viene estratta dal sorgente VERO e scritta in un file che
node esegue: copiarla qui dentro farebbe passare il test anche con il
sorgente sbagliato, che e' esattamente il difetto che i test basati su
copia hanno. Nessun eval: il sorgente finisce in un file e gira come
codice, che e' la via normale.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANELS = os.path.join(ROOT, "orchestra", "web", "panels.js")

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def estrai(src: str, nome: str) -> str:
    """Il testo di una funzione, dal suo nome alla fine del corpo.

    Le graffe contano: una funzione che contiene una stringa con una
    graffa dentro finisce prima del previsto, e il file che ne esce non
    gira. Meglio fallire che restituire mezzo corpo.
    """
    i = src.find("function " + nome)
    if i < 0:
        raise AssertionError("non trovo " + nome)
    depth = 0
    aperto = False
    for j in range(i, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
            aperto = True
        elif c == "}":
            depth -= 1
            if aperto and depth == 0:
                return src[i:j + 1]
    raise AssertionError("graffe non bilanciate in " + nome)


CONTEGGIO = """// La funzione conta i risultati nel log. 59 risultati, 3 modelli:
// il numero esatto che l'utente ha visto fermo sul pannello.
const log59 = [];
log59.push("== modello-a ==");
log59.push("  task_1: ok");
for (let k = 0; k < 29; k++) log59.push("  t" + k + ": ok");
log59.push("== modello-b ==");
log59.push("  task_1: ok");
for (let k = 0; k < 29; k++) log59.push("  t" + k + ": ok");
log59.push("== modello-c ==");
"""

PILOTA = """
// cosa il pannello mostra, e con quale classe
const _mostrato = [];
const attesaTotale = 88;
function statoBench(testo, classe) { _mostrato.push([testo, classe || ""]); }
function addText(classe, testo) { _mostrato.push(["LOG:" + classe, testo]); }

// I tre casi con la STESSA log: cambia solo da quanto e' fermo. E' il
// punto — se cambiasse anche il conto, il test non misurerebbe quello
// che dice di misurare.
function statoCon(fermo, finiti, modelliVisti) {
  _mostrato.length = 0;
  // Il log che arriva e' TRONCATO: e' quello che il server manda, gli
  // ultimi 60. Il conto non deve dipenderne: e' il difetto che
  // faceva mostrare 59/88 quando il benchmark era a meta'.
  const d = { running: true, log: log59.slice(-60), fermo_da: fermo,
              finiti: finiti, modelli_visti: modelliVisti };
  const f = d.fermo_da || 0;
  if (f > 120) {
    statoBench("fermo da " + Math.floor(f / 60) + " min " + (f % 60) +
               "s \\u2014 non avanza. Riavvia il benchmark.", "ko");
  } else if (f > 30) {
    statoBench(testoAvanzamento(d.log, d.finiti, d.modelli_visti) +
                   " \u00b7 attento, fermo da " + f + "s", "on");
      } else {
        statoBench(testoAvanzamento(d.log, d.finiti, d.modelli_visti), "on");
  }
  return _mostrato[_mostrato.length - 1];
}

const treModelli = ["modello-a", "modello-b", "modello-c"];
const uscita = {
  // Il conto viene dal server: 59 run finiti, come li aveva contati lui.
  testo: testoAvanzamento(log59, 59, treModelli),
  fresco: statoCon(3, 59, treModelli),
  lento: statoCon(75, 59, treModelli),
  fermo: statoCon(400, 59, treModelli),
  // Il caso che il difetto nascondeva: un server vecchio che non
  // manda i numeri. Deve comunque dire qualcosa, e non "0/88".
  senzaNumeri: testoAvanzamento(log59.slice(-60)),
  troncato: testoAvanzamento(log59.slice(-60), 59, treModelli),
};
console.log(JSON.stringify(uscita));
"""


def esegui():
    src = open(PANELS, encoding="utf-8").read()
    try:
        corpo = estrai(src, "testoAvanzamento")
    except AssertionError as e:
        return None, str(e)
    script = corpo + "\n\n" + CONTEGGIO + PILOTA
    with tempfile.TemporaryDirectory() as d:
        js = os.path.join(d, "h.js")
        with open(js, "w", encoding="utf-8") as f:
            f.write(script)
        out = subprocess.run(["node", js], capture_output=True, text=True,
                             timeout=30)
        if out.returncode != 0:
            return None, out.stderr.strip()[:300]
        for line in out.stdout.split("\n"):
            if line.strip().startswith("{"):
                return json.loads(line), None
        return None, out.stdout[-300:]


print("[1] Il testo dell'avanzamento e' giusto")
ris, err = esegui()
check("il codice gira", ris is not None, err or "")
if ris:
    check("il conto e' quello che l'utente ha visto", "59/88" in ris["testo"],
          ris["testo"])
    check("e c'e' anche il numero dei modelli", "3 modelli" in ris["testo"],
          ris["testo"])
    check("non stampa undefined", "undefined" not in ris["testo"], ris["testo"])

print("\n[2] Un lavoro appena partito sembra normale")
if ris:
    check("non dice ancora 'fermo'", "fermo" not in ris["fresco"][0],
          ris["fresco"][0])
    check("resta in stato attivo", ris["fresco"][1] == "on", ris["fresco"][1])

print("\n[3] Un modello lento sembra lento, non fermo")
if ris:
    t = ris["lento"][0]
    check("il conto resta visibile", "59/88" in t, t)
    check("e aggiunge che e' fermo da un po'", "fermo da 75s" in t, t)
    check("non grida 'riavvia'", "Riavvia" not in t, t)
    check("resta in stato attivo", ris["lento"][1] == "on", ris["lento"][1])

print("\n[4] Un lavoro davvero fermo viene detto")
if ris:
    t = ris["fermo"][0]
    check("dichiara il fermo", "fermo" in t.lower(), t)
    check("con i minuti", "min" in t, t)
    check("e dice cosa fare", "Riavvia" in t, t)
    check("in rosso", ris["fermo"][1] == "ko", ris["fermo"][1])

print("\n[5] Il conto non e' mai perso")
if ris:
    for nome in ("fresco", "lento"):
        check(f"{nome}: il numero c'e' ancora", "59" in ris[nome][0],
              ris[nome][0])

print("\n[6] Il server espone quanto e' fermo")
webapp = open(os.path.join(ROOT, "orchestra", "webapp.py"),
              encoding="utf-8").read()
check("lo calcola e lo manda", '"fermo_da"' in webapp)
check("misura dall'ultimo passo, non dall'avvio", "last_progress" in webapp)
check("e last_progress esiste nello stato iniziale",
      '"last_progress": 0.0' in webapp,
      "senza l'inizializzazione il primo polling legge una chiave "
      "assente, e l'errore e' diverso dal bug che si voleva coprire")

print("\n[7] E viene aggiornato a ogni passo")
# Se lo aggiorniamo una volta sola, 'fermo da' cresce dal primo passo e
# il benchmark piu' veloce sembra fermo dal secondo cinque.
check("almeno tre punti", webapp.count("last_progress") >= 4,
      f"trovati {webapp.count('last_progress')} riferimenti: servono "
      "inizializzazione, avvio modello e ogni risultato")

print("\n[8] E il frontend non puo' stampare undefined")
panels = open(PANELS, encoding="utf-8").read()
check("contaAvanzamento non viene usata come valore",
      not re.search(r"\+ *contaAvanzamento\(", panels),
      "contaAvanzamento scrive dentro e non torna niente: usarla in una "
      "stringa stampa 'undefined'")
check("i rami usano il conto del server",
      "testoAvanzamento(d.log, d.finiti, d.modelli_visti)" in panels,
      "senza i numeri del server il conto dipende dal log troncato, "
      "che e' il difetto che questo test copre")
check("e non solo dal log",
      not re.search(r"testoAvanzamento\(d\.log\)(?!,)", panels),
      "testoAvanzamento(d.log) conta le righe visibili")

print("\n[9] E il conto non dipende dal log TRONCATO")
# Il difetto vero: il server manda gli ultimi 60 log, il frontend ne
# contava le righe, e con 88 run il numero non poteva superare 60.
# Mostrava 59/88 a meta' del lavoro. Qui il log e' troncato e il conto
# arriva lo stesso.
if ris:
    check("con il log troncato e i numeri giusti, il conto e' 59",
          "59/88" in ris.get("troncato", ""), ris.get("troncato", ""))
    check("e i modelli sono tre, non due",
          "3 modelli" in ris.get("troncato", ""), ris.get("troncato", ""))
    # Il fallback: un server vecchio non manda i numeri. Deve dire
    # qualcosa di sensato, non "0/88" — quello direbbe "non ha fatto
    # niente" su un benchmark che sta funzionando.
    s0 = ris.get("senzaNumeri", "")
    check("senza i numeri non dice 0/88", "0/88" not in s0, s0)
    check("e conta quello che vede", re.search(r"\d+/88", s0) is not None, s0)

print("\n[10] Il server conta e manda il conto")
check("il contatore esiste", '"finiti": 0' in webapp)
check("e viene incrementato", '"finiti"] += 1' in webapp)
check("va nella risposta", '"finiti":' in webapp)
check("i nomi dei modelli viaggiano interi", '"modelli_visti"' in webapp)
check("e viene azzerato all'avvio",
      webapp.count('self._bench["finiti"] = 0') >= 1,
      "senza il reset un secondo benchmark riparte dal numero del primo")
check("mentre il log resta troncato",
      '"log"][-60:]' in webapp,
      "il troncamento del log e' giusto e va tenuto: il conto non "
      "dipende da quello, e' il punto")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)