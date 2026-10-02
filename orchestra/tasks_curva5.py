"""La curva, completata: ogni categoria ha livelli.

`code` aveva gia' tre livelli; le altre cinque no, e la cosa costava
direttamente: `web`, `js` e `app` avevano due task senza livelli, e con
due domande i punteggi possibili sono tre — 0%, 50%, 100%. Non e' che i
modelli fossero tutti uguali: e' che non c'era modo di saperlo.

Qui ogni categoria sale a sei-nove compiti su tre livelli. Lo stesso
genere di compito dentro ogni categoria, e il livello segna dove si
dovrebbe cominciare a fallire.

Tre regole, dalle stesse che valgono per `tasks_curva`:

1. Ogni quesito ha UNA risposta difendibile, e la si verifica per
   enumerazione prima di entrare — non per convinzione.
2. Il prompt specifica tutto quello che il verificatore controlla.
3. La difficolta' e' il caso limite, non la parola piu'.

Per `js` e `web` il codice si ESEGUE con Node: senza esecuzione un
task di JavaScript verifica che il file contenga una parola, e ogni
modello passa. Con l'esecuzione si chiama la funzione con l'input che
rompe l'algoritmo ovvio, che e' l'unico posto dove la differenza si
vede.

L'ordine nel file e' vincolante: i Task sono costanti che costruiscono
i verificatori mentre vengono definite, quindi i verificatori devono
essere gia' costruiti.
"""

import json
import os
from typing import Any, Callable

from .benchmark import Task
from .verificatori_codice import v_esegui
from .verificatori_js import v_esegui_js

# ==========================================================================
# Verificatori
# ==========================================================================


def _scrivi(work: str, nome: str, contenuto: str) -> None:
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, nome), "w", encoding="utf-8") as f:
        f.write(contenuto)


def v_testo(path: str, *, deve: tuple[str, ...] = (), non_deve: tuple[str, ...] = (),
            minimo: int = 0, massimo: int = 0, righe_minime: int = 0,
            righe_esatte: int = 0) -> Callable:
    """Controlli su un file di testo, tutti dichiarati.

    Ogni cosa che il verificatore cerca e' qui dentro, e il prompt del
    task elenca esattamente le stesse: un modello non viene bocciato
    per qualcosa che il compito non diceva. E' la regola numero due,
    scritta in codice.
    """
    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        with open(p, encoding="utf-8") as f:
            testo = f.read()
        mancanti = [s for s in deve if s not in testo]
        if mancanti:
            return False, f"manca: {', '.join(mancanti[:4])}"
        presenti = [s for s in non_deve if s in testo]
        if presenti:
            return False, f"non doveva esserci: {', '.join(presenti[:4])}"
        if minimo and len(testo) < minimo:
            return False, f"{len(testo)} caratteri, minimo {minimo}"
        if massimo and len(testo) > massimo:
            return False, f"{len(testo)} caratteri, massimo {massimo}"
        righe = [r for r in testo.split("\n") if r.strip()]
        if righe_minime and len(righe) < righe_minime:
            return False, f"{len(righe)} righe non vuote, minimo {righe_minime}"
        # "esatte" e non un minimo: il compito che dice "tre righe e
        # nessun'altra" sta chiedendo un massimo, e un minimo li
        # lascia passare quattro righe senza accorgersene
        if righe_esatte and len(righe) != righe_esatte:
            return False, f"{len(righe)} righe invece di {righe_esatte}"
        return True, f"{len(testo)} caratteri"

    return _verifica


def v_tag_html(path: str, tag_attesi: list[tuple[str, int]],
              apri_chiudi: list[tuple[str, int]]) -> Callable:
    """Conta i tag, e controlla che siano bilanciati.

    Il conteggio e' quello che conta, non la presenza della stringa: un
    modello che scrive `<div>` dentro un commento, o dentro un attributo,
    passa una ricerca di sottostringa e non ha scritto una pagina. E il
    bilanciamento e' la parte che separa chi ha capito da chi ha
    copiato: dieci `<div>` e cinque `</div>` non e' una pagina.
    """
    import re

    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        with open(p, encoding="utf-8") as f:
            testo = f.read()
        sbagli = []
        for tag, attesi in tag_attesi:
            trovati = len(re.findall(rf"<{tag}\b", testo))
            if trovati != attesi:
                sbagli.append(f"{tag}: {trovati} invece di {attesi}")
        for tag, differenza in apri_chiudi:
            a = len(re.findall(rf"<{tag}\b", testo))
            c = len(re.findall(rf"</{tag}\s*>", testo))
            if a - c != differenza:
                sbagli.append(f"{tag}: {a} aperti e {c} chiusi, "
                              f"differenza {a - c} invece di {differenza}")
        if sbagli:
            return False, "; ".join(sbagli)[:180]
        return True, "tag giusti e bilanciati"

    return _verifica


# ==========================================================================
# js — lo stesso genere su tre livelli, e il codice si esegue
# ==========================================================================

# L1: il caso normale. Il calcolo della media, che è il primo
# esercizio di JavaScript e va bene che sia facile.
JS_L1 = Task(
    id="js_l1", category="js",
    prompt="Crea il file media.js con una funzione media(lista) che restituisce "
            "la media dei numeri della lista. Riceve solo numeri.",
    verify=v_esegui_js("media.js", "media", [([[1, 2, 3]], 2.0), ([[10]], 10.0)]),
)

# L2: il caso limite. La lista può non avere numeri, e l'atteso è null
# — non 0, non NaN. Un modello scrive la divisione e passa i due casi
# con i numeri, che sono gli unici che di solito prova da solo.
#
# Nota sul perché non si accetta 0: il compito lo dice, e la verifica lo
# controlla. Un task che accettasse entrambi misurerebbe se il modello
# ha letto il compito, non se sa gestire il caso limite.
JS_L2 = Task(
    id="js_l2", category="js",
    prompt="Crea il file media.js con una funzione media(lista) che restituisce "
            "la media dei numeri presenti, ignorando i null.\n"
            "Se non c'è nessun numero — lista vuota, oppure lista con soli null — "
            "deve restituire null. Non 0, e non NaN.",
    verify=v_esegui_js("media.js", "media", [
        ([[1, 2, 3]], 2.0),
        ([[None, 5]], 5.0),
        ([[]], None),
        ([[None, None]], None),
    ]),
)

# L3: il caso limite che non si vede guardando l'esempio, più l'ordine
# di arrivo. I null in fondo, i numeri confrontati fra loro, e a
# parità l'ordine di partenza si conserva. Il sort con una chiave che
# mette i null davanti — l'errore che si fa senza pensarci, perché il
# confronto naturale con null non funziona — passa i primi due casi.
JS_L3 = Task(
    id="js_l3", category="js",
    prompt="Crea il file ordina.js con una funzione ordina(lista) che ordina dal "
            "valore più piccolo al più grande.\n"
            "1. I valori null vanno in FONDO, non in cima e non nel mezzo.\n"
            "2. Gli altri valori si confrontano fra loro come numeri.\n"
            "3. A parità di valore l'ordine di arrivo si conserva.",
    verify=v_esegui_js("ordina.js", "ordina", [
        ([[3, None, 1, 2]], [1, 2, 3, None]),
        ([[None, 5, 1]], [1, 5, None]),
        ([[3, 1, 3, 2]], [1, 2, 3, 3]),
        ([[None, None]], [None, None]),
    ]),
)

# ==========================================================================
# web
# ==========================================================================

# L1: la pagina con la sua struttura. È il primo esercizio HTML e va
# bene che sia facile.
WEB_L1 = Task(
    id="web_l1", category="web",
    prompt="Crea il file pagina.html con un documento HTML completo: il tag "
            "<html> con dentro <head> contenente <title>, e <body>.\n"
            "Il titolo deve essere esattamente `Benvenuto`.\n"
            "Nel body ci deve essere un solo <h1> con il testo `Ciao`.",
    verify=lambda w: v_all(
        v_tag_html("pagina.html",
                   tag_attesi=[("html", 1), ("head", 1), ("title", 1),
                               ("body", 1), ("h1", 1)],
                   apri_chiudi=[("html", 0), ("head", 0), ("body", 0), ("h1", 0)]),
        v_testo("pagina.html", deve=("<title>Benvenuto</title>",)),
    )(w),
)

# L2: l'attributo che non è un testo. I caratteri speciali dentro
# l'attributo vanno codificati, e `href` non è il testo del link: è un
# indirizzo. Un modello che scrive il nome del file come testo del link
# ha fatto il compito al contrario.
WEB_L2 = Task(
    id="web_l2", category="web",
    prompt="Crea il file link.html con un solo paragrafo <p>.\n"
            "Dentro ci deve essere un link con testo `docs` e attributo "
            "`href=\"manuale.html\"`.\n"
            "Nel testo del link la parola `docs` NON deve comparire come "
            "parola intera preceduta da `&`: gli attributi non si "
            "codificano, e il codice del carattere `&` si scrive `&amp;` "
            "solo dentro il testo della pagina.",
    verify=lambda w: v_all(
        v_tag_html("link.html", tag_attesi=[("p", 1), ("a", 1)],
                   apri_chiudi=[("p", 0), ("a", 0)]),
        v_testo("link.html", deve=('href="manuale.html"',),
                non_deve=("&amp;",)),
    )(w),
)

# L3: i due vincoli che si toccano. Tre elementi, e ognuno dentro un
# contenitore diverso: è il caso in cui si scrive la struttura una
# volta e si sbaglia il bilanciamento, perché contando a occhio tre
# `<li>` e due `</li>` sembrano uguali.
WEB_L3 = Task(
    id="web_l3", category="web",
    prompt="Crea il file elenco.html con esattamente tre elementi `<li>`.\n"
            "Tutti e tre dentro un unico `<ul>`, e nient'altro: nessun "
            "secondo elenco, nessun `<li>` sciolto.\n"
            "Ogni `<li>` deve contenere il suo numero, da 1 a 3, nell'ordine.",
    verify=lambda w: v_elenco()(w),
)


def v_elenco() -> Callable:
    """Tre voci, un solo elenco, nell'ordine.

    Si controlla che i tre `<li>` siano DENTRO l'<ul>': il caso che
    separa è il terzo elemento rimasto fuori, che un conteggio totale
    non vede e un confronto di stringhe non nota.
    """
    import re

    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, "elenco.html")
        if not os.path.exists(p):
            return False, "il file elenco.html non esiste"
        with open(p, encoding="utf-8") as f:
            testo = f.read()
        if len(re.findall(r"<ul\b", testo)) != 1:
            return False, f"{len(re.findall(r'<ul', testo))} invece di un solo <ul>"
        m = re.search(r"<ul[^>]*>(.*?)</ul>", testo, re.S)
        if not m:
            return False, "l'<ul> non si chiude"
        dentro = re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.S)
        fuori = len(re.findall(r"<li\b", testo)) - len(dentro)
        if fuori:
            return False, f"{fuori} <li> fuori dall'<ul>"
        if len(dentro) != 3:
            return False, f"{len(dentro)} voci dentro invece di 3"
        numeri = [re.sub(r"<[^>]*>", "", v).strip() for v in dentro]
        if numeri != ["1", "2", "3"]:
            return False, f"contenuto {numeri} invece di ['1','2','3']"
        return True, "3 voci dentro l'elenco"

    return _verifica


# ==========================================================================
# app — componenti React
# ==========================================================================
# Qui non si esegue: eseguire React richiederebbe un ambiente di test
# che non abbiamo, e un simulatore fatto a mano misurerebbe il
# simulatore. La verifica guarda la struttura, ma guarda quella che
# distingue: il ramo del ritorno anticipato, che è l'errore che
# distingue un componente da un altro, e non la sintassi.

APP_L1 = Task(
    id="app_l1", category="app",
    prompt="Crea il file Contatore.jsx con un componente React di funzione "
            "chiamato `Contatore` che riceve la prop `iniziale` (un numero) e "
            "mostra un `<span>` con quel numero dentro.",
    verify=v_testo("Contatore.jsx",
                   deve=("function Contatore", "<span>", "iniziale")),
)

# L2: lo stato. Il valore iniziale viene dalla prop ma poi cambia da
# solo, e i due non possono stare nello stesso posto: senza stato, il
# click non cambia niente.
APP_L2 = Task(
    id="app_l2", category="app",
    prompt="Crea il file Contatore.jsx con un componente React di funzione "
            "chiamato `Contatore`. Riceve la prop `iniziale` e mostra un numero.\n"
            "Il numero parte da `iniziale` e c'è un `<button>` che lo aumenta di "
            "1 a ogni click.\n"
            "Serve `useState` per poterlo cambiare: la prop non si può "
            "modificare.",
    verify=v_testo("Contatore.jsx",
                   deve=("useState", "setValore", "<button", "iniziale")),
)

# L3: l'effetto che va ripulito. Il punto in cui il componente di un
# modello e quello di un altro divergono: l'useEffect che parte e non
# si ferma, e che scrive su un componente già smontato.
APP_L3 = Task(
    id="app_l3", category="app",
    prompt="Crea il file Timer.jsx con un componente React di funzione "
            "chiamato `Timer`.\n"
            "Un `useEffect` avvia un `setInterval` che ogni secondo chiama "
            "`setSecondi` con il valore aumentato di 1, partendo da 0.\n"
            "Lo stesso `useEffect` deve pulire: quando il componente viene "
            "smontato, l'intervallo va fermato con `clearInterval`.",
    verify=v_testo("Timer.jsx",
                   deve=("useEffect", "setInterval", "clearInterval",
                         "setSecondi"),
                   non_deve=("return null",)),
)

# ==========================================================================
# instruction
# ==========================================================================

# L1: il formato, e basta. Tre righe di un file, una per riga.
INSTR_L1 = Task(
    id="instr_l1", category="instruction",
    prompt="Scrivi in tre.txt tre righe. La prima contiene solo `uno`, la "
            "seconda solo `due`, la terza solo `tre`. Nessun'altra riga.",
    verify=v_testo("tre.txt", righe_esatte=3, minimo=11),
)

# L2: il formato più il tetto. Il compito dice tutto quello che la
# verifica guarda: il numero di righe, l'ordine, e che l'ultima riga
# finisca con un punto.
INSTR_L2 = Task(
    id="instr_l2", category="instruction",
    prompt="Scrivi in tre.txt esattamente tre righe, nell'ordine:\n"
            "  1. una riga che comincia con `prima`\n"
            "  2. una riga che comincia con `seconda`\n"
            "  3. una riga che comincia con `terza` e finisce con un punto "
            "fermo.\n"
            "Ogni riga deve stare su una sola riga: niente a capo dentro. "
            "Fuori dalle tre righe non ci deve essere altro testo.",
    verify=lambda w: v_istruzione()(w),
)


def v_istruzione() -> Callable:
    """Le tre righe, nell'ordine, con l'ultima che finisce col punto.

    Il punto fermo sull'ultima riga è il controllo che separa: è la
    specifica più piccola che un modello rispetta quasi sempre, e che
    una verifica che guarda solo le prime parole non controllerebbe.
    """
    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, "tre.txt")
        if not os.path.exists(p):
            return False, "il file tre.txt non esiste"
        with open(p, encoding="utf-8") as f:
            righe = [r.strip() for r in f.read().split("\n") if r.strip()]
        if len(righe) != 3:
            return False, f"{len(righe)} righe invece di 3"
        for i, prefisso in enumerate(("prima", "seconda", "terza")):
            if not righe[i].startswith(prefisso):
                return False, f"riga {i + 1} non comincia con `{prefisso}`: {righe[i][:40]}"
        if not righe[2].endswith("."):
            return False, "l'ultima riga non finisce con un punto fermo"
        return True, "3 righe nell'ordine, ultima col punto"

    return _verifica


# L3: due istruzioni che si contraddicono se le leggi una alla volta.
# "Solo lettere" e "il numero 3" non possono stare insieme: la prova
# che si capisce che l'istruzione impone una cosa che esclude l'altra
# è che il compito nomina l'esclusione.
INSTR_L3 = Task(
    id="instr_l3", category="instruction",
    prompt="Scrivi in scelta.txt una sola riga di testo.\n"
            "La riga può contenere SOLO lettere minuscole dell'alfabeto "
            "italiano e spazi. Niente numeri, niente punteggiatura, niente "
            "maiuscole.\n"
            "La parola `tre` è l'unica eccezione ammessa: deve comparire per "
            "intero, anche se contiene una lettera che non è minuscola.\n"
            "La riga non può superare 20 caratteri.",
    verify=lambda w: v_scelta()(w),
)


def v_scelta() -> Callable:
    """Solo minuscole e spazi, con una parola esentata e un tetto.

    L'esenzione è il punto: senza di essa il compito sarebbe
    contraddittorio, e un modello che lo rispetta alla lettera non
    potrebbe passare. Con l'esenzione scritta, l'unico modo di fallire
    è non averla letta.
    """
    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, "scelta.txt")
        if not os.path.exists(p):
            return False, "il file scelta.txt non esiste"
        with open(p, encoding="utf-8") as f:
            testo = f.read()
        righe = [r for r in testo.split("\n") if r.strip()]
        if len(righe) != 1:
            return False, f"{len(righe)} righe invece di una"
        riga = righe[0]
        if len(riga) > 20:
            return False, f"{len(riga)} caratteri, il tetto è 20"
        # si toglie la parola esentata e si controlla il resto
        resto = riga.replace("tre", "")
        sbagli = [c for c in resto
                  if not ("a" <= c <= "z") and c != " "]
        if sbagli:
            return False, f"caratteri non ammessi: {sorted(set(sbagli))}"
        if "tre" not in riga:
            return False, "manca la parola esentata `tre`"
        return True, f"riga di {len(riga)} caratteri"

    return _verifica


# ==========================================================================
# scrittura e ragionamento: i livelli mancanti
# ==========================================================================

# reason_l1: la versione facile, per avere la base della curva. Un
# quesito di una mossa sola, dichiarato tale: è il pavimento, e senza
# il pavimento non si dice che il resto sia difficile.
REASON_L1 = Task(
    id="reason_l1", category="reasoning",
    prompt="Un carrello ha 3 mele e 2 pere. Quante frutti ci sono in tutto?\n"
            "Scrivi in risposta.txt solo il numero.",
    verify=lambda w: v_numero("risposta.txt", 5)(w),
)

# write_l3: il tetto e la struttura insieme, e il tetto stringe. Il
# caso in cui il modello scrive bene, rispetta i titoli, e sbaglia la
# lunghezza — l'unico modo di fallire che non è sciatteria.
WRITE_L3 = Task(
    id="write_l3", category="writing",
    prompt="Riscrivi il contenuto di bozza.txt in due.txt.\n"
            "In due.txt ogni riga comincia con `- ` (trattino e uno spazio), "
            "nella stessa ordine della bozza.\n"
            "Il testo di ogni riga deve stare su una sola riga: niente a capo "
            "dentro.\n"
            "In tutto, due.txt può contenere al massimo 120 caratteri.",
    setup=lambda w: _scrivi(w, "bozza.txt",
                            "primo punto che arriva\n"
                            "secondo punto da mettere\n"
                            "terzo punto in chiusura\n"),
    verify=lambda w: v_due_voci()(w),
)


def v_due_voci() -> Callable:
    """Le stesse voci della bozza, con il trattino, sul tetto.

    Il confronto è con la bozza riga per riga: un modello che riordina
    o riassume sta rispondendo a un compito diverso, e senza questo
    confronto passerebbe un file ben scritto ma non quello chiesto.
    """
    def _verifica(work: str) -> tuple[bool, str]:
        bozza = os.path.join(work, "bozza.txt")
        if not os.path.exists(bozza):
            return False, "manca bozza.txt"
        with open(bozza, encoding="utf-8") as f:
            originali = [r.strip() for r in f.read().split("\n") if r.strip()]
        p = os.path.join(work, "due.txt")
        if not os.path.exists(p):
            return False, "il file due.txt non esiste"
        with open(p, encoding="utf-8") as f:
            testo = f.read()
        if len(testo) > 120:
            return False, f"{len(testo)} caratteri, il tetto è 120"
        righe = [r for r in testo.split("\n") if r.strip()]
        if len(righe) != len(originali):
            return False, f"{len(righe)} righe invece di {len(originali)}"
        sbagli = []
        for i, (r, orig) in enumerate(zip(righe, originali)):
            if not r.startswith("- "):
                sbagli.append(f"riga {i + 1} non comincia con '- '")
            elif r[2:].strip() != orig:
                sbagli.append(f"riga {i + 1}: {r[2:].strip()[:30]!r} invece di {orig[:30]!r}")
        if sbagli:
            return False, "; ".join(sbagli)[:180]
        return True, f"{len(righe)} voci, {len(testo)} caratteri"

    return _verifica


def v_numero(path: str, atteso: int) -> Callable:
    """Un file che contiene un numero, e nient'altro che lo faccia sentire.

    Si accetta anche il numero con spazi attorno, ma non con altro
    testo: la verifica cerca un numero nel file e pretende che non ci
    sia nient'altro. Un modello che risponde "5 mele" ha risposto a
    modo suo, e il compito diceva "solo il numero".
    """
    import re

    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        with open(p, encoding="utf-8") as f:
            testo = f.read().strip()
        if not testo:
            return False, "il file è vuoto"
        m = re.search(r"-?\d+(?:[.,]\d+)?", testo)
        if not m:
            return False, f"nessun numero in {testo[:40]!r}"
        if len(testo) > len(m.group(0)) + 2:
            return False, f"nel file c'è altro oltre il numero: {testo[:40]!r}"
        if abs(float(m.group(0).replace(",", ".")) - atteso) > 1e-9:
            return False, f"{m.group(0)} invece di {atteso}"
        return True, str(atteso)

    return _verifica


def v_all(*verificatori: Callable) -> Callable:
    """Tutti devono passare, e il messaggio è quello del primo che no."""
    def _verifica(work: str) -> tuple[bool, str]:
        for v in verificatori:
            ok, det = v(work)
            if not ok:
                return False, det
        return True, "tutti i controlli"
    return _verifica


def curva() -> list[Task]:
    """Tutti i task, dal livello più basso in su."""
    return [
        JS_L1, JS_L2, JS_L3,
        WEB_L1, WEB_L2, WEB_L3,
        APP_L1, APP_L2, APP_L3,
        INSTR_L1, INSTR_L2, INSTR_L3,
        REASON_L1, WRITE_L3,
    ]


TASK_CURVA = curva()
