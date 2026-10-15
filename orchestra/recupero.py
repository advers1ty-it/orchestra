"""Recovery esplicito per la delega: riprova, cambia modello, restringi.

Il `Delegatore` di base non riprova mai: un figlio fallito torna un `Figlio`
con esito diverso da `risposto` e il padre decide. Qui si aggiunge una
politica opzionale, senza cambiare il default: `max_retry=0` significa
"nessun retry", come prima.

Regole:

- si riprova solo su fallimento del lavoro, mai sui tetti strutturali
  (profondita' massima, troppi figli): riprovare un "no" strutturale
  consumerebbe figli senza poter riuscire.
- i modelli alternativi si usano in ordine, un tentativo ciascuno;
  se finiscono, gli eventuali retry restanti riusano l'ultimo.
- con `accorcia_contesto=True`, al retry non si rimanda tutta la storia:
  si passa il motivo del fallimento + l'ultimo output utile troncato.
- ogni tentativo resta in `Delegatore.storia`: il retry non nasconde
  il costo dei tentativi falliti.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PoliticaRecupero:
    max_retry: int = 0
    modelli_alternativi: list[str] = field(default_factory=list)
    accorcia_contesto: bool = False
    max_contesto_chars: int = 2000

    def normalizzata(self) -> "PoliticaRecupero":
        try:
            retry = max(0, int(self.max_retry or 0))
        except (TypeError, ValueError):
            retry = 0
        modelli = [str(m).strip() for m in (self.modelli_alternativi or [])]
        modelli = [m for m in modelli if m]
        try:
            tetto = max(200, int(self.max_contesto_chars or 2000))
        except (TypeError, ValueError):
            tetto = 2000
        return PoliticaRecupero(
            max_retry=retry,
            modelli_alternativi=modelli,
            accorcia_contesto=bool(self.accorcia_contesto),
            max_contesto_chars=tetto,
        )


def _tetto_strutturale(figlio: Any) -> bool:
    motivo = str(getattr(figlio, "motivo", "") or "")
    return ("profondità massima" in motivo) or ("troppi figli" in motivo)


def _contesto_retry(
    contesto: str, figlio: Any, tentativo: int, tetto: int
) -> str:
    pezzi = [f"[retry {tentativo} dopo esito {getattr(figlio, 'esito', '?')}]"]
    motivo = str(getattr(figlio, "motivo", "") or "").strip()
    if motivo:
        pezzi.append(f"motivo: {motivo}")
    ultimo = str(getattr(figlio, "testo", "") or "").strip()
    if ultimo:
        pezzi.append("ultimo output utile (troncato): " + ultimo[-500:])
    if contesto and contesto.strip():
        pezzi.append("contesto originale: " + contesto.strip())
    testo = "\n".join(pezzi)
    if len(testo) > tetto:
        testo = testo[-tetto:]
    return testo


def delega_con_recupero(
    delegatore: Any,
    obiettivo: str,
    contesto: str = "",
    *,
    policy: PoliticaRecupero | dict[str, Any] | None = None,
    imposta_modello: Callable[[str | None], None] | None = None,
) -> Any:
    """Esegue una delega con retry opzionale. Non solleva mai per il lavoro.

    Torna sempre l'ultimo `Figlio`: se un retry riesce, quello riuscito;
    altrimenti l'ultimo fallimento, con tutta la storia dei tentativi
    nel delegatore.
    """
    if isinstance(policy, dict):
        policy = PoliticaRecupero(
            max_retry=policy.get("max_retry", 0),
            modelli_alternativi=policy.get("modelli_alternativi", []),
            accorcia_contesto=policy.get("accorcia_contesto", False),
            max_contesto_chars=policy.get("max_contesto_chars", 2000),
        )
    policy = (policy or PoliticaRecupero()).normalizzata()

    precedente = None

    try:
        for tentativo in range(policy.max_retry + 1):
            modello = None
            if tentativo > 0 and policy.modelli_alternativi:
                idx = min(tentativo - 1, len(policy.modelli_alternativi) - 1)
                modello = policy.modelli_alternativi[idx]
                if imposta_modello is not None:
                    try:
                        imposta_modello(modello)
                    except Exception:
                        pass
            elif imposta_modello is not None and tentativo == 0:
                try:
                    imposta_modello(None)
                except Exception:
                    pass

            contesto_eff = contesto
            if tentativo > 0 and policy.accorcia_contesto and precedente is not None:
                contesto_eff = _contesto_retry(
                    contesto, precedente, tentativo, policy.max_contesto_chars
                )

            figlio = delegatore.delega(obiettivo, contesto_eff)
            if getattr(figlio, "esito", "") == "risposto":
                return figlio
            if _tetto_strutturale(figlio):
                return figlio
            precedente = figlio
        return precedente
    finally:
        # Il retry non deve lasciare un modello forzato per le deleghe
        # successive: l'hook torna a "nessuna forzatura".
        if imposta_modello is not None:
            try:
                imposta_modello(None)
            except Exception:
                pass
