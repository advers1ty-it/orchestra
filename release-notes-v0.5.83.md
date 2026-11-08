## v0.5.83 — Il server che resta acceso

Nella 0.5.82 avevo elencato quattro cose viste e non toccate. Questa versione ne sistema una — la più grossa — e spiega perché le altre tre restano dove sono. La più grossa è questa: `run_shell` aspetta il comando e lo uccide al timeout, quindi Orchestra non poteva avviare un server e poi guardarlo. Per un lavoro web è metà del ciclo: il modo di sapere se una pagina si apre è aprirla.

### 1. `processo`: quattro azioni, e il comando resta vivo

Nuovo tool, in tutti i profili accanto a `run_shell`. `azione="avvia"` stacca il processo e restituisce un id; `azione="leggi"` dà le ultime righe dell'output; `azione="ferma"` chiude; `azione="elenca"` dice cosa è acceso. Il processo vive fra una chiamata e l'altra, quindi la sequenza vera funziona: avvia il server, scrivi il codice, ricarica la pagina, leggi gli errori, correggi.

### 2. L'output va su un file, non in una pipe

Una pipe la deve leggere qualcuno. Se nessuno la legge, il figlio si blocca appena il buffer è pieno — cioè un server che smette di rispondere proprio mentre lo stai guardando, senza aver scritto niente da nessuna parte. Il log finisce invece in `tmp/processi/<id>.log`, **dentro** la cartella di lavoro: così `read_file` lo può aprire, e "guarda il log" è un consiglio che il modello può seguire davvero.

La lettura è in coda e non consuma: due `leggi` di fila danno lo stesso stato. Un log che si svuota a ogni lettura è un log in cui il modello perde la riga che non aveva ancora guardato, e la ritrova solo rifacendo il comando.

### 3. Due secondi che evitano tre iterazioni sbagliate

Il caso peggiore di un comando in background è quello che muore subito: porta già occupata, modulo mancante, comando sbagliato (`npx` che non c'è). Con un id restituito comunque, l'agente apre la pagina, non trova niente, e cerca il difetto nel codice — quando `EADDRINUSE` era già scritto nel log.

Ora l'avvio aspetta due secondi (regolabili) e, se il processo è morto, lo dice con l'exit code e l'output: `USCITO SUBITO p1 (codice 1) dopo 0,3s.`

### 4. Il background non è una scorciatoia attorno ai permessi

Un secondo modo di eseguire comandi è anche un secondo modo di aggirare i controlli del primo: bastava `rm -rf src &` perché nessuno chiedesse niente. I quattro controlli che stavano dentro l'handler di `run_shell` — policy del bot, confine della root, file di credenziali, comandi distruttivi — sono ora una funzione sola in `_guard.py`, `verifica_comando`, e la usano entrambi i tool. Non duplicati: **gli stessi**. Un test prova che un percorso fuori dalla root, un `rm -rf` e un `sudo` vengono fermati anche passando dal background.

### 5. Nessun orfano

Due limiti, tutti e due per lo stesso motivo — un server dimenticato acceso è un guasto che si manifesta al turno dopo, con un sintomo che non c'entra: la porta occupata.

- Massimo 8 processi vivi. Il messaggio di rifiuto elenca i vivi e dice di fermarne uno: senza un tetto, un modello che riprova in loop riempie la macchina di server e la diagnosi diventa "perché va tutto lento".
- All'uscita di Orchestra si fermano tutti. Anche questo con un'attesa vera del decesso: `taskkill` ritorna quando ha **inviato** il segnale, non quando il processo è morto, e un `poll()` immediato risponde "vivo" a un processo che sta morendo.

Annullare un turno invece non li ferma: il server è una risorsa che l'utente sta guardando nel browser, e spegnerglielo mentre lo guarda è peggio che lasciarlo acceso con un `elenca` che lo mostra.

### 6. `list_dir` contava l'albero intero per ogni voce

Elencare la radice costava 0,8 secondi: per ogni sottocartella contava **tutti** i file ricorsivamente, per stampare una riga di riepilogo. Su un progetto con `node_modules` sono decine di migliaia di file scanditi per dire "(12480 elementi)". Ora il conteggio si ferma a 2.000 e dice `2000+`: il numero esatto non serve a nessuno, il "è enorme" sì. Sulla root di Orchestra: 0,8s → 0,2s.

### 7. Le altre tre cose: guardate, e lasciate

Vanno dette, perché "non l'ho fatto" e "ho deciso di non farlo" non sono la stessa cosa.

- **Nomi misti** (`read_file` accanto a `web_cerca`, `path` accanto a `nome_file`). Uniformare vuol dire rinominare identificatori pubblici: si rompono insieme i permessi salvati, i test, le skill e il pannello. Un alias per ogni nome raddoppia la superficie per nascondere il problema invece di risolverlo. Il costo di leggerli è una volta; il costo di rinominarli è una migrazione.
- **Due classi `ToolRegistry`** (`types.py` e `tools/__init__.py`, con un ponte di alias). Funzionano, e il ponte è testato. Unirle è un refactor che tocca tutto il loop per zero capacità in più: il momento giusto è quando c'è un difetto che nasce da lì, non prima.
- **`confronto.py`** (il confronto fra due modelli sui soli task che discriminano) è testato e non è raggiungibile da nessun comando. È attrezzatura per chi sceglie i modelli, non per l'agente, e il valore è di chi mantiene il progetto: resta scritto e provato, pronto per quando servirà un comando che lo chiami.

E una quarta, che non è una scelta: la suite `decisions-schema` non parte perché il provider risponde `404 — No endpoints found for inception/mercury-decide:free`. Il modello di sonda è stato ritirato. Sostituirlo alla cieca con un altro id gratuito sposterebbe il guasto senza verificarlo (serve una chiave per provarlo), quindi il test continua a dire "la sonda non c'è" invece di passare per finta.

### 8. Prove

Suite completa: **93 suite passate, 0 fallite** (due non eseguibili: `e2e` vuole una chiave vera, `decisions-schema` la sonda ritirata). `tests/test_processo.py` è nuovo, 45 controlli. L'ultima sezione non guarda le stringhe: avvia un vero `python -m http.server`, gli parla in HTTP, legge il log a server acceso, lo ferma, e verifica che la porta **torni** libera — un figlio rimasto vivo è il difetto che questa versione esiste per non avere. La prima stesura di quel controllo guardava a 0 secondi dallo stop e falliva su Linux: il socket lo libera il kernel quando il processo è davvero raccolto, qualche decimo dopo. Il controllo ora aspetta, e un orfano vero la tiene per tutta la finestra. Le altre sezioni coprono il comando che muore all'avvio (con l'exit code vero), la lettura ripetibile, il tetto dei processi, gli id sbagliati, e i tre rifiuti che devono arrivare anche dal background.
