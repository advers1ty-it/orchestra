## v0.5.76 — Il modello scelto a mano resta

### Il difetto
Nella 0.5.75 il cambio modello veniva salvato per davvero, ma al primo messaggio il modello tornava quello di prima. Non era il salvataggio: era l'**instradamento automatico**, che a ogni invio risceglie il modello in base alla categoria della richiesta e scrive la sua scelta nel `.env`. Il modello scelto a mano durava **una richiesta sola**.

Per questo la sequenza era: `/modello` → conferma → `/stato` giusto → scrivi → risposta di un altro modello → `/stato` di nuovo il vecchio. Niente, in quel giro, diceva che qualcuno stava decidendo al posto tuo.

### Cosa è cambiato
- La finestra questa cosa la faceva già, ma in una copia della regola scritta solo per la sua strada: Telegram salvava il modello e lasciava l'instradamento acceso. Ora la regola sta in un posto solo, e vale per il menu della finestra e per `/modello` da Telegram.
- Si spegne **solo** quando la scelta è tua. Un ripiego dopo un errore e la riparazione all'avvio continuano a instradare: quelli stanno rimediando, non decidendo.
- Lo spegnimento viene scritto nel `.env` (`ORCHESTRA_ROUTING`), quindi regge anche dopo un riavvio — prima il router si sarebbe riacceso a ogni avvio e il modello sarebbe tornato a durare una richiesta. L'interruttore del pannello Benchmark riaccende e rispegne, e anche quella scelta resta.
- La conferma di `/modello` ora dice che l'instradamento automatico è stato spento, e non promette più che il modello «vale dalla prossima richiesta», che era vero solo nel senso peggiore.

### Se vuoi l'instradamento automatico
Si riaccende dal pannello Benchmark. Con l'instradamento acceso, la scelta manuale vale per la richiesta in corso e la successiva torna a essere decisa dai punteggi: è il comportamento voluto di quella modalità, non un difetto.

### Test
- `tests/test_telegram_sessione.py` 118 check: nuovo blocco sull'interruttore (si spegne, resta scritto nel file — su un `.env` temporaneo, mai su quello vero — la conferma lo dice, spegnerlo due volte non è un errore, e la scelta arriva al cambio modello come scelta dell'utente).
- Verdi anche: `tests/test_telegram.py` 137, `tests/test_webapp.py` 48, `tests/test_rotte.py` 34.
- `tests/test_chiavi.py` 32/1: fallisce «c'è una data sui limiti», perché `NOTA_FREE` non contiene più un anno. Fallisce anche senza queste modifiche: è un check da aggiornare a mano quando si ricontrollano i piani gratis, e non l'ho toccato qui.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2). Dopo il riavvio, rifai `/modello` una volta: il fix agisce sul cambio, non su quello già fatto con la versione precedente.
