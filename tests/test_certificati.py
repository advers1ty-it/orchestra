"""I certificati e la riga di comando che l'installer usa.

Due difetti chiusi qui, e uno e' la ragione per cui questo file esiste.

**I certificati.** Un Windows appena installato non ha tutte le autorita' di
certificazione: le porta Windows Update. Orchestra le prende dal trust store
di sistema e non ha un elenco suo, quindi se manca la root `Go Daddy Root
Certificate Authority - G2` il comando `certificate verify failed:
self-signed certificate in certificate chain` arriva all'utente come "rete
non raggiungibile" — perche' Telegram manda la catena completa, root
self-signed inclusa. Il test verifica che l'impronta richiesta sia quella
vera, che chi manca sia detto con il nome giusto, e che il referto sia
ASCII: la console dell'installer non e' UTF-8 e un trattino lungo la fa
morire con UnicodeEncodeError.

**La riga di comando.** Serve all'installer per non avere una seconda lista
di dipendenze dentro un `.bat`. Il test la esegue con `subprocess`, come fa
l'installer, e verifica il formato: un campo per colonna, quattro colonne.

I due moduli si caricano **per percorso**, senza `import orchestra`: devono
girare da soli, e un test che passa dal pacchetto non se ne accorgerebbe.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def carica(nome_file: str):
    percorso = os.path.join(ROOT, "orchestra", nome_file)
    spec = importlib.util.spec_from_file_location(nome_file[:-3], percorso)
    modulo = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(modulo)
    return modulo


cert = carica("certificati.py")
dep = carica("dipendenze.py")


print("\n[1] Le radici richieste sono descritte per intero")
check("la lista non e' vuota", bool(cert.RADICI), str(cert.RADICI))
for voce in cert.RADICI:
    for campo in ("nome", "sha1", "host", "perche"):
        check(f"{voce.get('nome')}: c'e' {campo}", bool(voce.get(campo)),
              str(voce))
    impronta = (voce.get("sha1") or "").upper()
    check(f"{voce.get('nome')}: l'impronta e' uno SHA-1",
          len(impronta) == 40 and all(c in "0123456789ABCDEF" for c in impronta),
          impronta)

print("\n[2] Lo stato dice quali ci sono e quali mancano")
dati = cert.stato()
check("lo store e' dichiarato", dati.get("store") in ("Windows ROOT",
                                                      "non disponibile"),
      str(dati.get("store")))
check("una voce per ogni radice richiesta",
      len(dati["radici"]) == len(cert.RADICI), str(len(dati["radici"])))
check("ogni voce dice se c'e'", all("presente" in v for v in dati["radici"]),
      str(dati["radici"]))
check("i mancanti sono esattamente le voci assenti",
      dati["mancanti"] == [v["nome"] for v in dati["radici"]
                           if not v["presente"]],
      str(dati["mancanti"]))
if sys.platform.startswith("win"):
    # Fatto, non ipotesi: su questa macchina la radice c'e' (l'ha verificata
    # a mano il 2026-11-11 contro la catena vera di api.telegram.org).
    # Se questo check fallisce su un'altra macchina, quella macchina ha lo
    # store incompleto: e' il difetto che il modulo serve a trovare.
    check("su questa macchina le radici richieste ci sono",
          dati["mancanti"] == [], str(dati["mancanti"]))
else:
    check("fuori da Windows non c'e' uno store da interrogare",
          dati["store"] == "non disponibile", str(dati.get("store")))

print("\n[3] Una radice assente si vede, e si dice come rimediare")
finta = ({"nome": "Radice Inventata", "sha1": "00" * 20,
          "host": "esempio.invalid", "perche": "solo per il test"},)
rotto = cert.stato(radici=finta)
check("risulta mancante", rotto["mancanti"] == ["Radice Inventata"],
      str(rotto["mancanti"]))
referto = cert.report(rotto)
check("il referto la nomina", "Radice Inventata" in referto, referto)
check("il referto dice come si installa", "certutil" in referto, referto)
check("il referto e' ASCII (la console dell'installer non e' UTF-8)",
      referto.isascii(), repr(referto[:200]))
referto_ok = cert.report(dati)
check("con tutto a posto il referto e' ASCII anche lui",
      referto_ok.isascii(), repr(referto_ok[:200]))

print("\n[4] Il modulo si esegue da solo, come fa l'installer")
script = os.path.join(ROOT, "orchestra", "certificati.py")
esito = subprocess.run([sys.executable, script, "--json"], text=True,
                       capture_output=True, timeout=120)
check("--json risponde", esito.returncode in (0, 1),
      f"rc={esito.returncode} {esito.stderr[:200]}")
try:
    dati_cli = json.loads(esito.stdout)
    letto = True
except Exception as e:  # noqa: BLE001
    dati_cli, letto = {}, False
    print(f"    (json non valido: {e})")
check("--json e' JSON valido", letto, esito.stdout[:200])
check("--json porta le stesse radici", bool(dati_cli.get("radici")),
      str(dati_cli)[:200])
check("il codice di uscita segue i mancanti",
      esito.returncode == (1 if dati_cli.get("mancanti") else 0),
      f"rc={esito.returncode} mancanti={dati_cli.get('mancanti')}")
prova = subprocess.run([sys.executable, script, "--prova", "esempio.invalid"],
                       text=True, capture_output=True, timeout=60)
check("--prova distingue la rete dal certificato",
      prova.returncode == 1 and "rete non raggiungibile" in prova.stdout,
      f"rc={prova.returncode} {prova.stdout[:200]}")

print("\n[5] L'elenco delle dipendenze e' leggibile da un .bat")
script_dep = os.path.join(ROOT, "orchestra", "dipendenze.py")
elenco = subprocess.run([sys.executable, script_dep, "--elenco"], text=True,
                        capture_output=True, timeout=120)
check("--elenco risponde", elenco.returncode == 0,
      f"rc={elenco.returncode} {elenco.stderr[:300]}")
righe = [r for r in elenco.stdout.splitlines() if r.strip()]
check("una riga per dipendenza", len(righe) >= 3, str(righe))
check("quattro campi per riga (nome|stato|via|perche)",
      all(len(r.split("|")) == 4 for r in righe), str(righe[:3]))
nomi = [r.split("|")[0].lower() for r in righe]
for atteso in ("ddgs", "pillow", "pypdf"):
    check(f"c'e' {atteso}", atteso in nomi, str(nomi))
check("le opzionali ci sono", "faster-whisper" in nomi, str(nomi))
check("le di sistema ci sono, con la loro via",
      any(r.split("|")[2] == "winget" for r in righe), str(righe[:3]))
check("ogni riga dice a cosa serve", all(r.split("|")[3].strip()
                                        for r in righe), str(righe[:3]))
check("l'elenco e' ASCII (lo legge cmd, non un browser)",
      elenco.stdout.isascii(), repr(elenco.stdout[:200]))

print("\n[6] Gli errori d'uso non inventano comandi")
vuoto = subprocess.run([sys.executable, script_dep, "--installa"], text=True,
                       capture_output=True, timeout=60)
check("--installa senza nomi: 2", vuoto.returncode == 2,
      f"rc={vuoto.returncode} {vuoto.stderr[:200]}")
ignoto = subprocess.run([sys.executable, script_dep, "--installa",
                         "pacchetto-inventato"], text=True,
                        capture_output=True, timeout=120)
check("un nome inventato: 1 e lo dice",
      ignoto.returncode == 1 and "sconosciuta" in ignoto.stderr,
      f"rc={ignoto.returncode} {ignoto.stderr[:200]}")

print("\n" + "=" * 62)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
