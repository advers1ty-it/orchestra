# v0.5.104 — Il progetto si vede, dalla CLI alla cronologia

## La scheda del progetto entra nel prompt

Il blocco progetto diceva solo nome e ultimi file toccati. Ora porta anche
la cartella, la nota scritta a mano, gli alias, il giorno e l'ora locali, il
ramo git col numero di modifiche non committate e i tre piani più recenti
in `plans/`. La nota e gli alias si troncano corti, tutto sta nel blocco
volatile: il prefisso stabile e la cache dei provider non si toccano. Un
progetto riaperto dopo giorni non riparte più dalla scoperta.

## Il tool `progetti`

Tre azioni: `elenca` (percorso, nota, ultimo uso, file toccati, progetto
attivo segnato), `stato` (la scheda dell'attivo con alias e file recenti) e
`nota` (scrive solo la nota dell'attivo). Non cambia il progetto: quello
sposta la cartella in cui si scrive, e resta alla UI o al riconoscimento
deterministico dell'intento. Disponibile in tutti i profili.

## Le conversazioni appartengono a un progetto

La colonna `progetto` sulle sessioni arriva con migrazione; le chat già
salvate restano senza progetto e continuano a essere visibili. La sessione
nasce col progetto attivo, lo aggiorna se cambi progetto a chat aperta e lo
riporta quando la riapri (se la riga non ne aveva uno, adotta quello
attivo). Elenco e ricerca filtrano per progetto, sia nelle rotte sia nel
tool `storico_cerca` (`tutti` per cercare ovunque). La cronologia della UI
mostra `progetto: X`, oppure `senza progetto`, prima di aprire.

## Il progetto attivo funziona anche nella CLI

La CLI non impostava il nome nel thread: `progetti` diceva «nessun
progetto attivo» mentre i file finivano in un progetto registrato. Ora la
cartella corrente viene risolta nel progetto registrato che la contiene
(vince il più profondo), `ORCHESTRA_PROGETTO` può forzarlo, e la root dei
tool diventa quella del progetto. Il tool funziona anche quando il thread
ha solo il percorso e non il nome.

## Test

Nuove suite `progetto-prompt`, `tool-progetti`, `storico-progetto` e
`progetti-cli`; il test frontend copre la cronologia laterale e il pannello
con il progetto. Verificate anche le suite collegate: progetti, sessioni,
rotte, bots, memoria, UI e integrità HTML.
