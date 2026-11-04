# Orchestra e il Regolamento (UE) 2024/1689 (AI Act) — valutazione

Data della valutazione: **4 novembre 2026**. Non è un parere legale: è la
fotografia di quello che il prodotto fa, confrontata con gli obblighi in
vigore a questa data, con i buchi indicati per nome.

Fonti primarie consultate: [timeline ufficiale del Service Desk della
Commissione](https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act)
(aggiornata con il *Digital Omnibus on AI*), [testo dell'art.
50](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50),
[linee guida della Commissione sugli obblighi di
trasparenza](https://digital-strategy.ec.europa.eu/en/policies/guidelines-ai-transparency-obligations)
(ultimo aggiornamento 6 agosto 2026).

## 1. Che cosa è Orchestra, ai sensi del regolamento

| Domanda | Risposta |
|---|---|
| È un "sistema di IA" (art. 3(1))? | Sì: un'app che, dato un input, deduce come generare codice, testo e azioni. |
| Siamo "provider"? | **Sì** (art. 3(3)): distribuiamo il sistema sotto il nostro nome. |
| Siamo provider di un modello GPAI? | **No**: usiamo modelli di terzi via API. Non addestriamo, non distribuiamo pesi. |
| Siamo "deployer" (art. 3(4))? | Solo *verso i modelli di terzi* che consumiamo. Verso i nostri utenti siamo provider. |
| Addestriamo o facciamo fine-tuning? | No. Quindi gli obblighi art. 53-55 non ci riguardano. |

## 2. Classificazione del rischio: minimo / limitato

- **Annex I (art. 6(1))**: no. Non siamo componente di sicurezza di un
  prodotto sotto legislazione di armonizzazione.
- **Annex III (art. 6(2))**: no. Le otto aree tassative non includono lo
  sviluppo software. Un assistente alla programmazione non è high-risk per
  la sua finalità dichiarata.
- **Attenzione a tre usi prevedibili** che sposterebbero la valutazione:
  1. metriche sul lavoro di sviluppatori usate per valutarli (Annex III,
     punto 4 — occupazione e gestione dei lavoratori);
  2. vendita a scuole per ammissioni, valutazioni o sorveglianza d'esame
     (punto 3);
  3. codice generato che finisce in un dispositivo medico o in un
     macchinario (in quel caso il provider high-risk è chi produce il
     dispositivo, non noi, ma il nostro output è nella catena).
- Conseguenza operativa: **limiti d'uso espliciti** ("non usare per
  decisioni su persone, selezione del personale, ammissioni scolastiche,
  diagnosi o terapia") nei termini e nel README. Costano una riga e
  chiudono la discussione.
- Gli obblighi high-risk Annex III si applicano dal **2 dicembre 2027**
  (rinviati dal *Digital Omnibus*): oggi non sono dovuti, ma la
  valutazione di classificazione va comunque scritta e datata.

## 3. Obblighi in vigore oggi (4 novembre 2026)

### 3.1 Art. 50(1) — dire che si sta parlando con un'IA — **IN VIGORE dal 2 ago 2026**

I sistemi destinati a interagire direttamente con persone devono essere
progettati perché la persona **sia informata** che sta interagendo con un
sistema di IA, salvo che sia ovvio.

**Stato in Orchestra: manca.** Non c'è nessuna riga, né nell'interfaccia
né nel README, che lo dica. L'eccezione "è ovvio" è probabilmente
applicabile (chi apre un agente con un menu dei modelli sa cosa sta
facendo), ma è un'eccezione da **motivare**, non da dare per scontata — e
costa meno scriverla che difenderla.

### 3.2 Art. 50(2) — marcare i contenuti sintetici, in modo leggibile da macchina — **IN VIGORE dal 2 ago 2026**

Gli output generati (audio, immagine, video, testo) vanno marcati e
devono essere rilevabili come generati. Esenzione parziale per i sistemi
che svolgono "una funzione assistiva di editing standard" o che non
alterano sostanzialmente l'input del deployer.

Due casi distinti in Orchestra:

- **Codice e testo**: l'assistente riscrive e produce a partire da file
  dell'utente, quindi l'esenzione "standard editing / non alterazione
  sostanziale" è la posizione sostenibile. **Da documentare**, perché le
  linee guida della Commissione citano proprio lo "standard editing" tra
  gli esempi di esclusione. Non ho trovato conferma, nel documento
  ufficiale, di un'esclusione nominata del "codice sorgente": se serve
  certezza, va letto il PDF delle linee guida prima di affidarcisi.
- **Immagini generate** (`image_gen`): qui **non c'è esenzione**. Il tool
  scrive un'immagine generata e la mostra in chat senza alcuna marcatura
  né dichiarazione. È il gap più concreto del prodotto su questo
  articolo.

### 3.3 Art. 4 — AI literacy — **IN VIGORE dal 2 feb 2025**

Obbligo di adottare misure per *sostenere* lo sviluppo della literacy su
IA di chi usa il sistema per nostro conto (dopo il *Digital Omnibus* non
si deve "garantire" un livello). Per un progetto piccolo: una pagina di
onboarding che spieghi cosa fa l'agente, cosa vede, cosa può sbagliare, e
come annullare. **Oggi manca**: il README descrive le funzioni, non i
limiti.

### 3.4 Art. 5 — pratiche vietate — **IN VIGORE dal 2 feb 2025**

Nessun tool fa social scoring, manipolazione subliminale, sfruttamento di
vulnerabilità. `computer` (controllo del desktop) e `cron` (job
programmati) sono potenti ma non vietati: vanno descritti nei limiti
d'uso, non rimossi.

### 3.5 GPAI (art. 53-55) — non ci riguardano direttamente

Consumiamo modelli come deployer. Obbligo pratico: **due diligence sulla
catena** — sapere quale modello c'è dietro ogni provider (OpenRouter,
Groq, NVIDIA…), dove stanno i dati, e che il provider dichiari le proprie
obbligazioni GPAI. Orchestra già mostra e salva provider e modello per
ogni turno, che è la parte tecnica di questa due diligence.

## 3.6 La catena del valore: chi risponde di cosa

È la domanda che torna sempre — «ma il modello non è nostro?». La
risposta è che l'AI Act regola il **sistema** che metti a disposizione
delle persone, non chi ha addestrato il modello: il provider (art. 3(3))
è chi sviluppa un sistema di IA, *o lo fa sviluppare*, e lo immette sotto
il proprio nome, a pagamento o gratis.

| Soggetto | Risponde di |
|---|---|
| Provider del modello (OpenRouter, Groq, OpenAI, Google, Anthropic…) | obblighi GPAI (art. 53-55): documentazione del modello, riepilogo dei dati di addestramento, policy copyright, rischio sistemico |
| Noi, che sviluppiamo Orchestra | art. 50 (trasparenza e marcatura), art. 4 (literacy), divieti art. 5, classificazione e limiti d'uso, privacy di ciò che inviamo fuori |
| Azienda o persona che usa Orchestra per decidere su persone | diventa *deployer* ad alto rischio: valutazione d'impatto, sorveglianza umana, log |

Quello che **non** ci trasferiamo è la documentazione del modello:
resta di chi lo addestra. Verso di loro siamo *deployer*, e il nostro
dovere è la due diligence — sapere quale modello c'è dietro, dove
vanno i dati, e che il fornitore dichiari le proprie obbligazioni.
Quello che nessun fornitore può fare al posto nostro sono le tre cose
sopra: la disclosure, la marcatura dei nostri output, la literacy dei
nostri utenti.

L'ultima riga è il motivo per cui i limiti d'uso non sono burocrazia:
se un'azienda usa l'agente per valutare o selezionare persone, l'alto
rischio è suo, ma noi dobbiamo aver detto chiaramente che non è l'uso
previsto.

## 3.7 La nostra posizione: gratuito, da un privato, su GitHub

Orchestra è distribuito gratuitamente su GitHub, sviluppato da una
persona e non da un'azienda, e non è venduto. Che cosa cambia:

- **Art. 2(12)**: l'esenzione per i sistemi rilasciati con licenza
  libera e open source **non copre** i sistemi che ricadono sotto gli
  articoli 5 o 50. Quindi la licenza libera non ci esime dalla
  trasparenza: la applichiamo lo stesso, e questa è la scelta
  prudente.
- **Art. 2(10)**: chi usa un sistema di IA per attività personale e non
  professionale non ha obblighi da deployer. Se Orchestra resta sulla
  macchina di chi la scarica per uso proprio, gli obblighi verso
  l'utente finale non nascono.
- **Nessuna attività commerciale**: non c'è vendita, non c'è prezzo,
  non c'è un rapporto contrattuale. Restano comunque — e questo è il
  punto — la correttezza verso chi usa il software e la possibilità che
  un giorno la distribuzione diventi commerciale: adeguarsi adesso
  costa una pagina, adeguarsi dopo costa un risarcimento.
- **Sviluppato con l'IA**: non cambia la classificazione (l'AI Act
  guarda il sistema distribuito, non gli strumenti di chi lo scrive),
  ma è una ragione in più per essere espliciti su cosa il software è.

## 4. Altri obblighi, che non sono AI Act ma arrivano dalla stessa parte

- **GDPR**: i prompt, il codice e gli screenshot vanno a provider terzi.
  Serve un'informativa su cosa esce dalla macchina, verso chi, con quale
  base giuridica e per quanto resta. **Oggi manca del tutto.**
- **Trasparenza verso l'utente sui costi**: il riepilogo di fine turno
  mostra token e costo stimato, quindi c'è già; va solo detto che la
  stima può discostarsi dalla fattura.
- **Sicurezza del prodotto**: `SECURITY.md` con un canale di
  segnalazione. **Manca.**

## 5. Tabella di conformità

| Requisito | Stato | Dove |
|---|---|---|
| Classificazione del rischio scritta e datata (art. 6) | **fatto**: questo documento | `AI-ACT.md` |
| Disclosure "stai interagendo con un'IA" (art. 50(1)) | **fatto**: badge permanente nella barra e riga al primo avvio | `web/index.html`, `web/app.css`, `README.md` |
| Marcatura delle immagini generate (art. 50(2)) | **fatto**: chunk `tEXt` nei PNG + sidecar `<nome>.ai.json` per ogni formato | `orchestra/marcatura.py`, `orchestra/image_gen.py` |
| Posizione documentata sul codice generato (art. 50(2)) | **parziale**: sezione 3.2; l'esclusione nominata del codice non è confermata sul documento ufficiale | `AI-ACT.md` |
| AI literacy: pagina su limiti e uso corretto (art. 4) | **fatto**: paragrafo «Trasparenza» e riga nell'onboarding | `README.md` |
| Limiti d'uso / casi esclusi (Art. 25, Annex III) | **fatto**: «A cosa non serve» | `README.md` |
| Informativa privacy sui dati inviati ai provider (GDPR) | **fatto**: «Cosa esce dalla macchina» | `README.md` |
| Log di provider/modello/costo per turno (buona pratica, art. 12 non dovuto) | **fatto** | `storico`, `riepilogo` |
| Due diligence sui modelli GPAI di terzi | **parziale** | provider e modello sono tracciati; manca la scheda per provider |
| Procedura e canale per gli incidenti | **manca** | `SECURITY.md` |
| Adesione al Codice di condotta trasparenza (volontaria) | **non fatta** | valutare: riduce l'incertezza dell'enforcement |

## 6. Sanzioni, per capire il rischio reale

Art. 50 rientra nella fascia da **15 milioni di euro o 3% del fatturato
mondiale annuo**, con il criterio più favorevole per microimprese e PMI
(art. 99(6): si applica il minore tra importo fisso e percentuale). In
Italia la vigilanza di mercato è dell'**ACN**, con AgID autorità di
notifica (d.lgs. 179/2026). Le verifiche partono da reclami e
segnalazioni, non da audit sistematici: il rischio concreto non è la
multa, è il reclamo di un utente a cui nessuno ha detto che stava
parlando con un'IA o che le sue immagini erano generate.

## 7. Cosa fare, in ordine di costo/beneficio

1. ~~Una riga di disclosure in apertura e nel README (art. 50(1))~~ — **fatto**.
2. ~~Marcatura delle immagini generate: metadato nel file e nota accanto all'anteprima (art. 50(2))~~ — **fatto** (`orchestra/marcatura.py`).
3. ~~Informativa privacy: quali dati escono, verso quali provider, per quanto (GDPR)~~ — **fatto**, nel README.
4. ~~Limiti d'uso nei termini e nel README (classificazione)~~ — **fatto**.
5. `SECURITY.md` con il canale di segnalazione — un'ora.
6. ~~Pagina di AI literacy: cosa fa l'agente, cosa può sbagliare, come si annulla (art. 4)~~ — **fatto**.
7. Scheda per ogni provider GPAI usato, con modello, dove girano i dati, riferimenti alle loro policy — una giornata, e va aggiornata quando cambia il catalogo.
8. Leggere il PDF delle linee guida del 20 luglio 2026 e chiudere la posizione sul codice generato (sezione 3.2).

## 8. Come si mantiene

Questo documento va riletto quando cambia qualcosa di sostanziale: un
nuovo tipo di output (immagini, audio, video), un nuovo provider, un uso
che si avvicina alle aree Annex III, o una nuova scadenza. La data in
testa è quella dell'ultima verifica: se è vecchia, non è una valutazione,
è un ricordo.
