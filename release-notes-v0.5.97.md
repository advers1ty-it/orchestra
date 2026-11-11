# v0.5.97 — L'installer guarda i certificati e chiede cosa installare

## Il caso

Su un Windows appena installato, salvare il token del bot Telegram
rispondeva questo:

```
Telegram ha rifiutato il token: rete non raggiungibile:
<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify
failed: self-signed certificate in certificate chain (_ssl.c:1010)>
```

Lettura naturale: la rete, un proxy, il firewall. Lettura giusta: niente
di tutto questo. `api.telegram.org` manda la catena **completa**, con
dentro la root `Go Daddy Root Certificate Authority - G2` firmata da sé;
OpenSSL, se quella root non è nel trust store, risponde
`self-signed certificate in certificate chain` e `telegram.py` lo
riportava come "rete non raggiungibile".

Perché solo su una macchina: Python su Windows **non ha un elenco di CA
suo**, le legge dal trust store di sistema. Un Windows vecchio, con anni
di aggiornamenti, ce l'ha; uno appena installato ha solo le radici
dell'immagine, perché le altre le porta Windows Update — che su una
macchina nuova non è ancora passato. Stesso interprete, stesso codice,
store diverso.

## Le radici che mancano, dette prima

`orchestra/certificati.py` è il posto unico in cui questo si controlla:
la radice richiesta è identificata dalla sua **impronta SHA-1**, non dal
nome (il nome è un testo, e "Go Daddy"/"GoDaddy" non fanno un certificato
diverso), e `--prova` fa un handshake vero per distinguere *certificato
non attendibile* da *rete non raggiungibile* — la distinzione che mancava
e che costava ore di diagnosi sbagliata.

Il referto è ASCII puro di proposito: la console dell'installer non è
UTF-8, e un trattino lungo faceva morire la stampa con
`UnicodeEncodeError`, cioè un errore di Python al posto della diagnosi.

## L'installer chiede quali funzioni vuoi

Prima l'installer installava Python, il codice e niente altro: `ddgs`,
`Pillow`, `pypdf`, `faster-whisper`, `cloudflared` restavano spenti, e il
modo di scoprirlo era un tool che rispondeva "installa Pillow" a chi
aveva appena finito di installare.

Ora il passo 5 mostra la lista con la funzione di ciascuna voce:

```
   1 - ddgs: ricerca sul web senza chiave (web_cerca)
   2 - Pillow: montaggio delle immagini (immagine)
   3 - pypdf: testo dei PDF (allegati e read_file)
   4 - cloudflared: tunnel remoto
   5 - faster-whisper: trascrizione audio (STT)
```

`Invio` installa tutto, `0` niente, oppure i numeri separati da spazio
(virgole e `;` tollerate). La lista non è scritta nel `.bat`: arriva da
`orchestra/dipendenze.py`, lo stesso modulo del pannello Opzioni, che ha
guadagnato una riga di comando (`--elenco`, `--installa`). Una seconda
lista è quella che resta indietro.

Il passo 4, subito prima, controlla le radici di certificati: se ne manca
una lo dice, propone di installarle da Windows Update con il consenso di
amministratore, e riverifica. Se il consenso non arriva, stampa i due
comandi da eseguire a mano.

## Un file solo dalla release

`Installa-Orchestra.bat` è ora **allegato alla release**: chi arriva qui
scarica quello, non l'archivio. Il `.bat` si porta dentro il downloader
(la sezione `REM-PS:`), quindi prende l'ultima versione da solo.

## Il difetto che è saltato fuori

Eseguire un modulo del pacchetto come file (`python orchestra/x.py`)
mette `orchestra/` in `sys.path[0]`, dove `orchestra/types.py` oscura la
`types` della standard library e l'import muore con *partially
initialized module*. Serve perché l'installer possa chiamare questi
moduli senza importare il pacchetto (che all'import migra i dati e
registra l'installazione). La riga che lo evita è la stessa che
`update.py` usava già.

## Verifiche

`tests/test_certificati.py` (nuovo, 33 controlli): impronte ben formate,
ramo "mancante" provato con una radice finta, referto ASCII, i due CLI
eseguiti con `subprocess` come fa l'installer. `tests/test_dipendenze.py`
resta verde (38 controlli). La subroutine `:dipendenze` è stata estratta
dal `.bat` vero ed eseguita: scelta `0` non installa nulla, `1 2` installa
ddgs e Pillow. Verificati anche i fine riga (CRLF) e che ogni
`goto`/`call` abbia la sua etichetta.

Il ramo che chiede l'elevazione non è stato esercitato: la macchina di
sviluppo ha già lo store completo, quindi il controllo esce "1/1 a
posto".
