"""Persistenza delle impostazioni tra riavvii.

Il difetto: il server legge ORCHESTRA_MAX_ITERS da os.environ (che non viene
aggiornato quando si salva via /api/iterazioni). Riavviando il server si
perde il valore salvato.
"""
import os
import tempfile
import shutil

from orchestra import keys
from orchestra.tools import default_registry
from orchestra.webapp import Handler


def _setup():
    """Crea una root di test isolata con un .env vuoto."""
    root = tempfile.mkdtemp(prefix="orchestra-persist-")
    env_path = os.path.join(root, ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("ORCHESTRA_ROOT=" + root + "\n")
    return root, env_path


def test_iterazioni_persistono_dopo_riavvio():
    """Salvare 40, riavviare, deve leggere 40 (non 20)."""
    root, env_path = _setup()
    try:
        reg = default_registry()
        handler1 = Handler(root, reg)
        # Primo "avvio": leggo da os.environ (vuoto) -> default 20
        assert handler1.app.session.agent.config.max_iterations == 20, (
            f"default atteso 20, trovato {handler1.app.session.agent.config.max_iterations}"
        )

        # Salvataggio via API: scrive in .env e in self.app.env
        keys.scrivi(env_path, "ORCHESTRA_MAX_ITERS", "40")
        handler1.app.env["ORCHESTRA_MAX_ITERS"] = "40"
        handler1.app.session.agent.config.max_iterations = 40

        with open(env_path, encoding="utf-8") as f:
            contenuto = f.read()
        assert "ORCHESTRA_MAX_ITERS=40" in contenuto, (
            f"non ho trovato ORCHESTRA_MAX_ITERS=40 in {contenuto!r}"
        )

        # Secondo "avvio": deve leggere 40, non 20
        handler2 = Handler(root, reg)
        assert handler2.app.session.agent.config.max_iterations == 40, (
            f"dopo riavvio atteso 40, trovato {handler2.app.session.agent.config.max_iterations}"
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_modello_persistente_tra_avvii():
    """Il modello scelto deve sopravvivere al riavvio."""
    root, env_path = _setup()
    try:
        reg = default_registry()
        handler1 = Handler(root, reg)
        keys.scrivi(env_path, "MODEL", "claude-opus-4-20250514")
        handler1.app.env["MODEL"] = "claude-opus-4-20250514"

        with open(env_path, encoding="utf-8") as f:
            contenuto = f.read()
        assert "MODEL=claude-opus-4-20250514" in contenuto, (
            f"non ho trovato MODEL=... in {contenuto!r}"
        )

        handler2 = Handler(root, reg)
        assert handler2.app.env.get("MODEL") == "claude-opus-4-20250514"
    finally:
        shutil.rmtree(root, ignore_errors=True)