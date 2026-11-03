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

print("\n[5] Integrita': asset, digest, zip-slip")

rel = {"zipball_url": "https://api.github.com/zipball",
       "assets": [{"name": "orchestra-0.6.0.zip",
                   "browser_download_url": "https://example.test/a.zip",
                   "digest": "sha256:abc123"}]}
check("l'asset vince sullo zipball",
      U.scegli_asset(rel) == "https://example.test/a.zip")
check("il digest dell'asset viene letto",
      U._asset_scelto(rel) == ("https://example.test/a.zip", "abc123"))
solo_zipball = {"zipball_url": "https://api.github.com/zipball", "assets": []}
check("senza asset si usa lo zipball",
      U.scegli_asset(solo_zipball) == "https://api.github.com/zipball")
check("lo zipball non ha digest dichiarato",
      U._asset_scelto(solo_zipball)[1] == "")

# Un archivio valido: il digest giusto passa, quello sbagliato no.
buono = os.path.join(tempfile.mkdtemp(prefix="dl-"), "buono.zip")
with zipfile.ZipFile(buono, "w") as z:
    z.writestr("radice/file.txt", "x")
import hashlib  # noqa: E402
with open(buono, "rb") as fh:
    giusto = hashlib.sha256(fh.read()).hexdigest()
dest = os.path.join(tempfile.mkdtemp(prefix="dl-"), "scarico.zip")
url = "file:///" + buono.replace("\\", "/")
check("con il digest giusto scarica",
      U.scarica(url, None, dest, giusto) == giusto)
try:
    U.scarica(url, None, dest, "0" * 64)
    check("con il digest sbagliato rifiuta", False, "accettato")
except U.UpdateError as e:
    check("con il digest sbagliato rifiuta", "sha256" in str(e), str(e))

# GitHub che risponde HTML invece dello zip.
html = os.path.join(tempfile.mkdtemp(prefix="dl-"), "errore.html")
with open(html, "w", encoding="utf-8") as fh:
    fh.write("<html>rate limit</html>")
try:
    U.scarica("file:///" + html.replace("\\", "/"), None,
              dest, "")
    check("un corpo HTML non passa per zip", False, "accettato")
except U.UpdateError as e:
    check("un corpo HTML non passa per zip", "non e' uno zip" in str(e),
          str(e))

# Zip-slip: un percorso che esce dalla cartella viene rifiutato PRIMA di
# estrarre, non riparato in silenzio.
slip = os.path.join(tempfile.mkdtemp(prefix="rel-"), "slip.zip")
with zipfile.ZipFile(slip, "w") as z:
    z.writestr("radice/../../fuori.txt", "x")
try:
    U.applica(slip, root)
    check("zip-slip rifiutato", False, "accettato")
except U.UpdateError as e:
    check("zip-slip rifiutato", "esce dalla cartella" in str(e), str(e))
check("l'estrazione non ha scritto fuori",
      not os.path.exists(os.path.join(os.path.dirname(root), "fuori.txt")))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
