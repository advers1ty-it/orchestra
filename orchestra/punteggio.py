"""Il numero unico: quanto vale un modello, in una percentuale sola.

Il problema che risolve: la tabella per categoria non dà una risposta.
Un modello può essere ottimo su web e mediocre su reasoning, un altro
il contrario, e "scegli il migliore" resta senza risposta. Serve un
numero — ma un numero onesto, che non nasconda sotto la sua stessa
esistenza il fatto che alcuni punteggi vengono da due test e altri da
quaranta.

TRE REGOLE, e perché

1. Ogni categoria pesa uguale. Non per generosità verso le categorie
   grandi, ma per l'opposto: `code` ha 6 task e `web` ne ha 2, e con
   un peso per singolo test la categoria con piu' compiti farebbe la
   parte dominante di un numero che dovrebbe dire "quanto vale in
   generale". Se invece ti interessa solo web, il confronto si fa sulla
   colonna web — e questa tabella non deve impedirlo.

2. Dentro la categoria, il livello moltiplica: facile x1, medio x1.5,
   difficile x2. Non e' un premio arbitrario: passare un caso limite
   dice piu' del fatto di saper fare la divisione, e senza questo la
   curva non serve a niente nel numero finale.

3. Chi ha meno prove viene tirato verso la media degli altri. Un
   modello con 2 test perfetti ha 100% esattamente come uno con 40,
   ma porta una prova incomparabilmente minore. Senza questa
   correzione il numero premia la sfortuna: basta misurare due modelli
   a caso e il meno testato vince. È la correzione che rende
   confrontabili due numeri con basi diverse — e senza di lei tutta la
   parte sulla base campionaria non serve a niente.

   La correzione e' quella bayesiana usuale: il numero osservato conta
   `n`, e la media degli altri ne avanza `k`. Con molte misurazioni
   `n` domina e il peso torna a essere tutto suo, che e' il
   comportamento giusto: la correzione serve quando le prove sono
   poche, non per penalizzare chi e' stato misurato tanto.
"""

from typing import Any

# Il moltiplicatore del livello. Facile 1, medio 1.5, difficile 2.
PESO_LIVELLO = {"l1": 1.0, "l2": 1.5, "l3": 2.0}

# Quante prove "equivale" a non avere ancora opinioni. Con 4 prove il
# numero e' per meta' suo e meta' della media degli altri: si vede che
# non si sa, che e' il punto. Con 40 prove la media degli altri pesa
# il 4% e il numero e' suo.
PRIOR_PROVE = 4.0


def livello_di(task_id: str) -> str:
    """Il livello si legge dall'id: `code_l2` -> `l2`.

    Non da un campo apposito, perche' un campo vuoto prima o poi
    farebbe sparire un livello senza che nessuno se ne accorga. Un
    task senza livello torna "senza", che pesa come il facile: si
    misura, ma non fa finta di essere difficile.
    """
    parti = task_id.rsplit("_", 1)
    if len(parti) == 2 and parti[1] in PESO_LIVELLO:
        return parti[1]
    return "senza"


def _categoria_di(task_id: str) -> str:
    """La categoria sta nel risultato, non nell'id."""
    return ""


def punteggio_unico(risultati: list, media_di_insieme: float | None = None) -> dict[str, Any]:
    """Un numero per modello. Ritorna anche tutto quello che serve a dubitarne.

    La struttura che torna ha tre cose, e non una: `punteggio` (quello
    che metti nella colonna), `prove` (quanta base ha) e `contrasto`
    (quanto il numero si discosta da quello che avresti senza correggere
    per le prove scarse). Una colonna sola costringerebbe a fidarsi,
    e il numero e' la cosa che va controllata per prima.

    `media_di_insieme` e' la media dei punteggi di tutti i modelli,
    calcolata DOPO la prima passata quando non la passi: la media
    globale e' appunto il punto verso cui si sta contraendo il numero,
    e tirare verso se stessi e' un circolo.
    """
    # 1) raccoglie, per modello e per categoria
    grezzi: dict[str, dict[str, dict[str, float]]] = {}
    task_ids: dict[str, set] = {}
    for r in risultati:
        task_ids.setdefault(r.model, set()).add(r.task_id)
        if getattr(r, "unusable", False):
            continue
        cat = getattr(r, "category", "") or _categoria_di(r.task_id)
        peso = PESO_LIVELLO.get(livello_di(r.task_id), 1.0)
        m = grezzi.setdefault(r.model, {}).setdefault(
            cat, {"peso_passati": 0.0, "peso_totale": 0.0, "task": 0.0})
        m["peso_totale"] += peso
        m["task"] += 1.0
        if r.passed:
            m["peso_passati"] += peso

    # 2) il punteggio GREZZO: media delle categorie, pesi uguali
    grezzi_pct: dict[str, float] = {}
    for modello, cats in grezzi.items():
        punteggi = [c["peso_passati"] / c["peso_totale"]
                    for c in cats.values() if c["peso_totale"] > 0]
        grezzi_pct[modello] = (sum(punteggi) / len(punteggi) * 100) if punteggi else 0.0

    if media_di_insieme is None:
        vals = list(grezzi_pct.values())
        media_di_insieme = sum(vals) / len(vals) if vals else 0.0

    # 3) la correzione per le prove
    out: dict[str, Any] = {}
    for modello, cats in grezzi.items():
        grezzo = grezzi_pct[modello]
        # "prove" qui sono i task col loro peso: un livello difficile
        # conta come due prove perche' e' un'affermazione piu' forte
        prove = sum(c["peso_totale"] for c in cats.values())
        if prove > 0:
            ridotto = (prove * grezzo + PRIOR_PROVE * media_di_insieme) / (prove + PRIOR_PROVE)
        else:
            ridotto = media_di_insieme
        out[modello] = {
            "punteggio": round(ridotto, 1),
            "grezzo": round(grezzo, 1),
            "prove": round(prove, 1),
            "task": int(sum(c["task"] for c in cats.values())),
            "categorie": len(cats),
            "contrasto": round(grezzo - ridotto, 1),
            "per_categoria": {
                c: round(v["peso_passati"] / v["peso_totale"] * 100, 1)
                for c, v in cats.items() if v["peso_totale"] > 0
            },
            # l'insieme di task su cui e' stato misurato: senza questo
            # non si puo' sapere se due numeri sono confrontabili
            "task_id": sorted(t for t in task_ids.get(modello, ())),
        }

    # Confronto possibile solo sugli stessi task. Il numero resta
    # calcolato e resta visibile — nasconderlo sarebbe peggio — ma
    # dichiara che il confronto non è su misura uguale per tutti.
    insiemi = [set(v["task_id"]) for v in out.values() if v["task_id"]]
    stessi = bool(insiemi) and all(i == insiemi[0] for i in insiemi)
    comuni = set.intersection(*insiemi) if insiemi else set()

    # Con un solo modello non c'e' niente da confrontare: non e' che
    # siano diversi, e' che non ce n'e' un altro. Con zero idem. Dire
    # "misurati su insiemi diversi" sarebbe una frase vera solo per
    # caso, e in un modulo il cui compito e' dichiarare la verita' una
    # frase vera per caso e' peggio di una falsa.
    if len(insiemi) < 2:
        stessi, motivo = True, ""
    elif stessi:
        motivo = ""
    else:
        motivo = f"misurati su insiemi diversi: {len(comuni)} task in comune"

    return {
        "modelli": out,
        "media_di_insieme": round(media_di_insieme, 1),
        "confrontabili": stessi,
        "task_comuni": len(comuni),
        "motivo": motivo,
    }
