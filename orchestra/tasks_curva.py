"""Una curva di difficolta', non un elenco di task piu' lunghi.

Il problema che l'ha motivata: i punteggi in alto erano compressi. Sette
modelli, tre sopra il 90%, e due a 100% che sembravano uguali perche'
uno era stato misurato su una categoria sola. Con venti task facili il
benchmark misura una soglia — "riesci a non sbagliare" — e sopra la
soglia non c'e' piu' niente da misurare: tutti i bravi sembrano
identici.

Una curva risolve alla radice, se e' vera curva: stessi compiti, un
livello in piu' di difficolta'. Chi risolve il livello 1 e il 2 e
sbaglia il 3 si separa da chi li risolve tutti, e la tabella dice
perche'.

Tre regole, prese dai task che si sono rivelati sbagliati:

1. Ogni quesito ha UNA risposta difendibile. Se ne ha due il benchmark
   non misura niente: un modello che ragiona viene contado come uno
   che indovina (e' successo con reason_sched).

2. Il prompt specifica tutto quello che il verificatore controlla. Un
   campo mai specificato fa fallire un modello che ha risposto in modo
   ragionevole (e' successo con extract_campi).

3. La difficolta' sta nel compito, non nella formulazione. "Piu' verbo"
   non e' piu' difficile: e' piu' occasioni di sbagliare la
   riformulazione. Qui e' il caso limite, l'input che rompe l'algoritmo
   ovvio, o il vincolo che interagisce con un altro.

I livelli stanno nell'id: `code_l1`, `code_l2`, `code_l3`.

L'ordine nel file e' vincolante: i Task sono costanti che costruiscono
i verificatori mentre vengono definite, quindi i verificatori devono
essere gia' costruiti. E' gia' successo due volte in questo progetto —
CLIENTI in tasks_scrizione.py, e v_ordina qui — e ogni volta il modulo
si e' fermato sul primo nome.
"""

import json
import os
from typing import Any, Callable

from .benchmark import Task
from .verificatori import v_testo_contiene
from .verificatori_codice import esegui, v_esegui

# ==========================================================================
# Verificatori
# ==========================================================================


def _scrivi(work: str, nome: str, contenuto: str) -> None:
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, nome), "w", encoding="utf-8") as f:
        f.write(contenuto)


def v_json(path: str, attesi: dict[str, Any]) -> Callable:
    """Un JSON scritto dal modello, campo per campo, tutto dichiarato.

    Non un confronto "contiene": ogni campo e' qui per intero, anche
    quelli che il compito non nomina. Un modello che azzecca i campi
    chiesti e lascia gli altri inventati deve fallire — altrimenti la
    verifica guarda meta' del compito, e la curva non curva niente.
    """
    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        try:
            with open(p, encoding="utf-8") as f:
                dati = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return False, f"JSON non leggibile: {str(e)[:80]}"
        if not isinstance(dati, dict):
            return False, f"nel file c'e' un {type(dati).__name__}, non un oggetto"
        sbagli = []
        for k, v in attesi.items():
            if k not in dati:
                sbagli.append(f"{k} manca")
            elif dati[k] != v:
                sbagli.append(f"{k}: {dati[k]!r} invece di {v!r}")
        if sbagli:
            return False, "; ".join(sbagli)[:180]
        return True, f"{len(attesi)}/{len(attesi)} campi"

    return _verifica


def v_ordina() -> Callable:
    """Quattro prove, e l'ultima guarda l'ingresso.

    L'ingresso non si verifica con `v_esegui`, che chiama e basta: qui si
    richiama la funzione e si controlla anche che la lista sia arrivata
    intatta. Serve un processo perche' la lista attraversa la frontiera
    del subprocess: il figlio deve riportare indietro com'era entrata.
    """
    prove = [
        ([[3, None, 1, 2]], [1, 2, 3, None]),
        ([[None, 5, 1]], [1, 5, None]),
        ([[3, 1, 3, 2]], [1, 2, 3, 3]),
        ([[None, None]], [None, None]),
    ]
    base = v_esegui("ordina.py", "ordina", prove)

    def _verifica(work: str) -> tuple[bool, str]:
        ok, det = base(work)
        if not ok:
            return ok, det
        out = esegui(os.path.join(work, "ordina.py"),
                     [{"nome": "ordina", "args": [[[3, None, 1]]]}])
        if out and "valore" in out[0] and out[0]["valore"] == [3, None, 1]:
            return False, ("la funzione ha restituito la lista invariata: "
                           "ordina sul posto, o non ordina")
        return True, det

    return _verifica


def v_avviso() -> Callable:
    """Le tre sezioni come intestazioni vere, in ordine, entro il tetto.

    I titoli si cercano come righe che iniziano con "## ", non come
    sottostringhe: un modello che scrive i titoli dentro un paragrafo
    li fa passare e non ha scritto un file Markdown. E ogni sezione deve
    avere testo sotto, altrimenti un titolo a fine file soddisfa il
    titolo e non l'avviso.
    """
    attesi = ["## Cosa e' successo", "## Cosa non fare", "## Cosa fare"]

    def _norm(t: str) -> str:
        """L'apostrofo e' l'unica cosa che si normalizza.

        'e' ed è sono la stessa lettera: un modello che scrive
        l'accento ha scritto bene quanto uno che non lo mette, e
        bocciarlo significa misurare la tastiera invece della
        scrittura. Su una categoria che si chiama `writing` è
        particolarmente fuori luogo.
        """
        return t.replace("è", "e'").replace("È", "E'")

    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, "avviso.md")
        if not os.path.exists(p):
            return False, "il file avviso.md non esiste"
        with open(p, encoding="utf-8") as f:
            testo = f.read()
        righe = [r.strip() for r in testo.split("\n") if r.strip()]
        titoli = [_norm(r) for r in righe if r.startswith("## ")]
        if titoli != attesi:
            return False, f"sezioni {titoli} invece di {attesi}"
        if len(testo) > 180:
            return False, f"{len(testo)} caratteri, il tetto e' 180"
        for i, r in enumerate(righe):
            if r in attesi:
                if i + 1 >= len(righe) or righe[i + 1].startswith("## "):
                    return False, f"sezione senza testo: {r}"
        return True, f"3 sezioni, {len(testo)} caratteri"

    return _verifica


def v_uno() -> Callable:
    """Tutti e tre i file, non uno: e' un task sugli strumenti, e la meta'
    e' il caso in cui ci si ferma al primo."""
    def _verifica(work: str) -> tuple[bool, str]:
        mancanti = [n for n in ("uno/uno.txt", "due/due.txt", "tre/tre.txt")
                    if not os.path.exists(os.path.join(work, n))]
        if mancanti:
            return False, f"non creati: {', '.join(mancanti)}"
        return True, "3 file"

    return _verifica


def v_numeri() -> Callable:
    """Le quattro righe, pulite, E nessuna riga vuota in mezzo.

    La versione precedente filtrava via le righe vuote prima di
    confrontare: un file con "1\n2\n\n3\n4\n" passava come se fosse
    pulito, che e' esattamente cio' che il compito vieta. Si conta
    prima quante righe non vuote ci sono e poi si guarda se il totale
    combacia — se non combacia, qualcuna era vuota.
    """
    def _verifica(work: str) -> tuple[bool, str]:
        p = os.path.join(work, "numeri.txt")
        if not os.path.exists(p):
            return False, "il file numeri.txt non esiste"
        with open(p, encoding="utf-8") as f:
            testo = f.read()
        righe = testo.split("\n")
        # l'ultima riga di un file che finisce con \n e' vuota per
        # costruzione, e non e' una riga vuota "lasciata dentro"
        if righe and righe[-1] == "":
            righe = righe[:-1]
        pulite = [r.strip() for r in righe if r.strip()]
        if len(pulite) != len(righe):
            return False, (f"{len(righe) - len(pulite)} righe vuote lasciate dentro: "
                           f"{righe}")
        if pulite != ["1", "2", "3", "4"]:
            return False, f"contenuto {pulite} invece di ['1','2','3','4']"
        return True, "4 righe pulite, nessuna vuota"

    return _verifica


# ==========================================================================
# code — lo stesso genere di compito, tre livelli
# ==========================================================================

# L1 e' quello che c'era gia'. Senza il livello facile non si puo' dire
# che il difficile e' difficile, e non si distingue "peggio" da
# "diverso".
CODE_L1 = Task(
    id="code_l1", category="code",
    prompt="Crea il file fib.py con una funzione fib(n) che restituisce il "
            "n-esimo numero di Fibonacci. fib(0) fa 0, fib(1) fa 1. "
            "Aggiungi un blocco __main__ che stampi fib(10).",
    verify=v_esegui("fib.py", "fib", [([0], 0), ([1], 1), ([10], 55)]),
)

# L2: il caso limite. L'algoritmo ovvio e' sbagliato perche' la lista
# puo' non avere numeri, e l'atteso e' None — non 0, non un errore. Un
# modello scrive la divisione e passa i due casi con i numeri, che
# sono gli unici che di solito prova da solo.
CODE_L2 = Task(
    id="code_l2", category="code",
    prompt="Crea il file media.py con una funzione media(lista) che calcola la "
            "media dei numeri presenti, ignorando i None. Se non c'e' nessun "
            "numero — lista vuota, oppure lista con soli None — deve restituire "
            "None, non 0 e non un errore.",
    verify=v_esegui("media.py", "media", [
        ([[1, 2, 3]], 2.0),
        ([[None, 5]], 5.0),
        ([[]], None),
        ([[None, None]], None),
        ([[7]], 7.0),
    ]),
)

# L3: il caso limite che non si vede guardando l'esempio, piu' la
# stabilita' e il divieto di modificare l'ingresso. Il None va in
# fondo, non in cima: e' l'errore che si fa senza pensarci, perche' il
# confronto naturale con None non funziona e si finisce per metterlo
# davanti per sbaglio.
CODE_L3 = Task(
    id="code_l3", category="code",
    prompt="Crea il file ordina.py con una funzione ordina(lista) che ordina "
            "dal valore piu' piccolo al piu' grande.\n"
            "Regole, da applicare in quest'ordine:\n"
            "1. I valori None vanno in FONDO, non in cima e non nel mezzo.\n"
            "2. Gli altri valori si confrontano fra loro come numeri.\n"
            "3. A parita' di valore l'ordine di arrivo si conserva.\n"
            "4. La lista data come argomento non va modificata.",
    verify=v_ordina(),
)

# ==========================================================================
# reasoning
# ==========================================================================

# Risposta unica, verificata per enumerazione prima di entrare nel
# benchmark: Ada fa C, Bo non fa B, quindi Bo fa A e Cy fa B. Unica.
#
# La prima versione chiedeva "chi fa A" scrivendo due righe sopra "Ada fa
# A": la risposta era leggibile a occhio, e il quesito non misurava
# niente. Come il vecchio reason_sched, che aveva due risposte valide e
# ne accettava una: due modi diversi di scrivere un compito che non si
# puo' sbagliare.
REASON_L2 = Task(
    id="reason_l2", category="reasoning",
    prompt="Tre ingegneri devono completare tre attivita' A, B, C entro fine "
            "giornata. Ognuno fa un'attivita' diversa, una sola.\n"
            "Ada fa C. Bo non fa B.\n"
            "Chi fa A? Scrivi in risposta.txt solo la parola con il nome.",
    # v_testo_presente controllava solo che il file esistesse, quindi
    # qualunque risposta passava: anche "Cy", che e' sbagliata. Il
    # compito non misurava niente e avrebbe dato 100% a ogni modello.
    # Il controllo e' sul contenuto, e la risposta giusta e' Bo.
    verify=v_testo_contiene("risposta.txt", ["Bo"]),
)

# Il conto su cinque eventi: l'errore tipico e' scordare un'occorrenza,
# e non si vede nella risposta se non si controllano i tre campi uno per
# uno. Un conteggio in prosa non e' confrontabile.
REASON_L3 = Task(
    id="reason_l3", category="reasoning",
    prompt="Da questa sequenza:\n"
            "  Ada fa A, Bo fa B, Ada fa C, Cy fa A, Bo fa C\n"
            "conta quante volte ciascuno fa A, quante B, quante C.\n"
            "Scrivi in risultato.json un oggetto con tre chiavi, una per "
            "persona. Il valore di ogni chiave e' una stringa con i tre "
            "numeri separati da uno spazio, nell'ordine A B C: per Ada "
            "\"2 1 0\" significa 2 volte A, 1 volta B, 0 volte C.\n"
            "Solo il file JSON, senza spiegazioni.",
    verify=v_json("risultato.json", {
        "Ada": "2 1 0", "Bo": "1 1 1", "Cy": "1 0 0",
    }),
)

# ==========================================================================
# estrazione
# ==========================================================================
CSV = (
    "cliente;totale;data\n"
    '"Rossi, Mario";120,50;2026-01-15\n'
    "Bianchi;80,00;2026-01-15\n"
    '"Verdi, Anna";200,25;2026-02-01\n'
    "Neri;50,00;2026-02-01\n"
)

# Il separatore e' il punto e virgola, i decimali la VIRGOLA dentro il
# campo, e i nomi con la virgola sono fra doppi apici. Un parser che
# divide su ";" sbaglia i numeri: "120,50" sembra un campo con un pezzo
# in piu'. E la somma, 450.75, si puo' fare solo se i campi sono stati
# separati bene.
EXTRACT_L2 = Task(
    id="extract_l2", category="extraction",
    prompt="Nel file ordini.csv c'e' un elenco di ordini. Il separatore fra i "
            "campi e' il punto e virgola, e i decimali sono separati dalla "
            "VIRGOLA dentro il campo. I nomi che contengono una virgola sono "
            "racchiusi fra doppi apici, come in questa riga:\n"
            '  "Rossi, Mario";120,50;2026-01-15\n'
            "Calcola la somma dei totali e scrivi il numero in totale.json come "
            "un oggetto con una chiave \"somma\" il cui valore e' il numero.\n"
            "Solo il file JSON.",
    setup=lambda w: _scrivi(w, "ordini.csv", CSV),
    verify=v_json("totale.json", {"somma": 450.75}),
)

# I due totali non quadrano, e la differenza ha una soglia e un nome.
# Il compito dice cosa scrivere in ciascuno dei due casi, quindi non c'e'
# spazio per l'interpretazione: o la regola e' stata capita o no. La
# soglia e' dichiarata perche' 0.03 e 0.02 non si distinguono a occhio.
EXTRACT_L3 = Task(
    id="extract_l3", category="extraction",
    prompt="Nel file conto.csv ci sono righe con voce 'totale' e righe con voce "
            "'dettaglio'. La voce 'totale' e' l'estratto conto gia' calcolato.\n"
            "Regola: se la differenza fra 'totale' e la somma dei 'dettaglio' e' "
            "entro 0.02, il conto e' coerente e in reporting.json scrivi "
            "{\"esito\": \"coerente\"} e nient'altro.\n"
            "Se la differenza e' oltre 0.02, il conto e' sbagliato: in "
            "reporting.json scrivi {\"differenza\": numero, \"riga\": numero}, dove "
            "\"riga\" e' il numero progressivo della riga di dettaglio che spiega "
            "lo scarto, contando dall'inizio del documento.\n"
            "Solo il file JSON.",
    setup=lambda w: _scrivi(w, "conto.csv",
                            "voce;importo\n"
                            "totale;100,00\n"
                            "dettaglio;40,00\n"
                            "dettaglio;60,03\n"),
    # 40,00 + 60,03 = 100,03 contro un totale di 100,00: scarto 0,03,
    # oltre la soglia. La riga che spiega lo scarto e' la seconda
    # riga di dettaglio, che e' la terza riga del documento contando
    # l'intestazione.
    verify=v_json("reporting.json", {"differenza": 0.03, "riga": 3}),
)

# ==========================================================================
# writing
# ==========================================================================

# Due vincoli che si toccano: le sezioni nell'ordine, e un tetto di
# caratteri che costringe a rinunciare. Chi scrive bene e lungo
# fallisce perche' ha scelto di non obbedire al tetto — e il tetto e'
# la parte che distingue questo compito.
WRITE_L2 = Task(
    id="write_l2", category="writing",
    prompt="Scrivi in avviso.md tre sezioni Markdown con questi titoli, "
            "nell'ordine esatto:\n"
            "## Cosa e' successo\n"
            "## Cosa non fare\n"
            "## Cosa fare\n"
            "Ogni sezione deve avere almeno una riga di testo sotto il "
            "titolo. In tutto il file puo' contenere al massimo 180 "
            "caratteri, titoli compresi. Nessuna premessa e nessuna "
            "spiegazione fuori dalle sezioni.",
    verify=v_avviso(),
)

# ==========================================================================
# tool_use
# ==========================================================================

TOOL_L1 = Task(
    id="tool_l1", category="tool_use",
    prompt="Crea i file uno/uno.txt, due/due.txt e tre/tre.txt, ognuno con "
            "dentro la parola del suo nome. Le cartelle non esistono: creale.",
    verify=v_uno(),
)

# Pulizia del file che si riscrive: gli spazi, le righe vuote. Il caso
# che separa e' la riga vuota in mezzo: un modello che riscrive riga per
# riga la lascia, e il file non torna come richiesto.
TOOL_L2 = Task(
    id="tool_l2", category="tool_use",
    prompt="Nel file numeri.txt c'e' un numero per riga, alcuni con spazi "
            "attorno, e qualche riga vuota. Riscrivi lo stesso file con i "
            "numeri senza spazi, uno per riga, e senza lasciare righe vuote.",
    setup=lambda w: _scrivi(w, "numeri.txt", "  1\n2  \n\n  3\n   4\n"),
    verify=v_numeri(),
)


def curva() -> list[Task]:
    """Tutti i task della curva, dal livello piu' basso in su."""
    return [
        CODE_L1, CODE_L2, CODE_L3,
        REASON_L2, REASON_L3,
        EXTRACT_L2, EXTRACT_L3,
        WRITE_L2,
        TOOL_L1, TOOL_L2,
    ]


TASK_CURVA = curva()
