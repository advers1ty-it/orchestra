## v0.5.77 — Se la foto non parte, ti dico chi la legge

### Perché `stealth/crouton-alpha` non è stato rifiutato
Il rifiuto per la foto scatta quando il catalogo dice che il modello è text-only — così funziona per `recursive/flint-v1.0:free`, che dichiara `input_modalities: ["text"]`. Crouton Alpha dichiara invece `text, image, video, file, audio`: per Orchestra era un modello con la vista, la foto è partita, e il modello non l'ha guardata.

Non c'era un dato migliore da usare. Gli endpoint di OpenRouter non espongono un campo sull'input immagine: ho confrontato `nemotron-3.5-super-vl:free` (legge le foto) e `crouton-alpha` (non le legge) e hanno gli stessi valori, `supports_image_reference: false` entrambi. La scheda del modello è l'unica dichiarazione disponibile, e per Crouton è sbagliata: descrive il modello, non quello che l'endpoint che ti serve accetta davvero. Un modello "stealth" è anonimo e in prova, ed è il posto dove queste sorprese capitano.

Quindi: nessun rifiuto prevedibile per quel caso. Il turno con la foto parte e il modello risponde al turno precedente, perché il messaggio con l'immagine non gli arriva.

### Cosa cambia
Il rifiuto — quando c'è — non è più un no senza uscita. Insieme al motivo propone due modelli del catalogo che **dichiarano la vista e sono gratis**:

- su Telegram il comando è pronto: `/modello nvidia/nemotron-3.5-super-vl:free`
- nella finestra il nome da scegliere dal menu in alto, perché lì un comando non esiste

La scelta non è a caso: prima chi ha il contesto più grande, che serve più spesso. Niente modelli a pagamento e niente modelli ciechi nella proposta. Se il catalogo non ha nessun candidato, resta una frase che manda a sceglierne uno, invece di una riga muta.

### Cosa resta da sapere
La proposta compare solo quando il rifiuto c'è: con un modello che *dichiara* la vista e non ce l'ha, Orchestra non ha modo di accorgersene prima. Se una foto non viene guardata, il modello è la prima cosa da cambiare — ora il rifiuto te ne dà uno pronto.

### Test
- `tests/test_telegram_sessione.py` 125: candidati solo gratis e con la vista, ordinati per contesto, nessun modello a pagamento o cieco nella proposta, il consiglio della finestra non nomina comandi che lì non esistono, e senza candidati resta una frase.
- Verdi anche: `test_telegram.py` 137, `test_webapp.py` 48, `test_rotte.py` 34, `test_allegato_giro.py` 15, `test_allegato_e2e.py` 19.
- `test_chiavi.py` resta 32/1 sul check preesistente «c'è una data sui limiti» (`NOTA_FREE` non contiene un anno), che fallisce anche senza queste modifiche.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
