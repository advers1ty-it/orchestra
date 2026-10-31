## v0.5.65 — Policy dei bot e tracce filtrabili

### Policy dei bot
- Ogni bot può avere quattro liste: **tool consentiti**, **tool vietati**, **shell consentita** e **shell vietata**. La policy si modifica da **Opzioni → Bot**.
- La policy si applica **dopo** il profilo strumenti: restringe, non allarga. Un tool fuori dal profilo resta fuori anche se compare tra i consentiti; il divieto vince sull'allowlist.
- La shell consentita confronta il primo programma di ogni sezione (`;`, `&&`, `||`, `|`, newline). Con l'allowlist attiva le sostituzioni `$(...)`, i backtick e `<(...)` sono rifiutati anche dentro le virgolette doppie; le virgolette singole le rendono testo.
- `run_shell` risponde `NON ESEGUITO` indicando la regola violata, invece di lasciare che il comando fallisca da solo.
- Un figlio nato da `delega` eredita la policy del padre: la delega non è una via per aggirarla.
- Anche i tool runtime (`bot_chiedi`, `proponi_merge`) seguono la stessa allowlist: se usi una lista di tool e vuoi che il bot chieda ad altri, aggiungi `bot_chiedi`.
- La policy è **in-process**, non una sandbox del sistema operativo: un programma consentito (per esempio `python`) può fare tutto quello che sa fare. Non sostituisce un container.
- I database dei bot esistenti vengono migrati automaticamente con la nuova colonna, senza perdere configurazione.

### Tracce dei turni
- La sidebar **Tracce** ha due filtri: esito e **solo errori**. I filtri vengono applicati dal database, non dopo il taglio della lista: un turno fallito di ieri non sparisce dietro cinquanta turni riusciti di oggi.
- Il dettaglio mostra l'offset temporale di ogni evento; ogni riga si espande nel payload grezzo: argomenti dei tool, risultati e motivo della verifica.
- I chunk di streaming non vengono salvati uno a uno: centinaia di eventi per turno renderebbero la sequenza illeggibile.
- API: `GET /api/tracce?esito=<codice>&errori=1&limite=N`, `GET /api/tracce/<id>`.
- `ultime()` accetta `esito` e `solo_errori`, con limite validato tra 1 e 500.

### Test
- Nuove suite `policy`, `traccia-filtri`; estesa `test_bots` con la policy HTTP e la sessione attiva.
- Verificato anche in anteprima: filtro traccia, dettaglio con payload grezzo, creazione bot con policy e rilettura da `/api/bots`.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
