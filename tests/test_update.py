"""Update da GitHub: confronto versioni, apply dello zip, conserve.

Niente rete qui: lo zip release e' costruito a mano, e il token si
prova su file/env. La rete vera resta al CLI provato a mano.
"""

import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import update as U  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("[1] Versioni dai tag")
check("v davanti tolta", U.versione_da_tag("v0.6.0") == "0.6.0")
check("senza v resta", U.versione_da_tag("0.6.0") == "0.6.0")
check("vuoto resta vuoto", U.versione_da_tag("") == "")

print("\n[2] Token: env vince, poi token.txt, poi errore")
os.environ["ORCHESTRA_UPDATE_TOKEN"] = "  abc  "
check("env con spazi puliti", U.leggi_token() == "abc")
del os.environ["ORCHESTRA_UPDATE_TOKEN"]
tmp = tempfile.mkdtemp(prefix="token-")
with open(os.path.join(tmp, "token.txt"), "w", encoding="utf-8") as fh:
    fh.write("tokenda-file\nseconda-riga-ignorata\n")
cwd = os.getcwd()
os.chdir(tmp)
try:
    check("letto da token.txt", U.leggi_token() == "tokenda-file")
finally:
    os.chdir(cwd)
os.chdir(tempfile.mkdtemp(prefix="vuota-"))
try:
    try:
        U.leggi_token()
        check("senza token errore", False, "nessun errore")
    except U.UpdateError as e:
        check("senza token errore", "token" in str(e).lower(), str(e))
finally:
    os.chdir(cwd)

print("\n[3] Apply: nuovi file entrano, i conservati restano")
root = tempfile.mkdtemp(prefix="install-")
os.makedirs(os.path.join(root, "orchestra"))
with open(os.path.join(root, "orchestra", ".env"), "w", encoding="utf-8") as fh:
    fh.write("CHIAVE_MIA=1")
with open(os.path.join(root, "token.txt"), "w", encoding="utf-8") as fh:
    fh.write("mio-token")
with open(os.path.join(root, "orchestra", "vecchio.py"), "w", encoding="utf-8") as fh:
    fh.write("vecchio")
zip_path = os.path.join(tempfile.mkdtemp(prefix="rel-"), "rel.zip")
with zipfile.ZipFile(zip_path, "w") as z:
    z.writestr("advers1ty-it-orchestra-abc123/orchestra/nuovo.py", "nuovo")
    z.writestr("advers1ty-it-orchestra-abc123/orchestra/vecchio.py", "aggiornato")
    z.writestr("advers1ty-it-orchestra-abc123/orchestra/.env", "CHIAVE_NUOVA=2")
    z.writestr("advers1ty-it-orchestra-abc123/token.txt", "token-nuovo")
esito = U.applica(zip_path, root)
check("due file applicati", esito["file"] == 2, str(esito))
with open(os.path.join(root, "orchestra", "nuovo.py"), encoding="utf-8") as fh:
    check("nuovo file presente", fh.read() == "nuovo")
with open(os.path.join(root, "orchestra", "vecchio.py"), encoding="utf-8") as fh:
    check("vecchio sovrascritto", fh.read() == "aggiornato")
with open(os.path.join(root, "orchestra", ".env"), encoding="utf-8") as fh:
    check(".env conservato", fh.read() == "CHIAVE_MIA=1")
with open(os.path.join(root, "token.txt"), encoding="utf-8") as fh:
    check("token conservato", fh.read() == "mio-token")
check("backup creato", bool(esito.get("backup")), str(esito))

print("\n[4] Zip malformati rifiutati")
vuoto = os.path.join(tempfile.mkdtemp(prefix="rel-"), "vuoto.zip")
with zipfile.ZipFile(vuoto, "w") as z:
    z.writestr("file-senza-radice.txt", "x")
try:
    U.applica(vuoto, root)
    check("zip senza radice rifiutato", False, "accettato")
except U.UpdateError:
    check("zip senza radice rifiutato", True)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
