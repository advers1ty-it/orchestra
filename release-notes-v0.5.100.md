# v0.5.100 — I consigli di fine turno, nella finestra e su Telegram

Questa release raccoglie quello che è cambiato dopo la 0.5.99. La cosa
nuova è che un turno finito non lascia più solo: propone le mosse che
servono adesso, con il prompt già scritto. Dietro, il prompt dell'agente
legge anche i messaggi prima, le regole salvate in memoria arrivano
davvero al modello, e il giro dei test finisce sempre.

## I consigli di fine turno

A turno finito si fa quasi sempre una di quattro cose: controllare di non
avere rotto qualcosa, rileggere le proprie modifiche, committare, oppure
decidere cosa fare dopo. Sono frasi che si riscrivono ogni volta, e quella
che servirebbe davvero — «quali test coprono i file che ho appena
toccato?» — viene in mente quando non serve più.

Nella finestra, sotto la risposta compare una riga di **pulsanti**:
*Controlla cosa può essersi rotto*, *Revisione di quello che ho toccato*,
*Commit di quello che c'è (N file)*, *Cosa resta aperto*. **Nessun modello
li inventa**: si ricavano dal riepilogo del turno — i file toccati con le
righe aggiunte e tolte — dai test che portano il loro nome
(`orchestra/skills.py` → `tests/test_skills.py`) e da `git status` in sola
lettura. Non compaiono tutti sempre: senza file toccati non c'è verifica,
con il git pulito non c'è commit.

Sono facoltativi e non aprono un secondo turno: un tocco **compila il
campo** con il prompt intero, che resta correggibile prima di inviare. Il
prompt nomina i file veri e i comandi giusti, e chiede di dire cosa si è
trovato *senza correggere* — un pulsante che promette «non hai rotto
niente» e poi incolla una frase generica sarebbe peggio di nessun
pulsante.

## Su Telegram i consigli stanno sotto la risposta

Prima ogni turno produceva due messaggi: la risposta e poi «E adesso?
(facoltativo)», che era solo un contenitore per dei bottoni. Ora la
tastiera è **attaccata all'ultimo pezzo della risposta** — un messaggio in
meno per turno, e i pulsanti dove l'occhio è già arrivato.

Toglierli dopo il tocco usa `editMessageReplyMarkup`, che cambia **solo**
la tastiera: la risposta non viene riscritta, quindi non può essere
degradata o persa per due bottoni. I prompt stanno in memoria per
**(chat, messaggio)**: un pulsante rimasto su una risposta di due turni fa
fa partire il suo prompt, non quello dell'ultimo turno. Il tetto dei
messaggi ricordati è **per chat**, così i turni di una persona non fanno
scadere i pulsanti di un'altra, e **scollegare una chat butta via i
suoi** — dal comando `/scollega` e dal pannello, anche per «stacca
tutto». Un turno che finisce dopo lo scollegamento non ne lascia: la chat
si ricontrolla prima di attaccare i pulsanti.

## Il prompt dell'agente

- **Le skill arrivano anche dai messaggi prima.** «E adesso?» dopo «mi
  servono le tabelle del pdf» non contiene nessuna parola utile: si
  guardano anche i sei messaggi precedenti (tagliati a 500 caratteri), con
  peso minore, così una parola vecchia non scavalca quella di adesso. E
  ogni parola conta una volta per sorgente: ripetere «pdf» sei volte non la
  fa più pesare sei volte.
- **Le regole salvate in memoria arrivano al prompt.** Il blocco
  `## Importanti` era cucito nel system prompt alla creazione della
  sessione: una regola dettata a chat aperta non entrava più. Ora si
  rilegge a ogni turno nel blocco volatile (il prefisso stabile resta
  uguale, e la cache dei provider continua a colpire), e una regola
  scritta in linguaggio naturale — «da ora in poi», «usa sempre» — finisce
  lì invece che in un archivio che nessuno legge.
- **La compattazione scatta a 60k**, non al 75% di una finestra da 1M.

## Fix

- **Telegram**: se il turno cade, il bot spiega l'errore invece di
  ripetere la risposta di prima.
- **Budget**: il pannello mostra `0` («illimitato»), non un campo vuoto.
- **Ragionamento**: il blocco nasce nascosto, e un turno non si chiude
  senza testo.
- **Ricerca web**: prova un motore alla volta invece di farsi bloccare da
  tutti insieme.
- **Il giro dei test finisce sempre**: ogni suite ha un tetto di tempo
  (300s, alzabile con `ORCHESTRA_SUITE_TIMEOUT`) e allo scadere viene
  uccisa con i suoi figli. *Scaduto* è uno stato suo, distinto da fallito e
  da crash, e il riepilogo nomina le suite scadute una per una: non sono
  verdi, e non si dice «tutto verde» quando qualcosa non è stato
  verificato.

## Note sull'aggiornamento

Gli asset di questa release sono due:

- `orchestra-0.5.100.zip` — il codice, con una sola cartella radice
  (`orchestra-0.5.100/`), nel formato che l'updater accetta.
- `Installa-Orchestra.bat` — l'installer per Windows. Legge
  `releases/latest`, quindi si rilancia su un'installazione esistente per
  aggiornarla: sovrascrive il codice e lascia stare `.env`, i database, il
  token di Telegram e le skill.

Poi:

- La cache del service worker porta il digest degli asset statici, quindi
  un `app.css` nuovo non resta dietro. Se la finestra sembra vecchia dopo
  l'aggiornamento, un ricarica risolve: è il service worker che si attiva.
- Niente da migrare: i consigli sono in memoria e nascono con il turno.
