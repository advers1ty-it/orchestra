# v0.5.85 — Allegati con un nome, e lo scontorno fatto in casa

## Il problema di ieri

Tre foto in un messaggio (il poster da tenere, il logo vero, la foto del
prodotto) arrivavano all'agente come tre allegati, ma i tool ne sapevano
nominare uno solo: `ultimo`. Il resto era irraggiungibile — e la risposta
dell'agente era "scontorna tu il logo e mandamelo".

## Cosa cambia

- **`allegato:N`**: `image_gen` e `image_edit` accettano `allegato:1`,
  `allegato:2`, … per l'n-esima immagine dell'ultimo messaggio (anche
  `allegato 2` e `allegato-2`). `ultimo` resta l'ultima.
- **Errore utile**: un indice che non esiste dice quante immagini ci sono e
  come si chiamano, invece di un silenzioso "non trovata".
- **`incolla` con `scontorna: true`**: toglie un fondo uniforme (bianco, di
  norma) e tiene il soggetto, con `tolleranza` (0-100, default 18),
  `sfumatura` (pixel di bordo morbido) e `colore_sfondo` (`#rrggbb`).
- **`incolla` con `ombra: N`**: ombra morbida sotto il ritaglio incollato,
  così un logo non sembra un adesivo appoggiato sopra.
- Il referto del montaggio dice quanta parte dell'immagine è diventata
  trasparente, così una tolleranza troppo alta si vede subito.

## Come si usa, in pratica

1. Allega il poster, il logo e la foto del telefono in un messaggio solo.
2. `image_gen` con `riferimenti: ["allegato:1", "allegato:2", "allegato:3"]`
   per ricomporre la scena attorno ai file veri.
3. Oppure `image_edit` per restare identici all'originale: `incolla` del logo
   e del telefono con `scontorna: true` e `ombra`, e il testo vero disegnato
   sopra.

## Limiti noti

- Lo scontorno funziona su fondo uniforme; su fondo sfumato o con oggetti
  dietro al soggetto resta meglio `image_gen` con i riferimenti.
- `resolution` (1K/2K/4K) non è ancora esposto nei parametri.
