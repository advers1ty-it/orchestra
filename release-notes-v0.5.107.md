# v0.5.107 — Chiude output non-streaming, fallback e riepilogo dei goal

_Note costruite dai messaggi dei commit dopo `v0.5.106`: rileggile prima di pubblicarle._

## Chiude output non-streaming, fallback e riepilogo dei goal

Il goal ora usa l'ultimo messaggio assistant quando il provider non
emette eventi, e il fallback si azzera a ogni turno invece di restare
appiccicoso. Il riepilogo riconosce risposta_finale e max_iterations,
e l'apprendimento accetta i turni conclusi normalmente: senza queste
voci un turno riuscito sembrava sospetto e la proposta di skill non
partiva mai.

ðŸ¤– Generated with Codebuff

## Corregge i test CI di processo e Telegram

- il test del processo cerca la riga letta solo nell'output, non nel
  comando che contiene la stessa parola e faceva uscire il ciclo troppo
  presto;
- _progetto_attivo tollera un'app costruita senza sessione, come quella
  usata dai test dei comandi Telegram.

ðŸ¤– Generated with Codebuff

## Installer Linux, launcher e rifinitura dell'interfaccia

- installer autonomo per Linux con venv, comando orchestra e voce di menu;
- launcher start/stop/restart/log e avvio automatico XDG;
- semplificata la UI (sidebar, memoria e pannelli) e aggiornate le icone;
- rimossi autoverifica e verifica manuale dei turni;
- migliorati progetti, browser, tool computer, certificati e dipendenze;
- test dell'installer e suite aggiornate.

ðŸ¤– Generated with Codebuff

## Permessi per azione, goal controllabili e storico append-only

- il consenso vale per percorso e azione, con revoca selettiva;
- i goal ricordano progetto e root, fermano i pending e riconciliano i running;
- lo storico salva i messaggi grezzi in modo incrementale con uid stabili;
- header di sicurezza su ogni risposta e remote_stop che non uccide PID estranei;
- documentati i limiti reali dei goal, con test mirati.

ðŸ¤– Generated with Codebuff
