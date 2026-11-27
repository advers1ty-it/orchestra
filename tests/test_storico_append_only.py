"""Lo storico e' append-only e la compaction non cancella la conversazione.

Il punto non e' che il DB accetti INSERT: e' che dopo una compattazione i
turni originali siano ancora leggibili, con gli stessi id, e che il
salvataggio di un turno non riscriva tutto quello che c'era prima.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="orchestra_storico_append_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra.context import RIEPILOGO_TAG  # noqa: E402
from orchestra.session import LoopConfig, Session  # noqa: E402
from orchestra.storico import storico  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import Message  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class ProviderMuto:
    name = "finto"
    model = "finto-1"

    def chat(self, *a, **k):
        raise AssertionError("questo test non esegue un turno")


print("\n[1] Salvataggio incrementale: gli id vecchi non cambiano")
st = storico()
sid = st.nuova_sessione(titolo="append-only")
primi = [
    {"uid": "u1", "ruolo": "user", "contenuto": "primo messaggio"},
    {"uid": "u2", "ruolo": "assistant", "contenuto": "prima risposta"},
]
st.salva_turno(sid, primi)
prima = st.messaggi(sid)
check("il primo salvataggio scrive i messaggi", len(prima) == 2, str(len(prima)))
ids = [r["id"] for r in prima]

terzo = {"uid": "u3", "ruolo": "user", "contenuto": "secondo turno"}
# Si ripassa anche la conversazione intera, come fa la sessione: il DB
# deve ignorare i duplicati e aggiungere solo il nuovo.
st.salva_turno(sid, primi + [terzo])
dopo = st.messaggi(sid)
check("il nuovo messaggio viene aggiunto", len(dopo) == 3, str(len(dopo)))
check("gli id esistenti restano gli stessi",
      [r["id"] for r in dopo[:2]] == ids, f"{ids} -> {[r['id'] for r in dopo]}")
check("il contenuto vecchio e' ancora quello",
      [r["contenuto"] for r in dopo[:2]] == ["primo messaggio", "prima risposta"],
      str([r["contenuto"] for r in dopo[:2]]))
check("un secondo salvataggio non duplica",
      (st.salva_turno(sid, primi + [terzo]), len(st.messaggi(sid)))[1] == 3,
      str(len(st.messaggi(sid))))

print("\n[2] Un errore a meta' non lascia un turno mezzo scritto")
st._conn.execute(
    "CREATE TRIGGER rifiuta_boom BEFORE INSERT ON messaggi "
    "WHEN new.contenuto = 'ROMPI' BEGIN SELECT RAISE(ABORT, 'boom'); END")
try:
    st.salva_turno(sid, [
        {"uid": "tx1", "ruolo": "user", "contenuto": "atomico"},
        {"uid": "tx2", "ruolo": "assistant", "contenuto": "ROMPI"},
    ])
    check("la transazione fallisce", False, "nessun errore")
except sqlite3.IntegrityError:
    check("la transazione fallisce", True)
finally:
    st._conn.execute("DROP TRIGGER rifiuta_boom")
    st._conn.commit()
testi = [r["contenuto"] for r in st.messaggi(sid)]
check("il messaggio prima dell'errore e' stato annullato",
      "atomico" not in testi and "ROMPI" not in testi, str(testi))

print("\n[3] Compaction: i turni grezzi restano nello storico")
s = Session(provider=ProviderMuto(), registry=default_registry(),
            system_prompt="BASE",
            config=LoopConfig(max_iterations=2, context_limit=160,
                              keep_recent=2))
originali = [
    Message(role="user", content="obiettivo originale " + "a" * 220),
    Message(role="assistant", content="risposta uno " + "b" * 220),
    Message(role="user", content="secondo passaggio " + "c" * 220),
    Message(role="assistant", content="risposta due " + "d" * 220),
    Message(role="user", content="terzo passaggio " + "e" * 220),
    Message(role="assistant", content="risposta tre " + "f" * 220),
]
s.agent.state.messages.extend(originali)
s.agent._maybe_compact()
compactati = [m.content for m in s.agent.state.messages]
check("la compaction ha davvero compattato",
      any(c.startswith(RIEPILOGO_TAG) for c in compactati), str(compactati)[:160])
check("il registro grezzo tiene tutti i turni",
      len(s.agent.state.messaggi_grezzi) == 6,
      str(len(s.agent.state.messaggi_grezzi)))

s._salva_su_disco()
sid_comp = s._sessione_id
righe = st.messaggi(sid_comp)
testi = [r["contenuto"] for r in righe]
check("tutti i messaggi originali sono nel DB", len(righe) == 6, str(len(righe)))
check("il primo turno e' leggibile",
      any("obiettivo originale" in t for t in testi), str(testi)[:200])
check("i turni fusi dal riepilogo sono ancora leggibili",
      all(any(originale.content == t for t in testi) for originale in originali),
      str(testi)[:300])
check("il riepilogo sintetico non finisce nello storico",
      all(not t.startswith(RIEPILOGO_TAG) for t in testi), str(testi)[:200])

print("\n[4] Riaprendo la chat si legge la cronologia completa")
s2 = Session(provider=ProviderMuto(), registry=default_registry(),
             system_prompt="BASE", config=LoopConfig(max_iterations=2))
check("la sessione compattata si riapre", s2.carica_sessione(sid_comp))
visibili = [m for m in s2.agent.state.messages
            if m.role in ("user", "assistant")]
check("reloaded: ci sono tutti i sei turni", len(visibili) == 6,
      str(len(visibili)))
check("reloaded: c'e' il primo obiettivo",
      any("obiettivo originale" in m.content for m in visibili))

# Un nuovo messaggio dopo la compaction si aggiunge senza toccare i sei.
s.agent.state.messages.append(Message(role="user", content="messaggio dopo"))
s._salva_su_disco()
finali = st.messaggi(sid_comp)
check("dopo la compaction i nuovi messaggi si accodano",
      len(finali) == 7 and finali[-1]["contenuto"] == "messaggio dopo",
      f"{len(finali)} / {finali[-1]['contenuto'] if finali else ''}")

# Riaprire e continuare non deve reinserire i sei turni gia' presenti: il
# ripristino deve conservare gli uid letti dal DB, non inventarne di nuovi.
s2.agent.state.messages.append(Message(role="user", content="dopo il reload"))
s2._salva_su_disco()
dopo_reload = st.messaggi(sid_comp)
check("riaprire e salvare non duplica la cronologia",
      len(dopo_reload) == 8, str(len(dopo_reload)))
check("il nuovo messaggio del reload c'e' una volta sola",
      [r["contenuto"] for r in dopo_reload].count("dopo il reload") == 1,
      str([r["contenuto"] for r in dopo_reload]))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
