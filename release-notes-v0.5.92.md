# v0.5.92 — Le falle del backup e della posta, chiuse

## La revisione, e cosa ha trovato

La 0.5.91 funzionava sui casi normali. Rileggendola con l'occhio di chi cerca
il caso storto — percorsi sbagliati, profili incrociati, server acceso — sono
uscite sette cose che valeva la pena correggere prima che le trovasse qualcun
altro.

## Backup

- **Un percorso esistente non è un'installazione.** `--profilo D:\` (o
  qualunque cartella) veniva accettato perché la cartella c'era: si zippava
  quello che conteneva, e un ripristino ci scriveva dentro. Ora si accettano
  solo cartelle dati vere (segnaposto, oppure nome esadecimale con file di
  dati).
- **Il percorso dell'installazione tornava rifiutato.** Il controllo nuovo
  scartava anche `D:\orchestra`, che è la cosa più naturale da scrivere e
  quella che stampa `--elenco`. Radice e cartella dati ora sono entrambe
  valide, e l'id funziona davvero (prima confrontava il nome con un percorso
  assoluto: mai uguale).
- **Le chiavi di un profilo finivano nel `.env` di un altro.** Ripristinando
  un'altra installazione che non aveva un `.env` proprio, si usava quello
  dell'installazione in uso: chiavi sovrascritte, in silenzio. Ora le chiavi
  si scrivono solo se c'è un `.env` di destinazione, e il ripristino dichiara
  quando le ha saltate.
- **L'installazione in uso non si ripristina dal browser.** Il server tiene
  aperte le connessioni sqlite (lo storico per tutta la vita del processo):
  sostituire i file sotto di lui lascia l'app a scrivere nel vecchio, e su
  Windows può fermarsi a metà. Il pannello lo dice e indica il comando da
  terminale a server chiuso; le altre installazioni si ripristinano
  normalmente.
- **Il segnaposto nasceva senza versione.** Veniva scritto prima che
  `__version__` esistesse: adesso è scritto in fondo, con la versione vera.
- **Il segnaposto dell'installazione non viaggia con i dati.** Veniva
  ripristinato anche `installazione.json`: i dati di B, ripristinati in B, si
  presentavano come quelli di A. Peggio, il percorso del `.env` veniva letto
  *dopo* aver estratto il segnaposto, quindi le chiavi finivano nel profilo
  sbagliato. Ora il segnaposto resta quello locale, e la destinazione delle
  chiavi si decide prima di estrarre qualsiasi cosa.
- **Un manifesto con `formato` non numerico** faceva cadere il ripristino con
  `ValueError` invece di dire che il formato non è conosciuto.

## Posta

- **Leggere un messaggio non scarica più tutto.** Si chiedevano i messaggi
  interi (`RFC822`): dieci mail con un allegato da 20 MB erano duecento
  megabyte per un'anteprima. Ora si chiede l'intestazione e al massimo 4 KB
  della prima parte di testo.
- **Il multipart si riconosce dal `Content-Type`.** Su sole intestazioni
  `is_multipart()` è sempre falso: un messaggio con allegato veniva letto come
  corpo unico, con i confini MIME dentro l'anteprima.
- **Le cartelle con lo spazio vanno fra virgolette.** `[Gmail]/Sent Mail`
  passato nudo sono due argomenti, e il server risponde BAD.
- **La connessione si chiude anche quando il login fallisce**, invece di
  lasciare un socket aperto per ogni tentativo.

## Verifiche

`test_backup.py` 46 check (destinazione arbitraria rifiutata, radice
dell'installazione accettata, id risolto, `.env` di un altro profilo intatto,
chiavi saltate dichiarate, segnaposto non sovrascritto, formato strano), `test_mail.py` 49 (richiesta a
pezzi, niente `RFC822`, cartella quotata, multipart con allegato letto dal
testo), più `test_rotte` 34, `test_ui` 54, `test_frontend_split` 34,
`test_webapp` 48, `test_documenti` 67. Tutti verdi.

Riavvia Orchestra per avere le correzioni.
