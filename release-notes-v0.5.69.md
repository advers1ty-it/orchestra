## v0.5.69 — Prima si approva, poi si vede cosa è cambiato

### Modalità piano: leggere prima di toccare
- Un interruttore in testa (`Piano`) inverte il default: i tool che modificano — scritture, shell, test, cron, MCP, memoria, skill, computer — restano bloccati, e l'agente deve prima leggere e poi proporre i passi con `proponi_piano`.
- Il piano arriva in una modale con «Approva il piano» e «Rifiuta»; il clic sull'opzione **è** la decisione, non un suggerimento da completare. Le righe si conservano fino a 6000 caratteri.
- L'approvazione vale **per il turno in corso**: al turno dopo si torna a proporre. Vive in un `threading.local`, quindi approvare in una scheda non sblocca le scritture di un'altra.
- Il parser è default-deny: si esegue solo con un sì riconoscibile. «No, cambia il passo 2» non approva; «approvo, ma togli il passo 3» approva e la nota torna al modello come indicazione da rispettare.
- Il blocco sta in un punto solo (`_execute_tool`): sparso nei tool, dimenticarsene in uno avrebbe reso la modalità una promessa. Senza nessuno collegato (CLI, benchmark) il piano non si approva: resta scritto e il turno si chiude.

### Letture in parallelo
- Quando un giro chiede più tool di **sola lettura** (leggere, cercare, elencare, analizzare, web, skill, render/screenshot) partono insieme, al massimo quattro. Una raffica di `read_file` indipendenti non aspetta più la somma dei tempi.
- Basta una scrittura — o un argomento rotto, o un cancel — per tornare in fila. L'ordine delle `tool_calls` è informazione: `write_file` seguito da `read_file` sullo stesso percorso deve vedere il file nuovo, e due scritture in parallelo sarebbero una corsa.
- L'elenco è esplicito (`parallelo.py`), non dedotto dal nome: un tool nuovo che legge perde solo velocità, uno che scrive non ci finisce per errore (il test lo controlla). Gli esiti restano nell'ordine chiesto dal modello; `LoopConfig.parallelo = False` spegne tutto.

### Diff del turno
- Il bottone `Δ` accanto all'undo mostra le modifiche del turno: un blocco per file, con le righe aggiunte e tolte e lo stato (`nuovo`, `modificato`, `cancellato`, `binario`).
- Il confine lo segna l'agente a inizio turno; il diff si calcola al momento della richiesta, quindi mostra lo stato vero del file. Non azzera i backup: l'undo continua a funzionare anche su ciò che è stato scritto prima.
- Un file binario dice che non c'è un diff invece di stamparne uno illeggibile; un diff enorme si tronca e lo dichiara.

### Allegati Office
- `.docx`, `.xlsx` e `.pptx` si leggono come testo, senza dipendenze: sono zip di XML, e bastano `zipfile` ed `ElementTree`. Prima venivano rifiutati come «formato non riconosciuto».
- Di Word si prendono i paragrafi in ordine, con tabulazioni e interruzioni; di Excel il nome del foglio e il **valore calcolato** (non la formula), una riga per riga; di PowerPoint le diapositive in ordine. Il testo si tronca a 150.000 caratteri e lo dice.
- Il magic number vince sull'estensione, come per tutti gli altri allegati: un PNG chiamato `.docx` resta un'immagine, e un `.docx` che non è uno zip riceve un errore che spiega cosa manca.

### Test
- Nuove suite: `piano` (un turno intero: blocco, proposta, approvazione, scrittura; e il turno dopo di nuovo bloccato), `parallelo` (tempo reale e ordine dei risultati), `diff` (confine del turno, righe vere, nuovo vs modificato), `office` (file Office costruiti come zip minimi validi, più i casi che mentono).
- Suite completa verde su Windows e Ubuntu.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
