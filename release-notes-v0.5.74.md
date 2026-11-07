## v0.5.74 — Il vocale, e la cronaca del turno

### Il vocale non ha mai trascritto
- Un vocale su Telegram rispondeva **«Non riesco a trascrivere il vocale: TypeError: open() got an unexpected keyword argument 'metadata_errors'»**. Non era un problema del file, del formato o di Telegram: `faster-whisper` 1.2.1 chiama `av.open(..., metadata_errors="ignore")`, e **PyAV 19 ha rimosso quel parametro** — ed è la 19 quella che pip installa oggi. L'errore arrivava prima di leggere un byte dell'audio.
- Il fix esiste a monte ma non è ancora rilasciato, quindi non lo si aspetta: `orchestra/stt.py` decodifica l'audio da sé, senza quel parametro (valido sia con PyAV vecchio sia con PyAV 19), e al modello passa campioni float32 mono a 16 kHz. Il percorso resta solo come ripiego se la decodifica non riesce.
- Vale per tutte e due le strade: i vocali dal telefono e la dettatura dal browser passano dallo stesso modulo.
- Verificato con un `.oga` Opus costruito apposta, cioè nel formato che manda Telegram: 16.000 campioni per un secondo, forma d'onda intatta, trascrizione che arriva in fondo. Su un tono e sul silenzio il testo è vuoto, che è la risposta giusta.

### Le azioni sono messaggi, non una riga che balla
- Prima tutto finiva in **un messaggio solo, riscritto**: si vedeva che qualcosa cambiava, non cosa era stato fatto. Ora un tool che parte è un messaggio suo, che resta in chat: `🛠 bash · pytest -q`, `🛠 read · orchestra/app.py`. Il nome da solo direbbe poco, il primo argomento utile dice su cosa sta lavorando.
- Il messaggio che si riscrive resta, ma per il **pensiero in corso**: una riga sola, che alla fine sparisce. Nessuno rilegge la coda del ragionamento, e lasciarla lì seppellisce la risposta.
- Due freni, perché una chat non è un log: i tool che partono nello stesso istante escono come **un messaggio solo con più righe** (non una raffica a un decimo di secondo), e ce ne sono al massimo **venti per turno**. Le azioni rimaste in coda quando il turno finisce partono lo stesso, in un messaggio solo.

### Test
- `tests/test_telegram.py` 137 check: le azioni come messaggi nuovi che restano, la sintesi cancellata, il raggruppamento della coda, e la decodifica dei campioni con il modello finto che verifica di ricevere campioni e non un percorso da riaprire.
- `tests/test_telegram_sessione.py` 100 check: un blocco nuovo fa girare gli eventi della **`Session` vera** (un `tool_start` con argomenti) e controlla che diventino un'azione con nome e argomento, e che non si ripeta agli eventi successivi.
- `tests/test_webapp.py` 48, `tests/test_bench_fermo.py` 33, `tests/test_rotte.py` 34: verdi.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2). Un'istanza già aperta tiene in memoria il codice vecchio: finché non riparte, il vocale dà lo stesso errore.
