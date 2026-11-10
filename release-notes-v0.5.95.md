# v0.5.95 — Il tunnel non si aggira

## Il caso

Un audit del percorso web, dei job programmati e dei server MCP ha
trovato che alcune difese si potevano aggirare senza un errore visibile.
Questa release chiude i punti critici e alti e rende privati i file che
possono contenere chiavi.

## Il tunnel non basta più a fingersi locale

- Il gate considerava locale tutto ciò che arrivava da `127.0.0.1`. Un
  reverse proxy o un tunnel che inoltra da loopback poteva quindi
  comandare l'agente senza token. Ora servono tre cose: client loopback,
  `Host` loopback e nessun header di inoltro (`CF-Connecting-IP`,
  `CF-Ray`, `X-Forwarded-For`, `X-Real-IP`, `Forwarded`,
  `X-Forwarded-Proto`).
- Cloudflared continua a funzionare, ma passa dal token; una pagina su
  un dominio pubblico che risolve a `127.0.0.1` non passa più (DNS
  rebinding).
- Il cookie di sessione è `Secure` quando la richiesta è HTTPS, anche
  dietro un proxy, e la risposta non viene messa in cache.
- `--remote` avvisa che resta HTTP in chiaro: per l'uso da fuori casa
  meglio tunnel o VPN.

## Cron e MCP

- I job shell vengono controllati alla creazione e all'aggiornamento, e
  ricontrollati quando lo scheduler li esegue: un job vecchio non passa
  più senza policy, root e divieti sui file di credenziali.
- Un job shell non eredita più l'ambiente del processo: niente chiavi
  API o token del padre.
- I server MCP stdio ricevono un ambiente minimo; le variabili che
  servono le dichiarano nel loro `env`.
- Aggiungere un server MCP stdio richiede una conferma esplicita e passa
  dalla policy della shell.

## Segreti, backup e shell

- Nuovo modulo `orchestra/segreti.py`: scrittura atomica e `0600` per
  `.env`, token Nous, stato del tunnel, configurazione MCP, cron e archivi
  di backup.
- Il ripristino da web accetta solo archivi presenti nell'elenco e non
  rimette le chiavi per default.
- I percorsi con `$HOME/...`, `%USERPROFILE%\...` o `$env:...\...` vengono
  espansi prima del controllo; `echo $HOME` resta un comando normale.
- `web_leggi` controlla il peer dopo la connessione, prima di leggere la
  risposta.
- Il pannello Dipendenze escapa i campi prima di costruire l'HTML.

## Verifiche

La suite completa `tests/run_all.py` è verde: tutte le suite che sono
partite passano. `test_e2e` non è potuta avvenire perché il provider
esterno non ha risposto: non è un fallimento del codice, ma quella
copertura resta da rifare.

Restano dichiarati: `--remote` in HTTP, l'API locale senza token su
macchine con più utenti, e il confine della shell come best-effort, non
sandbox.
