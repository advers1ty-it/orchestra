"""Una delega VERA, con un provider VERO.

I test offline verificano che il tetto funzioni e che un errore torni
dichiarato. Non verificano che un figlio torni indietro una risposta
vero.

Questo file sta fuori dal runner per una ragione: chiama il provider e
consuma token. Va eseguito a mano, quando si vuole spendere qualcosa
per vedere la delega funzionare davvero.

Il file di prova si crea da solo e si pulisce: se resta, il test
successivo legge il numero di righe di se' stesso e passa senza che
nessun modello abbia lavorato. E' il modo piu' economico con cui un
test delega si autocertifica.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestra.webapp import OrchestraApp  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio else ""))


def pulito(nome: str) -> Path:
    """Un file che non esiste e la cui cartella viene creata."""
    d = ROOT / "_delega_prova" / nome
    d.mkdir(parents=True, exist_ok=True)
    p = d / "conta.txt"
    if p.exists():
        p.unlink()
    return p


app = OrchestraApp.create()
print(f"  delega attiva: {app.delega_attiva}")
check("la delega e' attiva", app.delega_attiva is True)

if not app.delega_attiva:
    print("  nessuna fabbrica: niente da provare")
    sys.exit(1)

deleg = app.session._delegatore

# Un modello esplicito se l'ambiente ne fornisce uno.
#
# Non perche' l'instradamento sbagli: i free-tier hanno un tetto
# giornaliero e, quando lo raggiungono, rispondono 429 a qualunque
# cosa. Un test che fallisce perche' ha finito la quota non distingue
# "la delega non funziona" da "oggi OpenRouter ha detto basta", e un
# test che non distingue le due cose e' peggio di nessun test.
_modello = os.environ.get("ORCHESTRA_MODEL_TEST", "").strip()
if _modello:
    deleg._scegli_modello = lambda obiettivo: _modello
    print(f"  modello di prova: {_modello}")

# --------------------------------------------------------------------------
print("\n[1] Un figlio che sa fare il compito")
p = pulito("buono")
p.write_text("uno\ndue\ntre\n", encoding="utf-8")
rel = p.relative_to(ROOT).as_posix()
f = deleg.delega(
    f"Conta quante righe ha il file {rel}. "
    f"Rispondi solo con il numero, senza altro testo.",
    contesto=f"Il file e' in {ROOT}, leggilo con read_file.")
print(f"     -> esito={f.esito} modello={f.modello} passi={f.passi}")
print(f"     -> «{f.testo[:70]}»")
check("ha risposto", f.ok, f.esito)
check("il numero c'e'", "3" in f.testo, f.testo[:60])
check("non ha rifatto la domanda", "quante righe" not in f.testo.lower())

# --------------------------------------------------------------------------
print("\n[2] Un figlio che NON ci arriva, e lo dice")
f2 = deleg.delega(
    "Leggi il file non_esiste_qui.txt e dimmi cosa contiene.",
    contesto="Il file non esiste: è questo il punto del compito.")
print(f"     -> esito={f2.esito}")
print(f"     -> «{f2.testo[:70]}»")
check("ha risposto qualcosa", f2.ok or f2.esito == "errore", f2.esito)
if f2.ok:
    check("e NON ha inventato il contenuto",
          "non" in f2.testo.lower() or "nessun" in f2.testo.lower()
          or "esiste" in f2.testo.lower(),
          f2.testo[:70])
else:
    check("e l'errore e' dichiarato, non nascosto",
          "non e' un risultato" in f2.per_il_padre(), f2.per_il_padre()[:60])

# --------------------------------------------------------------------------
print("\n[3] Il padre non ha visto i passi del figlio")
# Il punto della delega: il padre riceve la risposta, non il
# trascorso. Qui si verifica che la risposta sia breve — un figlio che
# ritorna con venti passi di ragionamento ha rotto il patto.
check("la risposta e' corta", len(f.testo) < 600, str(len(f.testo)))
check("e non contiene un resoconto di tool",
      "read_file(" not in f.testo, f.testo[:80])

# --------------------------------------------------------------------------
print("\n[4] Il tetto: dalla profondita' 1 non si delega")
d1 = deleg.profondita
deleg.profondita = 1
puo, perche_no = deleg.puo_delegare()
print(f"     -> puo_delegare={puo} ({perche_no})")
check("non puo' delegare", not puo)
check("e dice perche'", "profondit" in perche_no, perche_no)
deleg.profondita = d1

# --------------------------------------------------------------------------
print("\n[5] Il conto")
print(f"     {deleg.resoconto()}")
check("il resoconto c'e'", "deleghe" in deleg.resoconto())
check("e due deleghe sono state fatte", deleg.n_figli == 2, str(deleg.n_figli))

# --------------------------------------------------------------------------
print("\n[6] Il padre ha ancora il tool, il figlio mai")
check("il padre ha delega", "delega" in app.session.registry.all_names())
figlio = app.session._fabbrica_figlio("prova")
check("il figlio non ce l'ha", "delega" not in figlio.registry.all_names())

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)