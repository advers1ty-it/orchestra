"""Tool run_tests: eseguire la suite del progetto senza indovinare il comando.

PERCHE' ESISTE

`run_shell` basta a lanciare i test, ma per farlo bisogna SAPERE qual e'
il comando: `pytest`, `npm test`, `cargo test`, `go test ./...`, oppure
`python tests/run_all.py`. L'agente lo scopriva leggendo i file di
configurazione, oppure lo indovinava — e un `pytest` lanciato in un
progetto Node non fallisce in modo utile: fallisce con "no module named
pytest", che sembra un problema dell'ambiente e non del comando.

Qui il rilevamento e' esplicito e il comando e' UNO, quello che il
progetto dichiara. Il tool non e' una scorciatoia per aggirare i
permessi: passa dallo stesso `run_shell`, quindi policy, gate e root
valgono identici.

COSA NON E'

Non e' un interprete dei risultati: non trasforma l'output in un
riassunto "3 test passati". Un test che fallisce si legge, e un riassunto
fatto male nasconderebbe proprio il messaggio d'errore che serve.
L'output viene accorciato (inizio + coda), non riscritto.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..types import Tool
from ._guard import _root

# Il comando puo' essere lungo (suite complete) ma non infinito: oltre,
# l'agente sta aspettando qualcosa che non finira' in questo turno.
_TIMEOUT_PREDEFINITO = 180
_TIMEOUT_MASSIMO = 600
# L'output completo di una suite e' spesso 50.000 caratteri. Il modello
# non lo legge e i token si pagano: si tengono l'inizio (il comando e i
# primi errori) e la coda (il riepilogo e i fallimenti).
_MAX_CARATTERI = 6000


def _esiste(root: Path, *nomi: str) -> bool:
    return any((root / n).exists() for n in nomi)


def _scripts_package(root: Path) -> dict:
    try:
        with open(root / "package.json", encoding="utf-8") as f:
            dati = json.load(f)
        return dati.get("scripts") or {}
    except Exception:  # noqa: BLE001
        return {}


def _rileva(root: Path, target: str) -> tuple[str, str]:
    """Torna (comando, perche'). Vuoto se non c'e' una suite riconoscibile."""
    # Prima il progetto stesso: `tests/run_all.py` e' una convenzione
    # esplicita, e vince su un `pytest` generico che magari non e'
    # nemmeno installato.
    if (root / "tests" / "run_all.py").is_file():
        cmd = "python tests/run_all.py"
        return cmd, "c'e' tests/run_all.py"

    if _esiste(root, "pyproject.toml", "pytest.ini", "tox.ini",
               "setup.cfg", "conftest.py") or (root / "tests").is_dir():
        cmd = "python -m pytest -q"
        if target:
            cmd += " " + target
        return cmd, "progetto Python con pytest"

    scripts = _scripts_package(root)
    if scripts:
        if "test" in scripts:
            gestore = "npm"
            if (root / "pnpm-lock.yaml").exists():
                gestore = "pnpm"
            elif (root / "yarn.lock").exists():
                gestore = "yarn"
            elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
                gestore = "bun"
            return f"{gestore} test", f"package.json con lo script test ({gestore})"
        return "", "package.json esiste ma non ha uno script 'test'"

    if (root / "Cargo.toml").is_file():
        return "cargo test", "progetto Rust"
    if (root / "go.mod").is_file():
        return "go test ./...", "progetto Go"
    if (root / "Makefile").is_file():
        try:
            testo = (root / "Makefile").read_text(encoding="utf-8",
                                                  errors="replace")
        except OSError:
            testo = ""
        if "test:" in testo:
            return "make test", "Makefile con un target test"
    for nome in ("run_tests.sh", "test.sh", "scripts/test.sh"):
        if (root / nome).is_file():
            return f"bash {nome}", f"c'e' {nome}"
    return "", ""


def _accorcia(testo: str) -> str:
    if len(testo) <= _MAX_CARATTERI:
        return testo
    testa = testo[:1200]
    coda = testo[-(_MAX_CARATTERI - 1200):]
    return (f"{testa}\n\n[... {len(testo) - _MAX_CARATTERI} caratteri "
            f"in mezzo omessi ...]\n\n{coda}")


def tool_run_tests() -> Tool:
    """Esegue la suite di test del progetto, col comando che il progetto usa."""

    # Lo stesso handler di run_shell: policy, gate, root e kill dei
    # processi valgono qui esattamente come li'. Un secondo percorso di
    # esecuzione sarebbe un secondo posto dove le guardie possono
    # mancare.
    from .run_shell import tool_run_shell
    shell = tool_run_shell().handler

    def handler(target: str = "", timeout: int = _TIMEOUT_PREDEFINITO,
                comando: str = "") -> str:
        root = _root()
        if comando.strip():
            # Un comando esplicito e' utile quando il progetto ha piu'
            # suite (unit + integrazione) e l'agente vuole una sola.
            cmd, perche = comando.strip(), "comando indicato da te"
        else:
            cmd, perche = _rileva(root, (target or "").strip())
        if not cmd:
            elenco = []
            if (root / "package.json").is_file():
                elenco.append("`npm test` (package.json)")
            if (root / "pyproject.toml").is_file():
                elenco.append("`python -m pytest` (pyproject.toml)")
            if (root / "Makefile").is_file():
                elenco.append("`make test` (Makefile)")
            return (
                "NESSUNA SUITE RICONOSCIUTA in questa cartella"
                + (f" ({perche})" if perche else "") + ".\n"
                "Non l'ho inventata: dimmi il comando giusto, oppure usa "
                "`run_shell` per vedere com'e' organizzato il progetto.\n"
                + ("Segnali trovati: " + ", ".join(elenco)
                   if elenco else "")
            )
        try:
            secondi = max(1, min(int(timeout or _TIMEOUT_PREDEFINITO),
                                 _TIMEOUT_MASSIMO))
        except (TypeError, ValueError):
            secondi = _TIMEOUT_PREDEFINITO

        esito = shell(cmd, timeout=secondi)
        return (f"comando: {cmd}\n"
                f"perche': {perche}\n"
                f"{_accorcia(esito)}")

    return Tool(
        name="run_tests",
        description=(
            "Runs the project's test suite with the command the project "
            "uses (tests/run_all.py, pytest, npm test, cargo test, go test, "
            "make test) and returns the output. It goes through the same "
            "permissions as run_shell. Use it to verify a change instead of "
            "declaring it done."
        ),
        schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": ("What to run, when the runner accepts "
                                    "it (e.g. one file or one pytest test). "
                                    "Empty = the whole suite."),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds (1-600, default 180).",
                },
                "comando": {
                    "type": "string",
                    "description": ("Explicit command, when the detected one "
                                    "is not the right one."),
                },
            },
        },
        handler=handler,
    )
