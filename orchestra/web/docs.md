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

## Steer e Stop
- Steer: durante un turno compare una barra sopra il campo; il messaggio arriva al modello alla prima occasione utile — dopo il tool in corso, o prima di chiudere se stava già rispondendo — senza fermare il turno (max 5 per turno). Fuori da un turno viene rifiutato, per non finire sulla domanda successiva.
- Stop: il pulsante ■ accanto a Invia ferma il turno; i tool non ancora eseguiti ricevono un risultato "cancellato".

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
- Pacchetto tester: `installer/Installa-Orchestra.bat` + `installer/LEGGIMI.txt` (il bat è autonomo: contiene anche lo scaricatore).
- Il tester lancia l'installer: controlla Python, scarica l'ultima release, crea `.env` da esempio, mette "Avvia Orchestra" sul Desktop.
- `Avvia-Orchestra.bat` fa `orchestra update --auto`, avvia il server in background e apre il browser; se riaperto a server acceso chiede Apri / Riavvia / Ferma.
- Pubblicare un update: alza `__version__`, committa, `git tag vX.Y.Z && git push --tags`, `gh release create vX.Y.Z --generate-notes`.
- `.env`, token, budget, storico e goals non vengono mai sovrascritti (lista CONSERVA in `orchestra/update.py`).
- Prima di una release: `python tests/run_all.py` col server acceso.

## Browser / computer
- Browser render apre Chrome/Edge locale (headless).
- Computer automation usa api Windows e richiede permesso.
- `screenshot_view` legge lo PNG prodotto da `browser_screenshot` / `computer_screenshot` e lo passa al modello come immagine: la cattura da sola dà un percorso, non uno schermo.

## Immagini
- `image_gen` genera un'immagine da un prompt con OpenAI Images, Google Gemini o OpenRouter, usando la chiave già presente in Opzioni, e la salva in `immagini/` nel progetto.
- Con `provider="openrouter"` si sceglie uno qualsiasi dei modelli immagine del catalogo (`modello`); `elenco_modelli=true` li elenca con lo slug, senza generare né spendere.
- Con `riferimento` modifica un'immagine esistente: un percorso del progetto, una data URL, oppure `ultimo` per l'immagine appena allegata in chat.
- La generazione è a pagamento sul provider (per immagine o in image token): il tool lo ricorda quando manca la chiave, e non è un'alternativa gratuita a `invokeai`.
- L'anteprima compare nel riquadro del tool; il file resta nel progetto.

## Bot
- Un bot è un'identità salvata: nome, servizio, modello, persona, progetto e conversazione propri. Si crea da **Opzioni → Bot** o dal menu identità in testa.
- Servizio e modello vuoti significano "come l'app": il bot segue la configurazione principale finché non ne scegli una sua. Il progetto è un default modificabile per bot.
- Ogni bot ha una sessione separata, quindi passare dall'uno all'altro non perde la conversazione; la cronologia è etichettata col nome del bot.
- Da **Opzioni → Bot** puoi avviare un compito in background: il bot lavora nella sua sessione senza cambiare l'identità attiva. Bot diversi avanzano davvero in parallelo, ciascuno nella propria cartella; lo stesso bot esegue un compito alla volta e accoda gli altri (max 20). Puoi cambiare bot mentre uno lavora: il turno continua nella sua sessione e lo ritrovi quando torni. Puoi anche attivare un bot già in corso e vedere il turno live, ma non puoi mandargli un secondo messaggio finché non finisce. La coda vive in memoria: un riavvio del server la svuota, mentre la conversazione già svolta resta nella cronologia.
- `bot_chiedi` è l'altra forma di collaborazione: un bot chiede a un altro dentro il proprio turno, in modo sincrono. È diversa dal lavoro in background, che non blocca chi lo ha avviato.
- `bot_chiedi` permette a un bot di chiedere a un altro: la risposta è sincrona e il turno del destinatario costa sul suo provider. I limiti sono strutturali: profondità 1 (chi riceve non può richiamare) e allowlist `parla_con` (vuota = nessuno).
- Non sono processi separati: condividono chiavi, permessi e processo. Non sono una sandbox. Non si avviano da soli in background: ricevono un turno quando l'utente o un altro bot glielo manda.

## Agente principale
- Anche l'agente principale ha un'identità: **Opzioni → Identità**, con nome e persona/istruzioni. Non serve creare un bot per personalizzarlo.
- Vale quando non è attivo un bot; con un bot attivo vale la persona del bot. Tornando all'agente principale ritrovi la sua identità e la sua conversazione.
- La persona è aggiunta dopo le regole di sistema: non cambia permessi, divieti o sicurezza. Il nome compare nel menu in testa al posto di "agente principale".
- Svuotare i campi e salvare riporta al prompt di Orchestra senza identità in più. Il salvataggio non duplica il blocco a ogni modifica.

## Supporto
- non ci sono dipendenze esterne per default.
- offline-first, DB locale; goal reminder su file persistente.
- credenziali mai stampate.