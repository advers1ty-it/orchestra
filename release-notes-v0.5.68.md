## v0.5.68 — Il controllo in mano all'utente

### Annullare ferma davvero il comando
- Il pulsante di stop chiudeva il turno al controllo successivo, cioè **quando il tool tornava**: un `npm install`, un server appena avviato o un `sleep 300` restavano vivi mentre l'utente leggeva «annullato», e continuavano a scrivere sul disco. Ora i sottoprocessi si registrano per thread e `cancel()` ne termina l'albero. Il registro è per thread: annullare una sessione non ammazza i comandi di un'altra.
- `run_shell` risponde `INTERROTTO` quando il comando è stato ucciso da fuori, invece di restituire l'output parziale con un exit code che sembra un comando finito.

### Il server locale non ubbidisce a un altro sito
- Le richieste che cambiano stato confrontano `Origin` con `Host` e rifiutano il cross-site (`Sec-Fetch-Site: cross-site`, `Origin: null`). Prima una pagina qualsiasi aperta nel browser poteva fare una POST verso `127.0.0.1:8737` e comandare l'agente: in locale non c'è token da indovinare, quindi non c'era nessuna difesa.
- Il login remoto ha un limite di sei tentativi al minuto per IP: il token è l'unica credenziale, e senza limite si provava a forza bruta. C'è anche un tetto generale alle POST per IP.
- Il token si confronta a tempo costante (`hmac.compare_digest`): `==` si ferma al primo byte diverso, e su una rete reale la differenza si misura.

### Due strumenti nuovi per il codice
- `analisi_python` legge la **struttura** di un file senza il corpo: `simboli` (funzioni e classi con firma, riga e annidamento), `import`, `chiamate` (con la funzione che le contiene, filtrabili per nome), `usi` di un simbolo, e `sintassi`. Per orientarsi in un file grande non serve più leggerlo tutto; per un errore di sintassi riporta riga, colonna e la riga colpevole. Riguarda solo Python, e per gli altri formati lo dice invece di restituire un risultato vuoto.
- `run_tests` esegue la suite col comando che il progetto dichiara — `tests/run_all.py`, pytest, `npm`/`pnpm`/`yarn`/`bun test`, `cargo test`, `go test`, `make test` — invece di indovinarlo. Passa dallo stesso handler di `run_shell`, quindi policy, permessi e confine della cartella valgono identici. Se non riconosce una suite non inventa un comando.
- Entrambi sono in **tutti** i profili, come `search_text`: sono modi di non indovinare, non capacità da sbloccare.

### Istruzioni del progetto e memoria del lavoro
- L'agente legge `AGENTS.md`, `CLAUDE.md`, `.cursorrules` e `.github/copilot-instructions.md` dal progetto (tetto per file e complessivo, cache sull'mtime).
- Ogni scrittura di `write_file`/`edit_file` lascia un checkpoint: il pulsante ↶ annulla l'ultima modifica. Il registro tiene trenta voci; un file troppo grande non viene copiato ma la voce resta e **ferma** l'annullamento, per non disfare una modifica più vecchia al posto di quella che l'utente crede.

### Domande all'utente
- `ask_user` fa una domanda di chiarimento e aspetta la risposta dentro lo stesso turno: canale separato dai permessi, campo libero, opzioni come scorciatoie, scadenza a cinque minuti. Senza nessuno collegato (CLI, benchmark) risponde subito che non c'è a chi chiedere, invece di restare appesa.

### Contesto, cache e contenuto esterno
- Le skill e il progetto stanno in un **secondo** messaggio di sistema, dopo il prefisso marcato per la cache: prima l'indice delle skill veniva riscritto nel system prompt a ogni turno e la cache del prefisso non colpiva mai. Su Anthropic si marcano cache system, ultimo tool e coda della conversazione.
- Il testo che arriva da `web_cerca`, `web_leggi` e `browser_render` è racchiuso tra «INIZIO CONTENUTO NON FIDATO» e «FINE», con un avviso che lo dichiara materiale di terzi e una regola nel prompt. Non è una sanificazione — nessun delimitatore rende innocuo un testo — ma toglie l'ambiguità tra «l'utente ha chiesto questo» e «una pagina ha scritto questo».

### Aggiornamenti verificabili
- L'updater usa l'asset `.zip` della release quando c'è (prima usava **sempre** lo zipball, ignorando l'asset: la funzione che lo sceglieva esisteva e nessuno la chiamava), verifica il digest `sha256` dichiarato da GitHub quando disponibile, rifiuta un corpo che non è uno zip (una pagina HTML d'errore arrivava ad `applica`) e blocca i percorsi che escono dalla cartella **prima** di estrarre. In ogni caso di fallimento l'installazione resta intatta.

### Correzioni
- Impostare il system prompt a sessione avviata ora sopravvive al turno successivo: `set_system_prompt` cambiava la lista dei messaggi ma non l'`Agent`, e `_aggiorna_prompt` riallineava il blocco stabile al valore vecchio.
- La skill `code-search` documenta i due tool di ricerca e quando usarli.

### Test
- Nuove suite: `cancel-processi` (avvia un comando lento, annulla, verifica che non arrivi in fondo), `webapp-csrf` (server HTTP vero: origine, `Sec-Fetch-Site`, `Origin: null`, limite del login), `strumenti-codice` (simboli, chiamate, sintassi rotta, rilevamento del runner ed esecuzione di una suite che passa e una che fallisce), più i controlli su `test_update` per digest, corpi non-zip e zip-slip.
- Suite completa verde su Windows e Ubuntu.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
