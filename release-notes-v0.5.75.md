## v0.5.75 — Il modello cambia davvero, e la foto la legge chi può

### `/modello` cambiava il modello e buttava via il servizio
- Il menu fa scegliere **prima il servizio e poi il modello**, ma al salvataggio arrivava solo il modello: il servizio restava quello di prima. Da qui due cose vere che sembravano un bug di `/stato`: la conferma diceva «modello cambiato» (e lo era) e `/stato` mostrava il precedente, perché la sessione successiva chiedeva il nuovo id **al servizio vecchio**, dove non esiste, e ripiegava su un altro modello. Per questo il modello in uso non era né il nuovo né esattamente il vecchio.
- Ora il servizio viaggia insieme al modello: viene validato sul catalogo **di quel servizio** (quello già letto dal menu, senza una richiesta di rete nuova dentro un tocco) e salvato con il modello — `ORCHESTRA_PROVIDER` nel `.env` per l'agente principale, o nel record del bot. La conferma dice anche su quale servizio il modello è attivo.
- Corretto anche un caso vicino: un tocco da Telegram poteva scrivere sul bot selezionato nel pannello invece che sull'agente che aveva ricevuto il comando.

### Una foto a un modello che non la legge
- `recursive/flint-v1.0:free` è dichiarato `text->text` da OpenRouter: **non legge immagini**. A un modello così la foto non dà errore — il modello risponde lo stesso, su qualcosa che non ha visto. Infatti alla foto del cappuccino è arrivata una frase sul proprio nome, che veniva dal system prompt.
- Il controllo sulla vista esisteva solo nella finestra, e guardava la variabile d'ambiente invece del modello della sessione: con un bot che ha un modello suo, veniva scavalcato. Ora c'è un controllo unico per tutte e due le strade, che risponde sì, no, o «il catalogo non lo sa» — e nel dubbio **non** blocca.
- Da Telegram la foto viene rifiutata con una riga che dice quale modello non la legge e cosa fare, invece di far finta di aver guardato.

### Test
- `tests/test_telegram_sessione.py` 109 check: nuovi blocchi sul menu (il servizio toccato resta, il modello è quello di quel servizio, la conferma lo nomina) e sulla foto a un modello cieco (rifiutata, turno non partito, modello sconosciuto non bloccato).
- Verdi anche: `tests/test_telegram.py` 137, `tests/test_webapp.py` 48, `tests/test_rotte.py` 34, `tests/test_bench_fermo.py` 33.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2). Un'istanza già aperta tiene in memoria il codice vecchio.
