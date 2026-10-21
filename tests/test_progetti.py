"""Test dei progetti: la cartella, la root, il riconoscimento.

Un progetto non e' un'etichetta: e' la cartella in cui l'agente
scrive, e il meccanismo che permette a un modello di lavorare su
tre progetti senza che le cose si mescolino. I test qui coprono i
tre pezzi che lo rendono vero:

1. LA CARTELLA. Il tool scrive dentro il progetto, non dentro la
   cartella di installazione.
2. IL RICONOSCIMENTO. "oggi lavoriamo al sito ristorante" cambia
   progetto; "ciao, come stai" non cambia niente.
3. LA MEMORIA. I fatti si etichettano col progetto e si rileggono
   col filtro giusto.

Il test gira in una cartella temporanea e con ORCHESTRA_HOME
separato: non deve toccare i dati veri, e non deve scrivere nel
progetto di qualcun altro.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

# La cartella dei dati di prova PRIMA di importare il pacchetto:
# i moduli leggono ORCHESTRA_HOME all'import, e un import tardivo
# scriverebbe nei dati veri.
_TMP = tempfile.mkdtemp(prefix="orchestra_progetti_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import progetti as pr   # noqa: E402


PASSATI = 0
FALLITI: list[str] = []


def check(nome: str, condizione: bool, dettaglio: str = "") -> None:
    global PASSATI
    if condizione:
        PASSATI += 1
        print(f"  OK   {nome}")
    else:
        FALLITI.append(nome)
        print(f"  FAIL {nome}" + (f" — {dettaglio}" if dettaglio else ""))


def sezione(titolo: str) -> None:
    print(f"\n== {titolo} ==")


# --------------------------------------------------------------------------
# la registrazione
# --------------------------------------------------------------------------

def test_registra() -> None:
    sezione("la registrazione")
    p1 = os.path.join(_TMP, "lavori", "sito-ristorante")
    p2 = os.path.join(_TMP, "lavori", "app-parrucchieri")
    os.makedirs(p1, exist_ok=True)
    os.makedirs(p2, exist_ok=True)

    pr.registra("Sito Ristorante", p1,
                alias="restaurant site, menu, ristorante")
    pr.registra("App Parrucchieri", p2,
                alias="hair salon app, salon, parrucchieri")
    check("il progetto si registra", pr.percorso_di("Sito Ristorante") == os.path.abspath(p1),
          str(pr.percorso_di("Sito Ristorante")))

    # Il nome non distingue maiuscole: su Windows "sito" e "Sito"
    # sono lo stesso progetto, e l'utente non deve accorgersene.
    check("il nome non distingue le maiuscole",
          pr.percorso_di("sito ristorante") == os.path.abspath(p1))

    # Registrare due volte lo stesso nome aggiorna, non duplica.
    pr.registra("Sito Ristorante", p2)
    check("registrare due volte aggiorna",
          pr.percorso_di("Sito Ristorante") == os.path.abspath(p2),
          str(pr.percorso_di("Sito Ristorante")))
    tutti = [p["nome"] for p in pr.tutti()]
    check("nessun duplicato", tutti.count("Sito Ristorante") == 1, str(tutti))
    # si rimette a posto per gli altri test. Gli alias NON vengono
    # toccati: cambiare il percorso non e' un'operazione sugli alias.
    pr.registra("Sito Ristorante", p1)
    check("cambiare il percorso non tocca gli alias",
          "restaurant site" in pr.alias_di(pr.per_nome("Sito Ristorante") or {}),
          str(pr.per_nome("Sito Ristorante")))

    check("l'elenco li contiene tutti", len(pr.tutti()) == 2, str(pr.tutti()))


# --------------------------------------------------------------------------
# il riconoscimento dell'intento
# --------------------------------------------------------------------------

def test_riconoscimento() -> None:
    sezione("il riconoscimento dell'intento")
    nome, motivo = pr.riconosci("oggi lavoriamo al sito ristorante")
    check("riconosce 'oggi lavoriamo al sito ristorante'",
          nome == "Sito Ristorante", f"tornato {nome!r} ({motivo})")

    nome, _ = pr.riconosci("passiamo al app parrucchieri")
    check("riconosce 'passiamo al app parrucchieri'",
          nome == "App Parrucchieri", f"tornato {nome!r}")

    nome, _ = pr.riconosci("voglio continuare con il parrucchieri")
    check("riconosce la parola distintiva",
          nome == "App Parrucchieri", f"tornato {nome!r}")

    nome, _ = pr.riconosci("ciao, come stai?")
    check("non riconosce una frase che non nomina progetti", nome == "", f"tornato {nome!r}")

    # IL NOME DA SOLO NON BASTA. Il progetto e' la cartella in cui
    # si scrive: spostarla e' un'azione, non un'etichetta. Serve
    # l'intenzione, e il nome da solo non la dà.
    nome, _ = pr.riconosci("il ristorante era bello")
    check("il nome da solo non sposta il progetto", nome == "",
          f"tornato {nome!r}: stai chiacchierando, non lavorando")

    nome, _ = pr.riconosci("voglio mangiare al ristorante stasera")
    check("una frase che parla del ristorante non sposta niente", nome == "",
          f"tornato {nome!r}")

    # Con l'intenzione esplicita, invece, il nome basta.
    nome, _ = pr.riconosci("oggi lavoriamo al ristorante")
    check("con l'intenzione il nome basta", nome == "Sito Ristorante",
          f"tornato {nome!r}")

    nome, motivo = pr.riconosci("lavoriamo al sito ristorante e poi al app parrucchieri")
    check("su due progetti non sceglie da solo", nome == "", f"tornato {nome!r}")
    check("e dice perche'", "parrucchieri" in motivo.lower(), motivo)

    # Una parola piu' lunga che contiene il nome NON e' un match:
    # "ristorantino" non e' "ristorante".
    nome, _ = pr.riconosci("sto scrivendo il ristorantino")
    check("non abbina dentro una parola piu' lunga", nome == "", f"tornato {nome!r}")

    # -- inglese --
    # L'inglese funziona grazie agli ALIAS: un progetto chiamato
    # "Sito Ristorante" non contiene la parola "restaurant", e nessun
    # algoritmo puo' tirare a indovinare che sono la stessa cosa.
    nome, _ = pr.riconosci("today let's work on the restaurant site")
    check("riconosce l'inglese con l'apostrofo",
          nome == "Sito Ristorante", f"tornato {nome!r}")

    nome, _ = pr.riconosci("let's work on the hair salon app")
    check("riconosce l'inglese con il nome distinto",
          nome == "App Parrucchieri", f"tornato {nome!r}")

    nome, _ = pr.riconosci("switch to the restaurant site")
    check("riconosce 'switch to'", nome == "Sito Ristorante", f"tornato {nome!r}")

    nome, _ = pr.riconosci("the restaurant was lovely")
    check("in inglese il nome da solo non sposta niente", nome == "",
          f"tornato {nome!r}")

    # E l'alias da solo, senza intenzione, non sposta niente: stessa
    # regola del nome.
    nome, _ = pr.riconosci("the menu looks great")
    check("un alias senza intenzione non sposta niente", nome == "",
          f"tornato {nome!r}")

    # Gli alias si leggono e si scrivono.
    alias = pr.alias_di(pr.per_nome("Sito Ristorante") or {})
    check("gli alias sono leggibili", "restaurant site" in alias, str(alias))
    check("gli alias sono senza duplicati", len(alias) == len(set(alias)),
          str(alias))

    # La stringa vuota CANCELLA gli alias. E' una distinzione che
    # conta: None vuol dire "non toccare", "" vuol dire "azzera".
    pr.registra("Sito Ristorante", pr.percorso_di("Sito Ristorante"),
                alias="")
    check("la stringa vuota cancella gli alias",
          not pr.alias_di(pr.per_nome("Sito Ristorante") or {}),
          str(pr.per_nome("Sito Ristorante")))
    # e si rimettono, per gli altri test
    pr.registra("Sito Ristorante", pr.percorso_di("Sito Ristorante"),
                alias="restaurant site, menu, ristorante")


# --------------------------------------------------------------------------
# la root per thread
# --------------------------------------------------------------------------

def test_root() -> None:
    sezione("la root per thread")
    from orchestra.tools import _guard

    p1 = os.path.join(_TMP, "lavori", "sito-ristorante")
    os.makedirs(p1, exist_ok=True)

    # Senza progetto la root e' quella globale.
    pr._set_root_sessione("", "")
    root_base = str(_guard._root())

    pr._set_root_sessione(p1, "Sito Ristorante")
    check("la root segue il progetto", str(_guard._root()).lower() == os.path.abspath(p1).lower(),
          f"{_guard._root()} invece di {p1}")
    check("il nome del progetto e' leggibile",
          pr._root_progetto() == "Sito Ristorante", pr._root_progetto())

    # Il path DENTRO la root non e' "fuori": e' il posto di lavoro.
    dentro = os.path.join(p1, "menu.txt")
    check("un path dentro la root non e' fuori", _guard._dentro_root(dentro))
    check("un path davvero fuori e' fuori",
          not _guard._dentro_root(os.path.join(_TMP, "altro", "x.txt")))

    # E con la root globale, un path dentro la root globale non e' fuori.
    pr._set_root_sessione("", "")
    check("la root torna a quella globale quando non c'e' progetto",
          str(_guard._root()) == root_base, f"{_guard._root()} invece di {root_base}")


# --------------------------------------------------------------------------
# i file toccati
# --------------------------------------------------------------------------

def test_file_toccati() -> None:
    sezione("i file toccati")
    pr.registra_file("Sito Ristorante", "index.html", "creato")
    pr.registra_file("Sito Ristorante", "style.css", "creato")
    pr.registra_file("App Parrucchieri", "turni.py", "creato")

    solo_ristorante = pr.file_toccati("Sito Ristorante")
    nomi = sorted(f["path"] for f in solo_ristorante)
    check("i file del progetto sono i suoi",
          nomi == ["index.html", "style.css"], str(nomi))

    tutti = pr.file_toccati("")
    check("senza filtro vengono tutti", len(tutti) >= 3, str(len(tutti)))

    azioni = {f["path"]: f["azione"] for f in pr.file_toccati("Sito Ristorante")}
    check("l'azione viene registrata", azioni.get("index.html") == "creato", str(azioni))


# --------------------------------------------------------------------------
# il tool scrive nel progetto
# --------------------------------------------------------------------------

def test_tool_scrive_nel_progetto() -> None:
    sezione("il tool scrive nel progetto")
    from orchestra.tools.write_file import tool_write_file

    p1 = os.path.join(_TMP, "lavori", "sito-ristorante")
    os.makedirs(p1, exist_ok=True)
    pr._set_root_sessione(p1, "Sito Ristorante")

    out = tool_write_file().handler("menu.txt", "Pasta 12 euro")
    check("il tool scrive", "creato" in out, out)
    check("il file e' dentro il progetto",
          os.path.exists(os.path.join(p1, "menu.txt")))

    # Il file toccato e' registrato col progetto giusto: e' quello che
    # la lista "i file di questo progetto" mostra.
    file = pr.file_toccati("Sito Ristorante")
    check("il file toccato e' registrato col progetto",
          any(f["path"].endswith("menu.txt") for f in file), str(file))

    pr._set_root_sessione("", "")


# --------------------------------------------------------------------------
# la memoria col progetto
# --------------------------------------------------------------------------

def test_memoria_col_progetto() -> None:
    sezione("la memoria col progetto")
    from orchestra.memoria import memoria

    m = memoria()
    m.aggiungi("Il gestore si chiama Mario", origine="test", importante=False,
               progetto="Sito Ristorante")
    m.aggiungi("I turni durano 30 minuti", origine="test", importante=False,
               progetto="App Parrucchieri")
    m.aggiungi("Preferisco le paste corte", origine="test", importante=False,
               progetto="")

    fatti_ristorante = m.fatti_per_progetto("Sito Ristorante")
    check("il filtro trova il fatto del progetto",
          any("Mario" in f for f in fatti_ristorante), str(fatti_ristorante))
    check("il filtro esclude gli altri progetti",
          not any("turni" in f for f in fatti_ristorante), str(fatti_ristorante))

    tutti = m.fatti_per_progetto("")
    check("senza filtro vengono tutti", len(tutti) >= 3, str(len(tutti)))


def test_il_cambio_e_annunciato() -> None:
    sezione("il cambio di progetto e' annunciato")
    import threading
    from orchestra.session import Session

    p1 = os.path.join(_TMP, "lavori", "sito-ristorante")
    os.makedirs(p1, exist_ok=True)

    eventi = []

    class BridgeFinto:
        def emit(self, kind, data):
            eventi.append((kind, data))

    class AgenteFinto:
        progetto = ""
        def _aggiorna_prompt(self):
            pass

    session = Session.__new__(Session)
    session._lock = threading.RLock()
    session.progetto = ""
    session.agent = AgenteFinto()
    session.bridge = BridgeFinto()

    nome = session._riconosci_progetto("oggi lavoriamo al sito ristorante")
    check("il progetto e' stato riconosciuto", nome == "Sito Ristorante",
          f"tornato {nome!r}")
    check("la sessione sa il progetto", session.progetto == "Sito Ristorante",
          f"{session.progetto!r}")
    check("l'agente sa il progetto", session.agent.progetto == "Sito Ristorante",
          f"{getattr(session.agent, 'progetto', None)!r}")

    # L'evento: e' la cosa che dice all'utente in che cartella si sta
    # scrivendo. Senza, la cartella cambia in silenzio.
    cambi = [d for k, d in eventi if k == "progetto_cambiato"]
    check("il cambio e' annunciato", len(cambi) == 1, f"eventi: {eventi}")
    if cambi:
        check("l'annuncio porta il progetto",
              cambi[0].get("progetto") == "Sito Ristorante", str(cambi[0]))
        check("l'annuncio porta la cartella",
              cambi[0].get("percorso"), str(cambi[0]))

    # Un testo che non nomina nessun progetto non deve cambiare niente.
    eventi.clear()
    session._riconosci_progetto("ciao, come stai?")
    check("un testo senza progetti non cambia niente",
          session.progetto == "Sito Ristorante", f"{session.progetto!r}")
    check("e non annuncia niente",
          not [1 for k, _ in eventi if k == "progetto_cambiato"],
          f"eventi: {eventi}")


def main() -> int:
    print("=" * 60)
    print("TEST PROGETTI")
    print("=" * 60)
    try:
        test_registra()
        test_riconoscimento()
        test_root()
        test_file_toccati()
        test_tool_scrive_nel_progetto()
        test_memoria_col_progetto()
        test_il_cambio_e_annunciato()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("\n" + "=" * 60)
    print(f"  {PASSATI} passati, {len(FALLITI)} falliti")
    if FALLITI:
        for f in FALLITI:
            print(f"  FALLITO: {f}")
        return 1
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
