"""Quali tool si possono eseguire in parallelo, e perche' solo quelli.

Un turno che chiede cinque `read_file` indipendenti passa cinque volte il
tempo del piu' lento per niente. Ma le tool_calls di un giro sono una
sequenza, e l'ordine e' informazione: un `write_file` seguito da un
`read_file` sullo stesso percorso deve vedere il file nuovo.

Quindi non c'e' parallelismo "cieco": c'e' un elenco esplicito di tool di
sola lettura, e un giro va in parallelo solo se TUTTE le sue chiamate sono
li'. Basta una scrittura per tornare in fila, ed e' voluto — un giro misto
in parallelo sarebbe una corsa sul file che nessuno ha chiesto.

L'elenco e' scritto a mano perche' va deciso guardando il tool, non
dedotto dal nome: `web_leggi` legge la rete (nessuno stato locale, va
bene), `memoria` con l'azione giusta scrive, `browser_render` lancia un
processo. Un tool nuovo che legge e non e' qui perde solo la velocita';
un tool che scrive e finisce qui per errore sarebbe un difetto, e per
questo il test controlla che i tool che modificano non ci siano.
"""

from __future__ import annotations

# Tool che non cambiano niente: nessun file, nessuna memoria, nessun
# processo lasciato acceso. Se ne aggiungi uno che scrive, il test
# `test_parallelo` fallisce — che e' il punto.
SOLA_LETTURA = frozenset({
    "read_file",
    "list_dir",
    "find_files",
    "search_text",
    "analisi_python",
    "calculate",
    "storico_cerca",
    "web_cerca",
    "web_leggi",
    "skill_cerca",
    "skill_leggi",
    "browser_render",
    "browser_screenshot",
    "computer_screenshot",
})


def sola_lettura(nome: str) -> bool:
    """True se `nome` e' un tool che si puo' eseguire insieme ad altri."""
    return nome in SOLA_LETTURA
