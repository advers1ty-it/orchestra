"""La memoria non cancella per somiglianza.

Quattro difetti P0, uno per sezione:

1. `Memoria.elimina` confrontava con `fatto in corpo`: cancellare
   "gatto" portava via "Il gatto si chiama Fido" e ogni riga che
   nominava la parola — intestazioni comprese, perche' il ciclo
   guardava tutte le righe del file e non solo i fatti.

2. `elimina` e `modifica` non sapevano niente di progetti: lo stesso
   testo in due progetti si toccava in entrambi, e un agente che
   lavorava su un progetto poteva cancellare il fatto di un altro.

3. `modifica` riconosceva la coda della riga con una regex scritta a
   mano che non conosceva `[auto]`: modificare una regola promossa
   dall'euristica la faceva uscire dal prompt (l'origine tornava
   "mano"), e quando la coda non combaciava portava via anche il
   progetto e la data.

4. `IndiceMemoria.elimina` faceva `DELETE WHERE testo = ?` e poi
   aggiornava `_ultimo_file`: con un fatto lungo indicizzato a chunk la
   ricerca continuava a restituire un fatto che il file non aveva piu'.

Niente rete e niente memoria vera: ogni caso ha la sua cartella
temporanea e il suo indice.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# La cartella dati dei test, PRIMA di importare orchestra: `memoria()` e
# `indice_memoria()` sono singleton, e senza questo un test potrebbe
# scrivere nella memoria di chi lo lancia.
os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orch-test-elimina-")

from orchestra import memoria as memoria_mod            # noqa: E402
from orchestra import memoria_indice as indice_mod      # noqa: E402
from orchestra.tools import memoria as tool_mem         # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def nuova_memoria(contenuto: str | None = None) -> memoria_mod.Memoria:
    """Una memoria usa-e-getta, mai quella di chi lancia i test."""
    cartella = tempfile.mkdtemp(prefix="orch-del-")
    percorso = os.path.join(cartella, "memory.md")
    if contenuto is not None:
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(contenuto)
    return memoria_mod.Memoria(percorso=percorso)


def nuovo_indice(m: memoria_mod.Memoria) -> indice_mod.IndiceMemoria:
    """L'indice sopra quella memoria, nel suo DB temporaneo."""
    return indice_mod.IndiceMemoria(
        sorgente=m,
        percorso=os.path.join(os.path.dirname(m.percorso),
                              "memoria_indice.db"))


def contenuto(m: memoria_mod.Memoria) -> str:
    with open(m.percorso, encoding="utf-8") as f:
        return f.read()


def righe_fatto(m: memoria_mod.Memoria) -> list[str]:
    return [r for r in contenuto(m).splitlines() if r.startswith("- ")]


# ---------------------------------------------------------------------------
print("\n[1] Il confronto e' il fatto esatto, non una sottostringa")

m = nuova_memoria()
m.aggiungi("Il gatto si chiama Fido", origine="test")
m.aggiungi("Il cane si chiama Lord", origine="test")

check("eliminare una parola non e' eliminare un fatto",
      m.elimina("gatto") is False)
check("nessun fatto e' sparito",
      sorted(m.fatti()) == ["Il cane si chiama Lord", "Il gatto si chiama Fido"],
      str(m.fatti()))
check("e il file ha ancora le sue due righe",
      len(righe_fatto(m)) == 2, contenuto(m)[-200:])
check("il fatto esatto si elimina", m.elimina("Il gatto si chiama Fido") is True)
check("resta solo il cane", m.fatti() == ["Il cane si chiama Lord"],
      str(m.fatti()))
check("l'intestazione e la sezione restano",
      "# Memoria di Orchestra" in contenuto(m)
      and "## Fatti" in contenuto(m), contenuto(m)[-200:])

# Un fatto che e' prefisso di un altro: il caso in cui `in` fa piu' danno,
# perche' cancella due fatti con una richiesta sola.
prefisso = nuova_memoria()
prefisso.aggiungi("Il sito ha 12 pagine", origine="test")
prefisso.aggiungi("Il sito ha 12 pagine e un blog", origine="test")
prefisso.elimina("Il sito ha 12 pagine")
check("un fatto che e' prefisso di un altro non porta via anche l'altro",
      prefisso.fatti() == ["Il sito ha 12 pagine e un blog"],
      str(prefisso.fatti()))

# Le righe che non sono fatti non sono cancellabili per parola: prima
# `Memoria` di Orchestra spariva perche' conteneva "Memoria".
intestazioni = nuova_memoria()
intestazioni.aggiungi("Il gestore si chiama Mario", origine="test")
check("cancellare una parola dell'intestazione non tocca il file",
      intestazioni.elimina("Memoria") is False)
check("l'intestazione e' ancora li'",
      "# Memoria di Orchestra" in contenuto(intestazioni))
check("cancellare 'Fatti' non porta via la sezione",
      intestazioni.elimina("Fatti") is False
      and "## Fatti" in contenuto(intestazioni))
check("e il fatto vero e' rimasto",
      intestazioni.fatti() == ["Il gestore si chiama Mario"],
      str(intestazioni.fatti()))

# Chi incolla la riga intera (con `- ` e la coda) deve poter cancellare.
marcata = nuova_memoria()
marcata.aggiungi("Consegna il venerdì", origine="agente", progetto="alfa")
riga = righe_fatto(marcata)[0]
check("la riga di prova ha la marcatura",
      "[progetto:alfa]" in riga and "_agente_" in riga, riga)
check("si puo' eliminare incollando la riga intera",
      marcata.elimina(riga) is True)
check("e il fatto e' sparito davvero", marcata.fatti() == [],
      str(marcata.fatti()))

# ---------------------------------------------------------------------------
print("\n[2] L'eliminazione rispetta il progetto")

m = nuova_memoria()
m.aggiungi("Consegna il venerdì", origine="test", progetto="alfa")
m.aggiungi("Consegna il lunedì", origine="test", progetto="beta")

check("col progetto sbagliato non si cancella niente",
      m.elimina("Consegna il venerdì", progetto="beta") is False)
check("il fatto e' ancora nel suo progetto",
      m.fatti_per_progetto("alfa") == ["Consegna il venerdì"],
      str(m.fatti_per_progetto("alfa")))
check("col progetto giusto si cancella",
      m.elimina("Consegna il venerdì", progetto="alfa") is True)
check("l'altro progetto resta intatto",
      m.fatti_per_progetto("beta") == ["Consegna il lunedì"],
      str(m.fatti_per_progetto("beta")))

# Lo stesso testo in due progetti: `aggiungi` non lo permette (deduplica
# sul testo), ma chi scrive il file a mano si'. Si toglie solo quello
# chiesto.
doppio = nuova_memoria(
    "## Fatti\n\n"
    "- Consegna il venerdì  [progetto:alfa]  _mano_  <!-- 2026-11-01 -->\n"
    "- Consegna il venerdì  [progetto:beta]  _mano_  <!-- 2026-11-01 -->\n")
check("stesso testo in due progetti: si toglie solo quello chiesto",
      doppio.elimina("Consegna il venerdì", progetto="beta") is True
      and doppio.fatti_per_progetto("alfa") == ["Consegna il venerdì"]
      and doppio.fatti_per_progetto("beta") == [],
      f"alfa={doppio.fatti_per_progetto('alfa')} "
      f"beta={doppio.fatti_per_progetto('beta')}")

# ---------------------------------------------------------------------------
print("\n[3] La modifica conserva progetto, fonte, data e [auto]")

REGOLA = "Da ora in poi usa solo il calendario Nova"
m = nuova_memoria()
m.aggiungi(REGOLA, origine="sessione", progetto="gestionale")
prima = righe_fatto(m)[0]
check("la riga nasce con progetto, fonte, data e [auto]",
      "[progetto:gestionale]" in prima and "_sessione_" in prima
      and "<!--" in prima and prima.rstrip().endswith("[auto]"), prima)

data = re.search(r"<!--\s*(.*?)\s*-->", prima).group(1)
NUOVO = "Da ora in poi usa solo il calendario di Nova gestionale"
check("la modifica riesce", m.modifica(REGOLA, NUOVO) is True)
dopo = righe_fatto(m)[0]
check("il testo e' quello nuovo", NUOVO in dopo, dopo)
check("la modifica conserva il progetto",
      "[progetto:gestionale]" in dopo, dopo)
check("la modifica conserva la fonte", "_sessione_" in dopo, dopo)
check("la modifica conserva la data", f"<!-- {data} -->" in dopo, dopo)
check("la modifica conserva [auto]", dopo.rstrip().endswith("[auto]"), dopo)
check("la regola resta promossa dall'euristica",
      dict(m.importanti_con_origine()).get(NUOVO) == "auto",
      str(m.importanti_con_origine()))
check("la regola resta fra gli Importanti (cioe' nel prompt)",
      NUOVO in m.importanti() and "## Importanti" in contenuto(m),
      str(m.importanti())[:200])
check("non ci sono due righe per lo stesso fatto",
      len(righe_fatto(m)) == 1, contenuto(m)[-200:])

# Il confronto esatto vale anche qui: modificare "gatto" non riscrive la
# riga che parla del gatto.
simile = nuova_memoria()
simile.aggiungi("Il sito ha 12 pagine", origine="test")
simile.aggiungi("Il sito ha 12 pagine e un blog", origine="test")
simile.modifica("Il sito ha 12 pagine", "Il sito ha 20 pagine")
check("la modifica non tocca il fatto che contiene il testo",
      sorted(simile.fatti()) == ["Il sito ha 12 pagine e un blog",
                                 "Il sito ha 20 pagine"],
      str(simile.fatti()))

# Anche la modifica rispetta il progetto.
due = nuova_memoria(
    "## Fatti\n\n"
    "- Consegna il venerdì  [progetto:alfa]  <!-- 2026-11-01 -->\n"
    "- Consegna il venerdì  [progetto:beta]  <!-- 2026-11-01 -->\n")
check("la modifica con progetto tocca solo quel progetto",
      due.modifica("Consegna il venerdì", "Consegna il sabato",
                   progetto="beta") is True
      and due.fatti_per_progetto("alfa") == ["Consegna il venerdì"]
      and due.fatti_per_progetto("beta") == ["Consegna il sabato"],
      f"alfa={due.fatti_per_progetto('alfa')} "
      f"beta={due.fatti_per_progetto('beta')}")

# La coda e' strutturale: un progetto scritto nel testo nuovo non deve
# poter spostare il fatto in un altro progetto.
iniezione = nuova_memoria()
iniezione.aggiungi("Nota di prova", origine="test", progetto="alfa")
iniezione.modifica("Nota di prova", "Nota di prova  [progetto:beta]")
riga = righe_fatto(iniezione)[0]
check("un progetto scritto nel testo nuovo non cambia il progetto",
      "[progetto:alfa]" in riga and "[progetto:beta]" not in riga, riga)

# ---------------------------------------------------------------------------
print("\n[4] Dopo elimina e modifica l'indice si riallinea dal file (chunk compresi)")

lungo = " ".join(["parola"] * 400) + " codaunica"
m = nuova_memoria()
idx = nuovo_indice(m)
idx.aggiungi("Fatto corto sul colore blu", origine="test")
idx.aggiungi(lungo, origine="test")

righe_attese = len(m.fatti())
check("il fatto lungo e' indicizzato a pezzi",
      idx._conto_db() > righe_attese,
      f"{idx._conto_db()} righe per {righe_attese} fatti")
check("la coda del fatto lungo si trova",
      bool(idx.cerca("codaunica", conta_usi=False)))

check("il fatto lungo si elimina dal file", idx.elimina(lungo) is True)
check("e non e' piu' nel file",
      all("codaunica" not in f for f in m.fatti()), str(m.fatti())[-200:])
check("e non e' piu' cercabile",
      idx.cerca("codaunica", conta_usi=False) == [],
      str(idx.cerca("codaunica", conta_usi=False))[:200])
check("nessun chunk resta nell'indice",
      idx._conto_db() == len(m.fatti()),
      f"{idx._conto_db()} righe, {len(m.fatti())} fatti")
check("anche la tabella FTS e' allineata",
      idx._query("SELECT COUNT(*) c FROM fatti_fts")[0]["c"]
      == len(m.fatti()),
      str(idx._query("SELECT COUNT(*) c FROM fatti_fts")[0]["c"]))
check("il resto della memoria si cerca ancora",
      bool(idx.cerca("blu", conta_usi=False)))

# La modifica di un fatto lungo in uno corto: i chunk del vecchio testo
# devono sparire, o la ricerca restituisce pezzi che il file non ha piu'.
lungo2 = " ".join(["beta"] * 400) + " codabeta"
idx.aggiungi(lungo2, origine="test")
check("prima della modifica la coda si trova",
      bool(idx.cerca("codabeta", conta_usi=False)))
check("la modifica lunga->corta riesce",
      idx.modifica(lungo2, "Fatto corto sostitutivo") is True)
check("i chunk del testo vecchio spariscono",
      idx.cerca("codabeta", conta_usi=False) == [],
      str(idx.cerca("codabeta", conta_usi=False))[:200])
check("il testo nuovo si trova",
      bool(idx.cerca("sostitutivo", conta_usi=False)))
check("l'indice e' allineato al file dopo la modifica",
      idx._conto_db() == len(m.fatti()),
      f"{idx._conto_db()} righe, {len(m.fatti())} fatti")
check("anche il fatto corto si toglie dall'indice",
      idx.elimina("Fatto corto sul colore blu") is True
      and idx.cerca("blu", conta_usi=False) == [])

# L'indice rispetta il progetto come il file.
m2 = nuova_memoria()
idx2 = nuovo_indice(m2)
idx2.aggiungi("Consegna il venerdì", origine="test", progetto="alfa")
idx2.aggiungi("Consegna il lunedì", origine="test", progetto="beta")
check("l'indice non cancella col progetto sbagliato",
      idx2.elimina("Consegna il venerdì", progetto="beta") is False
      and bool(idx2.cerca("venerdì", conta_usi=False)),
      str(idx2.cerca("venerdì", conta_usi=False))[:200])
check("e cancella col progetto giusto, lasciando l'altro",
      idx2.elimina("Consegna il venerdì", progetto="alfa") is True
      and idx2.cerca("venerdì", conta_usi=False) == []
      and bool(idx2.cerca("lunedì", conta_usi=False)),
      str(idx2.cerca("lunedì", conta_usi=False))[:200])

# Stessa cosa per la modifica: il progetto arriva al file, e l'indice si
# riallinea solo quando la modifica e' avvenuta.
m7 = nuova_memoria(
    "## Fatti\n\n"
    "- Consegna il venerdì  [progetto:alfa]  <!-- 2026-11-01 -->\n"
    "- Consegna il venerdì  [progetto:beta]  <!-- 2026-11-01 -->\n")
idx7 = nuovo_indice(m7)
check("l'indice non modifica col progetto sbagliato",
      idx7.modifica("Consegna il venerdì", "Consegna il sabato",
                    progetto="gamma") is False
      and m7.fatti_per_progetto("alfa") == ["Consegna il venerdì"],
      str(m7.fatti_per_progetto("alfa")))
check("e modifica solo il progetto giusto",
      idx7.modifica("Consegna il venerdì", "Consegna il sabato",
                    progetto="beta") is True
      and m7.fatti_per_progetto("alfa") == ["Consegna il venerdì"]
      and m7.fatti_per_progetto("beta") == ["Consegna il sabato"],
      f"alfa={m7.fatti_per_progetto('alfa')} "
      f"beta={m7.fatti_per_progetto('beta')}")

# ---------------------------------------------------------------------------
print("\n[5] Il tool passa dal percorso giusto")

vero = tool_mem.memoria
m3 = nuova_memoria()
m3.aggiungi("Il gatto si chiama Fido", origine="test", progetto="alfa")
tool_mem.memoria = lambda: m3
try:
    strumento = tool_mem.tool_memoria()
    risposta = strumento.handler(azione="elimina", fatto="gatto")
    check("il tool non cancella per sottostringa",
          "Non l'ho trovato" in risposta
          and m3.fatti() == ["Il gatto si chiama Fido"], risposta)

    risposta = strumento.handler(azione="elimina",
                                 fatto="Il gatto si chiama Fido",
                                 progetto="beta")
    check("il tool rispetta il progetto",
          "Non l'ho trovato" in risposta
          and m3.fatti() == ["Il gatto si chiama Fido"], risposta)

    risposta = strumento.handler(azione="elimina",
                                 fatto="Il gatto si chiama Fido",
                                 progetto="alfa")
    check("il tool cancella col progetto giusto",
          "Dimenticato" in risposta and m3.fatti() == [], risposta)

    m3.aggiungi("Il cane si chiama Lord", origine="test")
    risposta = strumento.handler(azione="modifica",
                                 fatto="Il cane si chiama Lord",
                                 nuovo="Il cane si chiama Rex")
    check("il tool modifica il fatto",
          "Modificato" in risposta and m3.fatti() == ["Il cane si chiama Rex"],
          risposta)
finally:
    tool_mem.memoria = vero

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
