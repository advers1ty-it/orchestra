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

## Browser / computer
- Browser render apre Chrome/Edge locale (headless).
- Computer automation usa api Windows e richiede permesso.

## Supporto
- non ci sono dipendenze esterne per default.
- offline-first, DB locale; goal reminder su file persistente.
- credenziali mai stampate.