"""Le skill che nascono dal lavoro, invece di aspettare che qualcuno le chieda.

Il problema che risolve. `skill_genera` esisteva, funzionava, rifiutava le
procedure senza prove — e non lo chiamava mai nessuno. Non il modello di
sua iniziativa (niente nel prompt glielo chiedeva), non il sistema dopo
un turno riuscito. Risultato: 159 skill in `skills/`, zero in
`skills/generate/`, e un'interfaccia che prometteva «lavora con lui e
guarda qui dopo».

Qui il grilletto. Dopo un turno che e' finito bene, si guarda cosa e'
stato eseguito davvero (gli eventi `tool_start`/`tool_end` della traccia,
accoppiati per id, tenendo solo quelli con esito ok). Se la stessa
sequenza di comandi torna, si conta. Alla terza volta non si scrive una
skill: si scrive una PROPOSTA, con le tre occorrenze come prove, e la si
mostra nel pannello Capacita' (tab Skill) con due pulsanti. Il modello non decide cosa
entra nel suo prompt; l'utente si'.

Perche' contare e non scrivere subito: una procedura eseguita una volta
puo' essere un colpo di fortuna — la cartella era vuota, il file c'era
gia', la rete e' andata bene. Tre volte e' una procedura. E' la stessa
soglia che `skills.py` dichiarava e che nessuno applicava.

Perche' i soli comandi e non tutti i tool: `write_file` e `edit_file`
portano il contenuto nella firma, quindi due turni che scrivono lo stesso
file con due testi diversi sarebbero due procedure diverse — e non lo
sono. I comandi sono l'unica cosa che si ripete identica e che qualcun
altro puo' rieseguire.

Perche' non costa un token: la proposta si costruisce dai fatti della
traccia. Nessuna chiamata al provider per indovinare cosa abbiamo
imparato, quindi nessun costo per turno e nessuna invenzione.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from . import skills as sk

# I tool che diventano una procedura. Sono quelli il cui argomento e' un
# comando da rieseguire: gli altri producono testo, non passi.
TOOL_PROCEDURA = {"run_shell": "command", "run_tests": "comando"}

_FILE = "apprendimento.json"
_LOCK = threading.Lock()


def _percorso() -> str:
    """Dove si tiene il conto, nella cartella dati dell'installazione.

    Non nella radice delle skill: quel file non e' una skill, e un
    `apprendimento.json` in mezzo a `skills/` finirebbe nel repository di
    chi usa Orchestra come checkout — un file di stato che cambia a ogni
    turno e che nessuno vuole committare.
    """
    from .dati import cartella_dati
    return os.path.join(cartella_dati(), _FILE)


def leggi() -> dict[str, Any]:
    try:
        with open(_percorso(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"firme": {}}
    if not isinstance(d, dict) or not isinstance(d.get("firme"), dict):
        return {"firme": {}}
    return d


def _scrivi(d: dict[str, Any]) -> None:
    """Scrittura atomica: un crash a meta' non deve azzerare i conteggi.

    Con un file troncato si ricomincerebbe da zero, quindi una procedura
    ripetuta tre volte non arriverebbe mai alla terza. E' lo stesso
    difetto delle scritture non atomiche, su un file che nessuno guarda.
    """
    p = _percorso()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


# --------------------------------------------------------------------------
# Dalla traccia ai comandi
# --------------------------------------------------------------------------


def _normalizza(comando: str) -> str:
    # Gli spazi interni non cambiano il comando, e una riga spezzata in
    # due modi diversi non deve contare come due procedure.
    return re.sub(r"\s+", " ", str(comando or "")).strip()


def comandi_da_eventi(eventi: list[dict[str, Any]]) -> list[str]:
    """I comandi eseguiti CON SUCCESSO, nell'ordine, da una traccia.

    `tool_start` e `tool_end` si accoppiano per `id`: un turno puo'
    chiamare due volte lo stesso tool, e abbinarli per nome
    attribuirebbe il successo di uno al fallimento dell'altro. Senza
    `id` (tracce vecchie) si ripiega sull'ordine, che e' l'unica cosa
    che resta.
    """
    avviati: dict[str, dict[str, Any]] = {}
    per_nome: dict[str, list[dict[str, Any]]] = {}
    comandi: list[str] = []
    for e in eventi or []:
        tipo = e.get("tipo")
        dati = e.get("dati") or {}
        if tipo == "tool_start":
            chiave = str(dati.get("id") or "")
            if chiave:
                avviati[chiave] = dati
            else:
                per_nome.setdefault(str(dati.get("name") or ""), []).append(dati)
            continue
        if tipo != "tool_end":
            continue
        nome = str(dati.get("name") or "")
        if not dati.get("ok"):
            continue
        campo = TOOL_PROCEDURA.get(nome)
        if not campo:
            continue
        chiave = str(dati.get("id") or "")
        avvio = avviati.pop(chiave, None) if chiave else None
        if avvio is None:
            coda = per_nome.get(nome) or []
            avvio = coda.pop(0) if coda else {}
        args = avvio.get("args") or {}
        valore = args.get(campo) if isinstance(args, dict) else ""
        comando = _normalizza(valore)
        if comando:
            comandi.append(comando)
    return comandi


def firma(comandi: list[str]) -> str:
    """Un'identita' stabile per una sequenza di comandi.

    Normalizza qui e non solo in `comandi_da_eventi`: la firma e' la
    chiave del conto, e un chiamante che passa i comandi senza
    normalizzarli creerebbe una seconda procedura per lo stesso lavoro.
    """
    testo = "\n".join(_normalizza(c) for c in comandi)
    return hashlib.sha256(testo.encode("utf-8", "surrogateescape")).hexdigest()[:16]


_SPORCO = re.compile(r"[^a-z0-9]+")


def nome_da_comandi(comandi: list[str]) -> str:
    """Un nome corto e leggibile, ricavato dal primo comando.

    `npm run build` diventa `npm-run-build`: chi guarda la lista deve
    poter dire di cosa si tratta senza aprire la procedura.
    """
    primo = comandi[0] if comandi else ""
    base = _SPORCO.sub("-", primo.lower()).strip("-")
    base = "-".join(base.split("-")[:4]) or "procedura"
    return base[:40]


def descrizione_da_comandi(comandi: list[str], volte: int) -> str:
    elenco = ", ".join(comandi[:3])
    if len(comandi) > 3:
        elenco += f" e altri {len(comandi) - 3}"
    return (f"Sequenza che ha funzionato {volte} volte: {elenco}.")


def _corpo(comandi: list[str], obiettivo: str, volte: int) -> str:
    passi = "\n".join(f"{i}. `{c}`" for i, c in enumerate(comandi, 1))
    quando = obiettivo.strip() or "un compito simile a quello che l'ha prodotta"
    return (
        f"# {nome_da_comandi(comandi)}\n\n"
        f"Procedura ricavata da un turno riuscito e ripetuta {volte} volte.\n\n"
        f"## Quando serve\n{quando}\n\n"
        f"## Passi\n{passi}\n\n"
        "## Note\n"
        "I comandi sono quelli eseguiti davvero, con esito positivo. Se nel "
        "progetto cambiano gli script o le cartelle, questa procedura va "
        "aggiornata o cancellata: ripeterla alla lettera su un progetto "
        "diverso non funziona.\n"
    )


@dataclass
class Proposta:
    """Una procedura che ha raggiunto la soglia, pronta da mostrare."""

    firma: str
    nome: str
    descrizione: str
    corpo: str
    comandi: list[str] = field(default_factory=list)
    prove: list[dict[str, Any]] = field(default_factory=list)
    volte: int = 0


def _proposta_da(voce: dict[str, Any], firma_: str) -> Proposta:
    comandi = [c for c in (voce.get("comandi") or []) if isinstance(c, str)]
    obiettivo = str(voce.get("obiettivo") or "")
    volte = int(voce.get("volte") or 0)
    prove = [p for p in (voce.get("prove") or []) if isinstance(p, dict)]
    if not prove:
        # Senza le occorrenze non c'e' prova, e una skill senza prove e'
        # un'affermazione. Si ricostruisce quella corrente: e' vera, e
        # dice quando e' stata vista.
        prove = [{
            "ts": time.time(),
            "obiettivo": obiettivo,
            "comandi": comandi,
            "esito": "riuscita",
        }]
    return Proposta(
        firma=firma_,
        nome=nome_da_comandi(comandi),
        descrizione=descrizione_da_comandi(comandi, volte),
        corpo=_corpo(comandi, obiettivo, volte),
        comandi=comandi,
        prove=prove,
        volte=volte,
    )


def osserva(eventi: list[dict[str, Any]], obiettivo: str = "",
            soglia: int | None = None) -> Proposta | None:
    """Registra i comandi di un turno riuscito; alla soglia, la proposta.

    Torna `None` quasi sempre: e' il caso normale. Un turno senza comandi
    (una domanda, una lettura) non insegna niente, e un comando eseguito
    una volta non e' una procedura. Contare e tacere e' la parte
    importante: il rumore nel prompt si paga a ogni messaggio.
    """
    soglia = int(sk.SOGLIA_RIPETIZIONI if soglia is None else soglia)
    comandi = comandi_da_eventi(eventi)
    if not comandi:
        return None
    f = firma(comandi)
    with _LOCK:
        stato = leggi()
        firme = stato.setdefault("firme", {})
        voce = firme.get(f)
        if not isinstance(voce, dict):
            voce = {"volte": 0, "comandi": comandi, "prove": []}
            firme[f] = voce
        if voce.get("proposto"):
            # Gia' proposta (o accettata, o scartata): non si ripropone.
            # Insistere su una cosa che l'utente ha gia' visto e' il modo
            # piu' rapido per fargli ignorare le proposte successive.
            return None
        voce["comandi"] = comandi
        voce["volte"] = int(voce.get("volte") or 0) + 1
        voce["obiettivo"] = (obiettivo or "").strip()[:400]
        prove = voce.setdefault("prove", [])
        if isinstance(prove, list):
            prove.append({
                "ts": time.time(),
                "obiettivo": voce["obiettivo"],
                "comandi": comandi,
                "esito": "riuscita",
            })
            # Il conto e le prove non devono crescere senza fine: una
            # procedura ripetuta cento volte non ha bisogno di cento
            # righe per convincere qualcuno.
            voce["prove"] = prove[-max(soglia, 3):]
        voce["visto_il"] = time.time()
        if voce["volte"] < soglia:
            _scrivi(stato)
            return None
        proposta = _proposta_da(voce, f)
        voce["proposto"] = proposta.nome
        _scrivi(stato)
        return proposta


def proponi(indice: sk.Indice, p: Proposta) -> str:
    """Scrive la proposta su disco. Non entra nel prompt finche' non e' accettata."""
    c = sk.Candidato(nome=p.nome, descrizione=p.descrizione, corpo=p.corpo,
                     prove=p.prove)
    return sk.salva_generata(indice, c, stato=sk.STATO_PROPOSTA,
                             firma=p.firma)


def segna_conclusa(firma_: str, *, nome: str, accettata: bool) -> None:
    """Ricorda che questa procedura e' stata proposta, e com'e' finita.

    Serve a non riproporla ogni tre turni. Il conto resta, cosi' si puo'
    vedere che una procedura continua a funzionare anche dopo che la
    skill e' stata confermata: e' l'unico modo per sapere se una skill
    serve ancora.
    """
    if not firma_:
        return
    with _LOCK:
        stato = leggi()
        voce = (stato.get("firme") or {}).get(firma_)
        if not isinstance(voce, dict):
            return
        voce["proposto"] = nome
        voce["accettata"] = bool(accettata)
        voce["conclusa_il"] = time.time()
        _scrivi(stato)
