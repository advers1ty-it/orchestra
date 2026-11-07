## v0.5.73 — Il turno che non partiva

### Il difetto
- Collegare una chat Telegram funzionava: token verificato, QR, chat aggiunta, pannello aggiornato. Il primo messaggio però rispondeva **«Errore durante il turno: 'Session' object has no attribute 'stream'»**, e nessun turno girava.
- La causa era una riga: `telegram_turno` leggeva gli eventi del turno con `sess.stream(...)`, ma `stream` **non è un metodo della `Session`**: vive sul suo `EventBridge`. Tutto quello che la finestra web ha sempre fatto (`sess.bridge.stream`) qui mancava di un pezzo, ed era il primo percorso a passare di lì.
- La chiamata stava **prima** di `sess.send(...)`, quindi l'eccezione arrivava prima che il turno esistesse: nessun token speso, nessuna risposta a metà, solo l'errore. I comandi che non fanno un turno (`/stato`, `/aiuto`, il saluto di collegamento) funzionavano, ed è per questo che il guasto sembrava a metà strada.

### Perché i test non lo vedevano
- La sessione finta usata dai test del ponte aveva un `stream` **inventato**, più generoso della classe vera: il test passava su un metodo che la produzione non ha. Ora il finto espone `bridge` → `BridgeEventiFinto.stream`, esattamente come `Session` → `EventBridge`, e un metodo che nella `Session` vera non esiste non può più passare inosservato.
- Accanto al contratto c'è un blocco che fa girare `app.telegram_turno` su una **`Session` vera**, con il solo provider finto: il turno deve partire, produrre gli eventi e finire con la risposta del modello dentro la chat. È il caso che mancava.
- Prova di regressione fatta: rimettendo `sess.stream` la suite fallisce con lo stesso `AttributeError` che si vedeva su Telegram.

### Test
- `tests/test_telegram_sessione.py` 97 check, 0 fail (quattro nuovi: gli eventi stanno su `bridge.stream`, e un turno vero completo).
- `tests/test_webapp.py` 48 check, `tests/test_telegram.py` 129 check, entrambe verdi.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2). Un'istanza già aperta tiene in memoria il codice vecchio: finché non riparte, Telegram continua a rispondere con l'errore.
