"""Una release in un comando solo, con ENTRAMBI gli asset.

PERCHE' ESISTE

La 0.5.99 e' uscita con il solo zip. L'installer era nel repository, la
release prima lo allegava, e quella dopo no: "quali asset vanno sulla
release" era una cosa da ricordare, e ricordarsela e' esattamente il
passo che si salta quando si e' di fretta. Qui gli asset sono una
costante — lo zip e `installer/Installa-Orchestra.bat` — e alla fine si
rilegge la release per pretendere che ci siano davvero tutti e due.

    python tools/rilascia.py                 # patch +1, note dal repository
    python tools/rilascia.py 0.6.0           # versione esplicita
    python tools/rilascia.py --prova         # dice cosa farebbe, non scrive
    python tools/rilascia.py --senza-push --senza-release

I passi, in ordine: controlli (ramo, albero pulito, tag libero) → versione
in `orchestra/__init__.py` → note (`release-notes-v<ver>.md`, costruite
dai commit se mancano) → commit e push → zip da `git archive HEAD` (la
verifica della radice e della versione sta in `genera_release.py`) → tag e
push del tag → `gh release create` con zip e installer → lettura della
release per controllare gli asset.

Se un passo fallisce ci si ferma li', senza inventare un "fatto": un tag
senza release o una release senza installer sono peggio di un comando
interrotto, perche' sembrano riusciti.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import genera_release  # noqa: E402

# L'installer non si rigenera a ogni versione (legge `releases/latest`),
# ma va allegato: senza, chi arriva dalla pagina delle release non ha da
# dove partire.
INSTALLER = os.path.join("installer", "Installa-Orchestra.bat")


class ErroreRelease(SystemExit):
    """Un passo non e' riuscito: niente da fare se non leggerlo."""


def esegui(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def git(root: str, *argomenti: str) -> str:
    r = esegui(["git", *argomenti], root)
    if r.returncode != 0:
        raise ErroreRelease(f"git {' '.join(argomenti)}: "
                            f"{(r.stderr or r.stdout).strip()}")
    return (r.stdout or "").strip()


def versione_attuale(root: str) -> str:
    return genera_release.versione(root)


def versione_successiva(v: str) -> str:
    """La patch successiva: 0.5.99 -> 0.5.100 (non 0.6.0).

    Una versione scritta a mano resta possibile; questa e' solo il
    default, e deve essere prevedibile: chi non passa niente si aspetta
    un +1, non un salto di minor.
    """
    parti = (v or "").strip().split(".")
    if len(parti) != 3 or not all(p.isdigit() for p in parti):
        raise ErroreRelease(f"versione non riconosciuta: {v!r} "
                            "(atteso qualcosa come 0.5.99)")
    return f"{parti[0]}.{parti[1]}.{int(parti[2]) + 1}"


def scrivi_versione(root: str, ver: str) -> None:
    percorso = os.path.join(root, "orchestra", "__init__.py")
    with open(percorso, encoding="utf-8") as f:
        testo = f.read()
    nuovo, quante = re.subn(
        r"""(__version__\s*=\s*["'])([^"']+)(["'])""",
        lambda m: m.group(1) + ver + m.group(3), testo, count=1)
    if not quante:
        raise ErroreRelease("__version__ non trovato in orchestra/__init__.py")
    with open(percorso, "w", encoding="utf-8", newline="") as f:
        f.write(nuovo)


def titolo_da_note(testo: str) -> str:
    """Il titolo e' la prima riga che comincia con `# `, senza la versione.

    Le note sono gia' scritte per essere lette: prendere il titolo da li'
    evita che il nome della release e il documento si contraddicano.
    """
    for riga in (testo or "").splitlines():
        riga = riga.strip()
        if riga.startswith("# "):
            titolo = riga[2:].strip()
            return re.sub(r"^v?\d+(\.\d+)*\s*[—-]\s*", "", titolo).strip()
    return ""


def _pulisci_corpo(corpo: str) -> str:
    """Toglie le righe di attribuzione dai messaggi dei commit."""
    tenute = [r for r in (corpo or "").splitlines()
              if not r.strip().startswith(("🤖", "Co-Authored-By: Codebuff",
                                          "Generated with Codebuff"))]
    return "\n".join(tenute).strip()


def note_da_commit(voci: list[tuple[str, str, str]], ver: str,
                   titolo: str, da: str) -> str:
    """Le note minime: un paragrafo per commit, con il suo perche'.

    I messaggi dei commit qui spiegano gia' il perche' (e' la regola del
    repository), quindi non si inventa prosa: si impagina quella che c'e'
    e si dice che va riletta.
    """
    righe = [f"# v{ver} — {titolo}", ""]
    if da:
        righe += [f"_Note costruite dai messaggi dei commit dopo `{da}`: "
                  "rileggile prima di pubblicarle._", ""]
    for _hash, oggetto, corpo in voci:
        righe.append(f"## {oggetto}")
        righe.append("")
        pulito = _pulisci_corpo(corpo)
        if pulito:
            righe.append(pulito)
            righe.append("")
    return "\n".join(righe).rstrip() + "\n"


def commit_da_ultimo_tag(root: str) -> tuple[list[tuple[str, str, str]], str]:
    """I commit dopo l'ultimo tag, e il tag stesso (vuoto se non ce n'e')."""
    try:
        ultimo = git(root, "describe", "--tags", "--abbrev=0")
    except ErroreRelease:
        ultimo = ""
    intervallo = f"{ultimo}..HEAD" if ultimo else "HEAD"
    # Un separatore che non puo' comparire in un messaggio: 0x1f fra i
    # campi, 0x1e fra i commit.
    grezzo = git(root, "log", intervallo, "--format=%h%x1f%s%x1f%b%x1e")
    voci: list[tuple[str, str, str]] = []
    for pezzo in grezzo.split("\x1e"):
        pezzo = pezzo.strip("\n")
        if not pezzo.strip():
            continue
        campi = pezzo.split("\x1f")
        if len(campi) < 3:
            continue
        voci.append((campi[0].strip(), campi[1].strip(), campi[2]))
    return voci, ultimo


def controlla(root: str, ver: str, ramo: str, remoto: bool) -> None:
    """Tutto quello che si puo' sapere prima di scrivere qualcosa."""
    if not os.path.isdir(os.path.join(root, ".git")):
        raise ErroreRelease(f"{root} non e' un repository git")
    attuale = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if attuale != ramo:
        raise ErroreRelease(f"sei su '{attuale}', non su '{ramo}': "
                            "una release parte dal ramo giusto")
    sporco = git(root, "status", "--porcelain", "--untracked-files=no")
    if sporco:
        raise ErroreRelease("ci sono modifiche non committate:\n" + sporco
                            + "\ncommittale o mettile da parte prima.")
    installer = os.path.join(root, INSTALLER)
    if not os.path.isfile(installer) or os.path.getsize(installer) == 0:
        raise ErroreRelease(f"manca l'installer ({INSTALLER}): senza, la "
                            "release non serve a chi parte da zero")
    if esegui(["git", "rev-parse", "-q", "--verify", f"refs/tags/v{ver}"],
              root).returncode == 0:
        raise ErroreRelease(f"il tag v{ver} esiste gia'")
    if remoto:
        if shutil.which("gh") is None:
            raise ErroreRelease("`gh` non e' nel PATH: senza, la release "
                                "resta un tag senza asset")
        r = esegui(["git", "ls-remote", "--tags", "origin",
                    f"refs/tags/v{ver}"], root)
        if r.returncode != 0:
            raise ErroreRelease("non riesco a leggere i tag del remoto: "
                                f"{(r.stderr or '').strip()}")
        if (r.stdout or "").strip():
            raise ErroreRelease(f"il tag v{ver} esiste gia' sul remoto")


def comando_release(ver: str, titolo: str, note: str, zip_path: str,
                    installer: str) -> list[str]:
    """La riga di `gh release create`: zip E installer, sempre in due.

    Il titolo arriva gia' calcolato: questa funzione non rilegge le note,
    cosi' non dipende da un file che nel frattempo puo' essere stato
    tolto dal repository (le note vecchie non ci sono piu').
    """
    return ["gh", "release", "create", f"v{ver}",
            "--title", f"v{ver} — {titolo}",
            "--notes-file", note, zip_path, installer]


def _leggi(percorso: str) -> str:
    with open(percorso, encoding="utf-8") as f:
        return f.read()


def controlla_asset(ver: str, zip_path: str, installer: str,
                    root: str) -> list[str]:
    """Rilegge la release e pretende che i due asset ci siano.

    Il punto di tutto lo script e' questo controllo: `gh release create`
    puo' riuscire avendo allegato un file solo, ed e' esattamente com'e'
    andata la 0.5.99. Qui si guarda cosa c'e' davvero.
    """
    r = esegui(["gh", "release", "view", f"v{ver}", "--json",
                "assets,isDraft,isPrerelease"], root)
    if r.returncode != 0:
        raise ErroreRelease("non riesco a rileggere la release: "
                            f"{(r.stderr or '').strip()}")
    dati = json.loads(r.stdout or "{}")
    if dati.get("isDraft"):
        raise ErroreRelease(f"v{ver} e' ancora una bozza")
    presenti = {str(a.get("name")) for a in (dati.get("assets") or [])
                if a.get("state") == "uploaded"}
    attesi = {os.path.basename(zip_path), os.path.basename(installer)}
    mancanti = attesi - presenti
    if mancanti:
        raise ErroreRelease(f"sulla release mancano: {sorted(mancanti)} "
                            f"(presenti: {sorted(presenti)})")
    return sorted(attesi)


def main(argv: list[str] | None = None) -> int:
    # L'output contiene il titolo della release, che ha un trattino lungo:
    # sulla console di Windows in cp1252 diventerebbe un punto interrogativo
    # dentro un comando da copiare. Qui si scrive in UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - un output meno bello non ferma niente
        pass
    p = argparse.ArgumentParser(
        prog="rilascia",
        description="Una release: versione, note, commit, zip, tag, push e "
                    "asset (zip + installer).")
    p.add_argument("versione", nargs="?", default="",
                   help="versione esplicita (default: patch +1)")
    p.add_argument("--titolo", default="",
                   help="titolo della release (default: dalle note)")
    p.add_argument("--note", default="",
                   help="file delle note (default: release-notes-v<ver>.md)")
    p.add_argument("--ramo", default="master")
    p.add_argument("--prova", action="store_true",
                   help="mostra cosa farebbe, senza scrivere niente")
    p.add_argument("--senza-push", action="store_true")
    p.add_argument("--senza-release", action="store_true",
                   help="solo i passi locali (commit, zip, tag)")
    a = p.parse_args(argv)

    root = git_out_root()
    if a.prova:
        return _prova(root, a)

    ver = a.versione.strip() or versione_successiva(versione_attuale(root))
    ramo_ok = a.ramo
    controlla(root, ver, ramo_ok, remoto=not (a.senza_push or a.senza_release))
    print(f"[1/7] controlli ok: {versione_attuale(root)} -> {ver}")

    scrivi_versione(root, ver)
    print(f"[2/7] versione scritta in orchestra/__init__.py")

    note = (a.note or "").strip() or os.path.join(
        root, f"release-notes-v{ver}.md")
    if os.path.isfile(note):
        titolo = a.titolo.strip() or titolo_da_note(_leggi(note))
        print(f"[3/7] note: {os.path.relpath(note, root)}")
    else:
        voci, ultimo = commit_da_ultimo_tag(root)
        titolo = a.titolo.strip() or (voci[0][1] if voci
                                      else f"Versione {ver}")
        with open(note, "w", encoding="utf-8", newline="") as f:
            f.write(note_da_commit(voci, ver, titolo, ultimo))
        print(f"[3/7] note create da {len(voci)} commit: "
              f"{os.path.relpath(note, root)} (rileggile)")
    if not titolo:
        raise ErroreRelease("non riesco a ricavare un titolo: passa --titolo")

    git(root, "add", "orchestra/__init__.py",
        os.path.relpath(note, root))
    git(root, "commit", "-m", f"Versione {ver}: {titolo}.")
    print(f"[4/7] commit fatto")

    percorso_zip = genera_release.costruisci(root, ver)
    print(f"[5/7] zip: {os.path.basename(percorso_zip)} "
          f"({os.path.getsize(percorso_zip) // 1024} KB, sha256:"
          f"{genera_release.digest(percorso_zip)[:16]}...)")

    installer = os.path.join(root, INSTALLER)
    if not a.senza_push:
        git(root, "push", "origin", a.ramo)
        print(f"[6/7] push di {a.ramo}")
    else:
        print("[6/7] push saltato (--senza-push)")
    git(root, "tag", "-a", f"v{ver}", "-m", f"v{ver} — {titolo}")
    if not a.senza_push:
        git(root, "push", "origin", f"v{ver}")
        print(f"      tag v{ver} pushato")
    else:
        print(f"      tag v{ver} creato in locale")

    if a.senza_release:
        print("[7/7] release saltata (--senza-release)")
        print(f"\nPer finire a mano:\n  gh release create v{ver} --title "
              f"\"v{ver} — {titolo}\" --notes-file {os.path.relpath(note, root)} "
              f"{os.path.basename(percorso_zip)} {INSTALLER}")
        return 0

    comando = comando_release(ver, titolo, note, percorso_zip, installer)
    r = esegui(comando, root)
    if r.returncode != 0:
        raise ErroreRelease("gh release create: "
                            f"{(r.stderr or r.stdout).strip()}")
    asset = controlla_asset(ver, percorso_zip, installer, root)
    print(f"[7/7] release v{ver} pubblicata con {len(asset)} asset: "
          f"{', '.join(asset)}")
    print(f"\nhttps://github.com/{_repo(root)}/releases/tag/v{ver}")
    return 0


def _prova(root: str, a: argparse.Namespace) -> int:
    """Il giro a vuoto: nessuna scrittura, solo cosa manca."""
    ver = a.versione.strip() or versione_successiva(versione_attuale(root))
    print(f"versione: {versione_attuale(root)} -> {ver}")
    print(f"ramo: {a.ramo}")
    c_installer = ("c'e'" if os.path.isfile(os.path.join(root, INSTALLER))
                   else "MANCA")
    print(f"installer: {INSTALLER} ({c_installer})")
    note = (a.note or "").strip() or os.path.join(
        root, f"release-notes-v{ver}.md")
    if os.path.isfile(note):
        print(f"note: {os.path.relpath(note, root)} (esistenti)")
        print(f"titolo: {a.titolo.strip() or titolo_da_note(_leggi(note))}")
    else:
        voci, ultimo = commit_da_ultimo_tag(root)
        print(f"note: da creare in {os.path.relpath(note, root)} "
              f"da {len(voci)} commit dopo {ultimo or 'nessun tag'}")
        for _h, oggetto, _c in voci:
            print(f"  - {oggetto}")
    try:
        controlla(root, ver, a.ramo, remoto=not (a.senza_push
                                                 or a.senza_release))
        print("controlli: ok")
    except ErroreRelease as e:
        print(f"controlli: BLOCCANO — {e}")
        return 1
    print("asset: " + os.path.basename(f"orchestra-{ver}.zip")
          + " e " + INSTALLER)
    print("\n(prova: non ho scritto niente)")
    return 0


def _repo(root: str) -> str:
    """`utente/nome` dal remoto, per stampare il link giusto."""
    try:
        url = git(root, "remote", "get-url", "origin")
    except ErroreRelease:
        return "0.0.0.0/none"
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
    return m.group(1) if m else url


def git_out_root() -> str:
    """La radice del repository, o un errore leggibile."""
    r = esegui(["git", "rev-parse", "--show-toplevel"], os.getcwd())
    if r.returncode != 0:
        raise ErroreRelease("non siamo in un repository git: "
                            f"{(r.stderr or '').strip()}")
    return (r.stdout or "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
