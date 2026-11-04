# Trasparenza

Orchestra è un assistente di intelligenza artificiale. Questo file dice,
in italiano semplice, cosa significa per chi lo usa: cosa fa, cosa esce
dalla tua macchina, cosa non devi aspettarti.

## Stai parlando con un'IA

- Le risposte, il codice e i testi che leggi sono **generati da un
  modello**, non scritti da una persona. Possono essere sbagliati, e a
  volte lo sono con sicurezza.
- L'avviso «assistente IA» è nella barra in alto, sempre visibile.
- Puoi sempre vedere e disfare: `Δ` mostra cosa è cambiato nei file in
  questo turno, `↶` annulla l'ultima modifica. Il pulsante di stop
  interrompe il lavoro in corso.

## Cosa esce dalla tua macchina

Orchestra non ha un server suo, non ha account, non manda telemetria: non
esiste un «noi» che riceve i tuoi dati.

Quello che **viene inviato** è solo ciò che serve al modello per
rispondere, e va al provider che hai scelto in Opzioni:

- il testo che scrivi e il prompt di sistema;
- il contenuto dei file che l'agente legge per lavorare;
- gli screenshot, quando usa il browser;
- le immagini di riferimento, quando ne modifica una.

Vale l'informativa di quel provider: è lui che tratta quei dati. Le
chiavi API restano nel tuo `orchestra/.env`, lo storico dei turni nel
tuo `storico.db` — sono file tuoi, sulla tua macchina, e puoi cancellarli
quando vuoi. Se preferisci non far uscire niente, puoi usare un motore
locale (Ollama o simile) e quei dati non lasciano il computer.

## Le immagini generate sono dichiarate

Ogni immagine prodotta da Orchestra è marcata come contenuto sintetico:
un metadato dentro i PNG e un file `<nome>.ai.json` accanto
all'immagine, con generatore, provider, modello e data.

La marcatura è un metadato, non una filigrana: una ricodifica può
toglierla dal file. Il `.ai.json` resta finché resta il file.

## A cosa non serve

Orchestra scrive codice, non decide sulle persone. Non usarlo per:

- selezione, valutazione o licenziamento del personale;
- ammissioni scolastiche o universitarie, valutazioni d'esame;
- credito, assicurazioni, mutui;
- diagnosi, terapia, decisioni sanitarie;
- qualunque decisione che produca effetti giuridici su una persona.

Non è un prodotto certificato e non garantisce un risultato: è software
gratuito, scritto da una persona. Il codice che genera va letto e provato
prima di finire in produzione — come tutto il codice generato.

## Se qualcosa non va

Le segnalazioni si aprono come issue sul repository GitHub del progetto.
Se il problema riguarda la sicurezza o un dato che non doveva uscire,
scrivilo nel titolo della issue: è la prima cosa che verrà letta.
