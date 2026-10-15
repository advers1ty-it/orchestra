# Orchestra — guida per tester

## Avvio rapido
- Copia `orchestra/.env.example` -> `orchestra/.env` e aggiungi chiavi.
- `python3 -m orchestra.cli doctor`
- `python3 -m orchestra.cli web` (default http://127.0.0.1:8737)
- Per CLI: `python3 -m orchestra.cli chat`

## Guida in UI
- Opzioni → Modello: seleziona provider/modello.
- Modal "Cosa fai?": carica profilo + prompt iniziale.
- Task e Tool → attiva profili (base/ricerca/skill/pieno).
- Dipendenze: pulsante "Dipendenze" per installare `ddgs`.

## Goal autonomo
- pulsante "Obiettivo": scrivi obiettivo + Avvia.
- stato/output live, Stop disponibile.
- per CLI: `orchestra goal "..."`.
- scheduler: `--depends-on A,B`, `--priority N`, `--max-attempts N`, `orchestra goals [--pronti]`, `orchestra goal-next`.
- coda automatica: `orchestra scheduler [--una-volta]` oppure bottone "Coda on/off" nel pannello (spenta di default).
- gate visivo nel pannello: badge `gate: ok / bocciato / parziale / in attesa` su ogni riga.
- piani `kind=piano`: contenitori che si chiudono quando i figli finiscono.
- gate di accettazione: solo risposta finale non vuota = done (o `--consenti-parziale`, o criteri `--criteri JSON`).
- multi-agente: disponibile se il modello chiama `delega`; retry opzionale con `--recovery JSON`.

## Tester senza GitHub
- Pacchetto: `installer/Installa-Orchestra.bat` + `scarica-release.ps1` (niente token, repo pubblico).
- Il tester lancia l'installer: controlla Python, scarica l'ultima release, crea `.env` da esempio, mette "Avvia Orchestra" sul Desktop.
- `Avvia-Orchestra.bat` fa `orchestra update --auto` a ogni avvio: riceve gli update senza fare niente.
- Pubblicare un update: alza `__version__`, committa, `git tag vX.Y.Z && git push --tags`, `gh release create vX.Y.Z --generate-notes`.
- Pacchetto tester: zip con `installer/Installa-Orchestra.bat` + `installer/scarica-release.ps1` + `installer/LEGGIMI.txt` (guida per l'utente).
- `.env`, token, budget, storico e goals non vengono mai sovrascritti (lista CONSERVA in `orchestra/update.py`).
- Prima di una release: `python tests/run_all.py` col server acceso.

## Browser / computer
- Browser render apre Chrome/Edge locale (headless).
- Computer automation usa api Windows e richiede permesso.

## Supporto
- non ci sono dipendenze esterne per default.
- offline-first, DB locale; goal reminder su file persistente.
- credenziali mai stampate.