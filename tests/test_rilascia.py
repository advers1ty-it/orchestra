"""`tools/rilascia.py`: una release, con tutti e due gli asset.

La 0.5.99 e' uscita con il solo zip perche' "quali file allegare" era una
cosa da ricordare. Questo test esegue il comando vero in un repository usa
e getta e guarda cosa resta dopo: versione, note, commit, zip (radice
unica, versione dentro), tag, e la riga di `gh` con dentro anche
l'installer. Niente rete: `--senza-push --senza-release` fermano il giro
prima di toccare GitHub.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import rilascia  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" -- {dettaglio}" if dettaglio and not cond else ""))


def git(cwd: str, *argomenti: str) -> str:
    r = subprocess.run(["git", *argomenti], cwd=cwd, capture_output=True,
                       text=True)
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(argomenti)}: {r.stderr}")
    return (r.stdout or "").strip()


def repo_finto() -> str:
    """Un repository minimo, con i file che servono a una release."""
    cartella = tempfile.mkdtemp(prefix="orch_rel_")
    git(cartella, "init", "-b", "master")
    git(cartella, "config", "user.email", "test@example.invalid")
    git(cartella, "config", "user.name", "Prova")
    os.makedirs(os.path.join(cartella, "orchestra"))
    os.makedirs(os.path.join(cartella, "installer"))
    with open(os.path.join(cartella, "orchestra", "__init__.py"), "w",
              encoding="utf-8") as f:
        f.write('"""Orchestra."""\n\n__version__ = "0.5.99"\n')
    with open(os.path.join(cartella, "installer",
                           "Installa-Orchestra.bat"), "w",
              encoding="utf-8") as f:
        f.write("@echo off\r\nREM installer\r\n")
    with open(os.path.join(cartella, "README.md"), "w",
              encoding="utf-8") as f:
        f.write("# prova\n")
    git(cartella, "add", "-A")
    git(cartella, "commit", "-m",
        "Prima cosa fatta", "-m", "Il perche' della prima cosa.")
    return cartella


def leggi(percorso: str) -> str:
    with open(percorso, encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------ le funzioni pure
print("\n[1] Versione, titolo e note")

check("la patch sale di uno, senza salti di minor",
      rilascia.versione_successiva("0.5.99") == "0.5.100",
      rilascia.versione_successiva("0.5.99"))
try:
    rilascia.versione_successiva("0.5")
    check("una versione corta viene rifiutata", False)
except SystemExit:
    check("una versione corta viene rifiutata", True)

titolo = rilascia.titolo_da_note(
    "# v0.5.99 — Telegram per più persone\n\nTesto.\n")
check("il titolo si prende dalla prima riga", titolo == "Telegram per più "
      "persone", titolo)
check("senza titolo non si inventa niente",
      rilascia.titolo_da_note("solo testo") == "")

note = rilascia.note_da_commit([
    ("abc1234", "Il fallback e' manuale", "Spiegazione.\n\n"
     "Generated with Codebuff 🤖\nCo-Authored-By: Codebuff <x@y>"),
], "0.5.100", "Un titolo", "v0.5.99")
check("le note hanno il titolo giusto", note.startswith("# v0.5.100 — Un titolo"),
      note.splitlines()[:1])
check("dicono da dove vengono", "v0.5.99" in note, note[:200])
check("un paragrafo per commit", "## Il fallback e' manuale" in note)
check("con il perche' del commit", "Spiegazione." in note)
check("senza l'attribuzione di Codebuff",
      "Codebuff" not in note, note)
check("e senza riga di chiusura vuota", note.endswith("\n")
      and not note.endswith("\n\n"))

comando = rilascia.comando_release(
    "0.5.100", "Un titolo", "release-notes-v0.5.100.md",
    "orchestra-0.5.100.zip",
    os.path.join("installer", "Installa-Orchestra.bat"))
check("il titolo finisce nel nome della release",
      "v0.5.100 — Un titolo" in comando, str(comando))
check("la riga di gh ha lo zip", "orchestra-0.5.100.zip" in comando,
      str(comando))
check("e l'installer, sempre",
      comando[-1].endswith(os.path.join("installer", "Installa-Orchestra.bat")),
      str(comando[-1:]))

# ------------------------------------------------ il giro vero, in locale
print("\n[2] Il giro completo in locale (senza GitHtub)")

cartella = repo_finto()
vecchia = os.getcwd()
try:
    os.chdir(cartella)
    codice = rilascia.main(["0.5.100", "--senza-push", "--senza-release"])
    check("il comando finisce bene", codice == 0, str(codice))

    versione = leggi(os.path.join(cartella, "orchestra", "__init__.py"))
    check("la versione e' scritta nel pacchetto",
          '__version__ = "0.5.100"' in versione, versione)
    check("e il resto del file e' intatto",
          versione.startswith('"""Orchestra."""'), versione)

    note_path = os.path.join(cartella, "release-notes-v0.5.100.md")
    check("le note sono state create", os.path.isfile(note_path))
    testo_note = leggi(note_path) if os.path.isfile(note_path) else ""
    check("e partono dai commit dopo l'ultimo tag",
          "Prima cosa fatta" in testo_note, testo_note[:200])
    check("il titolo viene dal primo commit",
          testo_note.startswith("# v0.5.100 — Prima cosa fatta"),
          testo_note.splitlines()[:1])

    ultimo = git(cartella, "log", "-1", "--format=%s")
    check("il commit dice versione e titolo",
          ultimo.startswith("Versione 0.5.100:"), ultimo)
    check("e contiene solo i due file della release",
          sorted(git(cartella, "show", "--name-only", "--format=").split())
          == ["orchestra/__init__.py", "release-notes-v0.5.100.md"],
          git(cartella, "show", "--name-only", "--format="))

    zip_path = os.path.join(cartella, "orchestra-0.5.100.zip")
    check("lo zip c'e'", os.path.isfile(zip_path))
    if os.path.isfile(zip_path):
        with zipfile.ZipFile(zip_path) as z:
            nomi = [n for n in z.namelist() if not n.endswith("/")]
            radici = {n.split("/")[0] for n in nomi}
            dentro = z.read("orchestra-0.5.100/orchestra/__init__.py"
                            ).decode("utf-8")
        check("con una radice sola", radici == {"orchestra-0.5.100"},
              str(radici))
        check("e la versione giusta dentro",
              '__version__ = "0.5.100"' in dentro,
              [l for l in dentro.splitlines() if "__version__" in l])

    tag = git(cartella, "tag", "--list", "v0.5.100")
    check("il tag e' stato creato", tag == "v0.5.100", tag)
    check("ed e' un tag annotato",
          git(cartella, "cat-file", "-t", "v0.5.100") == "tag",
          git(cartella, "cat-file", "-t", "v0.5.100"))
    check("l'albero e' pulito dopo la release",
          git(cartella, "status", "--porcelain",
              "--untracked-files=no") == "",
          git(cartella, "status", "--porcelain", "--untracked-files=no"))

    print("\n[3] Un secondo giro non rifa' la stessa release")
    try:
        rilascia.main(["0.5.100", "--senza-push", "--senza-release"])
        check("lo stesso numero di versione viene rifiutato", False)
    except SystemExit as e:
        check("lo stesso numero di versione viene rifiutato",
              "esiste gia'" in str(e), str(e))
finally:
    os.chdir(vecchia)
    shutil.rmtree(cartella, ignore_errors=True)

print("\n[4] La prova non scrive niente")

cartella = repo_finto()
vecchia = os.getcwd()
try:
    os.chdir(cartella)
    prima = leggi(os.path.join(cartella, "orchestra", "__init__.py"))
    # `--senza-release` anche qui: senza remote la prova non puo'
    # controllare i tag di GitHub, e girerebbe a vuoto per un motivo che
    # non c'entra con cio' che si sta verificando.
    codice = rilascia.main(["--prova", "--senza-release"])
    check("la prova finisce bene", codice == 0, str(codice))
    check("la versione non e' cambiata",
          leggi(os.path.join(cartella, "orchestra", "__init__.py")) == prima)
    check("nessun commit nuovo",
          git(cartella, "log", "--oneline").count("\n") == 0,
          git(cartella, "log", "--oneline"))
    check("nessun tag",
          git(cartella, "tag", "--list") == "",
          git(cartella, "tag", "--list"))
    check("nessuno zip",
          not [n for n in os.listdir(cartella) if n.endswith(".zip")],
          str(os.listdir(cartella)))
finally:
    os.chdir(vecchia)
    shutil.rmtree(cartella, ignore_errors=True)

print("\n[5] Senza installer la release non parte")

cartella = repo_finto()
vecchia = os.getcwd()
try:
    os.chdir(cartella)
    os.remove(os.path.join(cartella, "installer", "Installa-Orchestra.bat"))
    git(cartella, "add", "-A")
    git(cartella, "commit", "-m", "Senza installer")
    try:
        rilascia.main(["0.5.100", "--senza-push", "--senza-release"])
        check("il comando rifiuta di pubblicare senza installer", False)
    except SystemExit as e:
        check("il comando rifiuta di pubblicare senza installer",
              "installer" in str(e).lower(), str(e))
    check("e non ha lasciato un tag a meta'",
          git(cartella, "tag", "--list") == "",
          git(cartella, "tag", "--list"))
finally:
    os.chdir(vecchia)
    shutil.rmtree(cartella, ignore_errors=True)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("falliti:", FAIL)
sys.exit(1 if FAIL else 0)
