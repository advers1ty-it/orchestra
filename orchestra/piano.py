"""Modalita' piano: prima si propone, poi si tocca.

PERCHE' ESISTE

Un agente che scrive subito e' veloce quando ha capito, e costoso quando
ha capito male: l'utente vede il risultato sbagliato a lavoro finito,
quando rifare significa rifare tutto. La modalita' piano inverte il
default per i lavori che toccano piu' di un file: l'agente legge, propone
un piano, e aspetta. Solo dopo l'approvazione i tool che modificano
tornano disponibili — per il resto del turno.

DOVE STA LO STATO, E PERCHE' QUI

- `modalita_piano` sta sull'Agent: e' una proprieta' del turno, come il
  cancel, e vale anche senza sessione (CLI, benchmark, delega).
- L'APPROVAZIONE sta in un `threading.local`: una sessione esegue un
  turno in un thread suo, e il tool `proponi_piano` gira su quel thread.
  Approvare in una sessione non deve sbloccare le scritture di un'altra,
  e un'approvazione non deve sopravvivere al turno: si azzera in
  `nuovo_turno()`.

COSA NON E'

Non e' un permesso: i permessi rispondono a "posso toccare questo file?",
e restano. Il piano risponde a "questo e' il lavoro giusto?" e viene
prima. Un piano approvato non concede percorsi fuori dalla root: quelli
chiedono ancora, uno per uno.
"""

from __future__ import annotations

import threading
from typing import Any

# I tool che lasciano un segno: file, comandi, processi, stato salvato.
# Sono elencati per nome e non dedotti dallo schema perche' uno schema non
# dice se un tool scrive — `run_shell` ha un parametro `command`, non un
# flag `scrive=True`. Un tool nuovo che modifica va aggiunto qui, e il
# test controlla che i piu' importanti ci siano.
TOOL_CHE_CAMBIANO = {
    "write_file",
    "edit_file",
    "run_shell",
    "run_tests",
    "cron",
    "mcp",
    "memoria",
    "image_gen",
    "image_edit",
    "skill_genera",
    "skill_importa",
    "computer_click",
    "computer_type",
    "computer_open",
}

_L = threading.local()

BLOCCATO = (
    "NON ESEGUITO: la modalita' piano e' attiva e il piano non e' stato "
    "approvato. Questo tool modifica qualcosa ({nome}), quindi adesso non "
    "parte.\n"
    "Prima leggi quello che serve, poi chiama `proponi_piano` con i passi "
    "che vuoi fare. Se l'utente approva, i tool tornano disponibili per "
    "il resto di questo turno. Non aggirare il blocco con un altro tool."
)


def nuovo_turno() -> None:
    """Azzera l'approvazione: valeva per il turno di prima."""
    _L.approvato = False


def approvato() -> bool:
    return bool(getattr(_L, "approvato", False))


def approva() -> None:
    _L.approvato = True


def stato() -> dict[str, Any]:
    """Per i test e per chi deve spiegare cosa sta succedendo."""
    return {"approvato": approvato()}
