"""400 tool_call_id: deve riprovare, non saltare al fallback.

Il difetto: un 400 con "Missing required parameter: tool_call_id" non è in
RETRYABLE_STATUS e non fa scattare should_fallback. Quindi il turno si
interrompe e non si riprende finché non si riavvia il server.

Questo test fallisce col codice attuale (bug) e passa dopo il fix.
"""
from orchestra.providers import ProviderError, RETRYABLE_STATUS
from orchestra.fallback import should_fallback, FallbackReason


def test_400_tool_call_id_non_e_un_fallback():
    """Un 400 su tool_call_id NON deve far saltare al prossimo provider.

    Dopo il fix, should_fallback deve ritornare un FallbackReason diverso
    da UNAVAILABLE (es. TRANSIENT) così il codice sa di poter riprovare
    la stessa conversazione invece di abbandonarla.
    """
    e = ProviderError(
        "nous: HTTP 400 — Missing required parameter: 'messages[968].tool_call_id'",
        status=400,
    )
    fb = should_fallback(e)
    assert fb is not None, (
        f"atteso un fallback (perche' il codice puo' riprovare), trovato None"
    )
    assert fb != FallbackReason.UNAVAILABLE, (
        f"non deve saltare al prossimo provider, ma ritentare: trovato {fb}"
    )


def test_400_tool_call_id_e_riproducibile():
    """Lo stesso errore su un altro messaggio è riconosciuto."""
    e = ProviderError(
        "nous: HTTP 400 — Missing required parameter: 'messages[12].tool_call_id'",
        status=400,
    )
    fb = should_fallback(e)
    assert fb is not None
    assert fb != FallbackReason.UNAVAILABLE


def test_400_altro_e_fallback():
    """Un 400 su modello non trovato fa scattare il fallback (comportamento esistente)."""
    e = ProviderError(
        "nous: HTTP 400 — model not found",
        status=400,
    )
    assert should_fallback(e) == FallbackReason.UNAVAILABLE