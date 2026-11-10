# v0.5.94 — Il lavoro quotidiano, e un consiglio che vede

## Il caso

Questa release raccoglie due giri di lavoro che si tengono: i tool per
l'uso di tutti i giorni, e il consiglio di advisor. Il primo mancava nelle
note precedenti perche' era pronto dopo il tag della 0.5.93; il secondo
aveva un difetto che non si vedeva nel verdetto.

## Telegram e la macchina

- Il turno porta con se' il canale da cui arriva: l'agente sa di essere su
  Telegram e puo' rispondere li' con `telegram_invia`, in tutti i profili,
  senza vedere il token. Prima rispondeva «non posso inviarti messaggi su
  Telegram» mentre la risposta viaggiava proprio su quel ponte.
- «La macchina»: il prompt dice che i tool girano sul computer dell'utente,
  cosi' dal telefono non risponde piu' «non ho accesso al tuo computer» a
  chi gli chiede di lavorare sul proprio PC.

## I tool del lavoro quotidiano

- **Calendario** su un file `.ics` locale: eventi, tutto il giorno, ricerca
  per periodo, e la riga leggibile pronta da mandare.
- **Abbonamenti remoti**: un `.ics` pubblicato da Google, Outlook, iCloud o
  Nextcloud si legge in sola lettura, con ETag e `304`. La copia locale
  sopravvive a una rete assente, gli eventi remoti non si cancellano da
  qui, e un URL con credenziali dentro viene rifiutato. Google non accetta
  piu' le password applicative per CalDAV: per scrivere sul remoto serve
  un'app OAuth, ed e' una feature a se'.
- **Rubrica** in SQLite: stessa email significa aggiorna, non duplica.
- **Office in scrittura**: `.docx`, `.xlsx` e `.pdf`. Nel foglio: piu' fogli,
  formule vere (con ricalcolo all'apertura), intestazione bloccata,
  larghezze di colonna. `azione="aggiungi"` mette paragrafi in coda a un
  `.docx` e righe in coda a un `.xlsx` senza riscrivere il resto del file;
  un PDF si rifiuta, perche' non ha un «dopo» dove scrivere.
- **Il PDF sta dentro `office`**, non e' un quarantatreesimo tool: titolo,
  paragrafi e tabelle. Limite dichiarato: font base e codifica ristretta,
  quindi `€` diventa `EUR`.
- **`immagine`**: `image_gen` e `image_edit` sono un tool solo, con
  `azione="genera"` o `"modifica"`. Il contratto scende di circa 2.000
  caratteri e il modello sceglie un gesto, non due implementazioni.

## Il consiglio vede il tavolo che giudica

- I seat ricevevano la decisione e le chiavi «A», «B», «C» senza le
  etichette delle opzioni, e il prompt diceva di leggere `brief.md` a un
  agente senza tool: il dibattito era fluente e riguardava alternative che
  i seat non sapevano nominare. Ora il brief entra nel prompt di ogni
  round: decisione, sintesi del Chair, opzioni per esteso, assunzioni.
- Il cervello arriva intero: `principles.md` non veniva mai iniettato e
  `frameworks`/`positions` erano tagliati a meta'. Entrano le cinque sezioni
  utili senza troncare (tetto 96.000 caratteri; il piu' grande ne misura
  90.574).
- Il tavolo lo sceglie il Chair: da 2 a 7 seat, con una riga sul perche',
  Buffett sempre presente come guardia del downside. Nel pannello le card
  si cliccano, con «Consiglia tavolo», «Tutti» e «Tavolo abituale».
- Le citazioni con fonte vengono confrontate col cervello del seat: quelle
  che non tornano sono elencate nel verdetto e in `citazioni.json`.
- Il consiglio usa il provider e il modello scelti nell'app, non una
  priorita' scritta a mano; provider e modello restano scritti accanto
  alla sessione.
- Tre difetti di parsing trovati dal test nuovo: la confidenza era sempre
  10/10 (il round del voto non chiede `CONFIDENCE`), un `AMENDMENT` vuoto
  catturava la riga successiva, e «Endorse with amendment» contava come
  «Endorse».

## Sicurezza: i segreti restano fuori

- La redazione riconosce anche le credenziali **dentro un comando**, dove
  non c'e' un `NOME=valore` da intercettare: `mysql -p...`, `mysqldump
  -p...`, `sshpass -p`, `--password`, `PGPASSWORD` corto e le URL
  `schema://utente:password@host`. Sono le forme che una scansione per
  parole chiave non vede, e finivano intatte nello storico e nelle tracce.
- Se `ORCHESTRA_HOME` punta **dentro** un repository, la cartella dati si
  scrive un `.gitignore` con `*` e resta fuori da ogni `git add`. Sulla
  radice del repository Orchestra si ferma e lo dice, perche' li' un `*`
  ignorerebbe il progetto intero; `ORCHESTRA_HOME_FORZA=1` forza la
  scelta.

## Verifiche

`test_calendario_rubrica_office` 73 check (PDF riletto, tabella, append a
`.docx` e `.xlsx`, formula che si rilegge), `test_calendario_sync` 42
(server finto con ETag e 304), `test_documenti` 67, `test_office` 22.
`test_consiglio` 61 check con un provider finto (nessuna rete): brief ed
etichette nei prompt, cervelli interi su tutti e dodici i seat, tavolo
proposto, citazioni vere e inventate, matematica del verdetto, cap per il
rischio di rovina. `test_redazione` 69 (incluse le credenziali inline) e
`test_cartella_dati` 10 (cartella dentro il repo, radice rifiutata,
override esplicito, nessun effetto fuori da git). Verdi anche `test_rotte` 34 (135 rotte), `test_ui` 54,
`test_piano` 23, `test_file_tracciati` 3, e la CI su Ubuntu e Windows per
entrambi i commit delle funzioni.
