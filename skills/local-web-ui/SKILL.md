---
name: local-web-ui
description: Usa quando costruisci o tocchi un'interfaccia web locale. Solo HTML/CSS/JS, verifica con curl prima di dire che funziona.
version: 1.0.0
author: Orchestra
categoria: base
origine: scaricata
---

# Local Web UI

Interfacce locali: HTML, CSS e JavaScript puro, zero dipendenze
da installare. Se serve un server, quello del progetto o
`python -m http.server` — niente toolchain nuove per una prova.

## Costruire

- Un file fa tutto, oppure pochi file con nomi ovvi.
- Niente framework, niente build: la pagina deve aprirsi e
  funzionare così com'è.
- Testi e stati d'errore in italiano se l'app è in italiano.

## Verificare (obbligatorio)

1. Servi la pagina e colpiscila con `run_shell` + `curl`:
   lo status deve essere 200 e il corpo quello atteso.
2. Se il progetto ha strumenti browser (`browser_render`,
   `browser_screenshot`), usali per vedere davvero la pagina:
   un markup che "dovrebbe" funzionare non ha funzionato
   finché non l'hai visto.
3. Console pulita: nessun errore JavaScript. Un `console.log`
   dimenticato è rumore, un'eccezione è un bug.

## Mai

Mai dire "funziona" senza aver caricato la pagina almeno una
volta dopo l'ultima modifica. L'ultima modifica è sempre
quella che rompe.
