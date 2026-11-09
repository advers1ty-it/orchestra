# v0.5.90 — I dati si portano via, e la posta entra

## Cosa mancava

Reinstallare Orchestra su un altro computer significa ricominciare da zero:
memoria, cronologia, bot, lavori, collegamenti Telegram, budget e cron stanno
nella cartella dati dell'installazione, e nessun aggiornamento li sposta. Non
c'era un modo per portarli con sé, né per rimetterli senza copiare file a mano
sperando di aver preso quelli giusti.

E l'agente non sapeva leggere una casella di posta: nessun modo di dire «guarda
cosa mi hanno scritto» o «manda questa mail», se non passando da un servizio
esterno che della posta dell'utente non sa niente.

## Cosa c'è ora

- **`orchestra backup`**: mette tutti i dati in uno zip, più il `.env` con le
  chiavi (`--senza-chiavi` per lasciarle fuori). I database si copiano con il
  backup di sqlite, non con una copia del file: con il journal WAL il solo
  `.db` può non contenere le ultime scritture, e un backup incompleto si
  scopre solo al ripristino.
- **`orchestra restore archivio.zip`**: rimette i dati. Prima salva lo stato
  attuale, quindi un archivio sbagliato non distrugge niente; rifiuta gli zip
  senza manifesto e quelli con percorsi fuori dalla cartella dati.
- **Tool `email`**: legge la casella con IMAP (sola lettura, filtri per
  mittente, oggetto, testo, non letti, cartella) e manda con SMTP, allegati
  compresi. Preset per Gmail, Outlook, Libero, Virgilio, Aruba, Tiscali,
  iCloud, Yahoo, Fastmail, GMX; host a mano per tutto il resto. Nessun
  servizio da aprire: si usa la casella che c'è già.
- **Errori che spiegano**: se manca una chiave, se il fornitore non è noto o
  se il server rifiuta l'accesso, il messaggio dice cosa impostare e ricorda
  che Gmail e Outlook vogliono una password per le app.

## Verifiche

`test_backup.py` 26 check (archivio, riga nel database dopo il WAL, ripristino
in una home vuota, sicurezza prima di sovrascrivere, archivi estranei e
percorsi che escono rifiutati, chiavi incluse solo su richiesta) e
`test_mail.py` 44 check (preset e override, filtri IMAP, busta SMTP con Cc e
allegati, STARTTLS e porta 465, errori di accesso, tool senza configurazione).
Tutti verdi, con server finti: nessuna password vera e nessuna rete.

Riavvia Orchestra: i tool nuovi si registrano all'avvio.
