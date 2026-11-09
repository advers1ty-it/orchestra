## v0.5.84 — Tre immagini insieme

Questa versione nasce da una prova andata male: un poster da rifare partendo dall'originale, più il logo corretto e la foto vera del telefono. L'agente ha risposto incollando due rettangoli col fondo bianco sopra l'arte — il prezzo coperto a metà, il vecchio footer che spuntava da sotto, i bordi netti. Non era un modello che aveva capito male: era il gesto giusto per l'unico strumento che aveva a disposizione.

### 1. `image_gen` accetta più immagini, non una

Il limite era nostro: `genera()` prendeva un riferimento singolo, e `input_references` partiva con un elemento solo dentro. I provider ne accettavano molti di più — 14 su Gemini 3.1 Flash Image, 3 su Gemini 2.5 Flash Image, 16 su GPT Image — quindi con tre file (poster, logo, prodotto) l'unica strada possibile era il montaggio letterale di `image_edit`, che incolla i pixel e non fonde niente.

Ora c'è `riferimenti`: un elenco, in ordine, dove il primo è l'immagine da modificare e gli altri sono i file che il prompt nomina per posizione ("il logo nella seconda"). Ogni adapter fa la sua parte: OpenRouter riempie `input_references` con tutte le voci, Google mette un `inlineData` per immagine fra le parti, OpenAI ripete `image[]` nel multipart. La forma vecchia — un riferimento singolo — resta valida, quindi nessun chiamante si rompe.

Due dettagli che il caso vero ha reso necessari:

- **I riferimenti si alleggeriscono da soli** oltre i 3 MB complessivi: il lato lungo va a 1536 e il file si ricodifica (un PNG resta PNG, perché può avere la trasparenza). Tre foto a piena risoluzione in una richiesta JSON sono base64 su base64: si pagano come token di ingresso e rischiano un 413.
- **Il tetto è del modello, non dell'API.** Con 15 riferimenti ci si ferma prima di spendere; e se un modello ne accetta meno, il 400 non resta "parametri non validi" ma dice che quel modello ne vuole di meno e che si può sceglierne un altro.

### 2. E il testo torna dove deve stare

L'istruzione che l'agente legge per scegliere fra i tool diceva, giustamente, di non far ridisegnare un logo o un prezzo a un modello generativo. Era vera e, da sola, portava all'incolla. Adesso dice anche l'altra metà: quando la scena va **ricomposta** si parte da `image_gen` con i riferimenti veri, e il testo esatto (prezzo, indirizzo, nome) si ridisegna **dopo** con `image_edit` sopra il risultato. È l'unico ordine che tiene insieme la composizione e le cifre.

### 3. Telegram: tre foto sono una richiesta sola

Un album non è un messaggio: sono più aggiornamenti separati, legati solo da `media_group_id`, e il ponte trattava il primo come la richiesta. Da lì il turno con una foto sola e l'agente che chiedeva la foto appena mandata.

Ora i pezzi si raccolgono per gruppo, il timer si riarma a ogni arrivo e parte un turno solo con tutte le foto, con la didascalia vera al posto del "Guarda questa immagine" ripetuto. Se una foto viene rifiutata le altre passano lo stesso, e i timer pendenti si annullano quando il ponte si ferma: un album a metà non fa partire un turno su una chat chiusa.

### 4. `memory.md` non si allega più

Il ponte cerca i file scritti durante il turno e allega quelli con un'estensione utile. La memoria dell'agente è un `.md`, viene riscritta ogni volta che l'agente la legge, e quindi finiva in chat. Ora si salta la lista chiusa dei file di stato di Orchestra (`dati.FILE_STATO`: memoria, budget, obiettivi, cron, storico): non si indovina dal nome, e un `report.md` vero continua ad arrivare.

### 5. Le suite delle immagini entrano nel runner

`test_image_gen`, `test_image_edit` e `test_inpainting` erano scritte e fuori da `run_all.py`: nessuno le eseguiva, quindi nessuno sapeva. Sei controlli erano rossi da prima di questa versione — confrontavano i byte del provider con quelli salvati, ma da quando un'immagine generata porta dentro la dichiarazione AI Act i byte non sono più identici. Adesso girano nella suite completa.

### Cosa non c'è

`resolution` — i modelli Google accettano `1K`, `2K`, `4K` e noi mandiamo solo il rapporto d'aspetto. Per un poster da stampa è la differenza tra 1K e 4K veri; è un'aggiunta piccola ma separata, e non è in questa versione.
