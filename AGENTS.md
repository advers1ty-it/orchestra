# Istruzioni del progetto

Queste regole valgono per chi lavora nel repository di Orchestra.

## Comandi

- Test completi: `python tests/run_all.py`
- Una sola suite: `python tests/test_<nome>.py` (sono script standalone con
  riepilogo `PASS/FAIL`; un test nuovo va aggiunto anche a `tests/run_all.py`).
- Build: non c'è una build separata. Il pacchetto di release si crea con
  `python tools/rilascia.py`; non lanciarlo senza richiesta esplicita, perché
  pubblica tag e release.
- Avvio in locale: `python -m orchestra.cli web` (UI su `127.0.0.1:8737`).
- CLI: `python -m orchestra.cli chat`, `python -m orchestra.cli run "..."`,
  `python -m orchestra.cli doctor`.

## Convenzioni

- Python 3.11+, solo standard library dove possibile; le dipendenze
  facoltative stanno in `requirements.txt`.
- Codice, commenti, docstring e interfaccia sono in italiano.
- I test stanno in `tests/`, usano provider finti e non devono chiamare la
  rete né scrivere nella cronologia vera dell'utente.
- Preferire modifiche piccole e localizzate; mantenere i confini esistenti
  tra sessione, agente, tool e storico.
- Prima di consegnare: compilare i file toccati e lanciare la suite mirata
  più `git diff --check`.
- Non fare commit, push, tag o release senza richiesta esplicita.

## Da non toccare

- Segreti e credenziali: `.env`, `orchestra/nous_auth.json`, `token.txt`,
  `orchestra/.remote_state.json`.
- Dati e stato runtime: `sessions/`, `tmp/`, `plans/`, `_interno/`,
  `tests/_dati_test/`, `skills/scaricate/`, `skills/generate/`.
- Cartelle generate o locali: `Python/`, `.freebuff/`, `__pycache__/`,
  `.venv/`, `_probe/`, `_delega_prova/`.
- Zip e artefatti di release (`orchestra-*.zip`): sono prodotti locali, non
  sorgenti.
