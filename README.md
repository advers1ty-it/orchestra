# Orchestra

Orchestratore agentico in Python puro (solo stdlib, zero dipendenze a runtime).
Gli dai un obiettivo in linguaggio naturale: lui pianifica, usa strumenti
(file, shell, web, browser), verifica il risultato e — se serve — delega
sotto-compiti ad altri agenti. Con interfaccia web in italiano.

## Per iniziare (senza essere esperti)

1. Scarica il pacchetto tester e lancia `Installa-Orchestra.bat`
   (non servono Git né account GitHub).
2. All’avvio si apre il browser su `http://127.0.0.1:8737`.
3. Il file `orchestra/.env` si crea da solo al primo avvio:
   aprilo e inserisci almeno una chiave API (es. OpenRouter),
   oppure impostala dal pannello **Opzioni** nella UI.
4. Scrivi un obiettivo nel pannello **Obiettivo** e premi Avvia.
5. Gli aggiornamenti arrivano da soli a ogni avvio.

Dettagli per chi distribuisce in `installer/LEGGIMI.txt`.

## Per sviluppatori

```bash
python3 -m orchestra.cli doctor                    # verifica config e connessione
python3 -m orchestra.cli chat                      # sessione interattiva
python3 -m orchestra.cli web                       # interfaccia web (127.0.0.1:8737)
python3 -m orchestra.cli run "il tuo compito"      # esegui e esci
python3 -m orchestra.cli goal "obiettivo"          # obiettivo autonomo
python3 -m orchestra.cli goals --pronti            # coda: cosa partirebbe
python3 -m orchestra.cli goal-next                 # esegui il prossimo pronto
python3 -m orchestra.cli scheduler --una-volta     # svuota la coda e esci
python3 -m orchestra.cli update --check            # c'è un aggiornamento?
python tests/run_all.py                            # suite completa (server acceso)
```

Configurazione in `orchestra/.env` (mai committato; vedi `.env.example`).

## Cosa sa fare

- **Chat agentica** — conversa, chiama strumenti, mostra tool ed eventi in tempo reale, si può interrompere e resettare.
- **Obiettivi autonomi** — lavori lunghi in background, persistenti su disco: sopravvivono al riavvio e si possono fermare da fuori.
- **Piani e dipendenze** — un obiettivo parte solo quando le sue dipendenze sono `done`; i cicli vengono rifiutati; i contenitori `piano` si chiudono da soli a figli completati.
- **Gate di accettazione** — un lavoro interrotto (max iterazioni, errori, budget) non viene mai archiviato come completato: diventa `failed` con il motivo, oppure viene ritentato fino a `max_attempts`. Criteri dichiarativi opzionali (es. “il file report.md deve esistere e contenere X”).
- **Delega multi-agente** — il padre affida sotto-compiti a figli con contesto minimale; retry opzionale con modelli alternativi.
- **Identità dell'agente principale** — nome e persona/istruzioni configurabili da Opzioni → Identità, senza dover creare un bot. Valgono quando non è attivo un bot e restano dopo le regole di sistema.
- **Lavori durevoli** — la coda in background dei bot vive su SQLite: un riavvio non la perde, i lavori in attesa ripartono e quelli interrotti a metà si riprovano dal pannello invece di essere rieseguiti alla cieca.
- **Checkout isolati** — un lavoro su un progetto git scrive in un worktree separato (`orchestra/lavoro-<id>`), non nella cartella che hai aperta: due bot non si sovrappongono e le modifiche non committate restano intatte. Se ha testato e funziona, il bot propone il merge con riepilogo e verifica; il pannello mostra il ramo, permette di scartare il checkout e di unire con **Unisci**, che rifiuta un progetto sporco e annulla i conflitti. Unire resta una scelta esplicita dell'utente.
- **Bot** — identità salvate con modello, persona, progetto e conversazione propri. Puoi avviare un compito in background per ogni bot: bot diversi lavorano insieme, ognuno nella propria cartella, senza contendersi la sessione attiva. Si passano un compito anche con `bot_chiedi` solo se l'allowlist lo consente (profondità 1, nessun ciclo); lo stesso bot esegue un turno alla volta.
- **Coda automatica** — scheduler a singolo consumatore (CLI, API o bottone “Coda” nella UI), spento di default perché consuma token veri.
- **Benchmark onesto** — misura i modelli per categoria di compito con verifiche oggettive (niente LLM che giudicano LLM).
- **Permessi** — file fuori dalla cartella di lavoro e automazioni richiedono conferma esplicita; senza canale di conferma, default = nega.
- **Diagnostica** — `orchestra doctor`, pannello Diagnosi nella UI, docs integrate su `/docs`.
- **Consiglio (Roast Room)** — pannello per far dibattere una decisione tra advisor in round, con verdict del chair e export PDF. L’idea e parte dell’interfaccia del tavolo sono ispirate al progetto open source “Roast Room” (citazione dovuta agli autori originali).

## Struttura

| File | Cosa fa |
|---|---|
| `agent.py` | Il loop agentico e le sue invarianti |
| `goal.py` | Obiettivi persistenti, scheduler, retry |
| `delega.py` / `recupero.py` | Sub-agenti e politiche di retry |
| `bots.py` | Identità persistenti, sessioni separate e ponte fra bot |
| `lavori.py` | Coda durevole su SQLite per i lavori in background |
| `worktree.py` | Checkout git isolati per i lavori dei bot |
| `identita.py` | Nome e persona dell'agente principale, senza creare un bot |
| `accettazione.py` | Gate di completamento e criteri dichiarativi |
| `tools/` | Pacchetto dei tool: `__init__.py` registro e profili, `_guard.py` le guardie condivise, un modulo per tool |
| `providers.py` | Adapter provider OpenAI-compatibili |
| `context.py` | Conteggio token e compaction |
| `session.py` | Ponte loop sincrono / consumatori asincroni |
| `update.py` | Aggiornamento da release GitHub |
| `webapp.py` | Server HTTP stdlib + SSE |
| `web/` | Interfaccia HTML/CSS/JS puro, zero dipendenze |
| `cli.py` | Tutti i comandi |

## Sicurezza e limiti onesti

- Il server ascolta solo su `127.0.0.1` e **non ha autenticazione**: è pensato per uso locale, singolo utente. Non esporlo su rete senza protezioni.
- La sandbox dei file è una guardia sui percorsi, non un isolamento di processo: non far eseguire all’agente comandi che non lanceresti tu.
- Le chiavi API stanno solo nel tuo `.env` locale, mai nel repo.

## Test

```bash
python tests/run_all.py
```

La suite gira senza rete (l’e2e col provider vero si salta da solo senza chiave). Alcuni test vogliono il server acceso su `8737`. Dettagli e filosofia dei test nella documentazione integrata (`/docs`).
