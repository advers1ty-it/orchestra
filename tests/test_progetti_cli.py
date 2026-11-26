"""Il progetto attivo nella CLI: stato e nota devono funzionare.

Il difetto: il nome del progetto vive in un `threading.local` che la UI
imposta nel thread del turno. La CLI costruisce l'agente e chiama i tool
nello stesso thread, ma nessuno impostava quel nome: `progetti` diceva
"nessun progetto attivo" e `nota` si rifiutava, proprio mentre i file
venivano scritti dentro un progetto registrato.

Qui si coprono i tre pezzi:

1. la cartella corrente viene risolta nel progetto registrato che la
   contiene (vince il piu' profondo);
2. `_build_agent` imposta nome, root e prompt del progetto;
3. il tool `progetti` funziona anche se il thread ha solo la root, senza
   il nome (thread che non passano dalla UI).

Niente rete: il provider e' finto e nessun turno parte.
"""

from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="orchestra_progetti_cli_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)
os.environ["ORCHESTRA_ROOT"] = os.path.join(_TMP, "radice")

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

from orchestra import cli                                  # noqa: E402
from orchestra import progetti as pr                       # noqa: E402
from orchestra.tools.progetti import tool_progetti          # noqa: E402

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


def chiama(**kwargs) -> str:
    return tool_progetti().handler(**kwargs)


def volatile_di(agente) -> str:
    return next((m.content for m in agente.state.messages
                 if m.role == "system" and m.name == "__contesto__"), "")


P = os.path.join(_TMP, "lavori", "sito-ristorante")
DENTRO = os.path.join(P, "src", "pagine")
FUORI = os.path.join(_TMP, "altrove")
for percorso in (DENTRO, FUORI):
    os.makedirs(percorso, exist_ok=True)

pr.registra("Sito Ristorante", P,
            note="Cliente: Trattoria da Gino.",
            alias="restaurant site")

print("\n[1] Dalla cartella al progetto registrato")

nome, percorso = pr.per_percorso(DENTRO)
check("una sottocartella trova il progetto", nome == "Sito Ristorante",
      f"{nome!r}, {percorso!r}")
check("e restituisce la radice giusta",
      os.path.normcase(os.path.abspath(percorso)) ==
      os.path.normcase(os.path.abspath(P)), percorso)
check("fuori da ogni progetto non si inventa niente",
      pr.per_percorso(FUORI) == ("", ""), str(pr.per_percorso(FUORI)))

# Un progetto annidato vince sul genitore.
FIGLIO = os.path.join(P, "moduli", "checkout")
os.makedirs(FIGLIO, exist_ok=True)
pr.registra("Checkout", FIGLIO, note="")
profondo, _ = pr.per_percorso(os.path.join(FIGLIO, "src"))
check("vince il progetto piu' profondo", profondo == "Checkout", profondo)

print("\n[2] La CLI imposta progetto, root e prompt")

cwd = os.getcwd()
try:
    cli.build_provider = lambda *a, **k: ProviderFinto()
    os.chdir(DENTRO)
    agente = cli._build_agent({"ORCHESTRA_PROVIDER": "finto",
                               "ORCHESTRA_MODEL": "finto-1"})
    check("l'agente conosce il progetto",
          agente.progetto == "Sito Ristorante", agente.progetto)
    check("la root del thread e' quella del progetto",
          os.path.normcase(os.path.abspath(pr._root_sessione())) ==
          os.path.normcase(os.path.abspath(P)), pr._root_sessione())
    check("il nome e' nel thread", pr._root_progetto() == "Sito Ristorante",
          pr._root_progetto())
    volatile = volatile_di(agente)
    check("il prompt porta cartella e nota",
          "Cartella del progetto:" in volatile
          and "Trattoria da Gino" in volatile, volatile[:400])

    stato = chiama(azione="stato")
    check("stato vede il progetto attivo",
          "Progetto attivo: Sito Ristorante" in stato, stato[:300])
    esito = chiama(azione="nota", testo="Cliente: Gino. Consegna: lunedi'.")
    check("la nota si scrive dalla CLI", "aggiornata" in esito, esito)
    check("ed e' quella salvata",
          "Consegna: lunedi'." in (pr.per_nome("Sito Ristorante").get("note")
                                   or ""), str(pr.per_nome("Sito Ristorante")))

    print("\n[3] Fuori da un progetto la CLI non ne inventa uno")

    os.chdir(FUORI)
    senza = cli._build_agent({"ORCHESTRA_PROVIDER": "finto",
                              "ORCHESTRA_MODEL": "finto-1"})
    check("nessun progetto attivo", senza.progetto == "", senza.progetto)
    check("il tool lo dice", "Nessun progetto attivo" in chiama(azione="stato"))
finally:
    os.chdir(cwd)

print("\n[4] Il tool funziona anche col solo percorso nel thread")

# Un thread che imposta la root ma non il nome: e' quello che faceva la
# CLI prima di questa correzione.
try:
    from orchestra import progetti as _pr_mod
    _pr_mod._LOCALE.root = P
    _pr_mod._LOCALE.nome = ""
    check("il nome si ricava dalla root",
          _pr_mod.progetto_attivo() == "Sito Ristorante",
          _pr_mod.progetto_attivo())
    check("stato funziona lo stesso",
          "Progetto attivo: Sito Ristorante" in chiama(azione="stato"))
    check("e la nota pure",
          "aggiornata" in chiama(azione="nota", testo="Cliente: Gino."))
finally:
    _pr_mod._LOCALE.root = ""
    _pr_mod._LOCALE.nome = ""

print(f"\n{len(PASS)} passati, {len(FAIL)} falliti")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
    sys.exit(1)
