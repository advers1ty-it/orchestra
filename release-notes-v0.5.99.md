# v0.5.99 — Telegram per più persone, e il tetto di output che conta

Questa release raccoglie quello che è cambiato dopo la 0.5.98: il ponte
Telegram diventa utilizzabile da più persone e da un telefono senza
pannello, il tetto di output smette di essere un'impostazione che non
arrivava mai al modello, e la catena di ripiego si sceglie invece di
indovinarla.

## Telegram: più persone sullo stesso bot

Il collegamento era **una colonna sola** per bot: il secondo `/start`
sovrascriveva il primo, e chi c'era prima smetteva di ricevere risposte
senza che nessuno glielo dicesse.

Ora le chat collegate sono un elenco (fino a cinque per bot), ognuna con
il suo nome: chi si collega con un codice entra **senza staccare gli
altri**, e il benvenuto lo dice. Nel pannello Bot → Telegram l'elenco è
visibile con una riga per persona e il pulsante **Revoca**, che stacca
quella e lascia le altre (la rotta `/api/telegram/scollega` accetta un
`chat_id`); dal telefono `/scollega` stacca solo chi lo scrive, perché lì
non c'è modo di sapere chi sono gli altri. Il collegamento che c'era
prima viene migrato da solo al primo avvio: diventa il primo elemento
dell'elenco, non si perde.

Con più chat collegate, le risposte, i file prodotti e le domande
dell'agente (i pulsanti dei permessi) vanno **alla chat che ha avviato
il turno**, non alla principale: prima un permesso chiesto da una persona
finiva sotto gli occhi di un'altra, che non aveva chiesto niente.

La sessione invece resta una sola per bot, e i comandi che la toccano lo
dicono: `/stop` ferma il turno di chiunque stia lavorando, `/nuova`
azzera la conversazione anche agli altri. Con una sola chat collegata i
messaggi sono quelli di sempre.

## Telegram: comandi nuovi, e il menu che non resta quello di un'altra app

- `/ragionamento` senza argomento apre un **modulo a bottoni**: il
  livello di reasoning (`none` … `max`, più `auto`) e mostra/nascondi il
  ragionamento in chat, con il segno su quello che vale adesso. Prima dal
  telefono il livello non si poteva cambiare affatto, e l'interruttore
  era cieco. Le scorciatoie scritte restano: `/ragionamento high`,
  `/ragionamento on|off`.
- `/obiettivo <testo>` avvia un obiettivo in autonomia (come il pannello
  Obiettivo) e senza testo elenca quelli aperti.
- `/consiglio <decisione>` chiede al Chair chi mettere al tavolo, una
  riga per seat col perché.

Il livello è una sola impostazione di Orchestra (la stessa del pannello,
salvata in `ORCHESTRA_REASONING`), la vista in chat è per bot: il modulo
e ogni conferma lo dicono, perché scritte uguali sembravano valere
entrambe solo per quella chat.

Il **menu degli slash** veniva scritto senza `scope`, quindi solo nel
default: Telegram tiene i comandi per scope, e uno scope più specifico
(quel chat, tutti i privati) vince sul default. Un bot usato prima con
un'altra app continuava a mostrare i comandi di quella, con un `ok: true`
e nessun errore da nessuna parte. Ora si cancellano gli scope che
coprono il default — compreso quello di ogni chat collegata — e poi si
scrive il nostro. L'allineamento parte **all'avvio** del ponte, con
tentativi, e se fallisce viene ritentato: prima bastava una chiamata
caduta per lasciare il menu vecchio fino al riavvio successivo.

## Il tetto di output arriva davvero al modello

`ORCHESTRA_MAX_TOKENS` non aveva effetto: il loop leggeva `max_tokens` e
`temperature` dalla entry della catena (4096 e 0.7) invece che dalla
configurazione. Con `reasoning: max` il budget si esauriva dentro il
ragionamento, il provider rispondeva `finish_reason: "length"` e la
risposta arrivava troncata — e alzare la variabile non cambiava niente.

Ora entrambi i rami (streaming e blocco) prendono temperatura, tetto e
livello di reasoning da `self.config`; i tre campi corrispondenti sono
stati tolti da `ChainEntry`, perché un secondo posto per lo stesso numero
vince in silenzio. Goal e figli della delega, che costruivano il proprio
`LoopConfig` a mano e restavano a 4096, passano dagli stessi parametri;
la sessione web legge `ORCHESTRA_MAX_TOKENS` come la CLI.

## Una sola lettura delle impostazioni

Temperatura e tetto si leggevano in tre punti con due precedenze diverse,
e le variabili esportate (`ORCHESTRA_REASONING=low python -m orchestra
cli web`) venivano viste da alcuni percorsi e ignorate da altri nello
stesso costruttore. Ora c'è un lettore solo (`impostazioni()`,
`valore_da_env()`, `parametri_da_env()`): l'ambiente vince sul `.env`,
che resta la fonte salvata, e vale per CLI, sessione web, goal e figli
della delega.

## Il fallback si sceglie, non si indovina

La catena di ripiego veniva da una tabella scritta a mano che nominava
servizi che chi usa Orchestra può non avere, e non conosceva `nous`: con
quel provider la catena restava di un elemento, quindi nessun ripiego
mai. Con OpenRouter i tentativi si spendevano su servizi senza chiave, e
il turno finiva in "Nessun provider disponibile" invece che con l'errore
vero.

Ora il ripiego è **manuale**: in Opzioni → Modello c'è un interruttore e
da uno a tre modelli, anche di servizi diversi (solo quelli con una
chiave). Spento vuol dire solo il primario. Anche benchmark e council non
ripiegano: una risposta di un altro modello attribuita a quello misurato
è un numero sbagliato, non un numero in più.

## Lo scroll della chat segue l'intento

A fine turno la chat saltava a inizio conversazione: lo snapshot
ricostruisce il DOM, `innerHTML = ""` fa tornare `scrollTop` a 0, e il
controllo "sei in fondo?" rispondeva sempre no. Lo stesso vizio
riguardava la risposta finale e il risultato di un tool lungo. Ora c'è
`vaiInFondo()`, che salta senza soglia, e l'intento si riarma quando
torni in fondo: nessuno viene trascinato mentre legge, e una risposta
alta segue chi è tornato giù.

## Note sull'aggiornamento

Gli asset di questa release sono due:

- `orchestra-0.5.99.zip` — il codice, con una sola cartella radice
  (`orchestra-0.5.99/`), nel formato che l'updater accetta.
- `Installa-Orchestra.bat` — l'installer per Windows. Legge
  `releases/latest`, quindi si rilancia su un'installazione esistente per
  aggiornarla: sovrascrive il codice e lascia stare `.env`, i database, il
  token di Telegram e le skill.

Poi, sul codice:

- Il database dei collegamenti Telegram si migra da solo: la chat che era
  collegata diventa il primo elemento dell'elenco.
- `DEFAULT_CHAINS` e la funzione che la leggeva sono state rimosse: un
  agente senza catena esplicita usa solo il primario.
- `ChainEntry` non ha più `temperature`, `max_tokens` e `reasoning_level`:
  chi costruiva una entry a mano con quei campi non li trova più.
