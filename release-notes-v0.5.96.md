# v0.5.96 — Il server si aggiorna dal telefono

## Il caso

Aggiornare Orchestra voleva dire chiudere tutto, rilanciare
l'eseguibile e scegliere il tasto 2 per far ripartire il server. Con il
telefono in mano, e il computer in un'altra stanza, non c'era nessun
modo di farlo da Telegram.

## `/aggiorna` e `/riavvia`

- **`/aggiorna`** (o **`/update`**) controlla l'ultima release, la
  scarica e la applica con lo stesso codice del comando `update`: verifica
  sha256, conserva `.env`, token e stato, e toglie i file obsoleti. Se non
  c'è niente di nuovo risponde "già aggiornato" e non riavvia; se c'è,
  dice versione vecchia → nuova e riavvia da solo.
- **`/riavvia`** (o **`/restart`**) riavvia senza toccare la rete.
- Entrambi **rifiutano se c'è un turno in corso**: sovrascrivere il codice
  mentre l'agente lo esegue lascerebbe un turno spezzato. Si usa `/stop`
  prima. Una sola operazione di manutenzione per volta, così due comandi
  in rapida successione non si accavallano.
- Il messaggio con l'esito parte **prima** del riavvio: 4 secondi di
  attesa, non zero. Da Telegram si legge com'è andata, poi la chat torna.

## Il riavvio non passa dal launcher

`os.execv` con l'interprete e la riga di avvio originali — `python -m
orchestra.cli web ...` — quindi il processo resta lo stesso pid e non se
ne crea un secondo. Prima di sostituirsi ferma ponti Telegram, scheduler
di cron e obiettivi, processi dei tool, connessioni MCP e tunnel
cloudflared: niente lavoro orfano, niente porta occupata al ritorno.
Se l'avvio era da un eseguibile impacchettato, rilancia l'eseguibile.

## Il menu dei comandi Telegram torna di Orchestra

Il menu che appare premendo `/` è una proprietà del **bot**, non
dell'applicazione: un bot usato prima con un'altra app si portava dietro
i suoi comandi, e chi cambiava app trovava un elenco che sembrava rotto.
Ora Orchestra scrive il proprio elenco all'avvio del ponte e ogni volta
che una chat si collega, con i comandi veri (`/stato`, `/steer`, `/stop`,
`/nuova`, `/modello`, `/reasoning`, `/aggiorna`, `/riavvia`,
`/scollega`, `/aiuto`, `/start`). Il client può tenerlo in cache per un
minuto: chiudendo e riaprendo la chat si aggiorna.

## Verifiche

`tests/run_all.py` con la suite completa. Nuove prove: la riga di
riavvio nei tre avvii (modulo, eseguibile, file singolo), i comandi
Telegram che rifiutano un turno in corso e non si accavallano, il
riavvio che parte dopo la risposta, e il menu scritto con nomi validi e
riscritto al collegamento.
