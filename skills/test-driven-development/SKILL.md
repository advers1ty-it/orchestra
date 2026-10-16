---
name: test-driven-development
description: Usa quando aggiungi una funzione o correggi un bug. Prima il test che fallisce, poi il codice che lo fa passare.
version: 1.0.0
author: Orchestra
categoria: base
origine: scaricata
---

# Test-Driven Development

RED – GREEN – REFACTOR. Niente scorciatoie: l'ordine è il metodo.

## RED: il test che fallisce

Scrivi il test prima del codice, e lancialo con `run_shell`
(`pytest` o `python tests/...`). Deve fallire, e deve fallire
per il motivo giusto: un test che fallisce per un import rotto
non prova niente. Leggi l'errore e chiediti "è questo il
comportamento che voglio cambiare?" — se sì, il test è buono.

## GREEN: il minimo che passa

Scrivi il codice più piccolo che fa passare il test. Niente
generalizzazioni, niente "già che ci sono". Se per far passare
il test devi stravolgere mezzo progetto, il test sta dicendo
che il disegno è sbagliato: ascoltalo prima di forzarlo.

## REFACTOR: pulisci a test verdi

Solo ora: nomi migliori, duplicazioni via, funzioni corte.
Dopo ogni tocco, riesegui i test. Un refactor che rompe un test
non è un refactor, è un secondo task camuffato.

## Dove e come qui

I test vivono in `tests/test_*.py` e si lanciano con `run_shell`.
Prima di chiudere, la suite intera (`python tests/run_all.py`)
deve restare verde: un test nuovo non giustifica uno vecchio rotto.
