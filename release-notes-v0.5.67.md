## v0.5.67 — Le fondamenta: sicurezza, costi veri, ricerca

### Sicurezza
- I file di credenziali sono negati agli strumenti **anche dentro la cartella di lavoro**, non solo fuori. Prima `read_file(".env")` leggeva le chiavi del progetto mentre la shell le negava: il controllo valeva solo per i percorsi esterni, cioè quasi mai. Ora `.env` e le sue varianti (tranne i template), `.ssh`, `.aws`, `.gnupg`, `.docker`, `id_rsa`, `.netrc`, `.npmrc`, `.git-credentials` e `.git/config` sono protetti in lettura, scrittura, modifica ed elenco. Il messaggio dice che non è una scelta concedibile, così il modello non riprova.
- I comandi che distruggono la macchina sono bloccati **sempre**, anche senza policy del bot: `rm -rf /`, `rm -rf .`, `rm -rf *`, `del /f /s /q C:\`, `rd /s /q`, `format`, `mkfs`, `dd of=/dev/…`, `diskpart`, `bcdedit`, `vssadmin delete`, `cipher /w`, `shutdown`, fork bomb. Un `rm build/output.js` continua a passare: la lista è corta e specifica, non un divieto generico sui comandi distruttivi che verrebbe aggirato o disattivato.
- `web_leggi` blocca loopback, reti private, link-local, CGNAT e i nomi che risolvono lì, DNS rebinding compreso. I redirect vengono validati **prima** di seguirli: un sito pubblico che risponde 302 verso `169.254.169.254` non viene aperto.
- Il system prompt non contiene più un percorso personale né assume Windows: la shell dice se è cmd o bash, e i percorsi hanno il formato che gli strumenti mostrano.

### Costi e contesto
- Il budget non usa più una costante unica per ogni modello. Il prezzo viene dal catalogo (`prezzi.py`): un free tier costa zero, un modello da $15/M costa il suo prezzo, e se il prezzo non si conosce si dichiara una stima invece di spacciarla per misura. Prima un modello gratuito risultava a pagamento e uno caro sembrava gratis.
- `finish_reason=length` non chiude più il turno: la risposta è stata troncata dal tetto di output, non è finita. Si continua dal punto in cui il modello si è fermato, con un tetto ai «continua», e la UI lo scrive. Prima un file si interrompeva a metà riga sotto un «completato».
- Il conteggio dei token include immagini (~1.100 l'una) e `reasoning`. Prima la compaction non scattava su un turno con screenshot e arrivava il 400 per contesto pieno.
- La compaction usa un modello vero invece del troncamento testa/coda: in una conversazione lunga non sparisce più il centro, cioè le decisioni e gli errori già risolti. Se il riassunto fallisce si torna al troncamento, senza perdere il turno.
- Il ripiego dopo due errori conserva la categoria: prima un task di scrittura poteva ripiegare su un modello scelto per il codice.

### Ricerca nel progetto
- Due tool nuovi, in **tutti** i profili: `search_text` cerca testo o espressioni regolari nel contenuto e restituisce `file:riga: testo`; `find_files` trova nomi e percorsi con un glob. L'agente non deve più elencare cartelle a caso, leggere file interi per trovare una riga, o passare dalla sintassi di `grep` che cambia tra cmd e bash.
- Entrambi saltano `.git`, le dipendenze (`node_modules`, `.venv`), le cartelle locali (`_prova`, `_bench`) e i file di credenziali. Si fermano a un tetto di file **dicendolo**: prima una ricerca troncata rispondeva «nessuna corrispondenza», che è una bugia che manda il modello a cercare altrove.

### Repository
- Rimosso dal versionamento il runtime Python 3.15 incorporato: 2.319 file e 142 MB, con 599 manuali HTML di CPython che facevano dire a GitHub che il progetto è fatto al 73,8% di HTML. `.gitignore` lo escludeva già, ma era stato committato prima della regola e Git ignora solo ciò che non è tracciato. L'installer usa il Python 3.12 di sistema e `Avvia-Orchestra.bat` evita apposta il 3.15.
- Il badge ora dice la verità: Python 81%, JavaScript 12%, HTML 3%, CSS 3%, Batch 1%.
- Nota: i blob restano nella cronologia, quindi il peso del clone non cambia finché non si riscrive la storia.

### Test
- Nuova sentinella in `test_identita`: il test usava `"diverso"` come persona, e quella parola compare nel prompt di sistema. Falliva per collisione lessicale, non per un'identità rimasta.
- `test_lavori` non corre più contro il thread di ripresa: il caso dell'annullamento usa una coda senza consumatore. Su CI il thread vinceva la corsa e la suite moriva con «questo lavoro non è più annullabile».
- Dodici nuovi controlli offline su ricerca, credenziali, costo e troncamento; cinque nuovi su `test_security`.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
