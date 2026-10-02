"""Lo schema di /api/alpha/decisions, trovato facendo parlare l'endpoint.

La documentazione non e' raggiungibile da qui (estrazione non
disponibile, browser scaduto), ma l'endpoint valida lo schema e dice
quello che manca, campo per campo. Il trucco che rende la cosa
leggibile: la validazione avviene PRIMA del rate limit. Quindi

  400 = schema sbagliato
  429 = schema giusto, tetto giornaliero raggiunto

e si puo' mappare tutto il contratto senza consumare una richiesta.
"""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import load_env  # noqa: E402

MODELLO = "inception/mercury-decide:free"
URL = "https://openrouter.ai/api/alpha/decisions"

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def _chiedi(domanda):
    env = load_env(os.path.join(os.getcwd(), "orchestra", ".env"))
    chiave = env.get("OPENROUTER_API_KEY", "")
    req = urllib.request.Request(
        URL, data=json.dumps({
            "model": MODELLO, "state": {}, "questions": {"q?": domanda},
        }).encode(),
        headers={"Authorization": "Bearer " + chiave,
                 "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
        return 200, ""
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")
        dettaglio = ""
        try:
            err = json.loads(corpo)["error"]["message"]
            if isinstance(err, str) and err.lstrip().startswith("["):
                err = json.loads(err)
            if isinstance(err, list):
                dettaglio = str([x.get("path") for x in err])[:80]
            else:
                dettaglio = str(err)[:80]
        except Exception:
            dettaglio = corpo[:80]
        return e.code, dettaglio


def accettato(domanda):
    """True se lo schema e' valido.

    Un 429 conta come valido: significa che la richiesta ha superato
    la validazione e si e' fermata al rate limit. Un 400 no: lo schema
    e' sbagliato. E' il trucco che permette di mappare il contratto
    anche a tetto raggiunto.
    """
    codice, _ = _chiedi(domanda)
    return codice in (200, 429)


print("[1] Il tipo `noul` vuole `instructions`")
check("noul da solo non basta", not accettato({"type": "noul"}),
      "accettato senza istruzioni")
check("instructions come stringa va bene",
      accettato({"type": "noul", "instructions": "scegli"}))
check("come lista va bene", accettato({"type": "noul", "instructions": ["a", "b"]}))
check("come oggetto va bene", accettato({"type": "noul", "instructions": {"a": 1}}))

print("\n[2] Il tipo `choice` vuole `criteria` come oggetto")
check("choice da solo non basta", not accettato({"type": "choice"}))
check("criteria come oggetto va bene",
      accettato({"type": "choice", "instructions": "scegli",
                 "criteria": {"a": "migliore"}}))
check("criteria come lista NO — un record, non un array",
      not accettato({"type": "choice", "instructions": "scegli",
                     "criteria": ["a", "b"]}))

print("\n[3] Il tipo `score` vuole `criteria` come lista")
check("score da solo non basta", not accettato({"type": "score"}))
check("criteria come lista va bene",
      accettato({"type": "score", "instructions": "valuta",
                 "criteria": ["a", "b"]}))
check("criteria come oggetto NO",
      not accettato({"type": "score", "instructions": "valuta",
                     "criteria": {"a": "x"}}))

print("\n[4] I campi comuni")
check("manca il tipo", not accettato({"instructions": "x"}),
      "una domanda senza type passa: e' una scelta che spetta al chiamante")

# state mancante: l'errore dice "state", ed e' un 400 e non un tetto.
# Se fosse un 429 il tetto avrebbe coperto la verifica e non sapremmo
# niente — ed e' il caso in cui il test mentirebbe dicendo "obbligatorio".
env = load_env(os.path.join(os.getcwd(), "orchestra", ".env"))
req = urllib.request.Request(
    URL, data=json.dumps({"model": MODELLO,
                          "questions": {"q?": {"type": "noul",
                                               "instructions": "i"}}}).encode(),
    headers={"Authorization": "Bearer " + env.get("OPENROUTER_API_KEY", ""),
             "Content-Type": "application/json"})
codice_senza, corpo_senza = 200, ""
try:
    urllib.request.urlopen(req, timeout=30)
except urllib.error.HTTPError as e:
    codice_senza = e.code
    corpo_senza = e.read().decode("utf-8", "replace")
check("senza state e' rifiutato dallo schema", codice_senza == 400,
      f"HTTP {codice_senza}: se fosse 429 il tetto coprirebbe la verifica "
      f"e il test direbbe 'obbligatorio' senza saperlo")
check("e l'errore nomina proprio 'state'", "state" in corpo_senza,
      corpo_senza[:100])

print("\n[5] Lo schema completo, in una riga")
SCHEMA = {
    "model": "inception/mercury-decide:free",
    "state": {"qualsiasi": "oggetto con lo stato della decisione"},
    "questions": {
        "<domanda in chiaro>": {
            "type": "noul | choice | score",
            "instructions": "stringa | lista | oggetto",
            "criteria": "choice: oggetto   score: lista",
        }
    },
}
print("  " + json.dumps(SCHEMA)[:200])
print("\n  Non verificato: la FORMA della risposta. Il tetto giornaliero")
print("  (429 free-models-per-day-high-balance) e' gia' stato raggiunto,")
print("  quindi non ho visto un risultato vero. Quello che so e' che la")
print("  richiesta e' valida — non com'e' risposta.")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
