"""Cosa vede la UI quando guarda la memoria.

Tre difetti nello stesso punto — `stato()` e i suoi consumatori:

1. La lista mostrava un insieme solo. Con l'indice attivo `fatti()`
   escludeva gli Importanti, e il pannello diceva "nessuna regola"
   mentre il prompt le mostrava tutte: due memorie diverse nella stessa
   installazione.

2. `percorso` era quello del backend attivo, e con l'indice diventava
   il file `.db`. La UI lo mostra come "il file che puoi aprire": il
   database non e' quel file.

3. I fatti lunghi vivono nell'indice a chunk, e i chunk finivano
   nell'elenco e nella ricerca come se fossero fatti interi: pezzi di
   frase troncati, e un fatto contato due o tre volte.

Qui si prova il contratto di `stato()`, di `fatti()`/`importanti()` e
della ricerca con il backend a file e con l'indice.
"""

from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# La cartella dati dei test, PRIMA di importare orchestra: `memoria()` e
# `indice_memoria()` sono singleton.
os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orch-test-stato-")

from orchestra import memoria as memoria_mod            # noqa: E402
from orchestra import memoria_indice as indice_mod      # noqa: E402
from orchestra.rotte_storia import RotteStoria          # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def nuova_memoria(contenuto: str | None = None) -> memoria_mod.Memoria:
    cartella = tempfile.mkdtemp(prefix="orch-stato-")
    percorso = os.path.join(cartella, "memory.md")
    if contenuto is not None:
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(contenuto)
    return memoria_mod.Memoria(percorso=percorso)


def nuovo_indice(m: memoria_mod.Memoria) -> indice_mod.IndiceMemoria:
    return indice_mod.IndiceMemoria(
        sorgente=m,
        percorso=os.path.join(os.path.dirname(m.percorso),
                              "memoria_indice.db"))


def stato_con(backend) -> dict:
    """`stato()` con il backend scelto, poi rimette quello vero."""
    vero = memoria_mod.memoria
    memoria_mod.memoria = lambda: backend
    try:
        return memoria_mod.stato()
    finally:
        memoria_mod.memoria = vero


REGOLA = "Da ora in poi usa solo il calendario Nova"
DATO = "Il sito ha 12 pagine"

# ---------------------------------------------------------------------------
print("\n[1] stato() con il backend a file")

m = nuova_memoria()
m.aggiungi(DATO, origine="test")
m.aggiungi(REGOLA, origine="test")

s = stato_con(m)
check("mostra i fatti normali", DATO in s["fatti"], str(s["fatti"])[:240])
check("mostra anche gli Importanti", REGOLA in s["fatti"],
      str(s["fatti"])[:240])
check("gli Importanti sono elencati anche a parte",
      s["importanti"] == [REGOLA], str(s["importanti"])[:240])
check("i conteggi sono distinti",
      s["n_fatti"] == 2 and s["n_importanti"] == 1,
      f"n_fatti={s.get('n_fatti')} n_importanti={s.get('n_importanti')}")
check("il percorso e' quello di memory.md",
      s["percorso"] == m.percorso and s["percorso"].endswith("memory.md"),
      str(s["percorso"]))

# ---------------------------------------------------------------------------
print("\n[2] stato() con l'indice attivo (il percorso vero in produzione)")

m2 = nuova_memoria()
idx2 = nuovo_indice(m2)
idx2.aggiungi(DATO, origine="test")
idx2.aggiungi(REGOLA, origine="test")

s2 = stato_con(idx2)
check("con l'indice la lista contiene i normali e gli Importanti",
      DATO in s2["fatti"] and REGOLA in s2["fatti"],
      str(s2["fatti"])[:240])
check("con l'indice gli Importanti sono a parte",
      s2["importanti"] == [REGOLA], str(s2["importanti"])[:240])
check("n_fatti e' il numero di fatti, non di righe d'indice",
      s2["n_fatti"] == 2, str(s2.get("n_fatti")))
check("il percorso resta memory.md, non il database",
      s2["percorso"] == m2.percorso
      and s2["percorso"].endswith("memory.md")
      and not s2["percorso"].endswith(".db"),
      str(s2["percorso"]))

# La regressione: `fatti()` filtrava `importante = 0`, e la UI (che
# disegna `d.fatti`) perdeva proprio le regole che il prompt mostrava.
check("fatti() dell'indice include anche gli Importanti",
      DATO in idx2.fatti() and REGOLA in idx2.fatti(),
      str(idx2.fatti())[:240])
check("fatti() non duplica gli Importanti",
      len(idx2.fatti()) == len(set(idx2.fatti())) == 2,
      str(idx2.fatti()))
check("importanti() resta il sottoinsieme, non la lista intera",
      idx2.importanti() == [REGOLA]
      and DATO not in idx2.importanti(),
      str(idx2.importanti()))

# Anche il tool `elenca` (quello che l'agente usa) deve vedere tutto.
from orchestra.tools import memoria as tool_mem         # noqa: E402

vero_tool = tool_mem.memoria
tool_mem.memoria = lambda: idx2
try:
    elenco = tool_mem.tool_memoria().handler(azione="elenca")
finally:
    tool_mem.memoria = vero_tool
check("il tool `elenca` mostra normali e Importanti",
      DATO in elenco and REGOLA in elenco, elenco[:240])
check("e non li ripete", elenco.count(REGOLA) == 1, elenco[:240])

# ---------------------------------------------------------------------------
print("\n[3] I chunk dei fatti lunghi non sono fatti")

lungo = " ".join(["parola"] * 400) + " codaunica"
m3 = nuova_memoria()
idx3 = nuovo_indice(m3)
idx3.aggiungi(lungo, origine="test")
idx3.aggiungi("Fatto corto sul colore blu", origine="test")

check("l'indice ha davvero piu' righe dei fatti (i chunk)",
      idx3._conto_db() > len(m3.fatti()),
      f"{idx3._conto_db()} righe, {len(m3.fatti())} fatti")
check("fatti() restituisce il fatto intero",
      lungo in idx3.fatti(), str(idx3.fatti())[:240])
check("fatti() non restituisce pezzi",
      all(len(f) >= len(lungo) for f in idx3.fatti()
          if f.startswith("parola")),
      str([len(f) for f in idx3.fatti()]))
check("un fatto lungo conta come uno", len(idx3.fatti()) == 2,
      str(len(idx3.fatti())))

trovati = idx3.cerca("codaunica", conta_usi=False)
check("la ricerca trova il fatto lungo", len(trovati) == 1,
      str(trovati)[:240])
check("e restituisce il testo intero, non il chunk",
      bool(trovati) and trovati[0]["testo"] == lungo,
      str(trovati[0]["testo"])[:160] if trovati else "")

# Due chunk dello stesso fatto fanno match sulla stessa parola: e' un
# fatto solo e va mostrato una volta sola.
doppi = idx3.cerca("parola", conta_usi=False, limite=10)
voci = [x for x in doppi if x["testo"] == lungo]
check("due chunk non diventano due risultati", len(voci) == 1,
      str(doppi)[:300])
check("nessun risultato e' un pezzo del fatto",
      all(not (x["testo"].startswith("parola parola")
               and x["testo"] != lungo) for x in doppi),
      str(doppi)[:300])

stats = idx3.statistiche()
check("le statistiche contano il fatto una volta",
      stats["totale"] == 2, str(stats["totale"]))

# Anche un Importante lungo deve arrivare intero al prompt e alla UI.
regola_lunga = ("Da ora in poi usa sempre "
                + " ".join(["nota"] * 300) + " finaleunico")
m4 = nuova_memoria()
idx4 = nuovo_indice(m4)
idx4.aggiungi(regola_lunga, origine="test")
check("un Importante lungo e' intero, non a chunk",
      idx4.importanti() == [regola_lunga],
      str(idx4.importanti())[:200])
s4 = stato_con(idx4)
check("e stato() lo mostra intero una volta sola",
      s4["fatti"].count(regola_lunga) == 1
      and regola_lunga in s4["importanti"],
      str(s4["fatti"])[:200])

# ---------------------------------------------------------------------------
print("\n[4] La rotta vera: GET /api/memoria con l'indice attivo")


class FintaRotta:
    """Il minimo per chiamare un gestore senza un server."""

    def __init__(self) -> None:
        self.risposta: tuple | None = None
        self.app = None

    def _json(self, dati, code: int = 200) -> None:
        self.risposta = (dati, code)


DATO5 = "Il sito ha 12 pagine"
REGOLA5 = "Da ora in poi usa solo il calendario Nova"
LUNGO5 = " ".join(["parola"] * 400) + " codaunica"

m5 = nuova_memoria()
idx5 = nuovo_indice(m5)
idx5.aggiungi(DATO5, origine="test")
idx5.aggiungi(REGOLA5, origine="test")
idx5.aggiungi(LUNGO5, origine="test")

vero_mem = memoria_mod.memoria
vero_indice = indice_mod.indice_memoria
memoria_mod.memoria = lambda: idx5
indice_mod.indice_memoria = lambda: idx5
try:
    finta = FintaRotta()
    RotteStoria._r_get_memoria(finta, "/api/memoria", {}, None)
    risposta = finta.risposta or ({}, 0)
    dati, codice = risposta
finally:
    memoria_mod.memoria = vero_mem
    indice_mod.indice_memoria = vero_indice

fatti = dati.get("fatti") or []
check("la rotta risponde 200", codice == 200, str(codice))
check("la risposta contiene i fatti normali", DATO5 in fatti,
      str(fatti)[:240])
check("la risposta contiene gli Importanti", REGOLA5 in fatti,
      str(fatti)[:240])
check("gli Importanti sono elencati anche a parte",
      dati.get("importanti") == [REGOLA5], str(dati.get("importanti"))[:200])
check("il percorso nella risposta e' memory.md, non il database",
      dati.get("percorso") == m5.percorso
      and str(dati.get("percorso")).endswith("memory.md")
      and not str(dati.get("percorso")).endswith(".db"),
      str(dati.get("percorso")))
check("il fatto lungo arriva intero", LUNGO5 in fatti,
      str(fatti)[:240])
check("nessun chunk viene presentato come fatto",
      len(fatti) == 3
      and all(not (f.startswith("parola parola") and f != LUNGO5)
              for f in fatti),
      str([len(f) for f in fatti]))
check("n_fatti e' il numero di fatti, non di righe d'indice",
      dati.get("n_fatti") == 3, str(dati.get("n_fatti")))
check("la rotta porta anche le statistiche dell'indice",
      (dati.get("indice") or {}).get("totale") == 3,
      str(dati.get("indice"))[:200])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
