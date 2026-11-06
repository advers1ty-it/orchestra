"""La composizione dei gestori, per dominio.

`Handler` eredita da `Rotte`, che non contiene piu' codice: solo l'elenco
dei gruppi. Cosi' webapp.py resta il server, e ogni dominio si legge — e
si sposta — da solo.
"""

from __future__ import annotations

from .rotte_automazione import RotteAutomazione
from .rotte_chat import RotteChat
from .rotte_modelli import RotteModelli
from .rotte_progetti import RotteProgetti
from .rotte_sistema import RotteSistema
from .rotte_skill import RotteSkill
from .rotte_storia import RotteStoria
from .rotte_telegram import RotteTelegram


class Rotte(RotteAutomazione, RotteChat, RotteModelli, RotteProgetti,
            RotteSistema, RotteSkill, RotteStoria, RotteTelegram):
    """I gestori di tutte le rotte, composti per dominio."""
