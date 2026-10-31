"""I bot: identità persistenti che lavorano ognuna per conto suo.

CHE COSA E' UN BOT, E CHE COSA NON E'

Un bot e' un'identita' salvata: un nome, un modello, una persona, un
progetto di partenza, una conversazione che sopravvive. Non e' un
processo separato e non e' una sandbox.

Questo va detto subito perche' la parola "bot" promette due cose che
qui non ci sono. La prima e' l'isolamento: i bot girano nello stesso
processo, con le stesse chiavi e gli stessi permessi — condividono
tutto tranne la conversazione, il modello e la cartella di lavoro. Se
serve un confine vero, quello e' un altro lavoro (processi separati),
non una riga in questa tabella. La seconda e' l'autonomia: un bot qui
non si sveglia da solo. Riceve un turno quando qualcuno glielo manda,
e quel qualcuno e' l'utente o un altro bot.

PERCHE' ESISTE

Chi lavora su piu' cose insieme lo fa gia' con i progetti: la cartella
cambia, e i file stanno separati. Ma l'AGENTE resta uno: lo stesso
modello, lo stesso prompt, la stessa conversazione che si allunga. Un
progetto che chiede un modello veloce e uno che ne chiede uno che
ragiona si contendono la stessa sessione, e chi vince e' l'ultimo che
ha scritto. Il bot e' il pezzo che mancava: la stessa separazione dei
progetti, applicata all'agente invece che alla cartella.

L'ALLOWLIST, E PERCHE' VUOTA SIGNIFICA NIENTE

`parla_con` e' l'elenco dei bot a cui questo bot puo' chiedere
qualcosa. Il default e' NIENTE, non "tutti": due bot che si parlano
senza che nessuno l'abbia deciso sono due bot che possono darsi il
cambio per sempre, e la prima volta che accade la fattura arriva
prima della spiegazione. L'utente che vuole la conversazione la
accende nominando i bot; chi non tocca niente non puo' avere un ciclo
per sbaglio.

Un bot non parla mai con se stesso, e questo non si configura.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from typing import Any

from . import policy as policy_mod
from .dati import percorso as percorso_dati

_DB = "bots.db"

_LOCK = threading.RLock()

# Il nome e' quello che l'utente scrive in chat e nei menu: corto, senza
# virgole (la lista della allowlist e' separata da virgole) e senza
# spazi doppi. Un nome vuoto non e' un nome.
MAX_NOME = 40
MAX_PERSONA = 8000

# I profili di tool che un bot puo' dichiarare. Sono gli stessi di
# `tools/__init__.py`, e la lista e' ripetuta di proposito: importare
# `_PROFILI` (privato) per validare significherebbe che rinominare un
# profilo dentro i tool rompe il salvataggio dei bot senza che nessuno
# se ne accorga.
PROFILI_VALIDI = ("", "base", "ricerca", "skill", "pieno")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT    NOT NULL,
    provider    TEXT    NOT NULL DEFAULT '',
    modello     TEXT    NOT NULL DEFAULT '',
    persona     TEXT    NOT NULL DEFAULT '',
    progetto    TEXT    NOT NULL DEFAULT '',
    profilo     TEXT    NOT NULL DEFAULT '',
    parla_con   TEXT    NOT NULL DEFAULT '',
    -- Le quattro liste della policy, in JSON. Sta nella riga del bot e
    -- non in una tabella a parte: una policy senza il suo bot non ha
    -- significato, e si legge sempre insieme alla configurazione.
    policy      TEXT    NOT NULL DEFAULT '{}',
    creato      REAL    NOT NULL,
    aggiornato  REAL    NOT NULL
);

-- Il nome identifica un bot: due bot con lo stesso nome non si
-- potrebbero distinguere in un menu ne' in `bot_chiedi`. La ricerca e'
-- case-insensitive, come per i progetti: "Grok" e "grok" sono la stessa
-- cosa per chi scrive.
CREATE UNIQUE INDEX IF NOT EXISTS idx_bots_nome ON bots (LOWER(nome));
"""


def percorso_db() -> str:
    return percorso_dati(_DB)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(percorso_db(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # I database creati prima della policy non hanno la colonna, e
    # `CREATE TABLE IF NOT EXISTS` non li tocca. La migrazione e'
    # idempotente: dopo la prima volta l'ALTER fallisce e si ignora.
    try:
        conn.execute("ALTER TABLE bots ADD COLUMN policy TEXT NOT NULL "
                     "DEFAULT '{}'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn


def _norm_nome(nome: str) -> str:
    """Il nome come lo si salva: spazi normalizzati, virgole fuori.

    La virgola non e' un vezzo: `parla_con` e' una lista separata da
    virgole, e un nome che contiene una virgola si spezza in due nomi
    che non esistono. Meglio toglierla qui che scoprirlo dopo.
    """
    n = re.sub(r"\s+", " ", (nome or "").replace(",", " ")).strip()
    return n[:MAX_NOME].strip()


def _norm_lista(valore: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(valore, (list, tuple)):
        parti = [str(v) for v in valore]
    else:
        parti = str(valore or "").split(",")
    out: list[str] = []
    for p in parti:
        n = _norm_nome(p)
        if n and n.lower() not in [o.lower() for o in out]:
            out.append(n)
    return out


def _policy_da_riga(testo: Any) -> dict[str, list[str]]:
    """La policy salvata, o quella vuota se il JSON e' rotto.

    Un JSON rotto non deve impedire di leggere il bot: la configurazione
    resta visibile e modificabile, e la policy torna vuota. Il contrario
    — un bot che non si carica per una parentesi — e' peggio, perche'
    l'utente non ha modo di correggerlo dalla UI.
    """
    try:
        return policy_mod.normalizza(json.loads(testo or "{}"))
    except (ValueError, TypeError):
        return policy_mod.normalizza({})


def _riga(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "nome": str(r["nome"]),
        "provider": str(r["provider"] or ""),
        "modello": str(r["modello"] or ""),
        "persona": str(r["persona"] or ""),
        "progetto": str(r["progetto"] or ""),
        "profilo": str(r["profilo"] or ""),
        "parla_con": _norm_lista(str(r["parla_con"] or "")),
        "policy": _policy_da_riga(r["policy"] if "policy" in r.keys() else "{}"),
        "creato": float(r["creato"] or 0.0),
        "aggiornato": float(r["aggiornato"] or 0.0),
    }


def tutti() -> list[dict[str, Any]]:
    with _LOCK:
        conn = _db()
        try:
            righe = conn.execute(
                "SELECT * FROM bots ORDER BY LOWER(nome)").fetchall()
        finally:
            conn.close()
    return [_riga(r) for r in righe]


def nomi() -> list[str]:
    return [b["nome"] for b in tutti()]


def per_id(bot_id: int | str) -> dict[str, Any] | None:
    try:
        ident = int(bot_id)
    except (TypeError, ValueError):
        return None
    with _LOCK:
        conn = _db()
        try:
            r = conn.execute("SELECT * FROM bots WHERE id = ?",
                             (ident,)).fetchone()
        finally:
            conn.close()
    return _riga(r) if r else None


def per_nome(nome: str) -> dict[str, Any] | None:
    """Un bot dal nome, senza distinguere maiuscole.

    E' la funzione che usa `bot_chiedi`, dove il nome lo scrive un
    modello: "grok", "Grok" e "GROK" sono lo stesso bot, o il tool
    fallisce per una maiuscola e sembra rotto.
    """
    n = _norm_nome(nome)
    if not n:
        return None
    with _LOCK:
        conn = _db()
        try:
            r = conn.execute("SELECT * FROM bots WHERE LOWER(nome) = LOWER(?)",
                             (n,)).fetchone()
        finally:
            conn.close()
    return _riga(r) if r else None


def _valida_provider(provider: str) -> str:
    p = (provider or "").strip().lower()
    if not p:
        return ""
    from .providers import KNOWN_PROVIDERS

    if p not in KNOWN_PROVIDERS:
        raise ValueError(
            f"provider sconosciuto: {provider!r}. Disponibili: "
            f"{', '.join(sorted(KNOWN_PROVIDERS))}"
        )
    return p


def _valida_profilo(profilo: str) -> str:
    p = (profilo or "").strip().lower()
    if p not in PROFILI_VALIDI:
        raise ValueError(
            f"profilo sconosciuto: {profilo!r}. Usa uno di: "
            f"{', '.join(x for x in PROFILI_VALIDI if x)}"
        )
    return p


def _valida_parla_con(nomi: list[str], escludi: str = "") -> list[str]:
    """I nomi devono esistere, o l'allowlist non serve a niente.

    Un refuso in un nome e' la differenza fra "questo bot puo' chiedere
    a Grok" e "questo bot non puo' chiedere a nessuno", e le due cose
    si assomigliano troppo per lasciarle indistinguibili.
    """
    esistenti = {b["nome"].lower(): b["nome"] for b in tutti()}
    escluso = _norm_nome(escludi).lower()
    fuori: list[str] = []
    for n in nomi:
        chiave = n.lower()
        if chiave == escluso:
            raise ValueError("un bot non puo' parlare con se stesso")
        vero = esistenti.get(chiave)
        if vero is None:
            raise ValueError(f"bot inesistente: {n!r}")
        if vero not in fuori:
            fuori.append(vero)
    return fuori


def crea(nome: str, *, provider: str = "", modello: str = "",
         persona: str = "", progetto: str = "", profilo: str = "",
         parla_con: str | list[str] | None = None,
         policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Crea un bot. Il nome e' l'unica cosa obbligatoria.

    Provider e modello vuoti NON significano "nessun modello": la
    sessione del bot ereditera' quello configurato per l'applicazione.
    E' il default giusto perche' e' quello che l'utente ha gia'
    scelto in Opzioni, e un bot che nasce senza modello e non parte
    sarebbe un errore scritto a mano in una schermata di creazione.
    """
    n = _norm_nome(nome)
    if not n:
        raise ValueError("serve un nome per il bot")
    p = _valida_provider(provider)
    prof = _valida_profilo(profilo)
    pol = policy_mod.normalizza(policy)
    persona = (persona or "").strip()[:MAX_PERSONA]
    progetto = (progetto or "").strip()
    with _LOCK:
        if per_nome(n) is not None:
            raise ValueError(f"esiste gia' un bot che si chiama {n!r}")
        # Il bot non e' ancora nella tabella: un nome che punta a se
        # stesso verrebbe rifiutato come "inesistente", che e' un errore
        # vero ma dice la cosa sbagliata. Si controlla prima, e si dice
        # esattamente qual e' il problema.
        richiesti = _norm_lista(parla_con or "")
        if any(x.lower() == n.lower() for x in richiesti):
            raise ValueError("un bot non puo' parlare con se stesso")
        con = _valida_parla_con(richiesti, escludi=n) if richiesti else []
        ora = time.time()
        conn = _db()
        try:
            cur = conn.execute(
                "INSERT INTO bots (nome, provider, modello, persona,"
                " progetto, profilo, parla_con, policy, creato, aggiornato)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (n, p, (modello or "").strip(), persona, progetto, prof,
                 ", ".join(con), json.dumps(pol, ensure_ascii=False), ora,
                 ora))
            conn.commit()
            nuovo = int(cur.lastrowid)
        finally:
            conn.close()
    return per_id(nuovo) or {}


def aggiorna(bot_id: int | str, **campi: Any) -> dict[str, Any] | None:
    """Modifica i campi indicati. I campi assenti restano come sono."""
    attuale = per_id(bot_id)
    if attuale is None:
        return None
    valori: dict[str, Any] = {}
    if "nome" in campi and campi["nome"] is not None:
        n = _norm_nome(str(campi["nome"]))
        if not n:
            raise ValueError("serve un nome per il bot")
        altro = per_nome(n)
        if altro is not None and altro["id"] != attuale["id"]:
            raise ValueError(f"esiste gia' un bot che si chiama {n!r}")
        valori["nome"] = n
    if "provider" in campi and campi["provider"] is not None:
        valori["provider"] = _valida_provider(str(campi["provider"]))
    if "modello" in campi and campi["modello"] is not None:
        valori["modello"] = str(campi["modello"]).strip()
    if "persona" in campi and campi["persona"] is not None:
        valori["persona"] = str(campi["persona"]).strip()[:MAX_PERSONA]
    if "progetto" in campi and campi["progetto"] is not None:
        valori["progetto"] = str(campi["progetto"]).strip()
    if "profilo" in campi and campi["profilo"] is not None:
        valori["profilo"] = _valida_profilo(str(campi["profilo"]))
    if "parla_con" in campi and campi["parla_con"] is not None:
        nome_finale = str(valori.get("nome", attuale["nome"]))
        richiesti = _norm_lista(campi["parla_con"])
        valori["parla_con"] = ", ".join(
            _valida_parla_con(richiesti, escludi=nome_finale))
    if "policy" in campi and campi["policy"] is not None:
        valori["policy"] = json.dumps(
            policy_mod.normalizza(campi["policy"]), ensure_ascii=False)
    if not valori:
        return attuale
    valori["aggiornato"] = time.time()
    assegnazioni = ", ".join(f"{k} = ?" for k in valori)
    with _LOCK:
        conn = _db()
        try:
            conn.execute(f"UPDATE bots SET {assegnazioni} WHERE id = ?",
                         (*valori.values(), attuale["id"]))
            conn.commit()
        finally:
            conn.close()
    return per_id(attuale["id"])


def elimina(bot_id: int | str) -> bool:
    """Toglie un bot, e il suo nome dalle allowlist degli altri.

    Un nome che resta in una allowlist dopo che il bot non c'e' piu'
    e' un permesso a un fantasma: non fa danno oggi, ma rileggendo la
    configurazione domani sembra che quel bot esista ancora.
    """
    attuale = per_id(bot_id)
    if attuale is None:
        return False
    with _LOCK:
        conn = _db()
        try:
            conn.execute("DELETE FROM bots WHERE id = ?", (attuale["id"],))
            conn.commit()
            for altro in tutti():
                con = [n for n in altro["parla_con"]
                       if n.lower() != attuale["nome"].lower()]
                if len(con) != len(altro["parla_con"]):
                    conn.execute(
                        "UPDATE bots SET parla_con = ?, aggiornato = ? "
                        "WHERE id = ?",
                        (", ".join(con), time.time(), altro["id"]))
            conn.commit()
        finally:
            conn.close()
    return True
