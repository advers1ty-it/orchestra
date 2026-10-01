"""Task per estrazione e scrittura.

Le due categorie che non avevano nessun test. Il problema di `writing`
non e' scriverla: e' che "questa prosa e' buona?" non ha una risposta
oggettiva, e un test che premia la lunghezza premia il modello peggiore.

La via che funziona: si verifica la STRUTTURA, cioe' cio' che in un
documento o in una scheda e' un requisito e non una preferenza. Un
JSON senza il campo `totale` e' sbagliato, anche se il testo intorno e'
bellissimo. Una scheda senza la data e' sbagliata, anche se la prosa
e' ottima.

Questo rende il test severo verso i modelli che scrivono bene e
sbagliano il formato — che e' esattamente il difetto che ti fa
ritoccare a mano un JSON prima di usarlo. Un modello che inventa un
campo, o che mette "12,50" invece di 12.5, perde: e deve perdere.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.benchmark import Task, v_all  # noqa: E402
from orchestra.verificatori import (  # noqa: E402
    v_json_campi, v_json_somma, v_json_valori, v_testo_contiene,
    v_markdown_sezioni, v_testo_lungo, v_testo_presente,
    v_testo_presente_inesistente, v_tutte_sezioni,
)


# I file di partenza stanno QUI, nel codice, e non li genera l'agente.
# Altrimenti il task misurerebbe due cose insieme — la capacita' di
# estrarre e quella di inventare un documento — e un punteggio non saprebbe
# piu' quale delle due e' bassa.

SCHEDA = """# Scheda sopralluogo

**Luogo:** ex fabbrica Reggiane, via Emilia 12
**Data:** 3 settembre 1947
**Rilevatore:** Aria Dossena, matricola 1142
**Circostanze:** il fabbricante risulta assente dai registri comunali
dal 1945; la moglie dichiara un trasferimento a Sassuolo non documentato.
**Ipotesi:** destinazione dell'opificio non ancora nota
**Conclusione:** caso aperto, servono i registri di confine
"""

BOZZA = """# Scheda sopralluogo

**Luogo:** ex fabbrica Reggiane, via Mazzini 8
**Data:** 3 settembre 1947
**Rilevatore:** Aria Dossena, matricola 1042
**Circostanze:** il fabbricante risulta assente dai registri comunali
dal 1945; la moglie dichiara un trasferimento a Sassuolo non documentato.
**Ipotesi:** destinazione dell'opificio non ancora nota
**Conclusione:** caso aperto, servono i registri di confine
"""

CLIENTI = """id;nome;importo
1;Ferrari;1200
2;Bianchi;800
3;Romano;650
4;Gallo;300
5;Neri;200
"""


# ---------------------------------------------------------------- estrazione
# Il file di partenza e' un testo SEMPLICE, non un PDF: cosi' il test
# verifica l'estrazione e non la lettura del file. Se volessi provare
# anche quella, servirebbe un allegato — e un benchmark che richiede
# interazione non e' un benchmark: diventa una prova manuale.
LISTINO = """LISTINO CLIENTI - GIUGNO 2026
Cliente: Rossi S.r.l.   Codice: R-1043
Preventivo n. 2026/1847 del 14 giugno 2026
Servizi: consulenza 1200, sviluppo 3400, formazione 600
NOTE: il cliente richiede fattura differita a 30 giorni
"""


def _file(nome: str, contenuto: str):
    """Un setup che scrive un file di partenza.

    I file di partenza stanno QUI, nel codice, e non li genera
    l'agente. Altrimenti il task misurerebbe due cose insieme — la
    capacita' di estrarre e quella di inventare un documento — e un
    punteggio non saprebbe piu' quale delle due e' basso.
    """
    def setup(work: str) -> None:
        with open(os.path.join(work, nome), "w", encoding="utf-8") as f:
            f.write(contenuto)
    return setup


TASK_EXTRACTION = [
    Task(
        id="extract_campi",
        category="extraction",
        prompt=(
            "Leggi il file listino.txt nella cartella di lavoro e tira fuori i dati "
            "in un file preventivi.json.\n"
            "Deve essere un JSON valido con questi campi: cliente (stringa), "
            "codice (stringa), preventivo (stringa), data (stringa in formato "
            "AAAA-MM-GG), totale (numero).\n"
            "La data e' quella dentro 'Preventivo n. 2026/1847 del 14 giugno 2026'. "
            "Il totale e' la somma dei tre importi elencati dopo 'Servizi'.\n"
            "Scrivi solo il file JSON, senza spiegazioni."
        ),
        setup=_file("listino.txt", LISTINO),
        verify=v_all(
            v_testo_presente("preventivi.json"),
            v_json_campi("preventivi.json", ["cliente", "codice", "preventivo",
                                             "data", "totale"]),
            v_json_valori("preventivi.json", {
                "cliente": "Rossi S.r.l.",
                "codice": "R-1043",
                "preventivo": "2026/1847",
                "data": "2026-06-14",
            }),
            v_json_somma("preventivi.json", "totale", 5200),
        ),
    ),
    Task(
        id="extract_tabella",
        category="extraction",
        prompt=(
            "Nel file clienti.txt ci sono cinque righe di dati separati da "
            "punto e virgola, con l'intestazione come prima riga.\n"
            "Scrivi clienti.json: un array JSON di cinque oggetti, ognuno con "
            "chiavi 'id', 'nome' e 'importo'. L'importo e' un numero, senza "
            "simbolo di valuta e con il punto come separatore decimale.\n"
            "Non includere l'intestazione nell'array. Scrivi solo il JSON."
        ),
        setup=_file("clienti.txt", CLIENTI),
        verify=v_all(
            v_testo_presente("clienti.json"),
            v_json_campi("clienti.json", ["id", "nome", "importo"]),
            v_json_somma("clienti.json", "importo", 3150),
        ),
    ),
]


# ---------------------------------------------------------------- scrittura
# Qui si verifica la STRUTTURA, non la qualita' della prosa. Il testo
# deve contenere certe informazioni — ma il test non puo' dire se e'
# "bello", e non ci prova. Dice solo cio' che e' un requisito: la data
# c'e', il nome del rilevatore c'e', la conclusione e' dichiarata.






TASK_WRITING = [
    Task(
        id="write_struttura",
        category="writing",
        prompt=(
            "Scrivi un file scheda.md: una scheda di sopralluogo su un luogo, "
            "in italiano, con questi elementi e queste intestazioni esatte:\n"
            "## Luogo\n## Data\n## Rilevatore\n## Circostanze\n"
            "## Ipotesi\n## Conclusione\n"
            "Il luogo e' un'ex fabbrica a Reggio Emilia in disuso dal 1945. "
            "Il rilevatore e' Aria Dossena. La data e' il 3 settembre 1947. "
            "Le circostanze sono che il proprietario non risulta nei registri. "
            "L'ipotesi e' che l'opificio servisse a qualcosa di non registrato. "
            "La conclusione e' che il caso resta aperto.\n"
            "Scrivi solo il file."
        ),
        verify=v_all(
            v_testo_presente("scheda.md"),
            v_markdown_sezioni("scheda.md", ["## Luogo", "## Data",
                                             "## Rilevatore",
                                             "## Circostanze",
                                             "## Ipotesi", "## Conclusione"]),
            v_testo_contiene("scheda.md", ["Aria Dossena", "1947",
                                            "Reggio"]),
        ),
    ),
    Task(
        id="write_dati_giusti",
        category="writing",
        prompt=(
            "Riscrivi la scheda che trovi in bozza.md dentro un file "
            "scheda-finale.md, correggendo i dati sbagliati:\n"
            "- la via e' via Emilia 12, non via Mazzini\n"
            "- la matricola del rilevatore e' 1142, non 1042\n"
            "- il trasferimento e' avvenuto nel 1946, non nel 1945\n"
            "Non cambiare nient'altro: stesso testo, stesse sezioni, solo i "
            "dati corretti."
        ),
        setup=_file("bozza.md", BOZZA),
        verify=v_all(
            v_testo_presente("scheda-finale.md"),
            v_testo_contiene("scheda-finale.md", ["via Emilia 12", "1142",
                                                    "1946"]),
            v_testo_presente_inesistente("scheda-finale.md",
                                          ["via Mazzini", "1042"]),
            v_tutte_sezioni("scheda-finale.md", "bozza.md"),
        ),
    ),
    Task(
        id="write_senza_filler",
        category="writing",
        prompt=(
            "Scrivi in allarme.txt tre righe di avviso per un impianto "
            "chiuso per pericolo: cosa e' successo, cosa non fare, cosa fare. "
            "Massimo 240 caratteri in tutto.\n"
            "Niente premesse, niente 'ecco qui', niente ripetizioni: la "
            "prima parola e' gia' l'avviso."
        ),
        # La lunghezza massima e' l'unica cosa verificabile sulla
        # brevita'. Il resto — che non ci sia un "ecco qui" — e'
        # controllabile come assenza di stringhe, e basta: pretendere di
        # misurare la qualita' della prosa qui sarebbe fingersi un
        # giudice, che e' la cosa che questo benchmark non fa.
        verify=v_all(
            v_testo_presente("allarme.txt"),
            v_testo_lungo("allarme.txt", minimo=40, massimo=240),
            v_testo_presente_inesistente("allarme.txt",
                                          ["ecco qui", "Certamente", "Come richiesto",
                                           "spero che", "In conclusione"]),
        ),
    ),
]
