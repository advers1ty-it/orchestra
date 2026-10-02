"""Il motore di instradamento: quale modello, e perché.

Tutta la materia prima c'era già — `Catalog.select`, `best_for`,
`by_score`, e i punteggi misurati con la curva di difficoltà — e non la
usava nessuno. L'agente prendeva il provider che aveva e andava.
Questo modulo è il motore che mancava: non sostituisce il catalogo, ci
appoggia sopra.

TRE REGOLE, e perché

1. Si Instrada all'AVVIO, non a ogni turno. Cambiare modello a metà
   di una conversazione cambia il modo in cui lo stesso compito viene
   affrontato, e un agente che cambia modello ogni tre messaggi
   sembra instabile anche quando sta facendo bene. Si sceglie una
   volta, e si cambia solo se quello scelto si dimostra sbagliato —
   cosa che è il caso [3] sotto.

2. La CATEGORIA viene dalla richiesta, non da un modello che la
   indovina. Se per capire quale modello usare servisse un LLM, si
   pagherebbe due volte ogni turno. Qui è una regola: parole che
   indicano il genere di lavoro, e il default è `code` perché è la
   maggior parte di ciò che si fa qui.

3. Se il modello sbaglia due volte di fila, si prova il SUCCESSIVO per
   quella categoria — ed è la parte che i punteggi rendono possibile.
   Senza misurazioni non c'è "successivo": c'è solo l'unico che hai.
   Con, c'è una fila e si sa chi è il secondo.

LA COSA CHE NON FA

Non nasconde la scelta. Ogni decisione porta con sé il motivo, il
punteggio, la base su cui è stato misurato e le alternative scartate
con la loro ragione. Un instradamento invisibile è un errore che
appare tre settimane dopo e non ha una spiegazione: a quel punto
l'unica cosa che resta è spegnere tutto e ricominciare.
"""

from typing import Any

# La categoria viene da parole nel testo. Non è un modello: è una
# regola, e una regola che sbaglia costa poco — al massimo si
# instrada un task di scrittura a un modello di codice, che lo fa
# comunque, solo un po' peggio.
#
# L'ordine conta: la prima categoria che trova vince, e `code` sta
# per ultimo perché è la più facile da sbagliare — una parola come
# "file" compare in metà delle frasi che non sono di programmazione.
CATEGORIE: list[tuple[str, tuple[str, ...]]] = [
    ("extraction", ("estrai", "estrae", "leggi il file", "tira fuori",
                    "converti il csv", "parse", "dal file", "dal csv")),
    ("writing", ("scrivi", "riscrivi", "redigi", "sintetizza",
                 "riassumi", "risumi", "traduci", "correggi", "riformula")),
    ("instruction", ("esattamente", "solo le righe", "nel formato",
                     "senza spiegazioni", "un file per riga")),
    ("reasoning", ("perché", "perche", "quanti", "calcola", "deduci",
                   "confronta", "se e solo se", "dimostra")),
    ("js", ("javascript", " js ", "node", "npm", "react hook")),
    ("web", ("html", "css", "pagina", "browser", "dom", "layout", "http")),
    ("app", ("react native", "android", "app mobile", "screenn", "gradlew")),
    ("tool_use", ("cerca i file", "elenca", "leggi la cartella",
                  "quanti file", "dimensione")),
]

# Quanti errori di fila prima di cambiare modello. Uno è normale: un
# modello sbaglia una chiamata e si corregge. Due è il punto in cui
# il modello è sbagliato per quel compito, non per quella chiamata.
SOGLIA_DI_CAMBIO = 2

# Un modello con meno di questa base non puo' guidare una scelta:
# due test non dicono se e' il migliore o solo l'unico misurato.
MINIMO_PROVE = 3


def categoria(richiesta: str) -> str:
    """La categoria della richiesta, per regola.

    Il default e' `code`: e' la maggior parte di cio' che si fa qui,
    e sbagliare nel senso di "il modello di codice fa anche il resto"
    e' molto meno peggio del contrario.
    """
    testo = " " + (richiesta or "").lower() + " "
    for cat, parole in CATEGORIE:
        for p in parole:
            if p in testo:
                return cat
    return "code"


class Scelta:
    """Una decisione di instradamento, con tutto quello che la regge.

    Non e' una tupla e non e' un dizionario: e' un oggetto che si puo'
    stampare e mostrare all'utente, perche' la prima domanda da fare
    davanti a un routing automatico e' "perche' ha fatto cosi'".
    """

    def __init__(self, modello: str | None, categoria_: str,
                 punteggio: float | None, prove: float | None,
                 motivo: str, scartati: list[dict[str, Any]] | None = None,
                 confrontabile: bool = True):
        self.modello = modello
        self.categoria = categoria_
        self.punteggio = punteggio
        self.prove = prove
        self.motivo = motivo
        self.scartati = scartati or []
        self.confrontabile = confrontabile

    def spiega(self) -> str:
        """Una riga per l'utomo, con il motivo e le alternative."""
        if self.modello is None:
            return f"{self.categoria}: nessun modello adatto — {self.motivo}"
        testo = (f"{self.categoria} → {self.modello} "
                 f"({self.punteggio:.0f}% su {self.prove:.0f} prove)"
                 if self.punteggio is not None
                 else f"{self.categoria} → {self.modello}")
        testo += f"\n  perché: {self.motivo}"
        if not self.confrontabile:
            testo += "\n  ! confronto non convalido: misurati su insiemi diversi"
        for s in self.scartati[:3]:
            testo += f"\n  scartato {s['modello']}: {s['motivo']}"
        return testo

    def __repr__(self) -> str:
        return f"<Scelta {self.categoria} → {self.modello}>"


def instrada(cat: Catalog, richiesta: str, *,
             solo_gratis: bool = False,
             escluso: str | None = None,
             provider: str = "openrouter") -> Scelta:
    """Sceglie il modello per questa richiesta. Ritorna sempre una Scelta.

    Anche quando non trova niente: una decisione che non c'è non si
    distingue da un classifier che non ha girato, e la prima fa
    fallire il turno mentre la seconda passa inosservata.
    """
    cat_id = categoria(richiesta)
    candidati = cat.with_tools()

    # prima il punteggio, poi il filtro per costo
    def _punteggio(p):
        scores = getattr(p, "scores", None) or {}
        v = scores.get(cat_id)
        if isinstance(v, (int, float)):
            from .punteggio import PESO_LIVELLO
            livelli = getattr(p, "livelli", None) or {}
            peso = PESO_LIVELLO.get(livelli.get(cat_id, "senza"), 1.0)
            return float(v) * 100, peso
        return None, 0.0

    scartati: list[dict[str, Any]] = []
    con_punteggio = []
    senza_punteggio = []
    for p in candidati:
        if escluso and p.info.id == escluso:
            continue
        if solo_gratis and not getattr(p.info, "is_free", False):
            scartati.append({"modello": p.info.id, "motivo": "a pagamento"})
            continue
        v, peso = _punteggio(p)
        if v is None:
            senza_punteggio.append(p)
            continue
        con_punteggio.append((v, peso, p))

    if con_punteggio:
        con_punteggio.sort(key=lambda t: (-t[0], -t[1]))
        migliore = con_punteggio[0]
        for v, peso, p in con_punteggio[1:4]:
            scartati.append({
                "modello": p.info.id,
                "motivo": f"{v:.0f}% contro {migliore[0]:.0f}%",
            })
        if migliore[1] < MINIMO_PROVE:
            scartati.append({
                "modello": migliore[2].info.id,
                "motivo": f"poco misurato ({migliore[1]:.1f} prove)",
            })
            # con poche prove il punteggio non guida: si dichiara
            return Scelta(
                migliore[2].info.id, cat_id, migliore[0], migliore[1],
                f"miglior punteggio ma poche prove: scelta per non lasciare "
                f"la sessione senza modello",
                scartati)
        return Scelta(
            migliore[2].info.id, cat_id, migliore[0], migliore[1],
            f"il più alto in {cat_id} fra i misurati con strumenti",
            scartati)

    if senza_punteggio:
        # Nessuno misurato in questa categoria. Si prende il primo che
        # supporta i tool e si DICE che è una scelta per mancanza di
        # dati, non perché sia il migliore: è la differenza fra
        # " Orchestra sa" e " Orchestra ha scelto a caso".
        scelto = senza_punteggio[0]
        return Scelta(
            scelto.info.id, cat_id, None, None,
            f"nessuno misurato in {cat_id}: scelto il primo disponibile, "
            f"non perché sia il migliore",
            scartati)

    return Scelta(
        None, cat_id, None, None,
        "nessun modello con strumenti corrisponde ai vincoli", scartati)


def il_successivo(scelta: Scelta, cat: Catalog, *,
                  solo_gratis: bool = False,
                  provider: str = "openrouter") -> Scelta:
    """Il secondo modello per la stessa categoria: il ripiego.

    È la parte che i punteggi rendono possibile. Senza misurazioni non
    c'è "successivo": c'è solo l'unico che hai, e quando sbaglia non
    resta che dargli un altro compito. Con, c'è una fila e si sa chi
    viene dopo.
    """
    return instrada(cat, "", solo_gratis=solo_gratis, escluso=scelta.modello)
