"""Ricerca nel progetto: contenuto (`search_text`) e nomi (`find_files`).

PERCHE' ESISTONO

L'agente aveva `read_file` e `list_dir`, e nient'altro. Per rispondere a
"dove e' definita questa funzione" doveva elencare cartelle e leggere file
uno per uno, oppure chiamare `run_shell grep` — che su Windows e' `findstr`
e ha un'altra sintassi, quindi il comando che funziona nella chat non
funziona qui. Due tool tolgono di mezzo entrambi i problemi, e sono il
lavoro piu' comune di un agente che scrive codice.

COSA NON SONO

Non sono `rg` e non sono un indice: leggono i file a ogni chiamata. Per un
progetto normale va benissimo; su un monorepo da 100.000 file il tetto di
file visitati li ferma e lo dice, invece di bloccare il turno. Un indice
vero (e incrementale) e' un altro lavoro, e va fatto quando c'e' la prova
che serve.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from ..types import Tool
from ._guard import _motivo_sensibile, _safe_path

# Cartelle che non sono "il progetto": sono dipendenze o stato di altri
# programmi. Visitare `node_modules` per trovare una funzione di venti
# righe significa leggere quarantamila file e restituire il risultato
# sbagliato (quello dentro una libreria).
_CARTELLE_SALTATE = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".nuxt", ".cache", "coverage",
    ".idea", ".vscode", "target", "obj", "vendor", ".gradle",
}

# Un file piu' grande di questo non e' codice sorgente, e' un dato (dump,
# minificato, lockfile). Leggerlo costa tempo e non contiene la riga che
# si cerca.
_MAX_BYTE_FILE = 1_000_000
# Tetto ai file visitati in una chiamata. Oltre, si dice che ci si e'
# fermati: un tool che gira due minuti sembra rotto anche quando lavora.
_MAX_FILE_VISITATI = 4_000
# Tetto ai risultati: oltre, il modello non li legge e il contesto si
# riempie di righe che non servono.
_MAX_RISULTATI = 200


def _da_saltare(p: Path) -> bool:
    """Vero se il file non va letto: credenziali, binari, troppo grande."""
    if _motivo_sensibile(p):
        return True
    try:
        if p.stat().st_size > _MAX_BYTE_FILE:
            return True
    except OSError:
        return True
    return False


def _testo(p: Path) -> str | None:
    """Il contenuto, o None se il file e' binario.

    Il test e' il byte NUL nei primi 4 KB: e' quello che fa `git` e che
    distingue un PNG da un sorgente senza indovinare dall'estensione (un
    file senza estensione puo' essere codice, e un `.py` puo' essere un
    dump rotto).
    """
    try:
        with open(p, "rb") as f:
            testa = f.read(4096)
            if b"\x00" in testa:
                return None
            resto = f.read()
    except OSError:
        return None
    return (testa + resto).decode("utf-8", "replace")


def _cammina(base: Path, *, limite: int = _MAX_FILE_VISITATI,
             glob: str = ""):
    """I file di testo sotto `base`, saltando dipendenze e segreti.

    Il `glob` si applica PRIMA di leggere il file. Applicarlo dopo e'
    costato una ricerca sbagliata: con `glob='*.py'` il tool leggeva
    comunque i primi 4000 file (dataset, JSON, immagini) e si fermava
    prima di arrivare al codice, dichiarando "nessuna corrispondenza".
    Filtrando sul nome, i file che non c'entrano non si aprono proprio.
    """
    def passa(p: Path) -> bool:
        if not glob:
            return True
        rel = _relativo(p, base)
        return (fnmatch.fnmatch(p.name, glob)
                or fnmatch.fnmatch(rel, glob))

    if base.is_file():
        if passa(base) and not _da_saltare(base):
            testo = _testo(base)
            if testo is not None:
                yield base, testo
        return
    visti = 0
    for radice, cartelle, files in os.walk(base):
        # Cartelle che iniziano con `.` o `_` sono, per convenzione,
        # locali o generate: `.artificial_analysis`, `_bench`, `_prova`.
        # In questo repo contenevano migliaia di file e la ricerca si
        # fermava al tetto PRIMA di arrivare a `orchestra/`, dichiarando
        # "nessuna corrispondenza" per una funzione che c'era. Chi vuole
        # cercare li' passa quel percorso esplicitamente.
        cartelle[:] = sorted(
            c for c in cartelle
            if c.lower() not in _CARTELLE_SALTATE
            and not c.startswith((".", "_")))
        for nome in sorted(files):
            p = Path(radice) / nome
            if not passa(p) or _da_saltare(p):
                continue
            testo = _testo(p)
            if testo is None:
                continue
            visti += 1
            yield p, testo
            if visti >= limite:
                return


def _relativo(p: Path, radice: Path) -> str:
    """Il percorso come lo scrive l'utente: relativo alla root se ci sta.

    La radice si passa invece di risolverla a ogni file: su una ricerca da
    migliaia di file, una `resolve()` per riga e' lavoro sprecato per una
    stringa che non cambia.
    """
    try:
        return p.relative_to(radice).as_posix()
    except Exception:  # noqa: BLE001
        return str(p)


def tool_search_text() -> Tool:
    """Cerca un'espressione nel contenuto dei file del progetto."""

    def handler(pattern: str = "", path: str = ".", glob: str = "",
                max_results: int = 50, case_sensitive: bool = False,
                context: int = 0) -> str:
        if not (pattern or "").strip():
            return "Cosa cerco? Serve un pattern (testo o espressione regolare)."
        try:
            rx = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as e:
            return (f"ERRORE: espressione regolare non valida: {e}. "
                    f"Se cercavi un testo letterale, togli i caratteri "
                    f"speciali ( . * + ? ( ) [ ] {{ }} | ^ $ \\ ).")
        try:
            base = _safe_path(path or ".")
        except (ValueError, PermissionError) as e:
            return f"ERRORE: {e}"
        if not base.exists():
            return f"NON ESISTE: {path}"
        try:
            massimo = max(1, min(int(max_results or 50), _MAX_RISULTATI))
            contorno = max(0, min(int(context or 0), 5))
        except (TypeError, ValueError):
            massimo, contorno = 50, 0

        righe: list[str] = []
        file_con_risultati: set[str] = set()
        scansionati = 0
        troncato = False
        radice = _safe_path(".")
        for p, testo in _cammina(base, glob=(glob or "")):
            scansionati += 1
            rel = _relativo(p, radice)
            righe_file = testo.splitlines()
            for i, riga in enumerate(righe_file):
                if not rx.search(riga):
                    continue
                file_con_risultati.add(rel)
                righe.append(f"{rel}:{i + 1}: {riga.strip()[:300]}")
                for j in range(max(0, i - contorno),
                               min(len(righe_file), i + contorno + 1)):
                    if j == i:
                        continue
                    righe.append(f"{rel}:{j + 1}- {righe_file[j].strip()[:300]}")
                if len(righe) >= massimo:
                    troncato = True
                    break
            if len(righe) >= massimo:
                troncato = True
                break

        if not righe:
            # Dire "nessuna corrispondenza" dopo essersi fermati a meta'
            # e' una bugia che manda il modello a cercare altrove. Se il
            # tetto ha tagliato la ricerca, va detto qui, non solo nel
            # caso con risultati.
            incompleta = scansionati >= _MAX_FILE_VISITATI
            coda = ("\n...ma la ricerca e' INCOMPLETA: mi sono fermato a "
                    f"{_MAX_FILE_VISITATI} file. Restringi con `path` o "
                    f"`glob` (es. '*.py')." if incompleta else "")
            return (f"Nessuna corrispondenza per {pattern!r} in {path} "
                    f"({scansionati} file di testo letti)." + coda)
        testa = (f"{len(righe)} righe in {len(file_con_risultati)} file "
                 f"({scansionati} file letti)")
        coda = ""
        if troncato:
            coda = ("\n[...fermo al tetto: restringi con `glob` (es. '*.py') "
                    "o con un pattern piu' preciso]")
        elif scansionati >= _MAX_FILE_VISITATI:
            coda = (f"\n[...mi sono fermato a {_MAX_FILE_VISITATI} file: "
                    f"restringi il percorso]")
        return testa + "\n" + "\n".join(righe) + coda

    return Tool(
        name="search_text",
        description=(
            "Cerca un testo o un'espressione regolare DENTRO i file del "
            "progetto e restituisce `file:riga: contenuto`. Usalo per "
            "trovare dove sta una funzione, una variabile, un messaggio: "
            "e' molto piu' veloce ed economico che leggere file interi. "
            "Salta da solo .git, node_modules e i file di credenziali."
        ),
        schema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Testo o espressione regolare da cercare, es. "
                        "`def main` o `class\\s+Utente`."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File o cartella da cui partire (default '.', "
                        "cioe' la root del progetto)."
                    ),
                    "default": ".",
                },
                "glob": {
                    "type": "string",
                    "description": (
                        "Filtra i file per nome, es. '*.py' o '*.ts'. "
                        "Vuoto = tutti i file di testo."
                    ),
                    "default": "",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Righe massime da restituire (default 50, max 200).",
                    "default": 50,
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Distingue maiuscole e minuscole. Default false.",
                    "default": False,
                },
                "context": {
                    "type": "integer",
                    "description": (
                        "Righe di contesto prima e dopo ogni corrispondenza "
                        "(0-5, default 0)."
                    ),
                    "default": 0,
                },
            },
            "required": ["pattern"],
        },
        handler=handler,
    )


def tool_find_files() -> Tool:
    """Trova i file per nome o per percorso, con un glob."""

    def handler(pattern: str = "*", path: str = ".",
                max_results: int = 100) -> str:
        p = (pattern or "*").strip() or "*"
        try:
            base = _safe_path(path or ".")
        except (ValueError, PermissionError) as e:
            return f"ERRORE: {e}"
        if not base.exists():
            return f"NON ESISTE: {path}"
        try:
            massimo = max(1, min(int(max_results or 100), 500))
        except (TypeError, ValueError):
            massimo = 100

        # Senza metacaratteri si cerca il nome che CONTIENE la stringa:
        # chiedere "utente" e ricevere zero perche' il file si chiama
        # `utente.py` sarebbe un tool che risponde alla domanda sbagliata.
        glob_pattern = p if any(c in p for c in "*?[") else f"**/*{p}*"
        trovati: list[str] = []
        try:
            candidati = base.glob(glob_pattern) if base.is_dir() else [base]
        except (ValueError, OSError) as e:
            return f"ERRORE nel glob: {e}"
        for f in candidati:
            try:
                rel = f.relative_to(base).as_posix()
            except ValueError:
                rel = str(f)
            # Le cartelle saltate si guardano sul percorso RELATIVO: se il
            # progetto sta in una cartella chiamata "build", guardare i
            # `parts` assoluti lo salterebbe per intero.
            if any(parte.lower() in _CARTELLE_SALTATE
                   or parte.startswith((".", "_"))
                   for parte in Path(rel).parts[:-1]):
                continue
            if _motivo_sensibile(f):
                continue
            if f.is_dir():
                trovati.append(f"[dir]  {rel}/")
            else:
                try:
                    byte = f.stat().st_size
                except OSError:
                    continue
                trovati.append(f"[file] {rel}  ({byte} byte)")
            if len(trovati) >= massimo:
                break
        if not trovati:
            return f"Nessun file corrisponde a {p!r} in {path}."
        coda = ("\n[...fermo al tetto: usa un pattern piu' preciso]"
                if len(trovati) >= massimo else "")
        return "\n".join(trovati) + coda

    return Tool(
        name="find_files",
        description=(
            "Trova file e cartelle per nome o per percorso con un glob "
            "(es. '*.py', 'src/**/test_*.ts'). Senza metacaratteri cerca i "
            "nomi che contengono la stringa. Usalo per orientarti prima di "
            "leggere, invece di elencare cartelle una per una."
        ),
        schema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Glob sul nome o sul percorso, es. '*.py', "
                        "'**/*.test.ts', 'utente'. Default '*'."
                    ),
                    "default": "*",
                },
                "path": {
                    "type": "string",
                    "description": "Cartella da cui partire (default '.').",
                    "default": ".",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Risultati massimi (default 100, max 500).",
                    "default": 100,
                },
            },
        },
        handler=handler,
    )
