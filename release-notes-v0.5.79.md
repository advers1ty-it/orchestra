## v0.5.79 — I punti aperti della revisione, chiusi

Cinque cose erano rimaste segnalate e non corrette nella 0.5.78. Erano tutte piccole, nessuna era «da fare in fretta», e tutte avevano lo stesso difetto di fondo: una macchina che sa una cosa e non la dice a chi la sta usando.

### 1. Una scheda smentita da una prova non viene più creduta
`stealth/crouton-alpha` dichiara di leggere le immagini e, provato, ha risposto come se la foto non ci fosse. Gli endpoint di OpenRouter non espongono un campo sull'input immagine — `nemotron-3.5-super-vl:free` che funziona e crouton che non funziona hanno valori identici — quindi la scheda resta l'unica dichiarazione e a volte è falsa. Non essendoci un modo di prevederlo, c'è un elenco di **smentite registrate** (`VISTA_SMENTITA` in `catalog.py`): un id con la sua prova e il motivo. Chi c'è dentro viene trattato come «non legge», il rifiuto scatta, e il messaggio dice la verità invece di ripetere la scheda:

> `stealth/crouton-alpha`: la scheda dice che legge le immagini, ma non le ha viste quando l'ho provata. Prova `/modello nvidia/nemotron-3.5-super-vl:free`…

L'elenco è scritto per essere **corto e cancellabile**: una riga sparisce quando il modello torna a leggere le foto, perché un elenco che cresce e non cala diventa, in qualche mese, un elenco di bugie diverse.

### 2. Un salvataggio rifiutato non risponde più «ok»
`keys.scrivi` restituisce `(ok, messaggio)`, ma quasi tutti i chiamanti leggevano solo il secondo elemento o nessuno: un rifiuto (chiave non in lista, disco pieno, `.env` non scrivibile) diventava un «salvato» per chi l'aveva chiesto. È esattamente il difetto che ha reso `ORCHESTRA_ROUTING` inutile finché la chiave non è entrata nella lista.

Ora:
- `keys.scrivi_o_avviso` restituisce solo il problema (`""` se è andata), e sta in una riga: è la forma che i chiamanti usano davvero.
- Ogni rifiuto finisce comunque nel **log**, anche per i chiamanti che continuano a ignorare la tupla.
- Dove l'utente legge «salvato», il messaggio dice la verità: `/api/model`, `/api/provider`, `/api/routing`, `/api/reasoning`, `/api/iterazioni`, `/api/budget`, `/api/budget/reset` e `/modello` su Telegram. Se il valore è stato applicato a caldo ma non scritto, la risposta lo dice («Applicato, ma non salvato: …»), invece di far scoprire al riavvio che era tornato com'era prima. Per budget e instradamento la distinzione conta di più: sono un tetto di spesa e la ragione per cui un modello scelto a mano restava.

### 3. Lo stesso modello su due servizi: vale quello in uso
`modello_legge_immagini` guardava tutti i cataloghi in memoria e si fermava al primo che conosceva l'id — cioè all'ordine del dizionario delle cache, che non è un criterio. Se lo stesso id esisteva su due servizi con capacità diverse, poteva rispondere con la scheda di un servizio che la sessione non stava nemmeno chiamando. Ora l'ordine è esplicito: prima il servizio in uso, poi il catalogo dell'applicazione, poi gli altri già letti.

### 4. Il consiglio non può più diventare un'attesa lunga
Comporre la frase di un rifiuto poteva costare una richiesta di rete verso `/models`, e quel GET aveva **30 secondi** di timeout: un servizio lento teneva ferma la risposta per mezzo minuto, dopo un turno già fallito. Ora il timeout è 10 secondi, e un servizio che non risponde viene ricordato per due minuti: il caso lento costa una volta, non una per ogni foto. Il catalogo, in pratica, è quasi sempre già in memoria perché è lo stesso che ha popolato il menu dei modelli.

### 5. Il check sulla data dei piani gratis torna verde
`test_chiavi` era rosso su «c'è una data sui limiti». Non era un test sbagliato: `NOTA_FREE` aveva perso la data, quindi nessuno poteva sapere a quando risalivano quelle schede. La nota ora dice «Schede controllate a novembre 2026», e il test resta com'era — un'asserzione vera, non indebolita.

### Test
`test_chiavi` **35/0** (era 32/1), `test_telegram_sessione` **132/0**, `test_telegram` 137/0, `test_webapp` 48/0, `test_rotte` 34/0, `test_allegato_e2e` 19/0, `test_allegato_giro` 15/0, `test_switch_servizio` 11/0, `test_ttl_catalogo` 16/0.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
