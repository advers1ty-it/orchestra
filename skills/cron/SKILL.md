---
name: cron
description: "Job programmati: crea/modifica/elimina job cron che eseguono obiettivi o comandi shell a orari programmati. Usa il tool `cron`."
version: 1.0.0
author: Orchestra
categoria: base
origine: base
---

# cron

Usa il tool `cron` per programmare esecuzioni ricorrenti o one-shot.

## Quando usarlo
- L'utente chiede un'attività ricorrente (per esempio "ogni giorno alle 9", "lunedì mattina", "ogni ora").
- Per un'attività una tantum, non creare una regola cron che potrebbe ripetersi: usa un goal con `--not-before <epoch>` oppure chiedi quando eseguirlo se l'orario non è chiaro.
- Automatizzare report, backup, controlli periodici.

## Azioni
- `lista`: elenca i job.
- `crea`: crea un job. Parametri: nome, schedule, action_type (goal/shell), objective o command, profile, enabled.
- `modifica`: cambia campi di un job (id richiesto).
- `elimina`: rimuove un job.
- `abilita`/`disabilita`: toggle.
- `esegui`: esegue subito un job.
- `dettagli`: dettagli di un job.
- `stato`: stato dello scheduler cron.
- `avvia_scheduler`/`ferma_scheduler`: avvia/ferma il demone.

## Schedule
Espressione cron a 5 campi: `minuto ora giorno mese giorno-settimana`.
Shortcut: `@hourly`, `@daily`, `@weekly`, `@monthly`, `@yearly`, `@reboot` (una sola volta all'avvio).

Esempi:
- ogni giorno alle 9: `0 9 * * *`
- ogni lunedi' alle 8: `0 8 * * 1`
- ogni 15 minuti: `*/15 * * * *`
- ogni ora: `@hourly`

## Note
- I job di tipo goal avviano un obiettivo (costa token). I job shell eseguono un comando.
- Lo scheduler cron parte in automatico all'avvio del server (intervallo 30s). Si puo' fermare dal pannello Cron o via tool.
- Per modificare/eliminare usa l'id restituito da `lista`/`crea`.
