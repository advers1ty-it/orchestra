"""Isola i test dal DB della cronologia vera.

Senza questo, ogni test che chiama `Session.send()` fa girare il worker,
il worker salva il turno nello storico — e lo storico vero è
`~/AppData/Local/hermes/orchestra/storico.db`. Risultato: la cronologia
dell'utente si riempie di conversazioni di test ("lungo", "a", "lento",
"primo", "booma"...) da cancellare a mano.

La cura: `ORCHESTRA_HOME` su una cartella temporanea, impostata QUI,
prima di qualsiasi import di orchestra. Deve essere il più presto
possibile perché `storico()` è un singleton: la prima volta che viene
chiamto crea l'istanza sul percorso di allora, e cambiare l'env dopo non
lo sposta più.

Il percorso è dentro la cartella dei test, così resta visibile per
ispezionare una run fallita, e si può ripulire a mano.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_TMP = os.path.join(_ROOT, "_dati_test")

# Prima di tutto: se orchestra (o i test) apre il DB, lo apre qui.
os.environ["ORCHESTRA_HOME"] = _TMP
os.makedirs(_TMP, exist_ok=True)

sys.path.insert(0, os.path.dirname(_ROOT))
