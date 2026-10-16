---
name: systematic-debugging
description: Usa quando un bug resiste al primo fix o non sai dove nasce. Trova la causa radice prima di toccare codice.
version: 1.0.0
author: Orchestra
categoria: base
origine: scaricata
---

# Systematic Debugging

Un fix al sintomo sposta il bug, non lo chiude. Procedi in quattro fasi,
una ipotesi alla volta.

## 1. Riproduci

Trova il comando minimo che mostra il bug e lancialo con `run_shell`.
Se non si riproduce a comando, non hai un bug: hai un'impressione.
Annota l'output esatto, non un riassunto a memoria.

## 2. Restringi

Biseca: separa la metà che funziona da quella che rompe, e dimezza
di nuovo. Leggi il codice con `read_file` prima di cambiarlo —
mai modificare un file che non hai letto. Per le regressioni,
`git log` e `git blame` sul file dicono cosa è cambiato per ultimo:
la regressione abita quasi sempre lì.

## 3. Causa radice

Scrivi la causa in una frase: "succede X perché Y". Se la frase
contiene "e poi anche", non è la radice: scendi di un livello.
Se servono due fix in due punti diversi, manca ancora la causa vera.

## 4. Ripara e verifica

Un fix solo, poi riesegui il comando della fase 1: deve passare.
Poi cerca danni collaterali: casi simili nello stesso file e nei
fratelli (stesso bug, stessa famiglia). Chiudi solo quando la
riproduzione passa e niente altro si è rotto.
