## v0.5.81 — Il testo che c'era, dichiarato assente

Dopo `image_edit` sono tornato sugli altri tool con una domanda sola: dove un tool risponde con sicurezza una cosa falsa? Ne sono usciti sette difetti, tutti dello stesso tipo — il tool non si rompe, ti dice il contrario di com'è. Un PDF con il testo dentro dichiarato "scansionato". Un file di testo letto come byte. Un salvataggio che cambia la codifica del file. Un percorso risolto contro una cartella che non esiste. E, fuori dai tool, un pannello che elencava tre dipendenze su cinque e non leggeva il file che le dichiara.

### 1. Il PDF che "non aveva testo"

`attachments.py` usava `io.BytesIO` senza importare `io`. Il `NameError` finiva nell'`except Exception` che serve a dire "questo PDF è scansionato", quindi **ogni** PDF veniva dichiarato privo di testo: l'agente rinunciava a leggerlo e chiedeva una trascrizione a mano. Un errore di programmazione travestito da proprietà del file.

Ora i tre casi sono distinti e dicono cosa fare: manca `pypdf` → il comando da lanciare; PDF rotto → che è rotto; PDF davvero senza testo → che è scansionato, con l'hint di `pypdfium2` per l'OCR. `pypdf>=5.0` è in `requirements.txt`.

### 2. `read_file`: testo è testo, binario è binario

Prima leggeva i byte e li decodificava come UTF-8 con `errors="replace"`: un `.docx` diventava una parete di caratteri di sostituzione, un `.xlsx` la stessa cosa, un'immagine idem. Un file cp1252 perdeva le accentate senza dirlo.

`orchestra/testo.py` è il modulo nuovo che decide, in un posto solo: firme dei formati (PNG, JPEG, ZIP/Office, PDF), UTF-8 con e senza BOM, UTF-16, cp1252, latin-1. `read_file` estrae il testo da PDF e da `.docx/.xlsx/.pptx` con il codice che c'era già, manda le immagini a `screenshot_view`, e quando la codifica non è UTF-8 lo dice nell'intestazione invece di lasciar credere che il file fosse così.

### 3. `edit_file` non riscrive più tutto in UTF-8 con LF

Leggeva con `read_text` e riscriveva con `write_text`: su un file cp1252 le accentate diventavano mojibake, e su un file a fine riga Windows tutto il file risultava modificato al primo `git diff`. Ora legge i byte, conserva codifica e BOM, e conserva il fine riga; se una ricerca multilinea copiata da `read_file` non trova nulla, riprova con `\r\n` prima di dichiarare che il testo non c'è. Un binario viene rifiutato dicendo cos'è ("è un'immagine PNG"), non "testo non trovato". La scrittura passa da `scrittura.scrivi_bytes`, che è atomica come quella del testo.

### 4. `screenshot_view`, i profili, e la radice sbagliata

`screenshot_view` era l'unico tool che apriva file senza passare da `_safe_path`, e non era in nessun profilo che non fosse `pieno`: chi usava `base` non poteva vedere uno screenshot che `read_file` gli mandava. Ora usa le guardie e sta in base, ricerca, skill e pieno. `cron` e `mcp` sono nel profilo `pieno`, `calculate` è tornato in `skill`.

Il difetto più grosso era però sotto: `orchestra/tools/__init__.py` aveva una sua `_root()` che calcolava `D:\orchestra\orchestra` — la cartella del pacchetto invece di quella del progetto — e **ombreggiava** quella vera per tutti i tool che importavano da lì. I percorsi relativi venivano risolti contro una cartella che non esiste. Ora si riesporta `_guard._root`, e il test che scriveva in una temp esterna passava proprio grazie a quel buco: l'ho spostato dentro la root.

### 5. Le dipendenze: una lista sola, e viene da `requirements.txt`

Il pannello **Opzioni → Dipendenze** non leggeva `requirements.txt`. Aveva la sua lista scritta a mano, in **due** rotte (`GET` e `POST`) con due copie della stessa risposta. Nessun altro leggeva quel file: non l'installer, non `orchestra update`. Quindi `Pillow` (0.5.80) e `pypdf` (0.5.81) erano dichiarate, necessarie ai tool, e invisibili: il tool diceva "installa Pillow" e il pannello non lo nominava.

`orchestra/dipendenze.py` è ora l'unica fonte: legge il file, verifica lo stato vero modulo per modulo (con la mappa esplicita `Pillow` → `PIL`, perché il nome del pacchetto e quello del modulo non coincidono sempre), e sa cosa non arriva da pip (`cloudflared` via winget) e cosa è opzionale (`faster-whisper`). Il pulsante "Installa" costruisce il comando da quella tabella: non c'è più una catena di `if` in cui la prossima dipendenza non entrerebbe mai.

Il comando **Diagnosi → dipendenze** stampava il *percorso* del file come se fosse un referto. Ora stampa la tabella con versione e scopo di ogni voce.

### 6. Prove

`tests/test_documenti.py` (nuovo, 48 controlli) copre i tre casi del PDF, la mancanza simulata di `pypdf`, l'estrazione Office, i binari, cp1252, i fine riga, la root e i profili. `tests/test_dipendenze.py` (nuovo, 38 controlli) copre il parsing dei requisiti (commenti, specifiche, extras, marcatori), lo stato reale, i comandi di installazione, e **entrambe** le rotte: la `GET`, che è quella che il pannello chiama, e la `POST`. Non regressione: 568 controlli su quattordici file di test, zero falliti.
