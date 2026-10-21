"""La memoria che impara da sola.

I test qui coprono il pezzo che mancava: la conversazione che diventa
memoria senza che l'agente se ne ricordi.

Coprono tre cose, e sono tre difetti diversi:

1. L'estrazione viene DAVERO chiamata a fine turno. Prima non lo era:
   `estrai_fatti` e `applica_fatti` esistevano in `memoria.py` e nessuno
   le chiamava — la memoria era passiva, e ricordava solo quello che
   l'agente registrava a mano.

2. Il progetto viaggia con il fatto. Un archivio condiviso che non
   distingue "questo fatti è del sito ristorante" da "questo è della
   app parrucchieri" non è consultabile per progetto.

3. La ricerca usa l'indice e filtra per progetto. Il tool `memoria`
   filtrava in Python con `in` su tutti i fatti: l'infrastruttura FTS5
   che c'era nel pacchetto non veniva mai interrogata.
"""

from __future__ import annotations

import os
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Il DB su una cartella di test: la memoria vera dell'utente non si
# tocca. Deve stare PRIMA di qualsiasi import di orchestra, perché
# `memoria()` e `indice_memoria()` sono singleton.
os.environ["ORCHESTRA_HOME"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_dati_test")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

from orchestra import LLMResponse  # noqa: E402
from orchestra.memoria import (  # noqa: E402
    _pulizia_riga, applica_fatti, estrai_fatti,
)
from orchestra.session import Session  # noqa: E402
from orchestra.types import Message  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


# --------------------------------------------------------------------------
# 1. La pulizia della riga
# --------------------------------------------------------------------------

def test_pulizia():
    print("\n== pulizia della riga ==")
    # L'ordine dei marcatori conta: la fonte e la data stanno in coda,
    # il progetto in mezzo. Una pulizia che fa una passata sola lascia
    # metà della marcatura dentro il testo del fatto.
    corpo = "Il gestore si chiama Mario  _sessione:sito_  [progetto:sito-ristorante]  <!-- 2026-01-01 -->"
    testo, fonte, progetto = _pulizia_riga(corpo)
    check("il testo resta pulito", testo == "Il gestore si chiama Mario",
          f"tornato: {testo!r}")
    check("la fonte si legge", fonte == "sessione:sito", f"tornato: {fonte!r}")
    check("il progetto si legge", progetto == "sito-ristorante",
          f"tornato: {progetto!r}")

    # Il caso senza progetto non deve rompere niente.
    testo2, fonte2, progetto2 = _pulizia_riga("Solo un fatto  _agente_  <!-- 2026-01-01 -->")
    check("senza progetto il testo resta pulito", testo2 == "Solo un fatto",
          f"tornato: {testo2!r}")
    check("senza progetto il progetto e' vuoto", progetto2 == "",
          f"tornato: {progetto2!r}")

    # Un fatto scritto a mano, senza marcature, resta se stesso.
    testo3, _f, _p = _pulizia_riga("Un fatto a mano")
    check("un fatto senza marcature resta se stesso", testo3 == "Un fatto a mano",
          f"tornato: {testo3!r}")


# --------------------------------------------------------------------------
# 2. L'estrazione esiste e funziona
# --------------------------------------------------------------------------

class ProviderFinto:
    """Provider che risponde con una lista di fatti.

    Segue il contratto vero: `chat` riceve `Message`, non dict. Un
    provider finto che accetta dict nasconderebbe proprio il bug che
    questo file verifica.
    """

    name = "finto"
    model = "finto-1"

    def __init__(self, risposta=""):
        self.risposta = risposta
        self.chiamate = 0
        self.ultime_messaggi = []

    def chat(self, messages, tools=None, **kw):
        self.chiamate += 1
        self.ultime_messaggi = messages
        return LLMResponse(content=self.risposta)


def test_estrazione():
    print("\n== estrazione ==")
    p = ProviderFinto("Il gestore del ristorante si chiama Mario\n"
                       "Il sito usa WordPress con il tema Astra\n")
    fatti = estrai_fatti("parliamo del ristorante", p)
    check("estrae i fatti", len(fatti) == 2, f"tornati: {fatti}")
    check("i messaggi sono Message, non dict",
          all(isinstance(m, Message) for m in p.ultime_messaggi),
          f"tipo: {[type(m).__name__ for m in p.ultime_messaggi]}")

    # "NIENTE" significa niente da ricordare: non e' un errore.
    p2 = ProviderFinto("NIENTE")
    check("'NIENTE' vuol dire nessun fatto", estrai_fatti("niente", p2) == [])

    # Un provider che muore non deve far fallire il turno.
    class ProviderMorto:
        name = "morto"
        model = "x"

        def chat(self, *a, **k):
            raise RuntimeError("provider morto")

    check("un provider morto non alza", estrai_fatti("x", ProviderMorto()) == [])


# --------------------------------------------------------------------------
# 3. Il progetto viaggia col fatto
# --------------------------------------------------------------------------

def test_progetto_in_memoria():
    print("\n== il progetto viaggia col fatto ==")
    from orchestra import memoria as mem

    m = mem.memoria()
    # Fatti di prova, con un progetto diverso per ciascuno.
    m.aggiungi("Il ristorante si chiama Da Mario", origine="test",
               progetto="sito-ristorante")
    m.aggiungi("L'app ha tre tipi di appuntamento", origine="test",
               progetto="app-parrucchieri")
    m.aggiungi("Un fatto senza progetto", origine="test")

    solo_ristorante = m.fatti_per_progetto("sito-ristorante")
    check("il filtro per progetto funziona",
          any("Da Mario" in f for f in solo_ristorante),
          f"tornati: {solo_ristorante}")
    check("il filtro esclude gli altri progetti",
          not any("appuntamento" in f for f in solo_ristorante),
          f"tornati: {solo_ristorante}")

    progetti = m.progetti()
    check("i progetti sono visibili",
          "sito-ristorante" in progetti and "app-parrucchieri" in progetti,
          f"tornati: {progetti}")

    # Il progetto vuoto = tutti i fatti. E' il modo normale di chiedere.
    check("progetto vuoto = tutti i fatti",
          len(m.fatti_per_progetto("")) == len(m.fatti()))

    # Il fatto deve essere leggibile pulito: la marcatura non deve
    # finire nel testo, o il modello la legge come conoscenza.
    tutti = m.fatti()
    sporchi = [f for f in tutti if "progetto:" in f or "_test_" in f
               or "<!--" in f]
    check("nessun fatto porta la marcatura dentro", not sporchi,
          f"sporchi: {sporchi}")


# --------------------------------------------------------------------------
# 4. La ricerca usa l'indice e filtra per progetto
# --------------------------------------------------------------------------

def test_ricerca_per_progetto():
    print("\n== ricerca per progetto ==")
    from orchestra.tools.memoria import tool_memoria

    tool = tool_memoria()
    ris = tool.handler(azione="cerca", query="Da Mario", progetto="sito-ristorante")
    check("la ricerca col progetto trova il fatto",
          "Da Mario" in ris, f"risposta: {ris!r}")

    # Il progetto sbagliato non deve restituire il fatto. Il controllo
    # non puo' essere "la stringa non compare nella risposta": il
    # messaggio di "non trovato" la contiene ("Nessun fatto trovato
    # per: Da Mario"), e il test passerebbe solo per caso. Si guarda
    # se la risposta e' un elenco di fatti oppure un avviso, e in ogni
    # caso il fatto non deve esserci come voce.
    ris2 = tool.handler(azione="cerca", query="Da Mario", progetto="app-parrucchieri")
    voci = [v for v in ris2.splitlines() if v.strip().startswith("- ")]
    check("la ricerca col progetto sbagliato non trova",
          not any("Da Mario" in v for v in voci), f"risposta: {ris2!r}")

    # Il tool `aggiungi` accetta il progetto.
    tool.handler(azione="aggiungi", fatto="Nuovo fatto di prova del progetto",
                 progetto="progetto-di-prova")
    ris3 = tool.handler(azione="cerca", query="Nuovo fatto di prova",
                        progetto="progetto-di-prova")
    check("il tool aggiunge col progetto", "Nuovo fatto di prova" in ris3,
          f"risposta: {ris3!r}")


# --------------------------------------------------------------------------
# 5. Il turno ricorda da solo
# --------------------------------------------------------------------------

def test_il_turno_ricorda():
    print("\n== il turno ricorda da solo ==")
    provider = ProviderFinto("Il locale apre alle 19 e chiude di lunedì\n")

    class AgenteFinto:
        """Un agente finto che ha solo i messaggi che gli servono."""

        def __init__(self, provider):
            self.provider = provider
            self.state = type("S", (), {})()
            self.state.messages = [
                Message(role="system", content="prompt"),
                Message(role="user", content="Quando apre il ristorante?"),
                Message(role="assistant", content="Apre alle 19."),
            ]

    session = Session.__new__(Session)
    session.agent = AgenteFinto(provider)
    session.progetto = "sito-ristorante"
    # `Session.__new__` salta `__init__`: il lock non esiste, e
    # `imposta_progetto` lo prende. Senza questo il test muore con
    # AttributeError su un attributo che nella vita vera c'e' — e
    # sembra un difetto del codice invece che del test.
    session._lock = threading.RLock()

    # Il lavoro avviene in un thread: si aspetta che finisca, altrimenti
    # il test guarderebbe il momento sbagliato.
    session._ricorda_turno()
    _aspetta(lambda: provider.chiamate > 0, "il provider non e' stato chiamato")

    check("il provider è stato interrogato", provider.chiamate == 1,
          f"chiamate={provider.chiamate}")

    from orchestra import memoria as mem
    _aspetta(
        lambda: any("19" in f
                    for f in mem.memoria().fatti_per_progetto("sito-ristorante")),
        "il fatto non e' finito nel progetto")
    fatti = mem.memoria().fatti_per_progetto("sito-ristorante")
    check("il fatto è finito nel progetto giusto",
          any("19" in f for f in fatti), f"fatti: {fatti}")

    # Un turno vuoto non deve interrogare il provider: una chiamata
    # sprecata per niente è una chiamata che il modello non fa.
    provider.chiamate = 0
    session.agent.state.messages = [Message(role="system", content="prompt")]
    session._ricorda_turno()
    time.sleep(0.2)
    check("un turno vuoto non chiama il provider", provider.chiamate == 0,
          f"chiamate={provider.chiamate}")


def _aspetta(cond, messaggio, timeout=5.0):
    """Aspetta una condizione, con un timeout.

    Il thread della memoria e' asincrono: senza questo, il test
    guarderebbe il momento sbagliato e fallirebbe a intermittenza —
    che e' il modo peggiore di fallire.
    """
    fine = time.time() + timeout
    while time.time() < fine:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(0.05)
    return False


if __name__ == "__main__":
    test_pulizia()
    test_estrazione()
    test_progetto_in_memoria()
    test_ricerca_per_progetto()
    test_il_turno_ricorda()

    print(f"\n{'='*60}")
    print(f"  {len(PASS)} passati, {len(FAIL)} falliti")
    if FAIL:
        for f in FAIL:
            print(f"  FALLITO: {f}")
        sys.exit(1)
    print("  Tutti verdi.")
