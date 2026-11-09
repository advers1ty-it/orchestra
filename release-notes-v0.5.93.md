# v0.5.93 — Il percorso si registra solo se è vero

## Il caso

Il segnaposto `installazione.json` si scrive all'avvio con il percorso della
cartella del codice. Ma con `ORCHESTRA_HOME` impostata la cartella dati è
scelta a mano: chiunque può avviare una copia di Orchestra e puntarla sui dati
di un'altra installazione. In quel caso il percorso scritto sarebbe quello
della copia **sbagliata**, e l'elenco lo mostrerebbe come vero — su quella
riga si decide poi quale `.env` usare e quale installazione salvare.

Ora, con `ORCHESTRA_HOME` impostata, il segnaposto non si scrive: meglio una
riga «percorso non registrato» che una mappatura inventata. Il percorso si
registra quando Orchestra parte dalla propria cartella.

Effetto collaterale utile: le cartelle dei test non ricevono più il segnaposto,
quindi non finisce più nel repository né nello zip.

## Verifiche

`test_backup.py` 49 check (uno nuovo: con `ORCHESTRA_HOME` non viene scritto
nessun segnaposto), più le altre suite invariate e verdi.
