## v0.5.82 — La lingua del contratto, e i tool che rispondevano di no

Il contratto che il modello legge — descrizioni dei tool, schemi dei parametri, blocco delle skill nel prompt, frontmatter delle procedure — è ora in inglese, come la sua istruzione. Tradurre ha fatto emergere il resto: cinque parametri che non avevano descrizione, dodici in `mcp` che avevano solo il tipo, un paio di testi corrotti, e quattro difetti veri trovati rileggendo i tool uno per uno. Quelli sono la parte che conta: un tool che risponde "nessun file" perché non ha guardato, un profilo che toglie lo strumento che il messaggio chiedeva, un output tagliato che sembra completo.

### 1. Il contratto del modello è in inglese, gli identificatori no

Le descrizioni dei 37 tool e dei 126 parametri sono in inglese. I **nomi** dei tool, i **nomi** dei parametri e i **valori** degli enum restano quelli di prima (`azione: "lista"|"crea"`, `operazioni: "ritaglia"|"incolla"`): sono identificatori, stanno nelle preferenze di permesso salvate, nei test, nei corpi delle skill e nel pannello Strumenti. Rinominarli perderebbe in silenzio i permessi già concessi, e un permesso che sparisce è peggio di una descrizione in italiano. Per gli enum la mappatura sta nella descrizione — `lista|crea|... (list|create|...)` — così il modello legge il significato in inglese e passa il valore che il codice si aspetta.

Restano in italiano, per scelta: i messaggi e gli errori dei tool (`NON ESISTE:`, `MODIFICA FALLITA:`), i testi dell'interfaccia, la guida, e il prompt di sistema, che porta le convenzioni del progetto per un utente che scrive italiano.

### 2. Le skill: 77, due erano in italiano, nessuna rotta

Audit completo dell'indice: nome uguale alla cartella, descrizione presente e su una riga, corpo non vuoto, nessun nome doppio, le 19 skill di base con `categoria: base` e `origine: base`, e nessun tool citato che non esista più (le uniche sigle sconosciute sono valori di enum e nomi di parametri, che è corretto).

`cron` e `mcp` erano le due procedure di base scritte in italiano mentre le altre diciassette erano già in inglese: riscritte, con il contenuto riverificato contro il codice — le azioni elencate e i parametri corrispondono a quelli che i tool accettano davvero.

Il blocco che finisce nel prompt era anch'esso in italiano mentre le descrizioni elencate sotto erano in inglese: `## Available skills (N in total, …)`, `[2 proof(s)] … skill_leggi`, `Evidence that this procedure worked`, `Objective / Commands used / Outcome`. Un'istruzione in una lingua diversa dalle righe che la seguono è la riga che il modello salta.

### 3. Cinque parametri senza descrizione, e due testi rotti

`browser_attendi`, `browser_digita`, `browser_console` e `browser_rete` avevano parametri senza descrizione; `mcp` ne aveva **dodici** con il solo tipo. Uno schema che dice `args: array of string` senza dire cosa sono quegli argomenti è uno schema che il modello riempie a caso. Ora ogni parametro di ogni tool ha una descrizione, e c'è un test che lo impone (`ogni parametro di ogni tool ha una descrizione`).

Nello stesso giro: `browser_render` diceva "Chrome/Edge **sesso** del sistema" (una parola senza senso al posto di "stesso"), `ask_user` si fermava a metà frase, e `browser_apri` aveva un `\n` letterale dentro la descrizione.

### 4. Il profilo `auto` toglieva il tool che il messaggio chiedeva

`profilo_per_testo` sceglieva il profilo cercando tre gruppi di sottostringhe e prendendo il primo che combaciava. Due casi veri, entrambi sbagliati: "genera un'immagine di un gatto" conteneva `genera`, che stava fra le parole delle **skill**, e diventava il profilo `skill`; "apri https://esempio.it" non conteneva nessuna parola chiave e cadeva su `base`, che **non ha** `browser_apri`. L'agente rispondeva "tool inesistente" a un compito che il messaggio dichiarava per intero.

Ora si parte dalle capacità richieste e si prende il profilo più piccolo che le contiene tutte: browser, computer, cron e mcp stanno solo in `pieno`, quindi un testo che ne nomina uno vale `pieno`. `genera` non è più una parola delle skill (la genera anche `image_gen`). Otto casi sono nell'elenco delle prove, e per ognuno si controlla anche che il tool implicato sia davvero nel profilo scelto.

### 5. `find_files` non scendeva nelle sottocartelle

`find_files("*.py")` restituiva due file, non duecento. Il pattern con metacaratteri veniva passato intatto a `Path.glob`, quindi `*.py` era un glob di **primo livello**: da una radice di progetto trovava solo i file sciolti nella cartella di partenza. Il modello leggeva un elenco corto e concludeva che il file non c'era — e il tool non diceva niente, perché dal suo punto di vista aveva finito.

Un pattern senza `/` cerca ora in tutto l'albero (`*.py` = ogni `.py`), un pattern con `/` resta relativo a `path`. L'elenco esce ordinato: l'ordine di una glob dipende dal filesystem, e due chiamate identiche che rispondono in ordine diverso fanno sembrare cambiato un albero che non è cambiato.

### 6. Il taglio silenzioso

`run_shell` tagliava l'output a 8.000 caratteri **senza dirlo**, e `list_dir` le voci a 300. Un output che finisce a metà senza una riga che lo dichiari sembra un output completo: l'agente legge un traceback tagliato, conclude che il difetto è l'ultima riga che ha visto, e corregge quella. Ora entrambi chiudono con quanto è rimasto fuori, e `read_file`, `web_leggi` e `search_text` lo facevano già.

### 7. `memoria`: `dry_run` sembrava un'anteprima

La descrizione diceva "quando è vero (predefinito) riporta solo cosa succederebbe". È vero per `azione=ottimizza` e **falso** per tutte le altre: `dry_run` non ha effetto su `aggiungi`, `modifica`, `elimina`. Un modello che si fida della descrizione crede di aver fatto un'anteprima e ha già scritto in memoria. Ora la descrizione dice a quale azione si applica.

### 8. Un `import` che cancellava un file

`orchestra/tools/__init__.py` eseguiva `_pulizia_tools_obsoleti()` all'import: se trovava `orchestra/tools.py` accanto al pacchetto, lo cancellava. Era la migrazione da file a cartella, vecchia di parecchie versioni, e restava come effetto collaterale di un `import`. Un modulo che importa non deve scrivere sul disco, e una libreria che cancella file all'import è esattamente ciò che un antivirus ha ragione a fermare. La stessa pulizia resta dove serve il contrario di un import: all'avvio dell'app.

### 9. Il test che falliva solo da `tests/`

`test_servizi_ui` passava 23 controlli su 23 dalla radice e 4 su 19 da `tests/` — cioè dalla cartella da cui si lanciano i test. L'harness Node cercava `index.html` rispetto alla directory corrente, e il commento nel file diceva di gestire proprio quel caso. Ora il percorso glielo passa il lato Python (`ORCHESTRA_WEB_INDEX`), e il test passa da entrambe.

### 10. Le release note: una sola

Il repo teneva tredici file `release-notes-v0.5.xx.md` nella radice. Resta solo quello dell'ultima versione, la 0.5.82: le note delle versioni vecchie non servono a chi aggiorna, e un elenco di tredici file in radice è rumore in ogni `list_dir` e in ogni ricerca. Su GitHub resta la release corrente.

### 11. Cosa resta aperto, e perché

Tre cose le ho viste e non le ho toccate, e vanno dette:

- **Nomi misti.** Convive `read_file` con `web_cerca`, `path` con `nome_file` e `immagine`. Uniformare vorrebbe dire rinominare identificatori pubblici: permessi salvati, test e skill si rompono insieme. Costa più del fastidio che toglie, e un alias per ogni nome raddoppia la superficie.
- **Niente processi in background.** `run_shell` ha un `timeout` e uccide: un `npm run dev` non sopravvive alla chiamata, quindi l'agente non può avviare un server e poi guardarlo. È il buco più grosso che resta per un uso "al massimo".
- **`confronto.py` non è collegato** a nessun comando: il confronto fra due modelli sui task che discriminano esiste, è testato, e non c'è un modo di chiederlo. Due classi `ToolRegistry` convivono (`types.py` e `tools/__init__.py`), con un ponte di alias: funziona, ma è la duplicazione che genera il prossimo difetto.

### 12. Prove

Suite completa: **92 suite passate, 0 fallite**. Due non sono potute partire, e non è un verde mancato per distrazione: `e2e` vuole una chiave vera, e `decisions-schema` chiama `inception/mercury-decide:free`, che il provider ora risponde 404 — il modello è sparito, il test lo dice invece di passare. I file toccati: `test_documenti` 67, `test_istruzioni` 17, `test_offline` 66, `test_skill_tools` 61, `test_skills` 71, `test_servizi_ui` 23.
