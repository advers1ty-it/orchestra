## v0.5.66 — Più figli insieme, e una CI che guarda

### Delega in parallelo
- `delega_multi` prende una lista di obiettivi e li affida **insieme**: thread con un tetto di figli concorrenti (3 per default, tetto totale dei figli invariato) e una scadenza valida per **tutto il gruppo** (240 s). Un tetto per figlio si moltiplicherebbe per quanti sono, e chi aspetta non sa quanti ne ha in coda.
- I risultati tornano nello stesso ordine della lista, uno per figlio, ognuno con esito, passi, modello e costo. Restano separati: unirli è una decisione del padre, non un `join` automatico — come per i worktree.
- Un figlio che non finisce entro il tempo ha esito `scaduto`, distinto da `errore`: non si sa se ha sbagliato, si sa che non ha finito, e le due cose portano a decisioni diverse. Gli viene chiesto di fermarsi al passo successivo: un thread in corso non si uccide, e il motivo lo dice invece di fingere che sia finito.
- Il tool c'è nella chat e nei goal. Nei goal non applica il retry con modelli alternativi: quel retry forza il modello con uno stato condiviso, e in parallelo i figli si vedrebbero il modello l'uno dell'altro.
- Nella chat ogni figlio arriva come evento con `[n/totale]`: si vede che stanno lavorando invece che il padre sembrare fermo.
- Il parallelismo ha scoperto tre difetti che l'esecuzione sincrona non mostrava: il conto dei figli era letto e incrementato fuori da un lock, il tariffario leggeva il modello della delega precedente, e una delega scaduta che poi finiva veniva contata due volte.
- `delega` e `delega_multi` vengono riaccesi dopo `applica_profilo`, che al primo turno con un profilo scelto li spegneva in silenzio.

### Integrazione continua
- La suite gira a ogni push e pull request, su Ubuntu e Windows, da un checkout pulito e senza chiavi vere: le suite di questa corsia parlano con provider finti. Windows c'è perché è la piattaforma di sviluppo e diversi percorsi (shell, permessi, autostart) cambiano lì.
- Una corsia **notturna** esegue `test_e2e` con il provider vero, leggendo la chiave dal secret. `workflow_dispatch` esegue solo lei: "lancia il workflow" significa "verifica l'API adesso", non "spendi token senza saperlo".
- La sonda `decisions-schema` misura un endpoint alpha su un modello gratuito che può essere ritirato: quando non risponde più si dichiara **non avvenuta** invece di tenere la CI rossa per una causa esterna, che nasconderebbe i difetti veri.

### Difetti trovati dalla CI
Su Windows non potevano emergere, e il primo push li ha fatti uscire tutti.
- Su Linux ogni comando shell moriva con "Exception occurred in preexec_fn": venivano passati insieme `start_new_session` e una `preexec_fn` che chiamava `setsid`. Resta solo `start_new_session`, che è anche la forma sicura con thread attivi.
- Su POSIX il controllo dei percorsi della shell guardava solo le drive Windows e tre prefissi noti: `cat /etc/passwd` non chiedeva il permesso e, senza gate, non veniva fermato. Su Linux il confine della shell non esisteva.
- Il divieto sui percorsi sensibili guarda anche la forma **scritta**, non solo quella risolta: `/bin/ls` su Ubuntu è un symlink fuori da `/bin`, e il divieto spariva con la risoluzione. Un divieto aggirabile con un symlink non è un divieto.
- Revoca e consenso usano la stessa chiave canonica: prima la revoca toglieva un permesso costruito sul percorso grezzo mentre il consenso era salvato su quello risolto, e l'operazione dopo restava concessa.
- Su Windows di CI la cartella temporanea arriva come `RUNNER~1` e viene risolta nel nome lungo `runneradmin`: il gate considerava fuori dalla root file che stavano dentro, e il consenso veniva ricordato su una stringa e cercato su un'altra. I confronti passano da `realpath` e `normcase`.

### Cronologia
- Aprire una conversazione dalla cronologia aggiorna la chat: lo snapshot dichiara la sessione a cui appartiene e il client la confronta con quella che sta mostrando. Prima il clic selezionava la riga ma la conversazione a schermo restava la vecchia fino al refresh.

### Test
- `tests/test_permessi_integrazione.py` era fuori dal runner e importava `tools._safe_path`, sparita quando la guardia si è spostata in `_guard.py`: moriva con `AttributeError` e non se ne accorgeva nessuno. Un test fuori dal runner non è un test. Ora è nel runner e copre i sette casi che già provava.
- Nuova suite `delega-multi`: parallelismo reale, tetto della concorrenza, scadenza, deduplica della storia, costo per figlio e registrazione nei goal.
- Le suite che assumevano percorsi Windows su ogni sistema ora scelgono il percorso per piattaforma e confrontano percorsi canonici, non la loro forma.
- Lo stesso test dei permessi è stato rosso due volte in CI per due difetti veri del test — il percorso "vietato" relativo su POSIX e il nome breve della cartella temporanea — e ogni volta la correzione è stata nella direzione giusta: il codice non è cambiato.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
