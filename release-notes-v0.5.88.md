# v0.5.88 — Il ponte Telegram non perde più il filo

## Cosa succedeva

Tre difetti diversi, con lo stesso risultato: dal telefono il bot ragionava,
poi la risposta non arrivava — e aprendo la finestra la conversazione era lì,
finita.

1. **L'agente principale non era l'agente principale.** Il ponte usava «la
   sessione che la finestra sta guardando». Dopo un riavvio con un bot attivo
   (`ORCHESTRA_BOT` è salvato), un messaggio Telegram all'agente principale
   finiva dentro la conversazione di quel bot. Peggio: il ponte riscriveva il
   `bot_id` di quella sessione a 0, quindi le domande e i permessi del bot
   partivano verso la chat Telegram dell'agente principale — e chi doveva
   rispondere non le vedeva.
2. **Turno più lungo dell'attesa = risposta persa.** Alla scadenza il ponte
   smetteva di guardare e rispondeva «la risposta la trovi nella finestra».
   Dal telefono la finestra di solito è chiusa: il turno finiva, la risposta
   restava lì, e in chat non arrivava più niente.
3. **Un rifiuto temporaneo di Telegram buttava via la risposta.** Un 429 o un
   5xx diventavano una riga nel log e niente in chat.

## Cosa c'è ora

- L'agente principale usa **la sua** sessione, sempre: la finestra può
  guardare un bot senza che Telegram scriva lì dentro, e il `bot_id` delle
  sessioni dei bot non viene più sovrascritto.
- Se il turno è ancora in corso alla scadenza del ponte, la chat dice che sta
  lavorando — e la risposta viene **recapitata da sola** quando il turno
  finisce, insieme ai file prodotti. Il recapito guarda solo i messaggi nati
  dopo l'invio: una risposta vecchia non viene spacciata per quella nuova.
- Gli invii ritentano con attesa crescente su rete, 429 e 5xx (tre tentativi).
  Un 400 no: quello non passa ritentando.
- Se alla scadenza la sessione è già libera, l'`idle` è andato perso ma la
  risposta c'è: si manda quella, invece della scusa.

## Verifiche

`test_telegram_sessione.py` 141 check (5 nuovi: sessione giusta per l'agente
principale, recapito dopo la scadenza, nessun riciclo di risposte vecchie,
ritentativo su 429/500, nessun ritentativo su 400), `test_telegram.py` 145,
`test_bots.py` 101: tutti verdi.

Riavvia Orchestra perché il ponte riparta con il codice nuovo.
