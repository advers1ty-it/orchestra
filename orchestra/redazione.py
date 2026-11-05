"""Redazione dei segreti prima che finiscano su disco o sullo schermo.

`.env` e `.ssh` sono gia' chiusi in lettura (`tools/_guard.py`), ma la
shell e' legittimamente aperta: `echo $OPENAI_API_KEY`, `env`, un test
che stampa la configurazione, un `curl -v` con l'header di
autorizzazione. Quell'output oggi viene salvato verbatim nello storico
(SQLite, con indice full-text), nella traccia e nella UI: una chiave
detta una volta resta sul disco per sempre, e nello storico e' anche
cercabile.

Qui non si prova a indovinare cos'e' un segreto: si riconoscono i
formati che hanno una firma (i prefissi dei provider, le chiavi PEM, i
token di autorizzazione) e le assegnazioni del tipo `API_KEY=...`.
Tutto il resto passa intatto — un redattore troppo zelante rende
illeggibili i log e le persone lo spengono, che e' peggio di non
averlo.

Non e' una difesa contro chi ha gia' accesso al processo: e' igiene,
perche' un segreto in un file di storico e' un segreto in un backup, in
un allegato, in uno screenshot.
"""

from __future__ import annotations

import re
from typing import Any

# Il segnaposto dice CHE COSA e' stato tolto ma non quanto era lungo:
# la lunghezza e' un'informazione che serve a chi prova a ricostruire la
# chiave, non a chi legge il log.
SEGNAPOSTO = "[redatto]"


def _con_nome(nome: str) -> str:
    return f"[redatto:{nome}]"


# Formati con una firma riconoscibile. L'ordine conta: `sk-ant-` prima di
# `sk-`, o il generico mangerebbe il nome specifico.
_FIRME: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "anthropic-key"),
    (re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{20,}"), "openai-project-key"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "openai-key"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), "github-token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "github-pat"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"), "slack-token"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "google-key"),
    (re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}"), "nvidia-key"),
    (re.compile(r"\b(?:hsk|nebius)-[A-Za-z0-9_\-]{20,}"), "api-key"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
     "jwt"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}", re.IGNORECASE),
     "bearer-token"),
)

# Chiavi private: il blocco intero, non solo l'intestazione. Una chiave
# privata a meta' non e' meno utile a chi la legge.
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)

# `NOME=valore` e `NOME: valore`, per i nomi che di solito portano un
# segreto. Il valore e' catturato solo se sembra un valore e non una
# frase: almeno 16 caratteri senza spazi, o dentro virgolette.
_ASSEGNAZIONE = re.compile(
    r"""(?ix)
    \b(
        [A-Z0-9_]*
        (?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE[_-]?KEY
           |ACCESS[_-]?KEY|CLIENT[_-]?SECRET|AUTH[_-]?TOKEN|COOKIE)
        [A-Z0-9_]*
    )
    (\s*[=:]\s*)
    (?:
        "([^"\n]{8,})"
      | '([^'\n]{8,})'
      | ([^\s"',;]{16,})
    )
    """,
)


def redigi(testo: str) -> str:
    """Il testo con i segreti riconoscibili sostituiti. Idempotente."""
    if not testo:
        return testo
    fuori = _PEM.sub(_con_nome("private-key"), testo)
    for schema, nome in _FIRME:
        fuori = schema.sub(_con_nome(nome), fuori)

    def sostituisci(m: re.Match[str]) -> str:
        nome = m.group(1).upper()
        sep = m.group(2)
        valore = m.group(3) or m.group(4) or m.group(5) or ""
        # Un valore gia' redatto non si ri-redige: il doppio passaggio
        # (output del tool, poi salvataggio) e' normale, e
        # `[redatto:x]` non deve diventare `[redatto:[redatto:x]]`.
        if SEGNAPOSTO in valore:
            return m.group(0)
        return f"{m.group(1)}{sep}{SEGNAPOSTO}"

    return _ASSEGNAZIONE.sub(sostituisci, fuori)


def redigi_dati(dati: Any) -> Any:
    """Come `redigi`, ma su strutture: dict, liste, scalari.

    Serve per gli eventi di traccia, che sono JSON annidati: redigere
    solo le stringhe di primo livello lascerebbe passare `{"args":
    {"env": "..."}}`, che e' esattamente dove finiscono le chiavi.
    """
    if isinstance(dati, str):
        return redigi(dati)
    if isinstance(dati, dict):
        return {k: redigi_dati(v) for k, v in dati.items()}
    if isinstance(dati, (list, tuple)):
        return [redigi_dati(v) for v in dati]
    return dati
