# v0.5.89 — Telegram: la formattazione arriva, il ragionamento si può accendere

## Cosa si vedeva

Le risposte su Telegram arrivavano piene di segni: `### 1. Controlla i
programmi`, `**Ctrl + Maiusc + Esc**`. Non erano errori del modello: il
markdown è il formato in cui scrive, e Telegram non lo interpreta se non
glielo si dichiara. Noi non lo dichiaravamo.

E il ragionamento dell'agente restava fuori dalla chat: in un turno strano è
proprio quello che spiega perché è andata così, ma mandarlo sempre
riempirebbe il telefono.

## Cosa c'è ora

- **Il markdown diventa HTML di Telegram.** Grassetto, corsivo, titoli (i `#`
  spariscono), elenchi con il punto, codice in linea e blocchi di codice,
  link, barrato, righe di separazione. Dentro un blocco di codice non si
  converte niente: `a ** b` resta com'è scritto.
- **Se Telegram rifiuta l'HTML** (un tag che non conosce, 400) il testo parte
  lo stesso, senza formattazione. Una risposta brutta è meglio di una persa.
- **`/reasoning`** (o **`/ragionamento`**) accende e spegne il ragionamento
  per quel bot. Senza argomento fa da interruttore; `on`/`off` dicono lo
  stato voluto. La scelta resta scritta nella configurazione del bot.
  Acceso: il pensiero compare nello stato mentre lavora e arriva come
  messaggio suo a fine turno, prima della risposta.

## Verifiche

`test_telegram.py` 161 check (12 nuovi: dieci conversioni di markdown, il
ripiego senza formattazione, l'interruttore e la sua persistenza),
`test_telegram_sessione.py` 149 (7 nuovi: comando dalla chat, stato con e
senza ragionamento, e il 400 che fa un solo ripiego invece di tre
ritentativi). Tutti verdi.

Riavvia Orchestra: il ponte riparte col codice nuovo.
