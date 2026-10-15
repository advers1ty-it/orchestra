"""Gate di accettazione per i lavori autonomi.

Il problema che chiude: prima `run_goal` marcava `done` quasi ogni stato
terminale tranne verifica/cancel — anche `max_iterations`,
`troppi_errori_consecutivi`, `budget_exceeded`. Un lavoro interrotto veniva
archiviato come completato.

Qui la regola e' esplicita e senza giudice LLM:

- `risposta_finale` + output non vuoto -> ok (poi valgono eventuali criteri).
- stop anomalo -> fallito, salvo `consenti_parziale=True`.
- criteri dichiarativi (file/output) -> falliscono chiusi, senza eccezioni.

Niente rete, niente provider, niente esecuzione di comandi: i criteri
possono leggere file e output, non lanciare processi. Un gate che esegue
comandi arbitrari sarebbe un secondo `run_shell` senza permessi.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EsitoAccettazione:
    ok: bool
    motivo: str = ""
    dettagli: dict[str, Any] = field(default_factory=dict)


def _testo_finale(stato: Any) -> str:
    messaggi = getattr(stato, "messages", None) or []
    for m in reversed(messaggi):
        if getattr(m, "role", "") == "assistant":
            return (getattr(m, "content", "") or "").strip()
    return ""


def valuta_fine_base(stato: Any, *, consenti_parziale: bool = False) -> EsitoAccettazione:
    """Controllo minimo sulla chiusura del loop agentico."""
    if stato is None:
        return EsitoAccettazione(False, "stato mancante")
    fermo = getattr(stato, "stopped_because", "") or ""
    if fermo == "risposta_finale":
        testo = _testo_finale(stato)
        if not testo:
            return EsitoAccettazione(False, "risposta finale vuota")
        return EsitoAccettazione(True, "risposta finale presente")
    if not fermo:
        return EsitoAccettazione(False, "motivo di stop mancante")
    if consenti_parziale:
        return EsitoAccettazione(
            True,
            f"parziale accettato dopo stop anomalo: {fermo}",
            {"stop_anomalo": fermo},
        )
    return EsitoAccettazione(False, f"stop anomalo: {fermo}")


def _radice_assoluta(radice: str | None) -> str:
    base = radice or os.getcwd()
    return os.path.abspath(base)


def _percorso_sicuro(radice_ass: str, percorso: str) -> str:
    if not isinstance(percorso, str) or not percorso.strip():
        raise ValueError("percorso mancante")
    p = percorso.strip()
    if os.path.isabs(p):
        raise ValueError("percorsi assoluti non ammessi nei criteri")
    ass = os.path.abspath(os.path.join(radice_ass, p))
    if os.path.commonpath([radice_ass, ass]) != radice_ass:
        raise ValueError("percorso fuori dalla radice dei criteri")
    return ass


def valuta_criteri(
    criteri: list[dict[str, Any]] | None,
    *,
    radice: str | None = None,
    output: str = "",
) -> EsitoAccettazione:
    """Valuta criteri dichiarativi serializzabili in JSON.

    Tipi supportati:
    - output_non_vuoto
    - output_min_chars {n}
    - output_contiene {testo}
    - file_esiste {percorso}
    - file_non_vuoto {percorso}
    - file_contiene {percorso, testo}
    """
    if not criteri:
        return EsitoAccettazione(True, "nessun criterio")
    if not isinstance(criteri, list):
        return EsitoAccettazione(False, "criteri non in lista")
    radice_ass = _radice_assoluta(radice)
    testo_output = output or ""
    for i, c in enumerate(criteri):
        if not isinstance(c, dict):
            return EsitoAccettazione(False, f"criterio {i} non valido")
        tipo = c.get("tipo")
        try:
            if tipo == "output_non_vuoto":
                if not testo_output.strip():
                    return EsitoAccettazione(False, f"criterio {i}: output vuoto")
            elif tipo == "output_min_chars":
                n = int(c.get("n", 0))
                if len(testo_output.strip()) < n:
                    return EsitoAccettazione(
                        False, f"criterio {i}: output sotto {n} caratteri"
                    )
            elif tipo == "output_contiene":
                testo = str(c.get("testo", ""))
                if not testo:
                    return EsitoAccettazione(False, f"criterio {i}: testo mancante")
                if testo not in testo_output:
                    return EsitoAccettazione(False, f"criterio {i}: testo non trovato")
            elif tipo in ("file_esiste", "file_non_vuoto", "file_contiene"):
                path = _percorso_sicuro(radice_ass, str(c.get("percorso", "")))
                if not os.path.isfile(path):
                    return EsitoAccettazione(False, f"criterio {i}: file mancante")
                if tipo == "file_non_vuoto" and os.path.getsize(path) == 0:
                    return EsitoAccettazione(False, f"criterio {i}: file vuoto")
                if tipo == "file_contiene":
                    testo = str(c.get("testo", ""))
                    if not testo:
                        return EsitoAccettazione(False, f"criterio {i}: testo mancante")
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        contenuto = fh.read()
                    if testo not in contenuto:
                        return EsitoAccettazione(
                            False, f"criterio {i}: testo non nel file"
                        )
            else:
                return EsitoAccettazione(False, f"criterio {i}: tipo sconosciuto")
        except (OSError, ValueError) as e:
            return EsitoAccettazione(False, f"criterio {i}: {e}")
    return EsitoAccettazione(True, "criteri superati")


def valuta_goal(
    stato: Any,
    *,
    consenti_parziale: bool = False,
    criteri: list[dict[str, Any]] | None = None,
    radice: str | None = None,
) -> EsitoAccettazione:
    base = valuta_fine_base(stato, consenti_parziale=consenti_parziale)
    if not base.ok:
        return base
    testo = _testo_finale(stato)
    criteri_esito = valuta_criteri(criteri, radice=radice, output=testo)
    if not criteri_esito.ok:
        return criteri_esito
    if base.dettagli.get("stop_anomalo"):
        return EsitoAccettazione(True, base.motivo, base.dettagli)
    return EsitoAccettazione(True, "goal accettato")
