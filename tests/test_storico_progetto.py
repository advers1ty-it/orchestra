"""Le conversazioni appartengono a un progetto.

Il difetto: la cronologia diceva "ogni progetto ha le sue", ma le
sessioni non avevano nessun campo progetto. Tutte le chat di tutti i
progetti comparivano insieme, e riaprirne una mentre era attivo un altro
progetto continuava a scrivere nella cartella sbagliata.

Qui si coprono i cinque pezzi:

1. migrazione di un DB vecchio (la colonna arriva, le righe restano);
2. creazione della sessione col progetto attivo;
3. cambio progetto a chat aperta (la riga si aggiorna);
4. riapertura (il progetto torna, o si adotta quello attivo se la riga
   non ne aveva uno);
5. filtro di elenco e ricerca per progetto, con le conversazioni senza
   progetto che restano visibili.

Niente rete: il provider e' finto. Dati veri mai toccati: ORCHESTRA_HOME
punta a una cartella temporanea prima degli import.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="orchestra_storico_progetto_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

from orchestra.storico import Storico, storico                  # noqa: E402
from orchestra.session import LoopConfig, Session               # noqa: E402
from orchestra.tools import default_registry                    # noqa: E402
from orchestra.types import Message                             # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class ProviderFinto:
    name = "finto"
    model = "finto-1"

    def chat(self, *a, **k):
        raise AssertionError("il test non fa turni")


print("\n[1] Un DB vecchio migra senza perdere righe")

vecchio = os.path.join(_TMP, "vecchio.db")
conn = sqlite3.connect(vecchio)
conn.executescript("""
CREATE TABLE sessioni (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titolo TEXT NOT NULL DEFAULT '',
    modello TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    bot TEXT NOT NULL DEFAULT '',
    creata REAL NOT NULL,
    aggiornata REAL NOT NULL
);
CREATE TABLE messaggi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sessione_id INTEGER NOT NULL,
    ruolo TEXT NOT NULL,
    contenuto TEXT NOT NULL DEFAULT '',
    ragionamento TEXT NOT NULL DEFAULT '',
    nome TEXT,
    tool_json TEXT,
    token INTEGER NOT NULL DEFAULT 0,
    creata REAL NOT NULL
);
INSERT INTO sessioni (titolo, creata, aggiornata)
    VALUES ('chat vecchia', 1.0, 1.0);
""")
conn.commit()
conn.close()

migrato = Storico(percorso=vecchio)
colonne = [r["name"] for r in migrato._conn.execute(
    "PRAGMA table_info(sessioni)").fetchall()]
check("la colonna progetto c'e'", "progetto" in colonne, str(colonne))
vecchie = migrato.elenco()
check("la riga vecchia e' ancora li'", len(vecchie) == 1, str(vecchie))
check("la riga vecchia e' senza progetto",
      (vecchie[0].get("progetto") or "") == "", str(vecchie[0]))
check("l'indice del progetto esiste",
      bool(migrato._conn.execute(
          "SELECT name FROM sqlite_master WHERE type='index'"
          " AND name='idx_sessioni_progetto'").fetchone()))
migrato.chiudi()

print("\n[2] La creazione lega la sessione al progetto, il cambio la sposta")

s = Session(provider=ProviderFinto(), registry=default_registry(),
            system_prompt="BASE", config=LoopConfig(max_iterations=2))
s.imposta_progetto("Alfa")
s.agent.state.messages.append(Message(role="user", content="primo turno"))
s._salva_su_disco()
sid = s._sessione_id
check("il salvataggio crea la riga", sid is not None, str(sid))
riga = storico().sessione(sid)
check("la riga nasce col progetto attivo",
      (riga or {}).get("progetto") == "Alfa", str(riga))
s.imposta_progetto("Beta")
riga = storico().sessione(sid)
check("cambiare progetto aggiorna la riga",
      (riga or {}).get("progetto") == "Beta", str(riga))

print("\n[3] Riaprendo, il progetto torna con la conversazione")

# Una conversazione di Alfa, gia' salvata.
s2 = Session(provider=ProviderFinto(), registry=default_registry(),
             system_prompt="BASE", config=LoopConfig(max_iterations=2))
s2.imposta_progetto("Alfa")
s2.agent.state.messages.append(Message(role="user", content="roba di alfa"))
s2._salva_su_disco()
alfa_id = s2._sessione_id

s3 = Session(provider=ProviderFinto(), registry=default_registry(),
             system_prompt="BASE", config=LoopConfig(max_iterations=2))
prima = s3.progetto
ok = s3.carica_sessione(alfa_id)
check("la sessione si carica", ok)
check("il progetto e' quello della conversazione",
      s3.progetto == "Alfa", f"{prima} -> {s3.progetto}")
check("lo snapshot lo espone", s3.snapshot().get("progetto") == "Alfa",
      str(s3.snapshot().get("progetto")))

# Una riga senza progetto (legacy): apertura mentre Beta e' attivo.
legacy = storico().nuova_sessione(titolo="legacy")
storico().aggiungi_messaggio(legacy, "user", "vecchia chat senza progetto")
s4 = Session(provider=ProviderFinto(), registry=default_registry(),
             system_prompt="BASE", config=LoopConfig(max_iterations=2))
s4.imposta_progetto("Beta")
s4.carica_sessione(legacy)
check("una chat legacy non azzera il progetto attivo",
      s4.progetto == "Beta", s4.progetto)
check("e viene adottata dal progetto attivo",
      (storico().sessione(legacy) or {}).get("progetto") == "Beta",
      str(storico().sessione(legacy)))

print("\n[4] Elenco e ricerca filtrano per progetto")

altra = storico().nuova_sessione(progetto="Gamma")
# Una riga davvero senza progetto: quella aperta in [3] e' stata adottata
# da Beta, ed e' il comportamento voluto.
senza = storico().nuova_sessione(titolo="senza progetto davvero")
storico().aggiungi_messaggio(altra, "user", "parola segreta di gamma")
storico().aggiungi_messaggio(alfa_id, "user", "parola segreta di alfa")
storico().aggiungi_messaggio(senza, "user", "parola segreta senza progetto")
storico().aggiungi_messaggio(sid, "user", "parola segreta di beta")

elenco = storico().elenco(limite=50, progetto="Alfa")
titoli = {str(r.get("titolo") or "") for r in elenco}
check("l'elenco tiene Alfa", any("alfa" in t.lower() for t in titoli) or
      any(r["id"] == alfa_id for r in elenco), str(elenco))
check("l'elenco esclude Gamma", all(r["id"] != altra for r in elenco),
      str([r["id"] for r in elenco]))
check("l'elenco include le chat senza progetto",
      any(r["id"] == senza for r in elenco), str([r["id"] for r in elenco]))

risultati = storico().cerca("segreta", limite=50, progetto="Alfa")
sessioni = {r["sessione_id"] for r in risultati}
check("la ricerca trova Alfa", alfa_id in sessioni, str(sessioni))
check("la ricerca esclude Gamma", altra not in sessioni, str(sessioni))
check("la ricerca include la chat senza progetto", senza in sessioni,
      str(sessioni))

tutti = storico().cerca("segreta", limite=50)
check("senza filtro si cerca in tutto",
      altra in {r["sessione_id"] for r in tutti},
      str({r["sessione_id"] for r in tutti}))

print("\n[5] Il cambio progetto non tocca l'ordinamento per data")

prima_agg = (storico().sessione(alfa_id) or {}).get("aggiornata")
storico().imposta_progetto(alfa_id, "Delta")
dopo = storico().sessione(alfa_id) or {}
check("il progetto si aggiorna", dopo.get("progetto") == "Delta", str(dopo))
check("la data di aggiornamento resta", dopo.get("aggiornata") == prima_agg,
      f"{prima_agg} -> {dopo.get('aggiornata')}")

print(f"\n{len(PASS)} passati, {len(FAIL)} falliti")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
    sys.exit(1)
