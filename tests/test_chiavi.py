"""Il menu Opzioni scrive le chiavi. Questo controlla che lo faccia bene.

Il pericolo e' reale, non ipotetico: il server sta su 127.0.0.1 senza
autenticazione, quindi chiunque raggiunga la porta puo' fare richieste.
Un editor di chiavi che espone i valori, o che accetta nomi arbitrari,
trasformerebbe la porta locale in un buco.

I test qui sotto sono scritti per fallire se una di queste regole
cede, non per documentare che funzionano.
"""

import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import keys as K  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


# Una chiave finta ma SOMIGLIANTE a una vera: se questa finisce in un
# file, in una risposta o in un log, il test fallisce.
SEGRETO = "sk-or-v1-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJKKKK9999"
ALTRO = "sk-ant-1111-2222-3333-4444-5555-6666-7777-8888-9999"

print("\n[1] stato() non restituisce mai il valore")
tmp = tempfile.mkdtemp()
env_path = os.path.join(tmp, ".env")
K.scrivi(env_path, "OPENROUTER_API_KEY", SEGRETO)
vals = {"OPENROUTER_API_KEY": SEGRETO}
stato = K.stato(env_path, vals)
testo = json.dumps(stato)
check("il segreto non compare nel JSON", SEGRETO not in testo)
check("il segreto non compare in nessun campo",
      not any(SEGRETO in str(v) for r in stato for v in r.values()))
check("dice solo se e' presente", stato[0]["presente"] is True)
check("l'indizio sono 4 caratteri",
      len(stato[0]["indizio"]) <= 7 and SEGRETO[-4:] in stato[0]["indizio"],
      stato[0]["indizio"])
check("la lunghezza e' nota ma il valore no", stato[0]["lunghezza"] == len(SEGRETO))
# nemmeno un pezzo lungo del segreto
for n in (8, 12, 16):
    check(f"nessun prefisso di {n} caratteri",
          SEGRETO[:n] not in testo)

print("\n[2] Whitelist: si scrive solo cio' che Orchestra usa")
ok, msg = K.scrivi(env_path, "PATH", "/usr/bin")
check("una chiave fuori lista viene respinta", not ok, msg)
ok, _ = K.scrivi(env_path, "LD_PRELOAD", "/tmp/x.so")
check("una variabile pericolosa viene respinta", not ok)
ok, _ = K.scrivi(env_path, "ORCHESTRA_MODEL", "some/model:free")
check("un'impostazione ammessa viene accettata", ok)
contenuto = open(env_path, encoding="utf-8").read()
check("quella riga non e' finita nel file", "LD_PRELOAD" not in contenuto)

print("\n[3] Un valore non puo' rompere la struttura del file")
prima = open(env_path, encoding="utf-8").read()
ok, msg = K.scrivi(env_path, "GROQ_API_KEY", "abc\nEVIL=1")
check("un a capo nel valore viene respinto", not ok, msg)
ok, msg = K.scrivi(env_path, "GROQ_API_KEY", "abc\rdef")
check("un ritorno carrello viene respinto", not ok)
ok, _ = K.scrivi(env_path, "GROQ_API_KEY", "x" * 900)
check("un valore enorme viene respinto", not ok)
check("il file non e' cambiato",
      open(env_path, encoding="utf-8").read() == prima)

print("\n[4] Scrivere non perde il resto del file")
K.scrivi(env_path, "OPENROUTER_API_KEY", SEGRETO)
K.scrivi(env_path, "MISTRAL_API_KEY", ALTRO)
testo = open(env_path, encoding="utf-8").read()
check("la prima chiave c'e' ancora", SEGRETO in testo)
check("la seconda c'e' anche", ALTRO in testo)

print("\n[5] Rileggere restituisce quello che si e' scritto")
vals2 = {}
for riga in testo.splitlines():
    riga = riga.strip()
    if not riga or riga.startswith("#") or "=" not in riga:
        continue
    k, _, v = riga.partition("=")
    vals2[k.strip()] = v.strip()
check("OPENROUTER rileggibile", vals2.get("OPENROUTER_API_KEY") == SEGRETO)
check("MISTRAL rileggibile", vals2.get("MISTRAL_API_KEY") == ALTRO)

print("\n[6] Commenti e spazi sopravvivono")
p2 = os.path.join(tmp, "b.env")
with open(p2, "w", encoding="utf-8") as f:
    f.write("# mio commento\n\nexport MISTRAL_API_KEY=" + ALTRO + "\n")
K.scrivi(p2, "GROQ_API_KEY", "gsk-prova")
t2 = open(p2, encoding="utf-8").read()
check("il commento personale c'e' ancora", "# mio commento" in t2)
check("la riga con export e' stata aggiornata", "gsk-prova" in t2)
check("non ci sono due MISTRAL",
      t2.count("MISTRAL_API_KEY") == 1, str(t2.count("MISTRAL_API_KEY")))

print("\n[7] Cancellare toglie la riga invece di lasciarla vuota")
K.scrivi(p2, "MISTRAL_API_KEY", "")
t3 = open(p2, encoding="utf-8").read()
check("MISTRAL e' sparito", "MISTRAL_API_KEY" not in t3)
check("GROQ e' rimasto", "gsk-prova" in t3)
check("il commento e' rimasto", "# mio commento" in t3)

print("\n[8] Sovrascrittura atomica: nessun file temporaneo lasciato")
before = set(os.listdir(tmp))
K.scrivi(p2, "GROQ_API_KEY", "nuovo")
after = set(os.listdir(tmp))
check("nessun .env temporaneo rimasto", before == after, str(after - before))

print("\n[9] I consigli sui servizi gratis sono completi")
check("i servizi sono elencati", len(K.FREE_SERVICES) >= 5, str(len(K.FREE_SERVICES)))
check("ogni servizio dice se serve la chiave",
      all("chiave" in s for s in K.FREE_SERVICES))
check("ogni servizio dice come iniziare",
      all(s.get("come") for s in K.FREE_SERVICES))
check("i servizi senza chiave ci sono",
      any(not s["chiave"] for s in K.FREE_SERVICES))
check("c'e' una data sui limiti", "2026" in K.NOTA_FREE)
check("nessun servizio ha una chiave vera dentro",
      not any("sk-" in str(s) for s in K.FREE_SERVICES))

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
