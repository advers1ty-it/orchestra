"""Capire COSA e' andato storto in un test.

Il runner storico guardava solo il codice di uscita. Ma un codice di
uscita 1 vuol dire tre cose diverse:

  1. il test e' partito e ha trovato un difetto  -> FALLITO
  2. il test non e' mai partito (ImportError)     -> NON PARTITO
  3. il test e' morto per un errore unexpected  -> CRASH

Il caso 2 e' il peggiore, e perche' il runner non lo distingueva e' passato
inosservato per mesi. Un test che non parte non e' un test rosso: e' un
test ASSENTE. Il codice che copre non viene eseguito, e nessun report
dicono "quella zona non e' coperta" — dice solo "la suite e' fallita",
che si legge come "c'e' un difetto li'", cioe' il contrario.

Quattro suite ne soffrivano, tutte per la stessa ragione: un modulo
spostato e l'import rimasto indietro. Il sintomo era un ModuleNotFoundError
stampato in mezzo a 80 suite verdi, e nessuno ha guardato.

Qui la distinzione e' esplicita, e il codice di uscita del runner dice
anche QUALE. Un test che non parte e' un fallimento, ma un fallimento
diverso: e va detto.
"""

import os
import subprocess
import sys

# Esiti possibili di una suite.
OK = "OK"
FALLITO = "FALLITO"          # il test e' partito e ha trovato un difetto
NON_PARTITO = "NON PARTITO"  # mai partito: import rotto, raccolto dei nomi
CRASH = "CRASH"              # partito e morto con un'eccezione
NON_AVVENUTO = "NON AVVENUTO"  # la corsa non e' stata possibile (API esterna)

# I sintomi di un test che non ha mai iniziato a lavorare.
#
# Si cercano SOLO in stderr. In stdout no: un test puo' benissimo
# stampare la parola "ImportError" parlando di un difetto che ha
# trovato in un altro programma, e allora un test ROSSO sembrerebbe
# un test mai partito — il contrario esatto di quello che si vuole.
# Il traceback di un import rotto va su stderr, sempre.
_SINTOMI_NON_PARTITO = (
    "ModuleNotFoundError",
    "ImportError",
    "cannot import name",
    "No module named",
    "SyntaxError",
    "IndentationError",
)


class Esito:
    """Il risultato di una suite, con la ragione del fallimento."""

    def __init__(self, stato, codice, stdout="", stderr="", dettaglio="", nome=""):
        self.stato = stato
        self.codice = codice
        self.stdout = stdout
        self.stderr = stderr
        self.dettaglio = dettaglio
        self.nome = nome

    @property
    def ok(self):
        return self.stato == OK


def _prima_riga_significativa(testo):
    """La prima riga che dice qualcosa, saltando i Traceback decorativi."""
    for riga in (testo or "").splitlines():
        r = riga.strip()
        if not r:
            continue
        if r.startswith("File \"") or r.startswith("Traceback ("):
            continue
        return r
    return ""


def _riga_eccezione(testo):
    """La riga dell'eccezione: quella che dice COSA e' successo.

    Il traceback di un'eccezione finisce con la riga dell'eccezione:
    "ZeroDivisionError: division by zero". Quella e' l'informazione,
    non la riga di codice prima ("x = 1 / 0"), che dice solo DOVE.

    COME SI RICONOSCE, senza euristiche fragili
    -------------------------------------------
    Nel traceback di Python le righe del codice sono indentate ( quattro
    spazi) e l'ultima riga — l'eccezione — non lo e'. Dopo il traceback
    puo' venire un messaggio del programma, che non e' indentato: se
    prendessi "l'ultima riga non indentata", prenderei quella.

    Quindi: prendo le righe INDENTATE del blocco traceback, e la
    prima non indentata DOPO l'ultima di quelle. Nella pratica: la
    prima riga non indentata che segue l'ultima riga di codice.
    """
    righe = (testo or "").splitlines()
    # l'indice dell'ultima riga indentata dentro il traceback
    ultimo_codice = -1
    for i, riga in enumerate(righe):
        if riga.startswith("    ") and riga.strip():
            ultimo_codice = i
    if ultimo_codice < 0:
        return ""
    for riga in righe[ultimo_codice + 1:]:
        s = riga.strip()
        if not s:
            continue
        # la prima riga non indentata dopo il codice e' l'eccezione
        if not riga.startswith(" "):
            return s
        # dentro al traceback: e' la riga dell'eccezione
        return s
    return ""


def classifica(codice, stdout, stderr):
    """Distingue FALLITO da NON PARTITO da CRASH.

    L'ordine dei controlli conta. Un ModuleNotFoundError e' un ImportError
    dentro un traceback: se si guarda prima "c'e' un traceback", ogni
    import rotto sembra un crash, e il crash sembra un test fallito. La
    domanda giusta e' prima: questo test ha mai iniziato a fare il suo
    lavoro?
    """
    err = stderr or ""

    if codice == 0:
        return Esito(OK, codice, stdout, stderr)

    # Non e' partito: il sintomo e' in stderr, e la riga piu' utile e'
    # quella che nomina il modulo mancante.
    #
    # MA solo se il test non ha scritto niente. Un ImportError sollevato
    # DENTRO un test (non all'import) e' un test partito che e' morto:
    # la differenza si vede in stdout — un test che ha stampato
    # qualcosa ha iniziato a lavorare. Senza questo controllo, un
    # "import" dentro una funzione di test veniva dichiarato "mai
    # partito", e il difetto vero (l'eccezione) spariva dietro una
    # parola che parla d'altro.
    for sintomo in _SINTOMI_NON_PARTITO:
        if sintomo in err and not (stdout or "").strip():
            return Esito(NON_PARTITO, codice, stdout, stderr,
                        _dettaglio_import(err))

    # Un traceback con un'eccezione non prevista: il test e' partito e
    # poi e' morto. Diverso da "ha trovato un difetto": qui non c'e'
    # nessun verdetto, c'e' un codice che non arriva in fondo.
    if "Traceback (most recent call last)" in err:
        # La riga dell'eccezione ("ZeroDivisionError: division by
        # zero") dice COSA e' successo; la riga di codice prima dice solo
        # DOVE. Quella che serve e' la prima.
        dettaglio = _riga_eccezione(err) or _prima_riga_significativa(err)
        return Esito(CRASH, codice, stdout, stderr, dettaglio)

    # Niente traceback: il test e' partito e ha deciso che qualcosa
    # non torna. E' il caso normale, e la riga "FALLITI:" dice quali.
    #
    # Ma c'e' un caso in cui la corsa NON e' avvenuta: l'e2e parla con
    # l'API vera, e se il provider non risponde non c'e' nessun verdetto
    # sul codice. Il test lo dice ("IL PROVIDER NON HA RISPOSTO"), e
    # non e' un difetto: e' la rete. Confonderlo con un test rosso
    # fa litigare con il provider invece che col codice.
    if "IL PROVIDER NON HA RISPOSTO" in (stdout or ""):
        return Esito(NON_AVVENUTO, codice, stdout, stderr,
                    _prima_riga_significativa(stdout))

    return Esito(FALLITO, codice, stdout, stderr, _elenco_falliti(stdout))


def _dettaglio_import(testo):
    """La riga che dice cosa non si trova.

    "No module named 'orchestra.skill_tools'" e' l'informazione che
    basta a capire il difetto. Il traceback intero non serve: e' la
    stessa riga detta quattro volte, e nasconde quella che conta.
    """
    for riga in (testo or "").splitlines():
        r = riga.strip()
        if ("No module named" in r or "cannot import name" in r
                or "ModuleNotFoundError" in r or "ImportError" in r):
            return r
    return _prima_riga_significativa(testo)


def _elenco_falliti(stdout):
    """I nomi delle asserzioni fallite, se il test li stampa."""
    for riga in (stdout or "").splitlines():
        if riga.startswith("FALLITI:"):
            return riga[:200]
    return ""


def esegui(script, cwd=None, env=None, timeout=1800):
    """Esegue una suite e classifica l'esito.

    Il timeout e' esplicito perche' un test che si blocca non e' un test
    che passa: e' un test che non dice niente. Senza timeout il runner
    resta appeso per sempre e non dice niente nemmeno lui.
    """
    try:
        r = subprocess.run([sys.executable, script], cwd=cwd, env=env,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Esito(CRASH, -1, "", "",
                    f"timeout dopo {timeout}s: non ha finito",
                    os.path.basename(script))
    esito = classifica(r.returncode, r.stdout, r.stderr)
    esito.nome = os.path.basename(script)
    return esito
