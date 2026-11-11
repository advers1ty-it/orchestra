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
dichiarandolo, invece di bloccare un'installazione che .NET potrebbe
riuscire a fare.

## Una riparazione sola

`:ripara_radici` è l'unico posto con i due comandi: la usano la sonda
prima del download e il controllo dopo l'estrazione. `-generateSSTFromWU`
scrive solo un file e non chiede permessi; `-addstore` tocca lo store di
sistema, quindi si eleva **solo la seconda metà**.

## Perché Python 3.12 (verificato, non ricordato)

Il codice non richiede la 3.12: `pyproject.toml` dichiara `>=3.11`, la CI
gira su 3.11, `Orchestra.cmd` accetta qualunque > 3.10. La preferenza
per 3.12 nasce dal launcher (commit `56c54b9`: 3.12, poi 3.11, poi PATH)
e il 3.15 era evitato per un motivo che non era il codice: era un
**runtime portabile finito per sbaglio nel repo** (142 MB, tolti con
`b8c34fa`), con il launcher `py` che puntava lì.

Misurato adesso su quel runtime 3.15.0 (OpenSSL 3.5.9): `import
orchestra` funziona e `certificati.py` risponde "1/1 a posto"; quello che
non funziona è `python -m pip`, che muore all'import. E sulle dipendenze:
Pillow 13 ha le ruote cp311→cp315, ctranslate2 4.9 arriva a cp315,
`ddgs`/`pypdf`/`faster-whisper` sono ruote pure, mentre **onnxruntime
1.31.1 si ferma a cp314** — quindi la trascrizione audio su 3.15 è
rischiosa.

Conclusione: 3.12 resta la scelta prudente (tutte le ruote ci sono), la
3.14 è coperta da tutto, la 3.15 no finché onnxruntime non pubblica la
ruota.

## Verifiche

La sonda è stata estratta dal `.bat` vero ed eseguita in due harness:
host vero → passa e va al download; host inesistente → salta la
riparazione e prosegue. Etichette verificate (`tls_download`,
`ripara_radici`), fine riga CRLF, nessuna riga con spazio iniziale
rimasto. `tests/test_certificati.py` resta a 33 controlli verdi.

Il ramo che chiede l'elevazione resta non esercitato: la macchina di
sviluppo ha già lo store completo.
