"""Il tariffario: quanto costa davvero un token, per modello.

PERCHE' NON BASTAVA UNA FORMULA

Il budget moltiplicava i token per una costante unica
(`(prompt+completion)/1000*0.001`) per QUALUNQUE modello. Tre conseguenze,
tutte vere e tutte invisibili:

- un modello gratuito risultava a pagamento, e il tetto in dollari
  scattava su una spesa che non esisteva;
- un modello da $15 per milione risultava da $1, e il tetto non scattava
  mai dove serviva;
- la ripartizione "chi me l'ha fatta spendere" era rumore.

Il prezzo vero lo dichiara il provider nel catalogo. Qui si tiene una
copia in memoria, popolata quando il catalogo viene scaricato. Se un
modello non e' nel tariffario (provider non ancora interrogato, modello
nuovo) la funzione torna None: chi chiama decide, e la scelta onesta e'
dichiarare che il prezzo non si sa invece di inventarne uno.
"""

from __future__ import annotations

from typing import Any

# modello -> oggetto con `estimate_cost(prompt, completion)` (ModelInfo).
_PREZZI: dict[str, Any] = {}


def registra(info: Any) -> None:
    """Segna il prezzo di un modello. Chiamabile piu' volte (idempotente)."""
    mid = getattr(info, "id", "") or ""
    if not mid:
        return
    # Un prezzo a zero e' un fatto (free tier), non un'assenza: si registra
    # come gli altri. Distinguere "gratis" da "non lo so" e' esattamente
    # il punto di questo modulo.
    _PREZZI[str(mid)] = info


def registra_catalogo(modelli: Any) -> int:
    """Registra tutti i profili di un catalogo. Ritorna quanti ne ha visti.

    Accetta sia i `ModelProfile` (con `.info`) sia i `ModelInfo` nudi, perche'
    il catalogo e' passato in tutte e due le forme a seconda del punto.
    """
    n = 0
    for m in modelli or []:
        info = getattr(m, "info", m)
        if getattr(info, "id", ""):
            registra(info)
            n += 1
    return n


def costo(modello: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Costo in dollari, o None se il prezzo di quel modello non si sa."""
    info = _PREZZI.get(str(modello or ""))
    if info is None:
        return None
    try:
        return float(info.estimate_cost(int(prompt_tokens), int(completion_tokens)))
    except Exception:  # noqa: BLE001
        return None


def noto(modello: str) -> bool:
    return str(modello or "") in _PREZZI


def svuota() -> None:
    """Solo per i test: il tariffario e' uno stato di processo."""
    _PREZZI.clear()
