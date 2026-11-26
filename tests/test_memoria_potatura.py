"""La potatura che non potava mai niente.

`IndiceMemoria.ricostruisci` reinseriva ogni fatto con `creata = adesso`,
`usi = 0`, `origine = ''` e `scade = None`. `ottimizza_memoria`
ricostruiva l'indice a ogni chiamata — anche in `dry_run` — e quindi ogni
fatto sembrava nuovo di zecca nel momento stesso in cui si decideva se
era vecchio: la potatura non poteva rimuovere niente, mai.

Qui si prova che:

1. una ricostruzione conserva `creata`, `usi`, origine e `scade` (quello
   che il file non sa), e prende la data dal file per un fatto nuovo;
2. `dry_run` non scrive nell'indice, nemmeno quando l'indice e' vuoto e
   andrebbe ricostruito;
3. un fatto vecchio e mai usato viene rimosso davvero — anche lungo,
   cioe' indicizzato a chunk, dove la cancellazione per testo non
   trovava niente.

Niente rete e niente memoria vera: ogni caso ha la sua cartella
temporanea e il suo indice.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# La cartella dati dei test, PRIMA di importare orchestra: `memoria()` e
# `indice_memoria()` sono singleton.
os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orch-test-potatura-")

from orchestra import memoria as memoria_mod            # noqa: E402
from orchestra import memoria_indice as indice_mod      # noqa: E402

PASS, FAIL = [], []
GIORNO = 86400.0


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def nuova_memoria(contenuto: str | None = None) -> memoria_mod.Memoria:
    cartella = tempfile.mkdtemp(prefix="orch-pot-")
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


def riga_di(idx: indice_mod.IndiceMemoria, testo: str):
    righe = idx._query(
        "SELECT testo, importante, origine, creata, scade, usi, progetto"
        " FROM fatti WHERE testo = ?", (testo,))
    return dict(righe[0]) if righe else None


def istantanea(idx: indice_mod.IndiceMemoria) -> list[dict]:
    """Tutte le righe dell'indice, per confrontare prima e dopo."""
    return [dict(r) for r in idx._query(
        "SELECT testo, importante, origine, creata, scade, usi, progetto"
        " FROM fatti ORDER BY testo")]


def invecchia(idx: indice_mod.IndiceMemoria, testo: str | None = None,
              giorni: float = 100) -> None:
    """Rende un fatto vecchio e mai usato, come dopo mesi di vita vera."""
    sql = ("UPDATE fatti SET creata = ?, usi = 0"
           + (" WHERE testo = ?" if testo else ""))
    args = (time.time() - giorni * GIORNO,) + ((testo,) if testo else ())
    with idx._lock:
        idx._conn.execute(sql, args)
        idx._conn.commit()


# ---------------------------------------------------------------------------
print("\n[1] La ricostruzione non azzera creata, usi, origine e scadenza")

m = nuova_memoria()
idx = nuovo_indice(m)
idx.aggiungi("Fatto vecchio mai usato", origine="sessione", progetto="alfa")
idx.aggiungi("Fatto usato spesso", origine="sessione", progetto="alfa")

adesso = time.time()
with idx._lock:
    idx._conn.execute(
        "UPDATE fatti SET creata = ?, usi = 0 WHERE testo = ?",
        (adesso - 100 * GIORNO, "Fatto vecchio mai usato"))
    idx._conn.execute(
        "UPDATE fatti SET usi = 3, scade = ? WHERE testo = ?",
        (adesso + 10 * GIORNO, "Fatto usato spesso"))
    idx._conn.commit()

idx.ricostruisci()

vecchio = riga_di(idx, "Fatto vecchio mai usato")
usato = riga_di(idx, "Fatto usato spesso")
check("la ricostruzione conserva creata",
      abs(float(vecchio["creata"]) - (adesso - 100 * GIORNO)) < 60,
      str(vecchio["creata"]))
check("la ricostruzione conserva usi", usato["usi"] == 3, str(usato["usi"]))
check("la ricostruzione conserva la scadenza",
      usato["scade"] is not None and float(usato["scade"]) > adesso,
      str(usato["scade"]))
check("la ricostruzione conserva l'origine",
      vecchio["origine"] == "sessione", str(vecchio["origine"]))
check("la ricostruzione conserva il progetto",
      vecchio["progetto"] == "alfa", str(vecchio["progetto"]))

# Un fatto che l'indice non ha mai visto: la data deve venire dal file,
# non da `time.time()`, o ogni riavvio lo farebbe sembrare nuovo.
m2 = nuova_memoria("# Memoria di Orchestra\n\n## Fatti\n\n"
                   "- Fatto scritto a mano, vecchio  <!-- 2026-01-01 -->\n")
idx2 = nuovo_indice(m2)
riga = riga_di(idx2, "Fatto scritto a mano, vecchio")
attesa = time.mktime(time.strptime("2026-01-01", "%Y-%m-%d"))
check("un fatto nuovo prende la data dal file, non da adesso",
      abs(float(riga["creata"]) - attesa) < 60, str(riga["creata"]))

# ---------------------------------------------------------------------------
print("\n[2] Il dry_run non modifica l'indice")

m3 = nuova_memoria()
idx3 = nuovo_indice(m3)
idx3.aggiungi("Fatto vecchio mai usato", origine="sessione")
invecchia(idx3, "Fatto vecchio mai usato")

prima = istantanea(idx3)
anteprima = idx3.ottimizza_memoria(dry_run=True, giorni_grazia=30)
dopo = istantanea(idx3)

check("l'anteprima propone il fatto vecchio",
      any(c["testo"] == "Fatto vecchio mai usato"
          for c in anteprima["candidati"]),
      str(anteprima["candidati"])[:240])
check("il dry run non cambia una riga dell'indice", prima == dopo,
      f"prima={prima} dopo={dopo}")
check("il dry run non tocca il file",
      m3.fatti() == ["Fatto vecchio mai usato"], str(m3.fatti()))
check("il dry run non dichiara rimozioni", anteprima["rimossi"] == 0,
      str(anteprima["rimossi"]))
check("e non si dichiara applicato", anteprima["applicato"] is False)

# Il caso peggiore: indice svuotato. Prima, il dry run lo ricostruiva —
# cioe' scriveva, e riportava `creata` a oggi proprio mentre decideva.
m4 = nuova_memoria("## Fatti\n\n- Fatto vecchio a mano  <!-- 2026-01-01 -->\n")
idx4 = nuovo_indice(m4)
with idx4._lock:
    idx4._conn.execute("DELETE FROM fatti")
    idx4._conn.commit()

proposta = idx4.ottimizza_memoria(dry_run=True, giorni_grazia=30)
check("il dry run non ricostruisce un indice vuoto",
      idx4._conto_db() == 0, str(idx4._conto_db()))
check("ma legge il fatto dal file e lo propone",
      any(c["testo"] == "Fatto vecchio a mano"
          for c in proposta["candidati"]),
      str(proposta["candidati"])[:240])

# ---------------------------------------------------------------------------
print("\n[3] Un fatto vecchio e mai usato viene rimosso")

m5 = nuova_memoria()
idx5 = nuovo_indice(m5)
idx5.aggiungi("Fatto vecchio mai usato", origine="sessione")
idx5.aggiungi("Fatto recente", origine="sessione")
invecchia(idx5, "Fatto vecchio mai usato")

anteprima = idx5.ottimizza_memoria(dry_run=True, giorni_grazia=30)
check("l'anteprima elenca solo il fatto vecchio",
      [c["testo"] for c in anteprima["candidati"]]
      == ["Fatto vecchio mai usato"],
      str(anteprima["candidati"])[:240])

esito = idx5.ottimizza_memoria(dry_run=False, giorni_grazia=30)
check("la potatura dichiara la rimozione", esito["rimossi"] >= 1,
      str(esito)[:240])
check("il fatto vecchio non e' piu' nel file",
      all("vecchio" not in f for f in m5.fatti()), str(m5.fatti()))
check("e non e' piu' cercabile",
      idx5.cerca("vecchio", conta_usi=False) == [],
      str(idx5.cerca("vecchio", conta_usi=False))[:200])
check("il fatto recente e' rimasto",
      m5.fatti() == ["Fatto recente"], str(m5.fatti()))
check("e resta cercabile", bool(idx5.cerca("recente", conta_usi=False)))
check("il file e' ancora una memoria valida",
      "# Memoria di Orchestra" in m5.leggi()
      and "## Fatti" in m5.leggi())

# Un fatto lungo non ha una riga d'indice col suo testo: ha i chunk. La
# cancellazione per testo non lo trovava, quindi la potatura lo
# proponeva e poi non riusciva a toglierlo.
lungo = " ".join(["parola"] * 400) + " codaunica"
m6 = nuova_memoria()
idx6 = nuovo_indice(m6)
idx6.aggiungi(lungo, origine="sessione")
invecchia(idx6)
idx6.aggiungi("Fatto recente", origine="sessione")

esito6 = idx6.ottimizza_memoria(dry_run=False, giorni_grazia=30)
check("anche un fatto lungo e vecchio viene potato",
      all("codaunica" not in f for f in m6.fatti()),
      str(m6.fatti())[:200])
check("e i suoi chunk spariscono dall'indice",
      idx6.cerca("codaunica", conta_usi=False) == [],
      str(idx6.cerca("codaunica", conta_usi=False))[:200])
check("il fatto recente resta",
      m6.fatti() == ["Fatto recente"], str(m6.fatti()))
check("la potatura ha contato una rimozione", esito6["rimossi"] >= 1,
      str(esito6["rimossi"]))

# Un fatto importante non si pota, nemmeno se vecchio e mai usato: e'
# l'unica categoria che qualcuno ha marcato come sempre vera.
m7 = nuova_memoria()
idx7 = nuovo_indice(m7)
idx7.aggiungi("Regola importante vecchia", origine="sessione",
              importante=True)
invecchia(idx7, "Regola importante vecchia")
idx7.ottimizza_memoria(dry_run=False, giorni_grazia=30)
check("un fatto importante non viene potato",
      "Regola importante vecchia" in m7.importanti(),
      str(m7.importanti())[:200])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
