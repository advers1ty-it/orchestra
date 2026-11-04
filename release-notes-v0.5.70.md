## v0.5.70 — Il browser che sa cliccare, e un confine più stretto

### Browser: interazione, non solo rendering
- Accanto ai tre tool esistenti (`apri`, `render`, `screenshot`, che restano e funzionano senza canale di debug) c'è un canale **CDP** scritto con la sola standard library (`orchestra/cdp.py`): WebSocket con handshake, maschera, lunghezza estesa, ping/pong, poi Chrome headless su una porta libera e una sessione per processo.
- Nuovi tool: `browser_click`, `browser_digita` (via `Input.insertText`, quindi i listener `input` scattano come per una digitazione vera), `browser_attendi` (selettore o testo), `browser_console` (log ed eccezioni JS), `browser_rete` (metodo, stato, URL, MIME).
- Il click è **JS sul selettore**, non sulle coordinate: un selettore assente lo dice invece di cliccare a vuoto.
- Console e rete arrivano dagli eventi `Runtime`/`Log`/`Network`, non da un polling: quello che la pagina ha scritto c'è anche se è successo prima della lettura.

### Riepilogo di fine turno
- A fine turno: esito tradotto dal codice interno, durata, file toccati (accorpati: lo stesso file due volte è un file), token e costo stimato. Compare come riga in chat; se la scheda è nascosta diventa una **notifica di sistema**, con il permesso chiesto al primo invio — un gesto dell'utente, non un permesso chiesto da solo a fine turno.
- Il costo si accumula a ogni risposta, non solo quando c'è un budget configurato: prima restava zero per chi non ne aveva uno.
- L'ultimo riepilogo è anche su `/api/riepilogo`.

### Rotte HTTP: una tabella, non centotrentanove `elif`
- Le 125 rotte stanno in una tabella (`orchestra/rotte.py`) accanto al gestore che le serve, con `@rotta(metodo, percorso)`. Il percorso esatto vince sul modello parametrico, e un doppione fa fallire l'import invece di scegliere in silenzio l'ultimo arrivato.
- Un solo punto di dispatch: percorso ignoto → `404`, metodo sbagliato → `405` con l'header `Allow`. Prima erano `404` entrambe, e un `POST` su una rotta di lettura sembrava una rotta inesistente.
- I gestori sono divisi per dominio in sette mixin: `rotte_chat`, `rotte_skill`, `rotte_sistema`, `rotte_storia`, `rotte_automazione`, `rotte_modelli`, `rotte_progetti`. `webapp.py` scende da 5.869 a 3.565 righe.
- `login` e `logout` restano fuori dalla tabella: sono il confine di autenticazione, che deve stare prima del corpo e della sessione.

### Frontend: `panels.js` diviso per area
- Un file da 5.320 righe diventa nove, uno per area della UI: `panels-bench`, `panels-opzioni`, `panels-lavoro`, `panels-skill`, `panels-storia`, `panels-shell`, `panels-progetto`, `panels-automazioni`, `panels-bot`.
- L'ordine di caricamento vive in un posto solo (`Handler.BUNDLE_ORDER`), che è già quello che il server usa per costruire `/app.js`: il bundle servito è identico.
- Ogni file si annuncia col proprio nome in `__diagFiles`: prima il marcatore diceva solo «panels», e capire quale pezzo non era arrivato era impossibile.
- I test leggono l'elenco da `BUNDLE_ORDER` (`tests/_web.py`): aggiungere un file non li rompe.

### Il menu non mente più dopo un cambio rifiutato
- Se il cambio servizio veniva rifiutato (409 «agente occupato», 400 chiave mancante), il ramo d'errore ridisegnava i selettori con uno stato vuoto che il server non manda mai: restavano su valori vecchi e **diversi tra loro** — uno sul servizio fallito, l'altro su quello di prima — e «nessuna chiave API configurata» sovrascriveva l'errore del server. Sembrava che le chiavi fossero sparite.
- Ora si rilegge lo stato vero con `caricaOpzioni()` e l'errore si scrive dopo il riallineamento, come già faceva il cambio modello.

### Trasparenza: l'AI Act, preso sul serio
- **La barra dice cosa sei**: «assistente IA» accanto alla versione, con la spiegazione completa nel tooltip; e al primo avvio una riga nel pannello degli obiettivi dice che risposte e file sono generati da un modello, che può sbagliare, e come si annulla (Δ per vedere, ↶ per tornare indietro). È l'art. 50(1) del Reg. UE 2024/1689, in vigore dal 2 agosto 2026.
- **Le immagini generate si dichiarano**: `image_gen` inserisce un chunk `tEXt` nei PNG e scrive sempre un `<nome>.ai.json` accanto al file, con generatore, provider, modello, prompt e data. Un PNG marcato resta un PNG valido (IHDR primo, IEND ultimo, CRC ricalcolati); un formato che non si può marcare dentro il file ha comunque il sidecar.
- **Il README dice cosa esce dalla macchina**: prompt, file letti, screenshot e immagini di riferimento vanno al provider configurato e a nessun altro; chiavi nel `.env` locale, storico in `storico.db` locale. E dice a cosa non serve: nessuna decisione su persone.
- **`AI-ACT.md` è per chi usa Orchestra, non per noi**: dice che si parla con un'IA, cosa esce dalla macchina e verso quale provider, che le immagini generate sono dichiarate, e a cosa il software non serve. Le cose da fare restano nostre.

### Test
- Nuove suite: `rotte` (inventario delle 125 rotte congelato, 405 con `Allow`), `cdp` (WebSocket con server d'eco locale sempre, click/digitazione/attesa/console/rete con Chrome vero quando c'è), `riepilogo`.
- `test_nessun_ora` non legge più una finestra di caratteri: esegue il bundle con il DOM finto (`_probe_menu_errore.js`), tenta i due cambi, il server risponde 400 e 409, e si guarda cosa resta nei menu. È così che è saltato fuori il difetto qui sopra.
- `test_popup_modelli` falliva per la decodifica dell'output di node (UTF-8 letto come cp1252), non per il badge.
- Nuova suite `marcatura`: PNG minimo valido, chunk aggiunto con CRC ricalcolati, pixel identici a quelli di partenza, non-PNG lasciati intatti, sidecar corretto e nessun `gatto.json` sovrascritto.
- Suite completa verde su Windows e Ubuntu.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
