"""Confrontare due modelli ripetendo gli stessi task.

Il problema che risolve: con 4-6 task per categoria non si distinguono
un 70 da un 84. Ma aggiungere venti task costa ore, e ripeterli costa
minuti. E la via economica funziona perche' i punteggi che si
somigliano sono rumore e quelli che differiscono sono segnale.

La regola che rende il confronto onesto: si guarda SOLO sui task che
discriminano, cioe' quelli dove almeno un modello sbaglia. Su un task
che tutti passano non c'e' informazione — e mescolarlo agli altri fa
solo salire la media di chi e' piu' vicino al muro, che non e' quello
che stai chiedendo.

E il numero che rende il tutto verificabile: QUANTI task discriminano.
Due modelli che differiscono su due task su quaranta non sono stati
confrontati: sono stati misurati in parte. Il risultato lo dice, e
dice anche quanto era solido: con una ripetizione sola la differenza
su un task puo' essere un colpo di sorte, e con cinque no.

Cosa NON fa, e va detto: non corregge un campione sbilanciato. Se un
modello e' stato misurato su tre task e l'altro su quaranta, non sono
confrontabili e nessuna media risolve — per quello c'e' il flag
`confrontabili` in punteggio.py.
"""

from collections import defaultdict
from typing import Any

# Quante ripetizioni servono perché una differenza su UN task sia
# credibile. Con una ripetizione, un modello che sbaglia un task una
# volta su una ha una probabilità non trascurabile di sbagliarlo anche
# se è capace: e allora il confronto misura il caso.
RIPETIZIONI_MINIME = 3

# Sotto quanti task discriminanti il confronto non vale niente e va
# detto. Non un numero magico: sotto sei task, due modelli che differiscono
# su due di loro non si distinguono da due che differiscono per caso.
DISCRIMINANTI_MINIMI = 6


def confronta(risultati: list, ripetizioni_attese: int = 1) -> dict[str, Any]:
    """Confronto modello per modello, ripetendo gli stessi task.

    `risultati` sono i RunResult di tutti i modelli insieme, come
    arrivano dal benchmark. Le ripetizioni sono piu' RunResult con lo
    stesso `task_id` e lo stesso `model`.
    """
    # 1) per modello e task: quante volte passato, quante tentato
    per_task: dict[tuple[str, str], list[bool]] = defaultdict(list)
    per_modello: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: defaultdict(list))
    for r in risultati:
        if getattr(r, "unusable", False):
            continue
        per_task[(r.model, r.task_id)].append(bool(r.passed))
        per_modello[r.model][r.task_id].append(bool(r.passed))

    modelli = sorted(per_modello)
    if len(modelli) < 2:
        return {"modelli": modelli, "classifica": [],
                "discriminanti": [], "confrontabile": False,
                # Le chiavi ci sono tutte anche quando non c'è niente da
                # confrontare: la tabella le legge senza controllare, e
                # un KeyError su un caso vuoto è un crash per chi vuole
                # solo stampare "non c'è niente".
                "motivo": "serve almeno due modelli",
                "ripetizioni": {}, "n_discriminanti": 0, "n_task": 0}

    # 2) i task che discriminano: dove almeno un modello sbaglia.
    #    Un task che tutti passano non porta informazione — contarlo
    #    fa solo alzare la media di chi e' piu' vicino al muro.
    discriminanti = []
    for task_id in sorted({t for _, t in per_task}):
        tassi = {}
        for m in modelli:
            prove = per_modello[m].get(task_id, [])
            if prove:
                tassi[m] = sum(prove) / len(prove)
        if len(tassi) < 2:
            continue
        if max(tassi.values()) - min(tassi.values()) > 1e-9:
            discriminanti.append({"task_id": task_id, "tassi": tassi,
                                  "prove": {m: len(per_modello[m][task_id])
                                            for m in tassi}})

    # 3) il confronto, sui soli task che separano
    classifica = []
    for m in modelli:
        passati = sum(d["tassi"].get(m, 0) for d in discriminanti)
        classifica.append({
            "modello": m,
            "su_discriminanti": passati,
            "discriminanti": len(discriminanti),
            "tasso": round(passati / len(discriminanti) * 100, 1)
            if discriminanti else 0.0,
            # i RUN, non i task distinti: col denominatore sui task e
            # il numeratore sui run la tabella mostrava 48/16
            "task_totali": len(per_modello[m]),
            "run_totali": sum(len(v) for v in per_modello[m].values()),
            "passati_su_tutti": sum(sum(v) for v in per_modello[m].values()),
            "tasso_su_tutti": round(
                sum(sum(v) for v in per_modello[m].values())
                / max(1, sum(len(v) for v in per_modello[m].values())) * 100, 1),
        })
    classifica.sort(key=lambda x: (-x["tasso"], -x["passati_su_tutti"]))

    # 4) quanto il confronto regge — e questo e' il numero che rende il
    #    resto onesto. Due modelli che differiscono su due task su
    #    quaranta non sono stati confrontati.
    stessi_task = len({
        frozenset(per_modello[m]) for m in modelli
    }) == 1
    ripetizioni = {m: min(
        (len(v) for v in per_modello[m].values() if v), default=0)
        for m in modelli}
    # il MINIMO e non il massimo: se un modello ha girato ogni task
    # cinque volte e l'altro una sola volta, la coppia piu' debole e'
    # quella che conta. Prendere il massimo dichiarerebbe convalidato
    # un confronto costruito sulla meta' dei dati.
    n_prove = min(ripetizioni.values()) if ripetizioni else 0

    problemi = []
    if not stessi_task:
        problemi.append("i modelli non sono stati misurati sugli stessi task")
    if len(discriminanti) < DISCRIMINANTI_MINIMI:
        problemi.append(
            f"solo {len(discriminanti)} task su cui i modelli differiscono: "
            f"la differenza non è distinguibile dal caso")
    if n_prove < RIPETIZIONI_MINIME:
        problemi.append(
            f"{n_prove} ripetizione/i per task: su un task la differenza "
            f"può essere un colpo di sorte")

    return {
        "modelli": modelli,
        "classifica": classifica,
        "discriminanti": discriminanti,
        "confrontabile": not problemi,
        "motivo": "; ".join(problemi),
        "ripetizioni": ripetizioni,
        "n_discriminanti": len(discriminanti),
        "n_task": len({t for _, t in per_task}),
    }


def tabella_confronto(esito: dict[str, Any]) -> str:
    """Il confronto in formato terminale, con l'avvertenza in testa.

    L'avvertenza sta SOPRA la classifica, non sotto: chi legge la
    prima riga e si ferma deve vedere che il confronto non regge prima
    di vedere chi ha vinto.
    """
    righe = []
    if not esito["confrontabile"]:
        righe.append("! CONFRONTO NON CONVALIDO: " + esito["motivo"])
        righe.append("")
    righe.append(f"task su cui i modelli differiscono: "
                 f"{esito['n_discriminanti']} su {esito['n_task']}")
    righe.append("")
    righe.append(f"{'modello':38} {'sui discriminanti':>18} {'su tutti i run':>16}")
    righe.append("-" * 70)
    for c in esito["classifica"]:
        nome = c["modello"][:38]
        righe.append(
            f"{nome:38} {c['su_discriminanti']:>8.1f}/{c['discriminanti']:<3} "
            f"{c['tasso']:>5.1f}% {c['passati_su_tutti']:>5}/"
            f"{c['run_totali']:<4} {c['tasso_su_tutti']:>5.1f}%")
    if esito["discriminanti"]:
        righe.append("")
        righe.append("dove differiscono:")
        for d in esito["discriminanti"]:
            dettaglio = ", ".join(
                f"{m} {t * 100:.0f}%" for m, t in sorted(d["tassi"].items()))
            righe.append(f"  {d['task_id']:24} {dettaglio}")
    return "\n".join(righe)
