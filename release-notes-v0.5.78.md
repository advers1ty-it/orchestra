## v0.5.78 — La proposta resta nel servizio giusto

Revisione del giro immagini/instradamento dopo le prove sul campo. Tre difetti veri, corretti.

### 1. Il consiglio poteva proporre un modello di un altro servizio
La proposta aggiunta nella 0.5.77 prendeva i modelli da tutti i cataloghi in cache. Su Telegram il menu `/modello` cambia modello **dentro il servizio del bot**: un id di un altro servizio risponde «non c'è», quindi il rimedio sarebbe stato un secondo vicolo cieco. Ora si guarda un catalogo solo, quello del servizio in uso. La funzione che lo risolve è una sola (`_catalogo_di`), e ha assorbito la copia che stava dentro `telegram_modelli`: era la seconda copia della stessa derivazione, cioè il posto dove un giorno si sarebbe dimenticata la cache o l'errore di rete.

### 2. Fra i candidati c'erano modelli da non consigliare
- Gli `stealth/*`: anonimi, in prova, e proprio quelli la cui scheda può non corrispondere — `crouton-alpha` dichiara le immagini e non le vede. Consigliarlo come rimedio sarebbe consigliare il modello che ha appena deluso.
- Chi dichiara `supports_tools` falso: risponderebbe a una foto e non saprebbe usare i tool, quindi non finirebbe il lavoro. `None` (servizio che non lo dichiara) resta ammesso: non dichiarato non vuol dire assente.

### 3. `/stato` non diceva se l'instradamento era acceso
Era l'unico posto dove si poteva vedere che il modello veniva riscelto al posto tuo — ed era la cosa che mancava in tre giri di diagnosi. Ora c'è una riga, solo per l'agente principale: per un bot il router non è attivo e la riga sarebbe rumore.

### 4. `/api/model` senza sessione diceva `routing: true` dopo aver scritto `off`
Il campo ora legge quello che c'è su disco, invece di un valore di comodo.

### Cosa resta aperto, e non è un difetto da correggere in fretta
- **Un modello che dichiara la vista e non ce l'ha non è prevedibile.** Gli endpoint di OpenRouter non espongono un campo sull'input immagine: `nemotron-3.5-super-vl:free` (che legge) e `crouton-alpha` (che non legge) hanno valori identici. La scheda è l'unica dichiarazione, e a volte è sbagliata. Il sintomo è la risposta che continua il turno precedente: lì la strada è cambiare modello.
- **Il consiglio può richiedere una richiesta di rete** quando il catalogo del servizio non è ancora in cache: dopo un turno fallito si aspetta qualche secondo. Si potrebbe usare solo la cache e dare la frase generica se manca, ma un consiglio con un secondo di attesa vale più di nessun consiglio.
- **`keys.scrivi` restituisce `(ok, messaggio)` e quasi tutti i chiamanti lo ignorano**: un salvataggio rifiutato (chiave non scrivibile, disco pieno) è silenzioso. È esattamente il difetto che ha reso `ORCHESTRA_ROUTING` inutile finché la chiave non è entrata nella lista. Non l'ho cambiato in blocco: sono una ventina di chiamanti e ognuno vuole un messaggio diverso.
- **`modello_legge_immagini` cerca in tutti i cataloghi** e si ferma al primo che conosce l'id. Se lo stesso id esistesse su due servizi con capacità diverse, risponderebbe per il primo che capita. Caso raro, annotato qui.
- **`test_chiavi` è 32/1** su «c'è una data sui limiti»: `NOTA_FREE` non contiene più un anno. Fallisce anche senza queste modifiche; è un check da aggiornare a mano quando si ricontrollano i piani gratis.

### Test
`test_telegram_sessione` 127, `test_telegram` 137, `test_webapp` 48, `test_rotte` 34, `test_allegato_e2e` 19, `test_allegato_giro` 15. `test_chiavi` 32/1 come sopra.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
