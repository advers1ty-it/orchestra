# Orchestra

Un assistente AI che lavora **sul tuo computer**. Gli scrivi in italiano
cosa vuoi ottenere, e lui lo fa: legge e scrive file, esegue comandi,
cerca sul web, apre il browser, controlla il risultato. Se il lavoro è
grande lo spezza in sotto-compiti e li porta avanti anche mentre non
guardi.

Tutto in locale, gratis, **senza account e senza abbonamenti**: l'unica
spesa sono le chiamate al modello che scegli tu (e con un motore locale
non spendi niente).

Un progetto di **advers1ty-it**. Il codice è scritto a quattro mani con
modelli di intelligenza artificiale — Claude, GPT e altri — e ogni
modifica viene letta, provata e committata da una persona prima di finire
in una release: nessuna riga arriva qui senza che qualcuno l'abbia capita.

> Orchestra è un programma che gira solo sulla tua macchina: non esiste un
> server nostro, nessuno riceve i tuoi dati, e puoi cancellare tutto
> chiudendo la cartella.

---

## Installazione (Windows, la via semplice)

1. Vai su **[Releases](https://github.com/advers1ty-it/orchestra/releases/latest)**
   e scarica `Installa-Orchestra.bat`. Non servono Git né un account GitHub.
2. Lancialo con un doppio clic. Se manca Python lo installa lui, controlla i
   certificati di Windows e ti chiede quali funzioni aggiuntive vuoi
   (ricerca web, immagini, PDF, voce, tunnel): Invio = tutte, `0` = nessuna.
3. Sul Desktop compare **Avvia Orchestra**: usalo ogni volta che vuoi
   partire. Si apre il browser su `http://127.0.0.1:8737`.

Se hai già installato Orchestra, rilanciare l'installer **aggiorna** senza
toccare `orchestra/.env`, i database, il token di Telegram o le skill.

## Installazione (Linux, la via semplice)

Serve Python 3.11 o superiore e il modulo `venv`. Se mancano, l'installer
propone di installare i pacchetti di sistema con `sudo`: mostra prima i
comandi e chiede conferma. `--no-sistema` salta questa parte e stampa le
istruzioni. Non serve Git né un account GitHub, e non vengono aggiunti
repository di terze parti.

Su Windows l'installer punta alla 3.14 (con un fallback se non è
installabile); su Linux usa la versione più recente già presente, preferendo
la 3.14 se è utilizzabile e accettando 3.11+. Non viene forzata la 3.14: la maggior
parte delle distribuzioni non la pacchettizza, e aggiungere un repository
esterno sarebbe più rischioso che utile.

1. Scarica `Installa-Orchestra.sh` dalla pagina
   **[Releases](https://github.com/advers1ty-it/orchestra/releases/latest)**,
   oppure da terminale:

   ```bash
   curl -fsSL -o Installa-Orchestra.sh \
     https://github.com/advers1ty-it/orchestra/releases/latest/download/Installa-Orchestra.sh
   bash Installa-Orchestra.sh
   ```

2. L'installer scarica l'ultima versione, crea un ambiente Python isolato in
   `~/.local/share/orchestra`, prepara il comando `orchestra` in
   `~/.local/bin` e aggiunge **Avvia Orchestra** al menu applicazioni (e al
   Desktop, se la cartella esiste). Se Python o `venv` mancano, prima chiede
   il permesso di installarli con `sudo`. Chiede anche se installare ricerca
   web, immagini e PDF: Invio = sì, `n` = no; `--no-deps` salta la domanda.
3. Avvia con **Avvia Orchestra** o con:

   ```bash
   ~/.local/share/orchestra/Avvia-Orchestra.sh
   ```

   Si apre il browser su `http://127.0.0.1:8737`. Per fermarlo:
   `~/.local/share/orchestra/Orchestra.sh ferma`.

Rilanciare l'installer aggiorna il codice senza toccare `.env`, database,
memoria, token o skill. I dati restano in `~/.orchestra`. Le funzioni
aggiuntive si possono installare anche dopo da **Opzioni → Dipendenze**.

Su Linux l'automazione del mouse e della tastiera richiede `xdotool`
(X11); senza, i tool del computer dicono cosa manca invece di fallire in
silenzio. Il rendering e gli screenshot delle pagine web richiedono Google
Chrome o Chromium (il fetch testuale funziona lo stesso). La trascrizione
audio (`faster-whisper`) e `cloudflared` per il tunnel sono opzionali e si
installano a parte. L'avvio automatico usa `~/.config/autostart`, quindi
funziona sui desktop che rispettano lo standard XDG (GNOME, KDE, XFCE).

## Il primo avvio in tre minuti

1. **Una chiave.** Nel pannello **Opzioni → Modello** incolla la chiave di
   un provider (OpenRouter ha un piano gratuito con limiti, ed è il modo
   più rapido per provare). In alternativa usa un motore locale come
   Ollama e non serve nessuna chiave.
2. **Un obiettivo.** Scrivi nel pannello **Obiettivo** qualcosa di
   concreto — «leggi i file in questa cartella e scrivimi un indice» — e
   premi **Avvia**. Lo vedi lavorare in tempo reale, e puoi fermarlo.
3. **Guarda cosa ha fatto.** Il pulsante `Δ` mostra i file che ha
   cambiato in quel turno, `↶` annulla l'ultima modifica.

Da qui in poi è una chat: puoi parlargli, correggerlo mentre lavora
(scrivendo durante un turno) o interromperlo con il pulsante di stop.

## Cosa sa fare

**Chat agentica.** Conversa, usa gli strumenti, ti mostra cosa sta facendo
mentre lo fa. Gli eventi, i tool e i loro argomenti sono visibili, non
nascosti dietro una risposta.

**Obiettivi autonomi.** Un lavoro lungo parte in background, viene salvato
su disco e sopravvive al riavvio del programma. Puoi chiuderlo, riaprirlo e
ritrovarlo dov'era; fermarlo dall'esterno se sta sbagliando strada.

**I limiti veri dei goal.** Un goal non è un processo che continua da solo
per sempre:

- il goal ricorda il progetto e la cartella in cui è nato; un progetto
  sconosciuto o una root che non coincide con il progetto vengono rifiutati;
- dopo un riavvio un goal interrotto torna `pending` e riparte solo se lo
  scheduler è acceso (di default è spento). Il turno che era in corso non
  riprende dal punto esatto: riparte dall'obiettivo;
- lo stop è cooperativo. Il turno si ferma ai punti di controllo
  dell'agente, quindi una chiamata al modello o un tool già partiti possono
  finire prima che il processo si accorga dell'annullamento;
- ogni esecuzione consuma token e ha un tetto di iterazioni. Esaurirlo è un
  fallimento, non un successo, salvo `consenti_parziale`; i tentativi
  automatici sono limitati e hanno un backoff;
- i criteri di accettazione possono controllare output e file, non eseguire
  comandi arbitrari. Il risultato resta da leggere e provare.

**Piani e dipendenze.** Un obiettivo può aspettare che un altro sia finito
prima di partire, e i giri viziosi vengono rifiutati invece di bloccare
tutto. Lo scheduler esegue un goal alla volta: due lavori sullo stesso
registro non si rubano la prenotazione.

**Niente finti successi.** Se un lavoro si interrompe (troppe iterazioni,
errori, tempo scaduto) non viene archiviato come «completato»: diventa un
fallimento con il motivo, oppure viene ritentato. Puoi anche dichiarare
dei criteri — «il file report.md deve esistere e contenere questa riga» —
e il risultato viene verificato davvero.

**Delega.** Per i lavori grandi Orchestra crea sotto-agenti con il minimo
contesto necessario, e può lanciarne più di uno insieme. I risultati
restano separati: unirli è una decisione del padre, non una magia.

**Cartelle di lavoro isolate.** Quando un lavoro tocca un progetto git,
Orchestra scrive in una copia separata (`orchestra/lavoro-<id>`), non nella
cartella che hai aperta: due bot non si pestano i piedi e le tue modifiche
non committate restano intatte. Se il lavoro passa i test, ti propone di
unire — e unire resta una scelta tua.

**Bot.** Identità separate, ognuna con il suo modello, le sue istruzioni, il
suo progetto e la sua conversazione. Bot diversi lavorano insieme, ognuno
nella propria cartella.

**Telegram.** Puoi collegare un bot Telegram e scrivere a Orchestra dal
telefono, con i permessi e gli strumenti di sempre. Più persone possono
scrivere allo stesso bot, e chi comanda lo sa (vedi [sotto](#telegram-dal-telefono)).

**Consiglio (Roast Room).** Una decisione importante può essere messa sul
tavolo: più advisor la guardano da angolazioni diverse, in round, e alla
fine c'è un verdetto con il parere del chair. L'idea e una parte
dell'interfaccia vengono dal progetto open source *Roast Room*: merito agli
autori originali.

**Benchmark onesto.** Misura i modelli per tipo di compito con verifiche
oggettive — niente modello che giudica un altro modello.

**Permessi.** Leggere fuori dalla cartella di lavoro, eseguire comandi o
avviare automazioni richiede una conferma esplicita. Se non c'è un canale
per chiedertela, la risposta predefinita è **no**.

**Diagnostica.** `orchestra doctor`, il pannello Diagnosi e la guida
integrata su `/docs`. Lo storico dei turni resta in `storico.db`: puoi
filtrare per esito, vedere gli errori e gli argomenti dei tool.

## Telegram dal telefono

In **Opzioni → Telegram** scegli il bot, incolla il token di
[@BotFather](https://t.me/BotFather) e fai leggere il QR con il telefono:
la chat resta collegata e da lì puoi lavorare senza il computer davanti.

| Comando | Cosa fa |
|---|---|
| `/aiuto` | la lista dei comandi |
| `/stato` | modello, turno in corso, chat collegate |
| `/modello` | cambiare modello con i pulsanti |
| `/ragionamento` | livello di ragionamento, e se vedere il suo pensiero in chat |
| `/obiettivo <testo>` | avviare un obiettivo (senza testo: elenco degli aperti) |
| `/consiglio <decisione>` | chi mettere al tavolo, e perché |
| `/steer <testo>` | guidare il turno mentre lavora |
| `/stop` | fermare il turno |
| `/nuova` | ricominciare da una conversazione vuota |
| `/aggiorna`, `/riavvia` | aggiornare o riavviare il server dal telefono |
| `/scollega` | staccare questa chat |

Più persone possono scrivere allo stesso bot (fino a cinque): ognuna si
collega con il codice del pannello, riceve le risposte nella propria chat,
e può essere revocata singolarmente dal pannello senza buttare fuori le
altre. La conversazione però è una sola per bot: `/nuova` la azzera per
tutti e `/stop` ferma il turno di chiunque stia lavorando — il bot te lo
dice quando le chat sono più di una.

## Modelli, provider, quanto spende

- **Provider.** Funziona con qualunque servizio compatibile OpenAI:
  OpenRouter, OpenAI, Google, Groq, NVIDIA, Nous e altri. Basta una chiave.
- **In locale.** Con Ollama o un endpoint compatibile non esce niente dalla
  tua macchina e non paghi niente.
- **Ripieghi a mano.** Se un modello cade, puoi dire a Orchestra quali
  altri provare (fino a tre, anche di servizi diversi). Spento, usa solo il
  modello scelto: nessun ripiego a sorpresa, e nel benchmark nessun
  risultato attribuito al modello sbagliato.
- **Livello di ragionamento.** Da `auto` a `max`. Più alto = più pensa e
  più costa.
- **Tetto di risposta.** `ORCHESTRA_MAX_TOKENS` in `orchestra/.env`, o dal
  pannello: alzalo se le risposte arrivano troncate.

## Dati, privacy, sicurezza

- Il server ascolta **solo su `127.0.0.1`** e non ha autenticazione: è
  pensato per un computer tuo, a casa. Non esporlo su internet senza
  proteggerlo.
- Le chiavi API stanno in `orchestra/.env` sulla tua macchina, e non
  vengono mai mandate da nessuna parte tranne al provider che hai scelto.
- Lo storico dei turni è in `storico.db`, sempre sul tuo disco.
- Quello che esce dal computer è solo ciò che serve al modello per
  rispondere: il testo, i file che legge, gli screenshot del browser.
- La sandbox dei file è una guardia sui percorsi, **non** un container: non
  far eseguire all'agente comandi che non lanceresti tu. Le policy dei bot
  restringono cosa può fare, ma girano nello stesso processo.

## Trasparenza (Reg. UE 2024/1689, AI Act)

**Stai parlando con un'IA.** Le risposte e i file che Orchestra scrive sono
generati da un modello di terzi e possono essere sbagliati, anche quando
sembrano sicuri. L'avviso è nella barra in alto e al primo avvio; le
modifiche di ogni turno si vedono con `Δ` e si annullano con `↶`.

**I contenuti sintetici sono dichiarati.** Le immagini generate portano un
metadato dentro il file e un `<nome>.ai.json` accanto, con generatore,
provider, modello e data.

**A cosa non serve.** Non è uno strumento per decidere sulle persone:
niente selezione del personale, ammissioni, credito, assicurazioni,
diagnosi o giustizia. Non è certificato e non garantisce un risultato: il
codice che produce va letto e provato prima di usarlo davvero.

Il dettaglio — cosa esce dalla macchina, come si annulla, cosa non devi
aspettarti — è in [`AI-ACT.md`](AI-ACT.md).

## Da sorgente (macOS, Linux, o se vuoi smanettare)

Serve Python 3.11 o superiore.

```bash
git clone https://github.com/advers1ty-it/orchestra.git
cd orchestra
python3 -m orchestra.cli web           # interfaccia web su 127.0.0.1:8737
```

Dalla riga di comando, senza aprire il browser:

```bash
python3 -m orchestra.cli doctor                 # controlla configurazione e connessione
python3 -m orchestra.cli chat                   # sessione interattiva
python3 -m orchestra.cli run "il tuo compito"    # esegui e esci
python3 -m orchestra.cli goal "obiettivo"        # obiettivo autonomo
python3 -m orchestra.cli goals --pronti          # cosa partirebbe adesso
python3 -m orchestra.cli scheduler --una-volta   # svuota la coda e esci
python3 -m orchestra.cli update --check          # c'è una versione nuova?
```

Le dipendenze facoltative (`ddgs` per la ricerca web, `Pillow` per le
immagini, `pypdf` per i PDF) stanno in `requirements.txt`: senza, Orchestra
funziona lo stesso e ti dice cosa manca quando serve.

Per contribuire o capire com'è fatto: `python tests/run_all.py` esegue la
suite completa. La stessa suite gira su GitHub Actions a ogni push, su
Ubuntu e Windows, senza chiavi vere.

## Licenza

**GNU Affero General Public License v3.0 o successive** (AGPL-3.0-or-later).
Il testo completo è in [`LICENSE`](LICENSE).

In due righe: puoi usarlo, studiarlo, modificarlo e ridistribuirlo
gratis — anche in azienda — a patto che le versioni modificate restino
libere allo stesso modo. Se un giorno qualcuno offre Orchestra modificato
come servizio in rete, deve rendere disponibile il codice sorgente a chi
lo usa. Non ci sono garanzie: è software gratuito, e chi lo usa se ne
prende la responsabilità.

Il nome **Orchestra** e il marchio **advers1ty-it** non sono coperti dalla
licenza: le versioni modificate non possono presentarsi come se fossero
questo progetto.

## Crediti e segnalazioni

- Ideato e mantenuto da **advers1ty-it**, con l'aiuto di codice generato da
  modelli di IA e rivisto prima di ogni rilascio.
- L'idea del *Consiglio* e una parte della sua interfaccia vengono dal
  progetto open source **Roast Room**.
- Un ringraziamento a chi tiene in piedi Python, SQLite e le librerie
  facoltative che Orchestra usa.

Problemi, idee, richieste: apri una
[issue](https://github.com/advers1ty-it/orchestra/issues). Se riguarda la
sicurezza o un dato che non doveva uscire, scrivilo nel titolo: è la prima
cosa che verrà letta. Non c'è un supporto garantito — questo è un progetto
gratuito portato avanti nel tempo libero.
