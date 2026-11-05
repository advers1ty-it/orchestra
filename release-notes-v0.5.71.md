## v0.5.71 — Il turno ha un orologio, e la guida dice la verità

### Un tetto di tempo, non solo di passi
- Finora il limite era il **numero di iterazioni**: venti giri con test da due minuti e un server MCP lento facevano un turno da mezz'ora, con il tempo di nessuno che lo guardava. Ora c'è anche `max_secondi_turno` (default 900, `ORCHESTRA_MAX_SECONDI_TURNO`, `0` = spento).
- Si controlla in cima al ciclo **e dentro il batch dei tool**. Nel secondo caso ogni tool_call riceve comunque il suo risultato: un taglio non lascia chiamate orfane, che i provider severi rifiutano con un 400 e che ti facevano perdere il turno intero invece di chiuderlo.
- L'esito ha un nome suo — «tempo scaduto» — quindi il riepilogo e le Tracce lo dicono in parole, non con un codice.
- **In Opzioni → Modello**, sotto «Max iterazioni», c'è «Tempo massimo per turno (min)»: si scrive in minuti perché «15» si legge e «900» si calcola. Si applica subito, senza riavviare, e resta salvato.

### Il budget si controlla prima di spendere
- `check_limits` accetta ora una stima (`extra_tokens`, `extra_cost`) e `verifica_preventiva` calcola il costo peggiore col tariffario **prima** della chiamata. Prima si registrava e poi si controllava: la chiamata che sforava veniva pagata, ed era la più cara del turno. Un limite che ferma dopo aver speso non è un limite.

### Difetti trovati guardando i bordi
- **I limiti della configurazione non arrivavano alla sessione**: `Agent.__init__` passava i limiti come primo argomento posizionale di `get_or_create_session`, cioè come `session_id`. Il budget del `.env` veniva ignorato e si leggeva quello vecchio. Ora è per nome, e un test lo tiene fermo.
- **Il salvataggio del tempo limite mentiva**: `ORCHESTRA_MAX_SECONDI_TURNO` non era in `keys.WRITABLE`, e in quel caso `scrivi` restituisce `False` senza sollevare. La rotta rispondeva «salvato», il valore viveva in memoria e al riavvio spariva. Un tetto di sicurezza che si cancella in silenzio è peggio di un tetto che non c'è: ora la chiave è scrivibile e la rotta controlla l'esito, con un 500 invece di un falso ok.
- **I test delle rotte scrivevano nella configurazione vera**: `ENV_PATH` è un percorso fisso dentro il repo, quindi le POST di prova finivano nel `.env` dell'utente. Ora il test sposta solo la destinazione delle scritture su un file temporaneo e verifica che il valore ci sia davvero — la persistenza si prova leggendo il file, non fidandosi di un 200.

### Niente segreti dove non devono stare
- `orchestra/redazione.py`: firme dei provider, JWT, header Bearer, blocchi PEM e assegnazioni `*_KEY=` / `*_TOKEN=`. Si applica ai risultati dei tool **prima** che diventino un fatto (quindi prima del modello, della UI e dello storico) e di nuovo alla porta di `storico` e `traccia`.
- Il testo normale e i nomi di variabile restano intatti: un redattore che mangia gli URL si spegne, e allora non serve a niente.

### Scritture atomiche, comandi distruttivi che chiedono
- `write_file` ed `edit_file` passano da `scrittura.scrivi_testo`: temporaneo nella stessa cartella, fsync, `os.replace`. Un crash a metà non lascia più un file troncato, e i permessi del file esistente sopravvivono alla sostituzione.
- `rm -rf build/`, `git reset --hard`, `git clean -fd`, `git checkout -- .`, `del /s`, `Remove-Item -Recurse`, `truncate -s 0` non escono dalla cartella di lavoro, quindi il confine non li vedeva e il checkpoint non copre le cancellazioni. Ora chiedono conferma come azione **distruggere**, e un permesso dato per un comando normale non le autorizza.

### La guida, riscritta per chi la usa
- Era ferma alla **0.5.45** e a un'impostazione da sviluppatori: `cp .env.example`, `python3 -m orchestra.cli`, un dizionario di profili. Il numero di versione viene ora dal pacchetto, quindi non può più invecchiare.
- Due sezioni esistevano nel corpo ma **non nell'indice**: chi cercava «Tracce» o «Istruzioni del progetto» non le trovava.
- Mancavano interi pezzi dell'interfaccia che si usano ogni giorno: Skill, Cestino, Servizi, Gratis, Diagnosi, Benchmark, Avvio automatico, il pulsante ✓ di verifica, gli allegati Office, la dettatura, il riepilogo di fine turno, i quattro motivi per cui un turno si ferma (iterazioni, tempo, budget, annullamento). Ci sono ora, in ordine d'uso.
- Un paragrafo diceva «SSE/HTTP in roadmap» mentre tre righe sopra spiegava che i tre trasporti MCP sono supportati: contraddizione tolta.
- In fondo c'è un'appendice per sviluppatori (CLI, API, variabili): il resto è per l'utente finale.

### Test
- Nuove suite: `limiti-turno` (13 check), `redazione` (51), `scrittura-sicura`, `rotte-sicurezza` (ora 50: Origin, path traversal, rate limit del login, JSON rotto, input storto mai 500).
- `test_webapp` controlla la guida servita: risponde 200, non contiene il segnaposto, dichiara la versione del pacchetto, ogni voce dell'indice porta a una sezione vera e nessuna sezione resta fuori dall'indice. Sono le tre cose che si rompono quando si aggiunge un capitolo di fretta.
- Suite completa verde su Windows e Ubuntu.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
