"""
Il web: cercare e leggere pagine. Due tool, un solo buco colmato.

PERCHÉ ESISTE

I dieci tool che c'erano facevano tutti la stessa cosa: leggere e
scrivere sul disco di chi usa Orchestra. Non uno cercava niente. Chiedere
"quanto costa il Bitcoin oggi" non aveva risposta — non perché il modello
non lo sapesse, ma perché *non poteva saperlo*: la sua conoscenza ha una
data di taglio e nessun tool gliela aggirava.

DUCKDUCKGO, NESSUNA CHIAVE

`ddgs` cerca su DuckDuckGo senza account, senza token, senza carta. È la
scelta coerente col resto: Orchestra è offline-first, gratis, e gira su
127.0.0.1. Una API con chiave significherebbe un account e un costo fisso.

MA SE MANCA LA LIBRERIA, NON SI MUORE

`ddgs` è una dipendenza NUOVA, ed è l'unica di rete di tutto il progetto.
Se non è installata i tool lo dicono e basta — non propagano
un'eccezione che uccide il turno. Orchestra senza web è esattamente
quello che era prima: funziona, solo non esce dal computer.

Il fetch delle pagine è a parte, su `urllib` dalla standard library: non
ha bisogno di nient'altro, ed è la metà più utile delle due.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from ..types import Tool

# Quanto prendiamo da una pagina. Una risposta troppo lunga torna al
# modello come muro di testo e costa token senza che legga la metà; troppo
# corta e perde il pezzo che cercavi. 6000 caratteri è circa una pagina
# e mezza di manuale.
TETTO_PAGINA = 6000

# Dove finisce il contenuto utile e inizia il contorno: navigazione,
# cookie, iscrizione alla newsletter. Sono i pezzi che una persona salta
# a occhio e un agente no, perché non sa che sono rumore.
RUMORE = re.compile(
    r"<(script|style|nav|footer|header|aside|noscript|svg|form|iframe)[^>]*>"
    r".*?</\1>",
    re.IGNORECASE | re.DOTALL)


def _html_a_testo(grezzo: str) -> str:
    """Da HTML a testo leggibile, senza dipendenze.

    Un parser HTML vero sarebbe più corretto, ma è un'altra dipendenza per
    un lavoro che è quasi tutto sostituzioni: togliere il rumore noto,
    i tag, e comprimere gli spazi. BeautifulSoup su 6000 caratteri di
    pagine vere non dà un risultato abbastanza migliore da giustificarlo.
    """
    t = RUMORE.sub(" ", grezzo)
    # i blocchi di testo diventano righe: senza, due paragrafi si
    # attaccano e il modello legge una frase che non esiste
    t = re.sub(r"</(p|div|li|h[1-6]|tr|br)>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    # le entità che si vedono sempre
    for prima, dopo in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                        ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        t = t.replace(prima, dopo)
    # comprime: più di due righe vuote di fila sono decorazioni
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


def _titolo(grezzo: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", grezzo, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120]


def tool_web_cerca() -> Tool:
    """Cerca sul web con DuckDuckGo. Nessuna chiave."""

    def handler(query: str = "", limite: int = 5) -> str:
        q = (query or "").strip()
        if not q:
            return "Cosa cerco? Serve una query."
        try:
            from ddgs import DDGS
        except ImportError:
            # Non è un errore dell'agente: è una scelta di chi installa.
            # Dirgli "non riesco a cercare" senza spiegare perché lo
            # mandrebbe a riprovare una cosa che non cambia.
            return ("La ricerca sul web non è installata. Manca la libreria "
                    "`ddgs`: con `pip install ddgs` si attiva. Il resto di "
                    "Orchestra funziona senza.")
        try:
            limite = max(1, min(int(limite or 5), 10))
            risultati = list(DDGS().text(q, max_results=limite))
        except Exception as e:
            # La rete può non rispondere: un DNS che non risolve o un
            # proxy che blocca. Distinguere il motivo aiuta a capire se
            # è colpa della query o della connessione.
            return (f"Ricerca fallita: {type(e).__name__}: {e}\n"
                    f"Se il problema è la rete, Orchestra funziona comunque "
                    f"in locale.")
        if not risultati:
            return f"Nessun risultato per: {q}"
        righe = []
        for i, r in enumerate(risultati, 1):
            titolo = (r.get("title") or "").strip() or "(senza titolo)"
            url = (r.get("href") or "").strip()
            corpo = (r.get("body") or r.get("description") or "").strip()
            righe.append(f"{i}. {titolo}\n   {url}")
            if corpo:
                righe.append(f"   {corpo[:300]}")
        return "\n".join(righe)

    return Tool(
        name="web_cerca",
        description=(
            "Cerca sul web (DuckDuckGo, senza chiave). Usala quando la "
            "domanda dipende da fatti che potrebbero essere cambiati dopo "
            "la tua data di addestramento — prezzi, versioni, notizie, "
            "documentazione. Non usarla per cose che sai già."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Cosa cercare."},
                "limite": {"type": "integer",
                           "description": "Quanti risultati, 1-10. Default 5."},
            },
            "required": ["query"],
        },
        handler=handler,
    )


def tool_web_leggi() -> Tool:
    """Scarica una pagina e la restituisce come testo."""

    def handler(url: str = "", righe: int = 0) -> str:
        u = (url or "").strip()
        if not u:
            return "Quale indirizzo? Serve un URL."
        p = urlparse(u)
        if p.scheme not in ("http", "https"):
            # Un `file://` o un percorso locale qui è un modo di leggere
            # il disco saltando `read_file` e il suo gate dei permessi.
            # Fuori http/https non si passa.
            return f"Schema non ammesso: {p.scheme or '(nessuno)'}. Solo http e https."
        import urllib.request
        # Chiariamo chi siamo: molti siti rispondono 403 a un client
        # senza User-Agent, e l'errore sembra di rete invece che di
        # presentazione.
        req = urllib.request.Request(u, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Orchestra/1.0)",
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
        })
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                grezzo = resp.read(1_200_000).decode(
                    resp.headers.get_content_charset() or "utf-8", "replace")
                finale = urljoin(u, resp.geturl())
        except urllib.error.HTTPError as e:
            return f"La pagina ha risposto {e.code} {e.reason}. URL: {u}"
        except Exception as e:
            return f"Non riesco a leggere {u}: {type(e).__name__}: {e}"

        testo = _html_a_testo(grezzo)
        if not testo:
            # PDF, immagini, JSON, o una pagina che si riempie con
            # JavaScript. Distinguere aiuta: su JSON il modello può
            # leggerlo, su PDF no.
            return (f"La pagina non ha testo estraibile ({len(grezzo)} byte "
                    f"grezzi). Se è un PDF o un'immagine, questo strumento "
                    f"non li legge.")
        # righe: tiene solo le prime N righe del testo, se richiesto.
        if righe and int(righe or 0) > 0:
            ls = testo.splitlines()
            n = max(1, int(righe))
            testo = "\n".join(ls[:n])
            if len(ls) > n:
                testo += f"\n\n[...troncato: {len(ls)} righe in tutto, mostro le prime {n}]"
        titolo = _titolo(grezzo)
        if len(testo) > TETTO_PAGINA:
            testo = (testo[:TETTO_PAGINA]
                     + f"\n\n[...troncato: {len(testo)} caratteri in tutto]")
        testa = f"# {titolo}\n{finale}\n\n" if titolo else f"{finale}\n\n"
        return testa + testo

    return Tool(
        name="web_leggi",
        description=(
            "Scarica una pagina web e ne estrae il testo. Usala DOPO "
            "`web_cerca` per aprire un risultato che promette di avere "
            "quello che serve: la ricerca dà il titolo e un riassunto, "
            "questo dà la pagina."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string",
                       "description": "Indirizzo http o https da leggere."},
                "righe": {
                    "type": "integer",
                    "description": (
                        "Tiene solo le prime N righe del testo (0 = tutte, "
                        "default). Per pagine lunghissime: la ricerca serve a "
                        "non riempire il contesto di una pagina intera."
                    ),
                    "default": 0,
                },
            },
            "required": ["url"],
        },
        handler=handler,
    )
