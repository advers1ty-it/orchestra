"""Verificatori per estrazione e scrittura.

Tutti obiettivi: dicono se un file c'e', se un JSON ha i campi giusti,
se i valori corrispondono, se una somma torna. Nessuno chiede "questa
prosa e' buona?" — un verificatore che risponde a una domesta di gusto
e' un giudice travestito da test, e finisce per premiare il modello
piu' verboso.

Il principio: si verifica cio' che in un documento e' un REQUISITO. Un
JSON senza `totale` e' sbagliato anche se il testo intorno e'
eccellente. Una scheda senza la data e' sbagliata anche con una prosa
ottima. Il resto — la qualita' — non si misura, e non si finge.
"""

import json
import os
import re
from typing import Any, Callable

# I numeri in italiano: "12,50" o "1.234,56" o "12.50". Un modello che
# scrive "12,50" in un JSON lo rende INVALIDO: JSON vuole il punto.
# E' una distinzione che sembra pignola e non lo e' — e' esattamente il
# motivo per cui un'estrazione va verificata invece che letta a vista.
_NUMERO = re.compile(r"-?\d+(?:\.\d+)?")


def _leggi_json(work: str, path: str) -> tuple[Any, str]:
    p = os.path.join(work, path)
    if not os.path.exists(p):
        return None, f"il file {path} non esiste"
    try:
        grezzo = open(p, encoding="utf-8", errors="replace").read().strip()
    except OSError as e:
        return None, f"non leggibile: {e}"
    if not grezzo:
        return None, f"{path} e' vuoto"
    # Tolgo un eventuale blocco ```json che alcuni modelli aggiungono
    # attorno. Non e' un JSON valido e non si puo' usarlo cosi', ma il
    # contenuto c'e' e la colpa non e' della logica del modello.
    m = re.match(r"^```(?:json)?\s*\n(.*?)\n?```\s*$", grezzo, re.S)
    if m:
        grezzo = m.group(1)
    try:
        return json.loads(grezzo), ""
    except json.JSONDecodeError as e:
        # Il messaggio dice DOVE e COSA: "JSON non valido" da solo fa
        # perdere il tempo a indovinare.
        return None, f"{path} non e' JSON valido: {e} (riga {e.lineno})"


def v_testo_presente(path: str) -> Callable[[str], tuple[bool, str]]:
    """Il file esiste e non e' vuoto."""
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        testo = open(p, encoding="utf-8", errors="replace").read()
        if not testo.strip():
            return False, f"{path} e' vuoto"
        return True, f"{len(testo.strip())} caratteri"
    return check


def v_testo_presente_inesistente(
        path: str, vietati: list[str]) -> Callable[[str], tuple[bool, str]]:
    """Nessuno dei pezzi vietati compare nel file.

    Serve per "non aggiungere spiegazioni" e "non ripetere i dati
    sbagliati". Un modello che scrive il file giusto e poi aggiunge
    "Ecco il risultato, spero che sia utile" non sta sbagliando il
    lavoro, sta facendo il lavoro piu' del dovuto — e in un'estrazione
    un wrapper di prosa e' rumore che finisce dentro il database.
    """
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        testo = open(p, encoding="utf-8", errors="replace").read().lower()
        trovati = [v for v in vietati if v.lower() in testo]
        if trovati:
            return False, f"nel file ci sono: {', '.join(trovati)}"
        return True, "nessun riempitivo"
    return check


def v_testo_lungo(path: str, *, minimo: int,
                  massimo: int) -> Callable[[str], tuple[bool, str]]:
    """Il file sta entro una fascia di lunghezza.

    Il massimo e' un requisito (un avviso di 240 caratteri che ne ha 600
    non e' un avviso). Il minimo serve a non accettare un file vuoto o
    di una parola: e' la soglia sotto la quale non hai scritto niente.
    """
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        testo = open(p, encoding="utf-8", errors="replace").read().strip()
        n = len(testo)
        if n < minimo:
            return False, f"{n} caratteri, meno di {minimo}: troppo corto"
        if n > massimo:
            return False, f"{n} caratteri, piu' di {massimo}: troppo lungo"
        return True, f"{n} caratteri"
    return check


def v_testo_contiene(path: str,
                     frammenti: list[str]) -> Callable[[str], tuple[bool, str]]:
    """Tutti i frammenti richiesti compaiono nel file.

    Il caso peggiore di un'estrazione e' quello che sembra funzionare:
    il file c'e', ha i campi giusti, e il valore dentro e' un numero
    inventato. Qui si richiede che i DATI richiesti ci siano davvero,
    il nome e la data per una scheda, l'id e l'importo per un
   'estrazione.

    Non e' un test di stile: richiede fatti presenti, non belle frasi.
    """
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        testo = open(p, encoding="utf-8", errors="replace").read()
        mancanti = [f for f in frammenti if f not in testo]
        if mancanti:
            return False, f"mancano: {', '.join(mancanti[:4])}"
        return True, f"{len(frammenti)} elementi presenti"
    return check


def v_json_campi(path: str, campi: list[str]) -> Callable[[str], tuple[bool, str]]:
    """Il JSON e' valido e ha tutti i campi richiesti.

    Accetta sia un oggetto sia un array di oggetti: un'estrazione di
    cinque righe e' un array, di una riga sola e' un oggetto, e
    chiedere all'autore di sapere quale sia stato il caso e' una
    domanda stupida.
    """
    def check(work: str) -> tuple[bool, str]:
        dati, errore = _leggi_json(work, path)
        if dati is None:
            return False, errore
        if isinstance(dati, list):
            if not dati:
                return False, f"{path} e' un array vuoto"
            primo = dati[0]
        else:
            primo = dati
        if not isinstance(primo, dict):
            return False, (f"{path} non e' un oggetto ne' un array di "
                           f"oggetti, ma {type(primo).__name__}")
        mancanti = [c for c in campi if c not in primo]
        if mancanti:
            return False, f"mancano i campi: {', '.join(mancanti)}"
        return True, f"campi presenti: {', '.join(campi)}"
    return check


def v_json_valori(path: str, attesi: dict[str, Any]) -> Callable[[str], tuple[bool, str]]:
    """Ogni campo ha ESATTAMENTE il valore atteso.

    Il confronto e' per stringa, non "fuzzy": se il campo `data` deve
    essere "2026-06-14" e il modello scrive "14/06/2026", e' sbagliato.
    Non e' pedanteria: e' il dato che finisce in un database, e un
    formato diverso ti fa fallire il caricamento tre giorni dopo, in
    produzione.
    """
    def check(work: str) -> tuple[bool, str]:
        dati, errore = _leggi_json(work, path)
        if dati is None:
            return False, errore
        if isinstance(dati, list):
            dati = dati[0] if dati else {}
        if not isinstance(dati, dict):
            return False, f"{path} non e' un oggetto"
        sbagliati = []
        for campo, voluto in attesi.items():
            if campo not in dati:
                sbagliati.append(f"{campo} mancante")
                continue
            got = dati[campo]
            if str(got).strip() != str(voluto).strip():
                sbagliati.append(f"{campo}={got!r} invece di {voluto!r}")
        if sbagliati:
            return False, "; ".join(sbagliati)
        return True, f"{len(attesi)} valori corretti"
    return check


def v_json_somma(path: str, campo: str,
                 atteso: float) -> Callable[[str], tuple[bool, str]]:
    """La somma di un campo numerico torna.

    Questo e' il verificatore che piu' di tutti distingue un'estrazione
    da un'invenzione: un modello puo' inventare un valore plausibile in
    un campo singolo, ma la somma di cinque righe deve tornare. Il
    numero e' l'unica cosa che non si puo' indovinare bene, e per
    questo si somma invece di confrontare riga per riga: richiede che
    TUTTE le righe siano giuste, non una.
    """
    def check(work: str) -> tuple[bool, str]:
        dati, errore = _leggi_json(work, path)
        if dati is None:
            return False, errore
        if isinstance(dati, dict):
            dati = [dati]
        if not isinstance(dati, list) or not dati:
            return False, f"{path} non e' un array non vuoto"
        valori = []
        for i, riga in enumerate(dati):
            if not isinstance(riga, dict):
                return False, f"riga {i} non e' un oggetto"
            if campo not in riga:
                return False, f"riga {i}: manca '{campo}'"
            grezzo = riga[campo]
            if isinstance(grezzo, (int, float)):
                valori.append(float(grezzo))
                continue
            testo = str(grezzo).strip()
            # Una virgola decimale dentro un valore numerico e' un
            # errore, non un formato accettabile. La mia regex ne
            # prendeva solo la parte intera, e la somma tornava
            # comunque: "1200,00" passava come 1200. Ma in JSON quel
            # valore e' una STRINGA, e un database che si aspetta un
            # numero riceve testo. La somma che torna non prova che il
            # file sia usabile.
            if "," in testo:
                return False, (f"riga {i}: '{campo}' = {grezzo!r} usa la "
                               f"virgola decimale. In JSON si usa il punto")
            m = _NUMERO.fullmatch(testo.replace(" ", ""))
            if not m:
                return False, (f"riga {i}: '{campo}' = {grezzo!r} non e' "
                               f"un numero")
            valori.append(float(m.group(0)))
        totale = sum(valori)
        if abs(totale - atteso) > 0.01:
            return False, (f"somma di '{campo}' = {totale:g} invece di "
                           f"{atteso:g} (valori: {valori})")
        return True, f"somma {totale:g} su {len(valori)} righe"
    return check


def v_markdown_sezioni(path: str,
                        sezioni: list[str]) -> Callable[[str], tuple[bool, str]]:
    """Le intestazioni richieste ci sono, con l'ordine dato.

    L'ordine conta: un documento con le sezioni tutte ma in ordine
    sparso e' un documento che nessuno usa, e verificarne solo la
    presenza lascerebbe passare la cosa che fa fallire l'uso.
    """
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        testo = open(p, encoding="utf-8", errors="replace").read()
        posizioni = []
        for s in sezioni:
            i = testo.find(s)
            if i < 0:
                return False, f"manca la sezione {s!r}"
            posizioni.append((i, s))
        if posizioni != sorted(posizioni):
            ordine = [s for _, s in posizioni]
            return False, f"sezioni fuori ordine: {', '.join(ordine)}"
        return True, f"{len(sezioni)} sezioni nell'ordine giusto"
    return check


def v_tutte_sezioni(path: str,
                    confronto: str) -> Callable[[str], tuple[bool, str]]:
    """Le stesse sezioni dell'originale, nello stesso ordine.

    Serve al task di riscrittura: l'obiettivo e' correggere i dati, non
    riformattare il documento. Se il modello approfitta per riscrivere
    anche le intestazioni, ha fatto un lavoro diverso da quello chiesto.
    """
    def check(work: str) -> tuple[bool, str]:
        nuovo = os.path.join(work, path)
        vecchio = os.path.join(work, confronto)
        for p, nome in ((nuovo, path), (vecchio, confronto)):
            if not os.path.exists(p):
                return False, f"{nome} non esiste"

        def intestazioni(t: str) -> list[str]:
            return [l.strip() for l in t.splitlines() if l.strip().startswith("#")]

        a = intestazioni(open(nuovo, encoding="utf-8", errors="replace").read())
        b = intestazioni(open(vecchio, encoding="utf-8", errors="replace").read())
        if a != b:
            return False, (f"intestazioni diverse: {a} invece di {b}")
        return True, f"{len(a)} intestazioni, invariate"
    return check
