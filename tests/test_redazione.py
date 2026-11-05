"""Redazione dei segreti.

Il caso vero: `echo $OPENAI_API_KEY` e' un comando legittimo, e il suo
output finiva nello storico SQLite (con indice full-text), nella traccia
e nella UI. Qui si verifica che i formati con una firma spariscano, che
le assegnazioni tipo `API_KEY=...` spariscano, e — altrettanto
importante — che il testo normale NON venga toccato: un redattore che
mangia gli URL e i nomi di variabile viene spento, e allora tanto vale
non averlo.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.redazione import SEGNAPOSTO, redigi, redigi_dati  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


CHIAVI = {
    "openai": "sk-" + "a" * 48,
    "anthropic": "sk-ant-api03-" + "b" * 40,
    "github": "ghp_" + "c" * 36,
    "github-fine": "github_pat_" + "d" * 40,
    "slack": "xoxb-" + "1" * 12 + "-" + "e" * 20,
    "google": "AIza" + "f" * 35,
    "nvidia": "nvapi-" + "g" * 40,
    "bearer": "Bearer " + "h" * 40,
    "jwt": "eyJ" + "i" * 20 + "." + "j" * 20 + "." + "k" * 10,
}

print("\n[1] I formati con una firma vengono redatti")
for nome, chiave in CHIAVI.items():
    testo = f"errore: la chiave {chiave} non e' valida"
    out = redigi(testo)
    check(f"{nome}: la chiave sparisce", chiave not in out, out)
    check(f"{nome}: resta il contesto", "errore:" in out and "non e' valida" in out)
    # Il segnaposto porta il NOME del formato (`[redatto:openai-key]`),
    # non solo `[redatto]`: guardando un log serve sapere che cosa e'
    # stato tolto, senza doverlo indovinare dal contesto.
    check(f"{nome}: il segnaposto dice cosa era", "[redatto:" in out, out)

print("\n[2] Assegnazioni e blocchi PEM")
casi = [
    "OPENAI_API_KEY=abcdefghijklmnopqrstuvwxyz123456",
    "export ORCHESTRA_TOKEN=\"un-token-lungo-abbastanza\"",
    "api_key: 'valore-segreto-lungo'",
    "CLIENT_SECRET=ABCdef1234567890XYZ",
]
for testo in casi:
    out = redigi(testo)
    check(f"redatto: {testo[:28]}", SEGNAPOSTO in out, out)
    check(f"  nome conservato: {testo.split('=')[0][:22]}",
          testo.split("=")[0].split(":")[0].strip() in out, out)

pem = ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n"
       "-----END RSA PRIVATE KEY-----")
out = redigi(f"chiave:\n{pem}\nqui sotto")
check("la chiave privata sparisce intera",
      "MIIEow" not in out and "BEGIN RSA" not in out, out)
check("il testo attorno resta", out.startswith("chiave:") and
      out.rstrip().endswith("qui sotto"), out)

print("\n[3] Il testo normale non si tocca")
intatti = [
    "https://api.openai.com/v1/chat/completions",
    "if token and api_key: return token",
    "git commit -m 'aggiungi SKU e tokenizzatore'",
    "la password va chiesta all'utente, non scritta nel codice",
    "pip install orchestra==0.5.70",
    "tests/run_all.py -> 143 suite verdi",
]
for testo in intatti:
    check(f"intatto: {testo[:34]}", redigi(testo) == testo, redigi(testo))

print("\n[4] Idempotente: due passaggi non peggiorano il risultato")
una = redigi("OPENAI_API_KEY=abcdefghijklmnopqrstuvwxyz123456 e " + CHIAVI["openai"])
due = redigi(una)
check("stesso risultato al secondo giro", una == due, f"{una!r} != {due!r}")
check("nessun segnaposto annidato", "[redatto:[" not in due, due)

print("\n[5] Strutture annidate")
dati = {
    "tool": "run_shell",
    "args": {"command": f"export X={CHIAVI['github']}"},
    "lista": [{"key": CHIAVI["openai"]}, 42, None],
}
out = redigi_dati(dati)
testo = repr(out)
check("niente chiavi in un dict annidato",
      CHIAVI["github"] not in testo and CHIAVI["openai"] not in testo, testo)
check("i numeri e i None sopravvivono",
      out["lista"][1] == 42 and out["lista"][2] is None, testo)
check("le chiavi del dict restano",
      set(out) == {"tool", "args", "lista"}, str(set(out)))

print("\n[6] Alla porta: lo storico non salva la chiave")
_root = tempfile.mkdtemp(prefix="redazione-")
os.environ["ORCHESTRA_ROOT"] = _root
os.environ["ORCHESTRA_HOME"] = _root
from orchestra.storico import Storico  # noqa: E402

st = Storico(os.path.join(_root, "storico.db"))
sid = st.nuova_sessione(modello="m", provider="p", titolo="prova")
st.aggiungi_messaggio(
    sid, "tool",
    f"la variabile vale {CHIAVI['openai']} e questo e' tutto",
    nome="run_shell")
st.aggiungi_messaggio(
    sid, "assistant", "ho letto OPENAI_API_KEY=abcdefghijklmnopqrstuvwxyz123456")
salvati = st.messaggi(sid)
grezzo = repr(salvati)
check("la chiave firmata non e' nel DB",
      CHIAVI["openai"] not in grezzo, grezzo[:200])
check("l'assegnazione non e' nel DB",
      "abcdefghijklmnopqrstuvwxyz123456" not in grezzo, grezzo[:200])
check("il resto del testo e' rimasto",
      "questo e' tutto" in grezzo and "ho letto" in grezzo, grezzo[:200])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
