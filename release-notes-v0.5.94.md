# v0.5.94 — Il consiglio vede il tavolo che giudica

## Il caso

Il consiglio discuteva una decisione con dodici seat e sembrava informato:
citava fonti, rispettava i round, produceva un verdetto. Ma ogni seat
riceveva la decisione e le chiavi «A», «B», «C» senza le etichette delle
opzioni, e il prompt gli diceva di leggere `brief.md` — un file che non
poteva aprire, perché gira con un registro di tool vuoto. Il dibattito era
fluente e riguardava alternative che i seat non sapevano nominare.

## Cosa cambia

- Il brief entra nel prompt di ogni round: decisione, sintesi del Chair,
  opzioni per esteso, assunzioni sui numeri mancanti.
- Il cervello arriva intero: `principles.md` non veniva mai iniettato e
  `frameworks`/`positions` erano tagliati a metà. Ora entrano le cinque
  sezioni utili, senza troncare (tetto 96.000 caratteri; il più grande ne
  misura 90.574).
- Il tavolo lo sceglie il Chair: da 2 a 7 seat, con una riga sul perché,
  Buffett sempre presente come guardia del downside. Nel pannello le card
  si cliccano, con «Consiglia tavolo», «Tutti» e «Tavolo abituale».
- Le citazioni con fonte vengono confrontate col cervello del seat: quelle
  che non tornano sono elencate nel verdetto e in `citazioni.json`.
- Il consiglio usa il provider e il modello scelti nell'app, non una
  priorità scritta a mano; provider e modello restano scritti accanto alla
  sessione.
- Tre difetti di parsing trovati dal test nuovo: la confidenza era sempre
  10/10 (il round del voto non chiede `CONFIDENCE`), un `AMENDMENT` vuoto
  catturava la riga successiva, e «Endorse with amendment» contava come
  «Endorse».

## Verifiche

`test_consiglio.py` 61 check con un provider finto (nessuna rete): brief e
etichette nei prompt, cervelli interi su tutti e dodici i seat, tavolo
proposto, citazioni vere e inventate, matematica del verdetto, cap per il
rischio di rovina. Verdi anche `test_rotte` 34 (135 rotte), `test_ui` 54,
`test_piano` 23, `test_file_tracciati` 3, e la CI su Ubuntu e Windows per
il commit delle funzioni.
