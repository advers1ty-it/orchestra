# Orchestra

Orchestratore agentico scritto da zero. Loop, tool, contesto e provider
sono nostri; zero dipendenze esterne a runtime, solo stdlib.

Non è un wrapper attorno a un altro agente. Il nucleo è in `orchestra/agent.py`
e sta in una pagina.

## Perché da zero

Per capire ogni riga. Un orchestratore non è il loop: è tutto quello che
si rompe intorno al loop. I quattro punti critici sono identificati e
coperti da test, non lasciati a emergere in produzione.

## Uso

```bash
python3 -m orchestra.cli doctor                    # verifica config e connessione
python3 -m orchestra.cli models --free             # modelli gratuiti disponibili
python3 -m orchestra.cli run "il tuo compito"       # esegui e esci
python3 -m orchestra.cli chat                      # sessione interattiva
python3 tests/run_all.py                           # suite completa
```

Configurazione in `orchestra/.env` (copia da `.env.example`, mai committato).

## Struttura

| File | Cosa fa |
|---|---|
| `types.py` | `Message`, `ToolCall`, `Tool`, `ToolRegistry`, `LLMResponse` |
| `providers.py` | Normalizzazione delle API. Adapter OpenAI-compatibili |
| `context.py` | Conteggio token e compaction a due fasi |
| `agent.py` | Il loop. Tutte le invarianti vivono qui |
| `tools.py` | Tool concreti + guard del root |
| `cli.py` | `run`, `chat`, `doctor`, `models` |

## Le invarianti del loop

Sono in `agent.py`, e ognuna ha un test che la copre. Se le tocchi, il test
che le copre è il primo che deve dirti di no.

1. **Un tool che fallisce non uccide il turno.** L'eccezione torna al modello
   come contenuto del messaggio `tool`, così può correggere. Un agente che si
   blocca su un errore recuperabile è un agente che spreca soldi.
2. **Ogni `tool_call` riceve SEMPRE un risultato**, anche se vuoto o in
   errore. Altrimenti la sequenza ha un buco e molti provider la rifiutano.
3. **Gli ultimi `keep_recent` messaggi non si compattano mai.** Il modello
   deve poter vedere dove si trova.
4. **Il loop è cancellabile** via `should_continue`, e `AgentState` è
   ispezionabile dall'esterno.
5. **Il circuit breaker richiede errori consecutivi reali.** Azzerare il
   contatore dopo ogni chiamata — anche quelle fallite — rende la guardia
   irraggiungibile. È successo, ed è coperto da test.

## Compaction a due fasi

`fit_context` esegue le fasi in ordine di costo, e ritorna un **report** di
cosa ha fatto. Il report serve per misurare, non per indovinare:

- se `tools_pruned` è sempre 0, la finestra è semplicemente larga
- se `history_merged` scatta a ogni turno, il riassunto sta lavorando troppo
  e il problema è a monte

Fase 1 pota i risultati tool vecchi conservando le prime 200 caratteri
(spesso bastano a orientare il modello). Fase 2 fonde i turni utente
vecchi, preservando sempre il system prompt e il primo messaggio utente —
l'obiettivo originale della sessione.

## Sicurezza

Il **root è un confine, non una convenzione**, ed è imposto a entrambi i
tool che toccano il filesystem.

`run_shell` aveva inizialmente la guardia di `read_file` come unico baluardo.
Bastava un `head -2 ../../.env` per leggere le chiavi API. Ora entrambi
verificano: blocca `..`, percorsi assoluti, home esplicite e file di
credenziali (`.env`, `.ssh`, `.aws`, `.git-credentials`, `.npmrc`).

**Quello che NON è un sandbox**: `curl` può ancora scaricare, e un processo
avviato dalla shell può fare quello che vuole. Per un isolamento vero serve
il confinement a livello di processo, non un handler. Da fare prima di
esporre questo a qualcun altro.

## Il percorso della shell

Su Windows `shell=True` usa `cmd.exe`, non bash. I due dialetti divergono in
modo che produce **falsi successi**: `;` non è un separatore in cmd, quindi
`cmd1; cmd2` esegue solo `cmd1` e restituisce `exit 0` — il secondo comando
sparisce senza errore.

Osservato in un test e2e: 3 iterazioni spese a diagnosticare un output vuoto
che era un comando mai eseguito. Ora cerchiamo una shell POSIX nel PATH con
`shutil.which` e la usiamo esplicitamente; se non c'è, l'output del tool
dice esplicitamente al modello che il separatore è `&&`.

L'output è letto con `errors="replace"`: un byte non-UTF-8 altrimenti
solleva `UnicodeDecodeError` dentro `subprocess` e uccide il tool, facendo
perdere il risultato di un comando che è andato a buon fine.

## Provider

Un solo adapter (`OpenAICompatAdapter`) copre OpenRouter, Groq, NVIDIA,
Together, Cerebras, Mistral e OpenAI, che parlano tutti
chat-completions. Non fingiamo che le API siano identiche: le differenze che
cambiano il comportamento del loop sono esposte esplicitamente.

**Gatekeeper sui corpi di errore.** Alcuni gateway rispondono HTTP 200 e
nascondono l'errore nel corpo:

```json
{"error": {"message": "Provider returned an empty response", "code": 502}}
```

Senza controllarlo, il fallimento si presenta come "nessuna choice", non è
retryable, e il task muore invece di recoverare. Trovato in un test e2e
reale, ora coperto da test di regressione.

Retry: 4 tentativi con backoff esponenziale (0.5, 1, 2 s) sui soli errori
transitori — 429, 5xx, rete. Nessun retry su 401/402: la chiave non si
guarisce col tempo e insistere è solo rumore.

## Test

```bash
python3 tests/run_all.py
```

| Suite | Cosa copre | API |
|---|---|---|
| `test_offline.py` | Tool, compaction, invarianti del loop, callback | no |
| `test_resilience.py` | 429/500/401/402, compaction sotto carico, degenerazione, normalizzazione | no |
| `test_shell.py` | Comportamento reale della shell su questa macchina | no |
| `test_security.py` | Escape dal root via shell, blocco dei segreti | no |
| `test_e2e.py` | Task reali col provider vero | sì |

L'e2e verifica le **contratte**, non la qualità della prosa del modello:
il file esiste, `fib(10) == 55`, il file di sistema non è trapelato. Assert
sul numero di iterazioni misurerebbero la pazienza del modello, non la nostra
correttezza, e cambierebbero ogni settimana.

## Cosa non c'è ancora

Dichiaro i buchi invece di lasciarli scoprire:

- **Nessun routing per capacità.** Un solo provider per volta. È il
  differenziale previsto e non è iniziato.
- **Nessuna persistenza.** Lo stato vive in memoria: chiudere il processo
  perde la sessione.
- **Nessun caricamento selettivo dei tool.** `ToolRegistry` ha già
  `activate`/`deactivate` e `api_payload` passa solo gli attivi, ma la
  politica di *quale* attivare non è scritta.
- **Nessun adapter Anthropic nativo.** Punto di innesto:
  `AnthropicAdapter` in `providers.py`, per `tool_use` e `cache_control`.
- **Nessun subagent, nessuno scheduler, nessuna memoria fra sessioni.**
- **Nessun sandbox vero** (vedi Sicurezza).

## Configurazione

`ORCHESTRA_ROOT` (default: cwd) è la radice entro cui l'agente può
leggere e scrivere. `ORCHESTRA_CONTEXT_LIMIT` è in token stimati; il
conteggio esatto arriva dal provider a ogni risposta e aggiorna la
stima.
