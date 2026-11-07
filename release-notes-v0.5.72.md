## v0.5.72 — Il telefono è un canale, e i servizi sono una pagina

### Telegram: non un esperimento, un canale
- Ogni bot di Orchestra può avere il suo bot Telegram, con la sua persona, il suo modello, i suoi tool e la sua policy. Telegram è il filo, non un secondo agente.
- **La porta si apre con un codice.** Un bot Telegram è raggiungibile da chiunque ne conosca il nome utente, e dietro c'è un agente con accesso a shell e file: il primo messaggio di una chat è un collegamento, non una richiesta, e vale solo con un codice a uso singolo e con scadenza che compare nella finestra. Chi non è collegato riceve una spiegazione e **nessun turno**: nessun tool, nessuna spesa.
- Il QR del codice lo disegniamo noi (`orchestra/qr.py`, Python puro, versioni 1–10). L'alternativa era un servizio esterno, comodo ma con dentro proprio il codice che apre il bot. Le matrici sono state rilette con zbar su 13 casi prima di dichiararle buone.
- **Dal telefono arrivano anche i file**: una foto è un'immagine per il modello, un PDF si legge, un `.docx` si estrae, un vocale si trascrive se il motore vocale c'è (e se non c'è lo dice). Video e archivi vengono rifiutati spiegando perché, e oltre i 20 MB del Bot API non si scarica nemmeno.
- **Il turno non è più muto.** Un messaggio solo, riscritto al massimo ogni 2,5 secondi, con secondi, giro, tool in corso e la coda di quello che l'agente scrive. A turno finito si toglie e resta la risposta.
- **L'ascolto non si ferma mai.** Prima, mentre l'agente lavorava, il ponte non faceva `getUpdates`: proprio le cose che servono durante un turno — guide e stop — restavano su Telegram fino alla fine. Ora quello che scrivi mentre lavora è una guida al turno in corso, non una seconda richiesta accodata.
- Comandi: `/aiuto`, `/stato`, `/steer`, `/stop`, `/nuova`, `/modello`, `/scollega`. Non costano token e non entrano nella conversazione. `/stop` cambia mestiere: ferma il turno, che dal telefono non si potrebbe fare in nessun altro modo; staccare la chat passa a `/scollega`.
- **`/modello` è un menu**: prima i servizi collegati, poi i modelli di quello scelto, e si attiva toccandolo. Il menu è un messaggio solo che si riscrive, e non tiene stato sul server: la scelta sta nel `callback_data`, quindi un menu rimasto in chat da ieri funziona lo stesso. Con un catalogo vero (Nous ne dichiara 354) si fermano ai 40 più utili e lo dice; un servizio senza chiave non compare.
- **Permessi e domande arrivano in chat**, con i pulsanti. La risposta scritta vale come risposta alla domanda aperta, non come guida al turno; per un permesso il testo non basta e il bot lo dice. Ogni modulo porta il segno della sua richiesta, quindi un pulsante di ieri non concede il percorso di oggi.
- **E tornano indietro i file**: immagini come foto, il resto come documento, fino a cinque da 50 MB. Il codice resta fuori, e quello che non si può mandare lo si dice invece di farlo sparire.
- In Opzioni → Bot → Telegram ci sono le tre cose nell'ordine in cui vanno fatte: token di @BotFather (verificato mentre lo incolli, e mai rileggibile dal browser), QR, stato. C'è anche l'agente principale fra i bot collegabili, e un clic porta a BotFather, l'unico passaggio che l'API non può fare.

### Servizi e chiavi: una pagina sola
- «Servizi» e «Gratis» erano due voci di Opzioni per la stessa cosa: una aveva il campo della chiave, l'altra la descrizione. Per capire cosa fosse NVIDIA si cambiava sezione. Ora è **una sezione sola**, in tre gruppi — gratis, a pagamento, sul tuo computer — con la descrizione accanto al campo della chiave.
- Il legame servizio↔chiave sta **nei dati** (il campo `env` di `FREE_SERVICES`), non in una tabella nel frontend: un servizio nuovo porta con sé il suo campo.
- **Anthropic era un vicolo cieco**: provider supportato, ma la chiave non era fra le scrivibili, quindi non c'era modo di metterla dal pannello.
- Il posto dove prendere la chiave era un dominio dentro un blocco di codice; ora è un link che si clicca (`target="_blank"`, `noopener`).
- **Niente doppioni.** Se il legame si rompe, la stessa chiave ricompare in «Altre chiavi» sotto la scheda che la spiega e il pannello chiede due volte la stessa cosa. In «Altre chiavi» resta solo ciò che non è un servizio.
- **Il tempo massimo per turno smette di comparire due volte**: ha già il suo campo in Modello, in minuti. Un secondo campo in secondi per lo stesso numero voleva dire due valori per la stessa impostazione, e nessuno che sappia quale il server usa. Ora è il dato a dire dove vive una chiave (`dove` in `keys.stato`), e il frontend non tiene una seconda lista di esclusioni per conto suo.
- Un indirizzo o un numero di secondi si leggono **in chiaro**: nasconderli renderebbe impossibile accorgersi di un errore di battitura. Solo le credenziali sono campi password.

### Skill: nascono dal lavoro, entrano nel prompt solo se le accetti
- La soglia delle tre ripetizioni era dichiarata e mai applicata: in 159 skill ce n'erano zero fra le generate. Ora ogni turno finito bene registra la sequenza di comandi con esito ok, e alla terza ripetizione scrive una proposta con le sue prove — che resta fuori dal prompt finché non la tieni.
- Skill e cestino escono dalle Opzioni: il modale «Apri tutte le capacità» è l'unico posto, con tre tab (Skill, Cestino, Strumenti). Prima erano due elenchi della stessa cosa, e due elenchi della stessa cosa mentono appena divergono.
- Nel farlo è emerso un difetto del server: il 403 dell'origine e il 429 del rate limit venivano inviati **senza leggere il corpo della POST**, e il client riceveva «connessione interrotta» invece del messaggio. È il modo peggiore di dire «troppe richieste», perché sembra un guasto di rete.

### Avvio e aggiornamento
- **Un solo launcher.** `Orchestra.cmd` e `Avvia-Orchestra.bat` facevano le stesse tre cose con due implementazioni: una si fidava di `where py`, l'altra no; una fermava per socket, l'altra per riga di comando; due nomi diversi per il log. Ora c'è una implementazione sola, e il `.bat` del Desktop resta un guscio sottile.
- I candidati Python vengono **eseguiti** con una sonda che controlla la versione minima, non cercati: su questa macchina `py` esiste e punta a un Python disinstallato, quindi il launcher sceglieva un interprete che non partiva e l'avvio moriva in silenzio.
- Netstat può dire CLOSED mentre il server risponde: «ferma» diceva «non è stato possibile fermarlo» con il server vivo. C'è il ripiego sulla riga di comando.
- **L'avvio automatico nomina un programma che esiste**: `sys.executable` più `-WorkingDirectory`, non `py -3`. Se la voce non potrebbe partire, il pannello lo dice e offre Ripara invece di lasciar credere che funzioni.
- La cartella passata all'aggiornamento finiva con un apice (`--root "D:\cartella\"`): la barra mangiava l'apice di chiusura e `update.py` cercava la versione in una cartella inesistente senza dirlo. Ora `--root "%ROOT%."`, che vale anche per la radice di un disco.
- Lo zip dell'asset c'è anche questa volta: la 0.5.71 era stata pubblicata senza, e l'aggiornamento ripiegava sullo zipball invece che sull'archivio preparato.

### Test
- Nuova suite `servizi-ui` (23 check) che esegue il bundle vero in Node sul catalogo vero: ogni servizio che chiede una chiave ha il suo campo, nessuna chiave ha due riquadri, «Altre chiavi» contiene esattamente ciò che non è un servizio, e il campo in Modello del tempo massimo esiste ancora.
- Nuove suite per il ponte Telegram (43 e poi 129 check: arretrato, codice a uso singolo, estraneo respinto, file, avanzamento, comandi), per il QR (21), per il menu `/modello` (95), per la chat lato sessione (93, 70, 69, 48), per il launcher e l'avvio automatico.
- L'inventario delle rotte conosce le quattro rotte del ponte: senza, la suite era rossa per una rotta non dichiarata e non serviva più da allarme.
- Suite completa verde. Due suite non sono potute avvenire perché parlano con API esterne (`decisions-schema`, `e2e`): non sono un difetto del codice, ma non sono nemmeno una verifica.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
