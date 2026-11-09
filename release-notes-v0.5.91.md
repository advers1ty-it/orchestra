# v0.5.91 — Il backup vede tutte le installazioni, e ha un pannello

## Cosa non andava

`orchestra backup` salvava una sola installazione: quella che stava girando.
Chi ha l'app in AppData, una copia su `D:` e due server di prova ha quattro
cartelle dati diverse, e le altre tre restavano fuori dall'archivio. Non era
una svista da correggere con un `--tutto`: le cartelle si chiamano con un hash
del percorso (`3f2a9c1b77de`), e nessuno può dire quale sia quale. Chiedere
"quale vuoi salvare?" mostrando quegli identificativi sarebbe stata una domanda
senza risposta.

## Cosa c'è ora

- **Ogni cartella dati registra il proprio percorso** in un
  `installazione.json`, scritto all'avvio. L'hash non si può invertire; il
  percorso sì, e ora è lì.
- **`orchestra backup --elenco`** mostra le installazioni con percorso, id,
  file, dimensione e versione. `--tutte` fa un archivio per ciascuna (e non si
  ferma alla prima che va male), `--profilo D:\orchestra` sceglie quella.
- **`orchestra restore`** accetta `--profilo`: ripristina dove dici tu, e
  stampa da dove viene l'archivio. Senza indicazioni va nella corrente: non
  segue il percorso scritto nell'archivio, che su un altro computer non esiste.
- **Opzioni → Backup**: la stessa cosa dal browser. Le installazioni si
  leggono per percorso, con "Salva questa" e "Salva tutti"; sotto ci sono gli
  archivi già presenti, con "Ripristina" e una conferma che dice **dove** si
  va a scrivere. Il ripristino si rifiuta se c'è un turno in corso.
- **Le cartelle che non sono installazioni restano fuori.** Sotto
  `%LOCALAPPDATA%\orchestra` non ci sono solo cartelle dati: ci finiscono una
  copia del codice, i test e perfino un Python. Un'installazione si riconosce
  dal segnaposto, oppure da un nome esadecimale di 12 caratteri con dentro
  file di dati; una cartella di codice con un `budget_global.json` ereditato
  non basta, e "Salva tutti" non zippa più 370 MB di `node_modules`.
- **Nomi degli archivi senza collisioni**: due backup nello stesso secondo
  (Salva tutti subito dopo Salva questa) scrivevano lo stesso file. Peggio: il
  ripristino crea il backup di sicurezza *mentre* legge l'archivio, e se il nome
  coincide lo tronca a metà — l'archivio risultava corrotto. Ora il nome libero
  si cerca prima di scrivere.

## Verifiche

`test_backup.py` 40 check (14 nuovi: due installazioni con percorsi diversi,
la corrente per prima, scelta per percorso, un archivio per ciascuna, elenco
degli archivi per profilo, ripristino nell'installazione indicata, profilo
sconosciuto segnalato, e una cartella di codice accanto che non deve essere
scambiata per un'installazione). `test_rotte.py` 34 (tre rotte nuove e l'inventario a
133), `test_ui.py` 54, `test_frontend_split.py` 34, `test_webapp.py` 48,
`test_documenti.py` 67. Tutti verdi.

Riavvia Orchestra: le rotte e il pannello nuovi arrivano col codice nuovo, e
il segnaposto del percorso si scrive al primo avvio.
