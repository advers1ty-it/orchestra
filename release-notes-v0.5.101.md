# v0.5.101 — Tool locali sicuri, browser senza rete locale e MCP pronti

Questa release raccoglie tutto quello che è cambiato dopo la 0.5.100. Il
filo comune è lo stesso: i tool devono poter lavorare sul progetto senza
aprire una seconda strada per uscire dalla root, dalla rete locale o da
una conferma esplicita.

## Git in sola lettura, commit con conferma

Il nuovo tool `git` legge lo stato del repository con tre azioni:
`status`, `diff_stat` e `log`. Non esegue comandi arbitrari, non passa da
una shell, non usa driver esterni o `textconv` configurati nel repository
e non aggiorna l'indice. L'output è tagliato a 12.000 caratteri e il taglio
viene dichiarato: un elenco che finisce a metà non deve sembrare completo.

Commit e push restano nella shell, ma ora chiedono una conferma esplicita
anche quando il comando gira dentro la cartella di lavoro. "Siamo nel
progetto" non è una risposta alla domanda "vuoi pubblicare?".

## Scaricare senza curl

Il nuovo tool `scarica` porta un file dal web dentro il progetto. Usa le
stesse guardie di `web_leggi` — host locali e rete privata bloccati,
redirect e peer ricontrollati, massimo 1.200.000 byte — e lo stesso confine
di percorso di `write_file`. Un file troppo grande non viene scritto; uno
esistente passa dal checkpoint prima di essere sostituito. Non serve più
`curl` nella shell per un PDF, uno zip o un'immagine.

## Modifiche a batch e processi interattivi

- `edit_file` accetta una lista di sostituzioni: legge il file una volta,
  le applica in ordine e scrive una volta sola. Se una voce non trova la
  sua stringa, non viene scritto niente. Il batch è atomico, non mezzo
  applicato.
- `processo` sa scrivere su stdin con `azione="scrivi"` (massimo 4.000 byte
  UTF-8 per chiamata, con `a_capo` opzionale), così un REPL o una CLI che
  chiede conferma può ricevere una risposta. La cartella di lavoro passa
  dal confine dei percorsi e il log di ogni nuovo processo viene troncato
  all'avvio: non si legge più l'output della sessione precedente.

## Browser: l'URL finale viene controllato

`browser_render` e `browser_screenshot` ora passano dal CDP e leggono
`location.href` dopo la navigazione. Se un URL pubblico reindirizza a
localhost o alla rete privata, il DOM non viene estratto e lo screenshot
non viene catturato. La sessione viene chiusa, così un successivo
`browser_console` o `browser_rete` non può rileggere la pagina locale.

Il ripiego senza browser continua a usare le guardie di `web_leggi`
(`_RedirectPubblico`, `_peer_pubblico` e il controllo dell'URL finale).
`browser_apri` resta l'eccezione voluta: apre la pagina nel browser
dell'utente e non riporta il contenuto al modello.

## Cron: il profilo non torna ad auto

Una modifica parziale di un job `goal` che cambia solo l'obiettivo non
riscrive più `profile`. Il valore già salvato resta quello del job; un
profilo esplicito continua ad applicarsi. Vale sia per il tool sia per
`/api/cron/update`.

## MCP: preset pronti e conferme

Il pannello MCP ha un catalogo di 53 preset con ricerca. Aggiungere o
connettere un server locale potente — filesystem, Git, database, Desktop
Commander, Grafana, Terraform — richiede una conferma esplicita. I preset
potenti non vengono riconnessi automaticamente, e il tool `mcp` usa il
gate di permesso anche su `connetti`.

## Riepilogo e consigli di fine turno

I consigli nascono dal turno appena finito, non da quello precedente. Il
riepilogo — esito, file e costo — appartiene alla sessione: due turni
insieme non si scambiano più i riepiloghi, e su Telegram i pulsanti del bot
leggono il riepilogo del bot che ha lavorato. `idle` arriva dopo il
riepilogo, e il turno resta occupato fino a quel momento, così un secondo
invio non parte mentre il primo sta ancora chiudendo.

## Test

Sono coperti con prove dedicate il tool `git`, `scarica`, il redirect
pubblico→locale del browser (anche con un 302 reale), la modifica parziale
del profilo cron, lo stdin dei processi, le modifiche a batch di
`edit_file` e la conferma di commit/push. Il test multichat aspetta il
turno prima di leggere la risposta, invece di dipendere dalla velocità di
Windows.

## Note sull'aggiornamento

Gli asset di questa release sono due:

- `orchestra-0.5.101.zip` — il codice, con una sola cartella radice
  (`orchestra-0.5.101/`), nel formato che l'updater accetta.
- `Installa-Orchestra.bat` — l'installer per Windows. Legge
  `releases/latest`, quindi si rilancia su un'installazione esistente per
  aggiornarla: sovrascrive il codice e lascia stare `.env`, i database, il
  token di Telegram e le skill.

Niente da migrare: i nuovi tool leggono lo stato esistente e non cambiano
il formato dei dati.
