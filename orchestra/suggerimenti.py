"""I pulsanti di fine turno: le mosse che servono adesso, gia' scritte.

PERCHE' ESISTE

A turno finito si fa quasi sempre una di quattro cose: controllare di non
avere rotto qualcosa, rileggere le proprie modifiche, committare, oppure
decidere cosa fare dopo. Sono frasi che si riscrivono ogni volta, e quella
che servirebbe davvero — "quali test coprono i file che ho appena toccato?"
— viene in mente quando non serve piu'.

Qui non c'e' nessun modello e nessuna chiamata: le proposte si ricavano da
quello che il turno ha lasciato — i file del riepilogo, i test che portano
il loro nome, il git del progetto. Un pulsante che promette "controlla di
non avere rotto niente" e poi incolla un prompt generico sarebbe peggio di
nessun pulsante: sembrerebbe che qualcuno abbia guardato, e non e' vero.

Il prompt si scrive per intero. Premere il pulsante COMPILA il campo, non
manda niente: l'ultima parola resta a chi preme, che puo' correggere prima
di inviare.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Callable

# Quattro pulsanti: oltre, la scelta non e' piu' una scelta. E quattro file
# nominati per esteso: un prompt che elenca quaranta percorsi non si legge,
# e quindi non si corregge prima di mandarlo.
MASSIMO = 4
NOMINATI = 4


def _file(rie: dict[str, Any]) -> list[dict[str, Any]]:
    """I file del turno, tenendo solo le voci che si possono nominare."""
    return [f for f in (rie or {}).get("file") or []
            if isinstance(f, dict) and f.get("percorso")]


def _elenco(files: list[dict[str, Any]], massimo: int = NOMINATI) -> str:
    """I file con le righe cambiate, e quanti restano fuori."""
    pezzi = []
    for f in files[:massimo]:
        percorso = str(f.get("percorso") or "?")
        aggunte = int(f.get("aggiunte") or 0)
        tolte = int(f.get("tolte") or 0)
        pezzi.append(f"{percorso} (+{aggunte}/-{tolte})"
                     if (aggunte or tolte) else percorso)
    resto = len(files) - len(pezzi)
    if resto > 0:
        pezzi.append(f"e altri {resto}")
    return ", ".join(pezzi)


def test_per(percorso: str, radice: str) -> str:
    """Il comando del test che porta il nome di questo file, se c'e'.

    `orchestra/skills.py` -> `tests/test_skills.py`. Non si indovina oltre
    il nome: un test nominato per sbaglio fa eseguire la suite sbagliata, e
    un pulsante che sembra una verifica ma verifica altro e' peggio di uno
    che non c'e'.
    """
    if not radice:
        return ""
    nome = os.path.basename(str(percorso or "").replace("\\", "/"))
    if not nome.endswith(".py") or len(nome) <= 3:
        return ""
    base = nome[:-3]
    if not base.startswith("test_"):
        base = "test_" + base
    if os.path.isfile(os.path.join(radice, "tests", base + ".py")):
        return f"python tests/{base}.py"
    return ""


def sporchi(radice: str) -> list[str]:
    """I file non committati del progetto, o [] se non e' un repo git.

    Letto, non eseguito: `git status --porcelain` non tocca niente. Se git
    non c'e' o la cartella non e' un repository si torna vuoto, e la
    proposta del commit sparisce — meglio nessun pulsante che uno che
    fallisce quando lo premi.
    """
    if not radice or not os.path.isdir(radice):
        return []
    try:
        esito = subprocess.run(
            ["git", "-C", radice, "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    if esito.returncode != 0:
        return []
    file: list[str] = []
    for riga in (esito.stdout or "").splitlines():
        percorso = riga[3:].strip() if len(riga) > 3 else ""
        # Le rinomine arrivano come "vecchio -> nuovo": quello che conta
        # per un commit e' il nome che ha adesso.
        if " -> " in percorso:
            percorso = percorso.split(" -> ", 1)[1]
        percorso = percorso.strip().strip('"')
        if percorso:
            file.append(percorso)
    return file


def _verifica(rie: dict[str, Any], radice: str) -> dict[str, Any] | None:
    """Cosa puo' essersi rotto: i file del turno e i test che li coprono."""
    file = _file(rie)
    if not file:
        return None
    comandi: list[str] = []
    for f in file[:NOMINATI]:
        comando = test_per(str(f.get("percorso") or ""), radice)
        if comando and comando not in comandi:
            comandi.append(comando)
    if comandi:
        parte = ("I test che portano il loro nome sono "
                 + ", ".join(f"`{c}`" for c in comandi)
                 + ": eseguili, e `python tests/run_all.py` per il giro "
                   "intero. ")
    else:
        parte = ("Per questi file non c'e' un test che ne porta il nome: cerca "
                 "quali test li importano e, se non ce n'e' nessuno, dillo "
                 "invece di scriverne uno nuovo. ")

    esito = str((rie or {}).get("esito_testo") or "").strip()
    errori = int((rie or {}).get("errori") or 0)
    if errori:
        apertura = (f"Il turno si e' chiuso con {errori} errori di tool"
                    f"{' (' + esito + ')' if esito else ''}. ")
    elif esito and esito != "finito":
        apertura = f"Il turno si e' chiuso cosi': {esito}. "
    else:
        apertura = ""

    prompt = (
        f"Il turno appena finito ha toccato {len(file)} file: "
        f"{_elenco(file)}.\n\n"
        f"{apertura}Guardali uno per uno e cerca quello che si rompe senza "
        "fare rumore: chi chiama le funzioni cambiate, i rami nuovi che "
        "nessun test attraversa, i comportamenti cambiati per sbaglio. "
        + parte +
        "Alla fine dimmi cosa hai trovato, con file e riga. Non correggere "
        "niente finche' non te lo dico."
    )
    return {"id": "verifica", "titolo": "Controlla cosa puo' essersi rotto",
            "prompt": prompt}


def _revisione(rie: dict[str, Any], sporchi_: list[str]) -> dict[str, Any] | None:
    """La revisione critica di quello che c'e' sul tavolo."""
    file = _file(rie)
    if file:
        oggetto = f"le modifiche del turno ({_elenco(file)})"
    elif sporchi_:
        oggetto = f"le {len(sporchi_)} modifiche non committate"
    else:
        return None
    prompt = (
        f"Rileggi in modo critico {oggetto} — quelle soltanto, non tutto il "
        "progetto (guarda il diff, non riscrivere da capo). Semplifica: togli "
        "quello che non serve (codice morto, controlli ridondanti, parametri "
        "che nessuno passa, rami che non si verificano mai), accorpa cio' che "
        "dice la stessa cosa, e lascia il comportamento identico. Se qualcosa "
        "e' utile ma scritto male, sistemalo invece di cancellarlo. Alla fine "
        "elencami cosa hai tolto e perche', e cosa hai deciso di NON toccare."
    )
    return {"id": "revisione", "titolo": "Revisione di quello che ho toccato",
            "prompt": prompt}


def _commit(sporchi_: list[str]) -> dict[str, Any] | None:
    """Il commit, se c'e' qualcosa da committare."""
    if not sporchi_:
        return None
    elenco = ", ".join(sporchi_[:8])
    if len(sporchi_) > 8:
        elenco += f" e altri {len(sporchi_) - 8}"
    quanti = "un file" if len(sporchi_) == 1 else f"{len(sporchi_)} file"
    prompt = (
        f"Ci sono {quanti} con modifiche non committate: {elenco}.\n\n"
        "Fai commit di queste modifiche, con un messaggio che spiega perche' "
        "sono state fatte e non solo cosa e' cambiato: una o due frasi, "
        "specifiche, niente elenchi di file. Tieni fuori quello che non "
        "c'entra (archivi, file generati, roba non tracciata). Non pushare."
    )
    return {"id": "commit", "titolo": f"Commit di quello che c'e' ({quanti})",
            "prompt": prompt}


def _seguito(rie: dict[str, Any]) -> dict[str, Any]:
    """Cosa fare dopo: c'e' sempre, ed e' l'unica che non ha prerequisiti."""
    file = _file(rie)
    dopo = (f"dopo aver toccato {_elenco(file, 2)}" if file
            else "dopo questo scambio")
    prompt = (
        f"Cosa resta aperto {dopo}? Rileggi il lavoro fatto e proponi tre "
        "follow-up concreti, ognuno con il perche' e con quanto costa in "
        "tempo. Niente liste generiche: cose che si possono iniziare adesso, "
        "con il file o il modulo da cui partire, e dimmi quale faresti per "
        "prima."
    )
    return {"id": "seguito", "titolo": "Cosa resta aperto", "prompt": prompt}


def proposte(rie: dict[str, Any] | None = None, *,
             radice: str = "",
             stato_git: Callable[[], list[str]] | None = None,
             massimo: int = MASSIMO) -> list[dict[str, Any]]:
    """I pulsanti da mostrare a fine turno, dal piu' urgente al piu' aperto.

    `stato_git` esiste per i test: leggere il git vero renderebbe il test
    dipendente dal repository in cui gira. In produzione resta None e si
    legge `git status` della radice.
    """
    sporchi_ = list((stato_git or (lambda: sporchi(radice)))() or [])
    tutte = [_verifica(rie or {}, radice),
             _revisione(rie or {}, sporchi_),
             _commit(sporchi_),
             _seguito(rie or {})]
    return [p for p in tutte if p][:max(0, massimo)]
