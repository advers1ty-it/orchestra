"""La ricerca web: un motore alla volta, non tutti insieme.

Il difetto segnalato dagli utenti: `web_cerca` rispondeva «Nessun
risultato» quasi sempre. Non era la query. `DDGS().text()` senza
`backend` usa il default `auto`, che interroga *tutti* i motori in
parallelo: il burst fa scattare i blocchi anti-bot (DuckDuckGo 202,
Brave 429, Mojeek 403) e il metasearch torna vuoto.

Qui si verifica il comportamento nuovo, senza rete: i motori sono finti.
Un motore che risponde 202 non si distingue da uno che non ha trovato
niente, e chiedere a un test di aspettare che un motore vero si sblocchi
è un test che fallisce per il motivo sbagliato.
"""

from __future__ import annotations

import os
import sys
import types

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

from orchestra.tools import web as web_mod  # noqa: E402
from orchestra.tools.web import tool_web_cerca  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# I motori finti: `comportamento` dice cosa fa ognuno, per nome.
chiamate: list[str] = []
comportamento: dict[str, object] = {}


class _FintoDDGS:
    def __init__(self, timeout=None, **_):
        self.timeout = timeout

    def text(self, q, max_results=10, backend="auto"):
        chiamate.append(backend)
        esito = comportamento.get(backend)
        if isinstance(esito, Exception):
            raise esito
        return list(esito or [])


class _DDGSException(Exception):
    """Il nome che `ddgs` usa: «No results found.»"""


RISULTATO = {"title": "Titolo di prova", "href": "https://example.com/a",
             "body": "Un estratto utile."}

# Il modulo finto al posto di quello vero: il handler importa `ddgs`
# dentro di se', quindi si sostituisce in `sys.modules`.
vero = sys.modules.get("ddgs")
finto = types.ModuleType("ddgs")
finto.DDGS = _FintoDDGS
sys.modules["ddgs"] = finto

# Le pause sono per i motori veri: in un test sono solo secondi buttati.
pausa_vera = web_mod.PAUSA_FRA_MOTORI
pausa_giro_vera = web_mod.PAUSA_SECONDO_GIRO
web_mod.PAUSA_FRA_MOTORI = 0
web_mod.PAUSA_SECONDO_GIRO = 0

try:
    print("\n[1] Motore bloccato, si passa al successivo")
    chiamate.clear()
    comportamento.clear()
    comportamento["duckduckgo"] = _DDGSException("No results found.")
    comportamento["yahoo"] = [RISULTATO]
    esito = tool_web_cerca().handler(query="prova", limite=3)
    check("DuckDuckGo e' stato chiesto per primo", chiamate[:1] == ["duckduckgo"],
          str(chiamate))
    check("non si e' fermato al primo motore", len(chiamate) >= 2, str(chiamate))
    check("il ripiego ha dato i risultati", "Titolo di prova" in esito, esito[:200])
    check("l'URL c'e'", "https://example.com/a" in esito, esito[:200])
    check("il testo e' nel recinto non fidato",
          "INIZIO CONTENUTO NON FIDATO" in esito, esito[:200])
    check("dopo il successo non si chiede altro",
          chiamate == ["duckduckgo", "yahoo"], str(chiamate))

    print("\n[2] Nessuno risponde: si dice quali motori, non solo «niente»")
    chiamate.clear()
    comportamento.clear()
    for motore in web_mod.MOTORI_RICERCA:
        comportamento[motore] = _DDGSException("No results found.")
    esito = tool_web_cerca().handler(query="query sfortunata")
    check("ha fatto i due giri previsti",
          len(chiamate) == web_mod.GIRI_RICERCA * len(web_mod.MOTORI_RICERCA),
          str(chiamate))
    check("nessun motore e' stato chiesto piu' di due volte",
          max(chiamate.count(m) for m in chiamate) <= web_mod.GIRI_RICERCA,
          str(chiamate))
    check("«auto» non viene mai usato", "auto" not in chiamate, str(chiamate))
    check("il messaggio nomina i motori provati", "duckduckgo" in esito, esito[:300])
    check("il messaggio dice che puo' essere un blocco",
          "blocco" in esito.lower(), esito[:300])
    check("indica la via d'uscita senza motore", "web_leggi" in esito, esito[:300])

    print("\n[3] Il motore che ha funzionato riparte per primo")
    chiamate.clear()
    comportamento.clear()
    comportamento["yahoo"] = [RISULTATO]
    tool_web_cerca().handler(query="seconda")
    check("yahoo e' il primo della seconda ricerca", chiamate[:1] == ["yahoo"],
          str(chiamate))

    print("\n[4] Un motore che torna vuoto non ferma il giro")
    chiamate.clear()
    comportamento.clear()
    web_mod._motore_buono = ""
    comportamento["duckduckgo"] = []
    comportamento["yahoo"] = []
    comportamento["brave"] = [RISULTATO]
    esito = tool_web_cerca().handler(query="terza")
    check("il vuoto non e' un successo", chiamate[:3] == ["duckduckgo", "yahoo",
                                                         "brave"], str(chiamate))
    check("il terzo motore ha dato i risultati", "Titolo di prova" in esito,
          esito[:200])

    print("\n[5] Un vuoto passeggero si recupera al secondo giro")
    chiamate.clear()
    comportamento.clear()
    web_mod._motore_buono = ""
    # Yahoo: vuoto al primo passaggio, risultati al secondo. E' quello
    # che si vede dal vero quando il motore risponde 200 con la pagina
    # sbagliata: la stessa query, poco dopo, funziona.
    sequenza = {"yahoo": [[], [RISULTATO]]}

    class _UnaVoltaSola(_FintoDDGS):
        def text(self, q, max_results=10, backend="auto"):
            chiamate.append(backend)
            coda = sequenza.get(backend)
            return list(coda.pop(0)) if coda else []

    finto.DDGS = _UnaVoltaSola
    esito = tool_web_cerca().handler(query="quarta")
    finto.DDGS = _FintoDDGS
    check("il secondo giro ha trovato i risultati", "Titolo di prova" in esito,
          esito[:200])
    check("non ha insistito oltre i due giri",
          max(chiamate.count(m) for m in chiamate) == 2, str(chiamate))
finally:
    web_mod.PAUSA_FRA_MOTORI = pausa_vera
    web_mod.PAUSA_SECONDO_GIRO = pausa_giro_vera
    web_mod._motore_buono = ""
    if vero is None:
        sys.modules.pop("ddgs", None)
    else:
        sys.modules["ddgs"] = vero


print("\n[6] Il sorgente non chiama piu' `text()` senza backend")
sorgente = open(os.path.join(RADICE, "orchestra", "tools", "web.py"),
                encoding="utf-8").read()
check("nessuna chiamata senza motore",
      "DDGS().text(" not in sorgente, "trovata `DDGS().text(`")
check("il backend e' esplicito", "backend=motore" in sorgente)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
