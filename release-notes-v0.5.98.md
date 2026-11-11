# v0.5.98 — I certificati si controllano prima del download

## Il caso

Nella 0.5.97 il controllo delle radici arrivava **dopo** aver scaricato la
release. Su un Windows con lo store molto incompleto il primo passo a
rompersi è il download, e il messaggio è il vecchio "Download fallito.
Controlla la connessione": la stessa diagnosi sbagliata, solo spostata di
un passo indietro.

## La sonda, prima del download

Subito prima di scaricare, l'installer prova un TLS verso
`api.github.com` con lo **stesso Python che servirà dopo**. La sonda è
generica di proposito: chiede "questo TLS regge?", non "c'è la radice di
Telegram". L'elenco delle radici che servono all'app resta in
`orchestra/certificati.py`: una seconda lista scritta nel `.bat` sarebbe
la copia che invecchia.

Solo `CERTIFICATE_VERIFY_FAILED` apre il discorso (con la proposta di
riparare); se manca la rete il download fallirà e lo dirà lui. Dopo la
riparazione si riprova, e se ancora non passa si prosegue lo stesso
dichiarandolo.

## Una riparazione sola

`:ripara_radici` è l'unico posto con i due comandi: la usano la sonda
prima del download e il controllo dopo l'estrazione. `-generateSSTFromWU`
scrive solo un file e non chiede permessi; `-addstore` tocca lo store di
sistema, quindi si eleva **solo la seconda metà**.

## Rilanciarlo non cancella niente

Prima, rilanciare l'installer su un'installazione che esisteva gia'
ricreava `orchestra/` da zero. Con lei spariva `.env`, cioe' le chiavi, e
il passo dopo ne creava uno vuoto: l'app si apriva dicendo "chiave
mancante" e sembrava rotta.

Ora la copia unisce i file: sovrascrive il codice, non cancella mai una
cartella e lascia stare `.env`, i database, il token di Telegram e le
skill, a qualunque livello si trovino. Rilanciare l'installer su una
copia gia' installata e' quindi un aggiornamento valido, ed e' anche il
modo per passare a Python 3.14 senza reinstallare da zero.

## Python 3.14, e sempre quello

L'installer ora installa **Python 3.14** (con winget, o con l'installer
ufficiale se winget non c'è) e lo usa **per percorso completo**, come
`%LOCALAPPDATA%\Programs\Python\Python314\python.exe`.

Non si fida più di un `py` o `python` già presente, e il motivo è un
guasto vero: quelli non sono interpreti, sono **selettori**. Il controllo
poteva rispondere "va bene" e poi il selettore puntava a un'altra
versione — e su un PC dove resta un runtime "portabile" registrato ma
cancellato, l'installazione si fermava a metà dicendo che Python non
c'era, dopo averlo trovato.

Il launcher (`Orchestra.cmd`) cerca lo stesso 3.14, così l'app continua a
girare con l'interprete con cui è stata installata.

E perché non il 3.15: lì manca la ruota di `onnxruntime`, che serve alla
trascrizione audio. Sul 3.14 ci sono tutte. Se il 3.14 non riesce a
installarsi, l'installer usa un Python esistente e **lo dice**, invece di
chiudersi a metà: un'avvertenza chiara serve più di un'uscita silenziosa.
