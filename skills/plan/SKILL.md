---
name: plan
description: Usa quando un lavoro è troppo grosso per farlo a braccio. Scrivi prima il piano in .orchestra/plans/, non eseguire niente.
version: 1.0.0
author: Orchestra
categoria: base
origine: scaricata
---

# Plan

Un piano è un file markdown, non una promessa. Si scrive prima,
si esegue dopo. Mai le due cose insieme.

## Come si scrive

1. Leggi i file rilevanti con `read_file` prima di proporre passi:
   un piano scritto senza aver guardato il codice è un augurio.
2. Crea `.orchestra/plans/<slug>.md` con `write_file`, in questa forma:
   - **Obiettivo**: una frase, misurabile.
   - **Contesto**: cosa sai già (file, vincoli, decisioni prese).
   - **Passi**: numerati, ognuno piccolo abbastanza da verificare
     da solo, con il comando o il file che lo chiude.
   - **Rischi**: cosa può andare storto e come te ne accorgi.
   - **Verifica finale**: come si dimostra che è finito
     (test, comando, output atteso).
3. Fermati lì. Non eseguire nessun passo: l'esecuzione è un
   lavoro separato, con il suo turno di verifica.

## Regole

- Un passo = una verifica. Un passo senza verifica è due passi
  di cui uno nascosto: dividilo.
- Se durante la scrittura scopri che manca un'informazione,
  scrivilo nei rischi invece di inventarla.
- Il piano vive nel repo (`.orchestra/plans/`): la prossima
  sessione lo ritrova e non ricomincia da zero.
