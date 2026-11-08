## v0.5.80 — Il fotoritocco che non rigenera la foto

Una richiesta semplice — «metti il prezzo e il logo su questa foto» — finiva sempre nello stesso posto: `image_gen`, che è generativo, quindi ridisegna tutto. Il logo tornava con le lettere sbagliate, il prezzo con altre cifre, e l'agente concludeva che un fotoritocco «chirurgico» non era possibile e consigliava Canva. La conclusione era sbagliata: mancava lo strumento giusto, non la capacità.

### 1. `image_edit`: montare, non generare

Il tool nuovo applica operazioni **deterministiche** a un'immagine esistente, con Pillow:

- `incolla` — un PNG con la sua trasparenza, scalato, con opacità;
- `testo` — dimensione, grassetto, colore, riquadro arrotondato, contorno, a capo, allineamento;
- `ritaglia`, `ridimensiona` — pixel o percentuali, proporzioni conservate se ne manca una.

È il gesto giusto perché i pixel che non tocca restano quelli dell'originale: un logo è il file del logo, non un'imitazione. Non usa chiavi, non usa credito, e su una foto vera il risultato è riproducibile: le stesse coordinate danno lo stesso file.

### 2. Il JPEG resta un JPEG

Chi manda una foto manda quasi sempre un JPEG, e un'immagine che torna PNG da 20 MB è un problema in più. L'uscita ha lo stesso formato dell'ingresso (JPEG qualità 95); la trasparenza si chiede con `formato="png"`, perché un JPEG non può conservarla. L'orientamento EXIF viene applicato prima di ogni operazione: senza, le coordinate valgono su un'immagine ruotata e ogni posizione è sbagliata.

### 3. La maschera: inpainting solo dove serve

`image_gen` accetta ora `zone` (rettangoli o ellissi, in pixel o percentuali, con `morbido` per sfumare il bordo) e costruisce lui la maschera nella convenzione di OpenAI: trasparente dove il modello può ridisegnare, opaco ovunque altro. In alternativa `maschera` prende un PNG già pronto, e viene controllato — PNG, canale alfa, stessa misura — prima di partire.

Serve perché nessuno ha una maschera in mano: senza il pezzo che la disegna dalle coordinate, il parametro sarebbe rimasto inutilizzabile. Il multipart di `/images/edits` manda ora due file, `image` e `mask`.

La maschera la accetta **solo OpenAI**. Con Google e OpenRouter il tool lo dice prima di partire, specificando che nessun credito è stato speso: una richiesta che parte e torna con la foto ridisegnata è peggio di un rifiuto.

### 4. Le guardie restano quelle di sempre

Le immagini si aprono passando dal confine del progetto, quindi fuori dalla root scatta la richiesta di permesso come per ogni altro tool; limite 12 MB e 60 MP controllati prima di decodificare; il file di partenza non viene mai toccato e non si sovrascrive mai (nome libero in `immagini/`); i font di sistema vengono da una lista bianca, mentre un `font` indicato dal modello passa dallo stesso gate dei percorsi; nessuna eccezione esce dal tool. Pillow entra in `requirements.txt` ma con import pigro: se manca, si ferma solo `image_edit` con la riga da installare, e il resto di Orchestra continua.

### 5. L'agente non manda più su Canva

`SYSTEM_PROMPT` ha un blocco «Immagini»: per testo, prezzo, logo e filigrana si usa `image_edit`; `image_gen` ridisegna e inventa le lettere, quindi non si promette che terrà un logo esistente; un'immagine allegata è già `ultimo` e non va chiesta di nuovo; e non si manda l'utente su Canva o Photoshop prima di aver provato il montaggio. Se il montaggio non basta davvero — maschere a parte, ombre, prospettiva — lo si dice in una riga, invece di far sembrare impossibile tutto il resto.

### Test

`test_image_edit` **45/0** (JPEG→JPEG, pixel fuori dalle zone montate invariati, logo con alfa, riquadro del testo, ritaglio, proporzioni, scala percentuale, errori leggibili, registro e profili), `test_inpainting` **42/0** (convenzione dei colori della maschera, percentuali, ellisse, bordo sfumato, misure sbagliate rifiutate, blocco dei provider senza maschera, corpo multipart con `image` e `mask`), `test_policy` 47/0, `test_piano` 23/0, `test_offline` 64/0.

`test_image_gen` resta **118/6**: i sei rossi sono confronti byte-per-byte contro la marcatura AI-Act dei PNG (`img.dati == PNG_1PX`), sono precedenti a questa versione e non riguardano il percorso di modifica. Non sono stati toccati.

L'inpainting non è stato provato con una chiave reale: il formato della richiesta è verificato sul corpo che parte, la qualità del riempimento no.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
