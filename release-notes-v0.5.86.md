# v0.5.86 — L'errore delle chiavi non mente più

## Cosa succedeva

Con OpenRouter configurato e funzionante, l'agente rispondeva "mancano le
chiavi API per generare immagini (OpenAI, Google, OpenRouter non
configurate)". Bastava che il modello forzasse `provider="openai"`: senza
`OPENAI_API_KEY` il tool diceva solo "manca OPENAI_API_KEY", e la risposta
all'utente diventava "mancano le chiavi", seguita dal consiglio di scontornare
a mano su Canva.

## Cosa cambia

- Chiedere un provider senza chiave ora dice **quale** manca e **quale c'è**:
  "manca OPENAI_API_KEY, la chiave di openai, che hai chiesto esplicitamente.
  Al momento c'è OPENROUTER_API_KEY (openrouter): richiama il tool senza
  `provider` e uso quella."
- La descrizione di `provider` dice di ometterlo: la scelta automatica usa il
  provider con la chiave configurata.
- `image_gen` rimanda a `image_edit` quando servono i pixel originali, invece
  di lasciare che il modello provi a ricomporre e chieda scontorni manuali.

## Nota

Nessuna chiave è stata cambiata o letta: il test usa una chiave finta. Le
suite `image_gen` (150 check), `image_edit` (50), `inpainting` (42) e
`documenti` (67) passano.
