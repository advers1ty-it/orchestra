"""L'ordine dei sorgenti del frontend, in un posto solo.

Era scritto a mano in quattro test diversi, e aggiungere un file al
bundle ne rompeva tre: il test non leggeva niente, ma falliva con
"elemento assente, handler non agganciato" — un messaggio che parla
del DOM e non della lista che si e' dimenticata di aggiornare.

Quindi la lista si legge dal server, che e' l'unico posto dove conta.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from orchestra.webapp import Handler  # noqa: E402

ORDER = tuple(Handler.BUNDLE_ORDER)
