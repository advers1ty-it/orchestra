---
name: github
description: Usa quando lavori con repository GitHub. Branch, issue, pull request, review e merge con la CLI gh.
version: 1.0.0
author: Orchestra
categoria: base
origine: scaricata
---

# GitHub via gh

Tutto passa dalla CLI `gh`, lanciata con `run_shell`. Niente click
raccontati a memoria: ogni stato si legge dal comando.

## Autenticazione

`gh auth login` una volta sola. Verifica con `gh auth status`
prima di una sessione di lavoro: un token scaduto si scopre
all'inizio, non al push.

## Ciclo issue → PR → merge

1. `gh issue list` / `gh issue view <n>` per il contesto vero.
2. Branch dal nome che dice cosa fa, mai lavoro diretto su main.
3. Commit piccoli con messaggi che dicono il perché, poi push.
4. `gh pr create`: titolo che riassume, corpo con cosa cambia
   e come è stato verificato.
5. `gh pr checks`: si mergia solo a CI verde. Una CI rossa
   ignorata è un bug spedito per posta.
6. `gh pr merge` e cancellazione del branch.

## Review

`gh pr diff <n>` prima di ogni opinione. I commenti inline
(`gh api` o interfaccia) citano righe precise, non impressioni.
Approvare senza aver letto il diff non è una review.

## Onestà di stato

Se un comando fallisce, riporta l'errore esatto e fermati:
mai "dovrebbe essere andata" senza l'output che lo conferma.
