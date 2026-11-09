# v0.5.87 — 1K, 2K, 4K: poster da stampa, non da anteprima

## Cosa cambiava

I modelli Google accettano un livello di risoluzione (`1K`, `2K`, `4K`), e noi
mandavamo solo il rapporto d'aspetto. Un poster generato a 1K si guarda bene a
schermo e si stampa sfocato: il livello è la differenza fra un'anteprima e un
file da tipografia.

## Cosa c'è ora

- `image_gen` ha il parametro `risoluzione`: `512`, `1K`, `1.5K`, `2K`, `4K`.
- Google: arriva come `imageConfig.imageSize`, accanto al rapporto d'aspetto
  (`aspectRatio`). Google non conosce `512`: chiederglielo è un errore
  esplicito, non un livello ignorato.
- OpenRouter: arriva come `resolution`. Non tutti i modelli del catalogo lo
  dichiarano, e chi non lo accetta rifiuta la richiesta nominando il
  parametro.
- OpenAI non ha livelli: chiedergliene uno dice di usare `dimensione`
  (1024x1024, 1536x1024, 1024x1536) e **non parte nessuna richiesta** — una
  generazione rifiutata si paga lo stesso.
- Un livello inventato (`8K`, `enorme`) elenca quelli veri invece di finire
  in una richiesta che il provider butterebbe via.

## Nota

Le suite `image_gen` (160 check), `image_edit` (50) e `inpainting` (42)
passano. Il livello più alto costa più credito: è la ragione per cui resta
una scelta esplicita e non un default.
