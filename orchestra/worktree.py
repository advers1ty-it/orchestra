"""Checkout git isolati per i lavori in background.

PERCHE' ESISTE

Un lavoro in background non deve scrivere nella cartella che l'utente ha
aperta. Se il bot parte mentre l'utente sta modificando lo stesso file, o
se due bot lavorano sullo stesso progetto, le scritture si sovrappongono e
nessuno dei due sa cosa ha vinto. Un worktree git e' la risposta naturale:
un checkout separato, un ramo suo, lo stesso repository.

QUANDO SI USA

Solo per i lavori dei bot, e solo se il progetto e' dentro un repository
git con almeno un commit. Un progetto senza git non ha un modo sicuro di
isolare le scritture: si continua nella cartella normale, e il pannello lo
dice. Un repository git senza commit, invece, fa fallire il lavoro: non
c'e' una base da cui partire, e ripiegare nella cartella dell'utente
sarebbe il danno che il worktree esiste per evitare. `ORCHESTRA_WORKTREE=0`
spegne del tutto il meccanismo.

IL CONFINE, DETTO UNA VOLTA

Il worktree parte da HEAD, non dal working tree dell'utente. Le modifiche
non committate nella cartella principale NON vengono copiate: un lavoro
isolato non deve poter portare con se' mezzo salvataggio. Se servono,
l'utente le committa prima di avviare il lavoro.

Il ramo si chiama `orchestra/lavoro-<id>` e il checkout vive dentro la
cartella dati di Orchestra. Dopo il lavoro resta li' per la revisione: non
si unisce niente da solo. Unire un ramo di un agente al repository
dell'utente e' una decisione dell'utente, non un effetto collaterale.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any

from .dati import cartella_dati

# I worktree stanno qui, accanto ai database. `w<id>` e' corto di
# proposito: su Windows un percorso profondo piu' un checkout git intero
# arriva facilmente oltre il limite, e l'errore sarebbe un "filename too
# long" che non dice niente.
_SOTTOCARTELLA = "worktrees"

# Quanto puo' durare un comando git locale. Un `worktree add` su un
# repository grande copia i file, ma non parla con la rete.
_TIMEOUT = 120


class WorktreeError(RuntimeError):
    """Il checkout isolato non si e' potuto creare o rimuovere."""


def abilitato() -> bool:
    """Il meccanismo e' acceso? Si spegne con ORCHESTRA_WORKTREE=0."""
    valore = (os.environ.get("ORCHESTRA_WORKTREE", "1") or "").strip().lower()
    return valore not in ("0", "no", "false", "off")


def _git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    """Esegue git senza chiedere nulla all'utente.

    L'ambiente e' quello scrubbed dei tool, non `os.environ`: anche un
    `git worktree add` esegue gli hook del repository (post-checkout), e
    un hook non deve poter leggere le chiavi API del processo padre.
    GIT_TERMINAL_PROMPT=0 evita che un hook o una configurazione strana
    lascino il comando appeso a un prompt di credenziali.
    """
    from .tools._guard import _sandbox_env

    env = _sandbox_env()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env,
        capture_output=True, text=True, timeout=_TIMEOUT,
    )


def _errore(risultato: subprocess.CompletedProcess) -> str:
    testo = (risultato.stderr or risultato.stdout or "").strip()
    return testo.splitlines()[-1] if testo else f"git: exit {risultato.returncode}"


def radice_repo(percorso: str) -> str | None:
    """La radice del repository che contiene `percorso`, o None.

    None significa "non isolare": non e' un errore, e' un progetto che
    non usa git. Un repository senza commit (HEAD non nato) e' None per
    la stessa ragione: non c'e' uno stato da cui partire.
    """
    percorso = os.path.abspath(percorso or "")
    if not os.path.isdir(percorso):
        return None
    try:
        r = _git("rev-parse", "--show-toplevel", cwd=percorso)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    radice = os.path.abspath((r.stdout or "").strip())
    if not os.path.isdir(radice):
        return None
    # Un repository bare non ha un working tree da cui partire.
    try:
        bare = _git("rev-parse", "--is-bare-repository", cwd=radice)
        if bare.returncode == 0 and (bare.stdout or "").strip() == "true":
            return None
        testa = _git("rev-parse", "--verify", "HEAD", cwd=radice)
    except (OSError, subprocess.SubprocessError):
        return None
    if testa.returncode != 0:
        return None
    return radice


def _sembra_git(percorso: str) -> bool:
    """C'e' un `.git` in questa cartella o in una delle sue antenate?

    Serve a distinguere "progetto non git, si lavora normalmente" da
    "progetto git che non si riesce a isolare". Nel secondo caso NON si
    ripiega nella cartella dell'utente: si fallisce. Senza questa
    distinzione, un repository senza commit (o una macchina senza git)
    sembrerebbe un progetto normale, e il lavoro scriverebbe proprio
    dove l'isolamento doveva proteggere.
    """
    attuale = os.path.abspath(percorso or "")
    while True:
        if os.path.exists(os.path.join(attuale, ".git")):
            return True
        genitore = os.path.dirname(attuale)
        if genitore == attuale:
            return False
        attuale = genitore


def _sotto_percorso(progetto: str, radice: str) -> str:
    """Il percorso del progetto DENTRO il repository.

    Il progetto puo' essere una sottocartella del repository. Il worktree
    e' un checkout dell'intero repository, quindi la radice del bot e'
    `worktree / quella sottocartella`. Un progetto fuori dal repository
    non puo' succedere dopo `radice_repo`, ma si controlla lo stesso.
    """
    rel = os.path.relpath(os.path.abspath(progetto), radice)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        raise WorktreeError("il progetto non e' dentro il repository")
    return rel


def prepara(progetto: str, lavoro_id: int | str) -> dict[str, Any] | None:
    """Crea un checkout isolato per un lavoro, o None se non serve.

    None = il progetto non e' git (o il meccanismo e' spento): si lavora
    nella cartella normale. Un errore git invece si propaga: se il
    progetto E' un repository, fallire l'isolamento e scrivere comunque
    nella cartella dell'utente sarebbe il peggior compromesso possibile.
    """
    if not abilitato():
        return None
    try:
        ident = int(lavoro_id)
    except (TypeError, ValueError):
        return None
    if ident <= 0 or not progetto:
        return None
    radice = radice_repo(progetto)
    if radice is None:
        if _sembra_git(progetto):
            raise WorktreeError(
                "il progetto e' un repository git ma non c'e' un commit "
                "da cui partire (o git non e' disponibile): fai un "
                "commit prima di avviare il lavoro")
        return None

    sotto = _sotto_percorso(progetto, radice)
    base = os.path.join(cartella_dati(), _SOTTOCARTELLA)
    os.makedirs(base, exist_ok=True)
    percorso = os.path.join(base, f"w{ident}")
    branch = f"orchestra/lavoro-{ident}"

    # Un percorso gia' occupato non si riusa: un lavoro ha un id solo, e
    # riusare un checkout vecchio significherebbe mescolare due turni.
    # Se e' un residuo manuale, l'utente lo toglie e riprova: meglio un
    # errore chiaro che una cancellazione silenziosa.
    if os.path.exists(percorso):
        raise WorktreeError(
            f"il checkout isolato esiste gia': {percorso}. "
            f"Rimuovilo o scarta il lavoro prima di riprovare."
        )
    # Un ramo omonimo puo' essere un residuo di una cancellazione a
    # meta'. Non lo si riusa (mescolerebbe due lavori) e non lo si
    # cancella: potrebbe essere un ramo dell'utente con lo stesso nome.
    try:
        esisteva = _git("show-ref", "--verify", "--quiet",
                        f"refs/heads/{branch}", cwd=radice).returncode == 0
    except (OSError, subprocess.SubprocessError):
        esisteva = False
    if esisteva:
        raise WorktreeError(
            f"il ramo {branch} esiste gia' nel repository. "
            f"Rinominalo o cancellalo prima di riprovare.")
    try:
        r = _git("worktree", "add", "-b", branch, percorso, "HEAD", cwd=radice)
    except (OSError, subprocess.SubprocessError) as e:
        raise WorktreeError(f"git worktree add non eseguibile: {e}") from e
    if r.returncode != 0:
        # Il ramo e' nostro (non esisteva prima): se `worktree add` e'
        # fallito a meta', lasciarlo renderebbe impossibile riprovare.
        try:
            _git("branch", "-D", branch, cwd=radice)
        except (OSError, subprocess.SubprocessError):
            pass
        shutil.rmtree(percorso, ignore_errors=True)
        raise WorktreeError(f"checkout isolato non creato: {_errore(r)}")

    lavoro_root = percorso if sotto == os.curdir else os.path.join(percorso, sotto)
    # Una sottocartella non tracciata da git non esiste nel checkout. Si
    # crea vuota: il bot ci lavora dentro, ma i file non tracciati della
    # cartella principale restano li' (e' il confine dichiarato sopra).
    os.makedirs(lavoro_root, exist_ok=True)
    comando = f'git -C "{radice}" merge {branch}'
    return {
        "repo": radice,
        "percorso": percorso,
        "radice": lavoro_root,
        "sotto": "" if sotto == os.curdir else sotto,
        "branch": branch,
        "creato": time.time(),
        "unisci": comando,
    }


def commit_modifiche(info: dict[str, Any] | None,
                     messaggio: str = "lavoro del bot") -> dict[str, Any]:
    """Committa le modifiche del checkout sul suo ramo.

    Un merge unisce commit, non file non committati: senza questo passo
    il bot potrebbe "proporre" un lavoro che poi il merge non porta con
    se'. Il commit avviene DENTRO il worktree isolato, sui soli file di
    quel lavoro; il progetto principale resta intatto.

    Se non c'e' niente da committare, torna l'HEAD attuale: il ramo e'
    comunque un punto valido, e chi unisce vede che non ci sono novita'.
    """
    if not isinstance(info, dict):
        raise WorktreeError("nessun checkout isolato da committare")
    percorso = os.path.abspath(str(info.get("percorso") or ""))
    base = os.path.abspath(os.path.join(cartella_dati(), _SOTTOCARTELLA))
    if not percorso or not os.path.isdir(percorso):
        raise WorktreeError("checkout isolato non trovato")
    try:
        dentro = os.path.commonpath([percorso, base]) == base
    except ValueError:
        dentro = False
    if not dentro or percorso == base:
        raise WorktreeError("il percorso non e' un checkout di Orchestra")
    try:
        add = _git("add", "-A", cwd=percorso)
        if add.returncode != 0:
            raise WorktreeError(f"git add non riuscito: {_errore(add)}")
        stato = _git("status", "--porcelain", cwd=percorso)
        if not (stato.stdout or "").strip():
            testa = _git("rev-parse", "HEAD", cwd=percorso)
            return {"commit": (testa.stdout or "").strip(), "nuovo": False}
        msg = " ".join(str(messaggio or "lavoro del bot").split())[:200]
        r = _git("commit", "-m", msg or "lavoro del bot", cwd=percorso)
        if r.returncode != 0:
            raise WorktreeError(
                "commit del checkout non riuscito (git ha un'identita' "
                f"configurata?): {_errore(r)}")
        testa = _git("rev-parse", "HEAD", cwd=percorso)
        return {"commit": (testa.stdout or "").strip(), "nuovo": True}
    except WorktreeError:
        raise
    except (OSError, subprocess.SubprocessError) as e:
        raise WorktreeError(f"git non eseguibile: {e}") from e


def unisci(info: dict[str, Any] | None,
           commit_atteso: str = "") -> dict[str, Any]:
    """Unisce il ramo del lavoro nel progetto, solo su richiesta esplicita.

    Non e' il bot a decidere: il bot puo' solo proporre (tool
    `proponi_merge`). Qui si esegue la decisione dell'utente, e si
    rifiuta se il progetto ha modifiche non committate: un merge su un
    working tree sporco puo' mescolare il lavoro del bot con quello
    dell'utente, ed e' esattamente cio' che il checkout isolato evitava.

    In caso di conflitto il merge viene annullato e il repository resta
    com'era. Meglio un errore che un conflitto lasciato aperto in una
    cartella che l'utente non sta guardando.
    """
    if not isinstance(info, dict):
        raise WorktreeError("nessun checkout isolato da unire")
    repo = os.path.abspath(str(info.get("repo") or ""))
    branch = str(info.get("branch") or "").strip()
    if not repo or not os.path.isdir(repo):
        raise WorktreeError("repository del checkout non trovato")
    if not branch:
        raise WorktreeError("il checkout non ha un ramo")
    try:
        testa = _git("rev-parse", "--verify", "HEAD", cwd=repo)
        if testa.returncode != 0:
            raise WorktreeError("il repository non ha un commit su cui unire")
        in_corso = _git("rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=repo)
        if in_corso.returncode == 0:
            raise WorktreeError(
                "c'e' gia' un merge in corso nel progetto: finiscilo o "
                "annullalo prima di unire il checkout")
        ramo = _git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=repo)
        if ramo.returncode != 0:
            raise WorktreeError(f"il ramo {branch} non esiste piu'")
        punta = (ramo.stdout or "").strip()
        if commit_atteso and punta != commit_atteso:
            raise WorktreeError(
                "il ramo e' cambiato dopo la proposta: il lavoro da unire "
                "non e' piu' quello che il bot ha verificato")
        stato = _git("status", "--porcelain", cwd=repo)
        if (stato.stdout or "").strip():
            raise WorktreeError(
                "il progetto ha modifiche non committate: committale o "
                "mettile da parte prima di unire il checkout")
        gia = _git("merge-base", "--is-ancestor", branch, "HEAD", cwd=repo)
        if gia.returncode == 0:
            return {"ok": True, "gia_unito": True, "branch": branch,
                    "commit": (testa.stdout or "").strip()}
        r = _git("merge", "--no-ff", "--no-edit", branch, cwd=repo)
        if r.returncode != 0:
            _git("merge", "--abort", cwd=repo)
            raise WorktreeError(f"merge non riuscito: {_errore(r)}")
        commit = (_git("rev-parse", "HEAD", cwd=repo).stdout or "").strip()
        return {"ok": True, "gia_unito": False, "branch": branch,
                "commit": commit}
    except WorktreeError:
        raise
    except (OSError, subprocess.SubprocessError) as e:
        raise WorktreeError(f"git non eseguibile: {e}") from e


def rimuovi(info: dict[str, Any] | None) -> dict[str, Any]:
    """Butta via il checkout e il ramo di un lavoro.

    `--force` e' voluto: lo scarto serve proprio a buttare via le
    modifiche non committate del bot. Prima si controlla che il percorso
    sia dentro la cartella dei worktree di Orchestra: un checkpoint
    corrotto non deve poter cancellare una cartella qualsiasi.
    """
    if not isinstance(info, dict):
        raise WorktreeError("nessun checkout isolato da rimuovere")
    percorso = os.path.abspath(str(info.get("percorso") or ""))
    repo = os.path.abspath(str(info.get("repo") or ""))
    base = os.path.abspath(os.path.join(cartella_dati(), _SOTTOCARTELLA))
    if not percorso or not repo:
        raise WorktreeError("checkout isolato incompleto")
    try:
        dentro = os.path.commonpath([percorso, base]) == base
    except ValueError:
        dentro = False
    if not dentro or percorso == base:
        raise WorktreeError("il percorso non e' un checkout di Orchestra")

    branch = str(info.get("branch") or "")
    rimosso = False
    if os.path.isdir(repo):
        try:
            r = _git("worktree", "remove", "--force", percorso, cwd=repo)
            rimosso = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            rimosso = False
        if not rimosso and os.path.isdir(percorso):
            # Il worktree non e' piu' registrato (cartella .git rotta,
            # repository spostato): si toglie la cartella, che e' nostra,
            # e si fa pulizia dei riferimenti.
            shutil.rmtree(percorso, ignore_errors=True)
            rimosso = not os.path.exists(percorso)
        try:
            _git("worktree", "prune", cwd=repo)
        except (OSError, subprocess.SubprocessError):
            pass
        if branch:
            try:
                # -D e non -d: il ramo contiene il lavoro del bot, che
                # l'utente ha appena deciso di scartare.
                _git("branch", "-D", branch, cwd=repo)
            except (OSError, subprocess.SubprocessError):
                pass

    if not rimosso and os.path.exists(percorso):
        raise WorktreeError(f"checkout non rimosso: {percorso}")
    return {"ok": True, "percorso": percorso, "branch": branch}
