"""Scrivere .docx e .xlsx veri, in sola stdlib.

PERCHE' UN MODULO A PARTE

`office.py` legge, e lo dice nella prima riga: un file Office e' uno zip di
XML e si legge in una direzione sola. Scrivere e' l'altra direzione, con
un rischio diverso: li' basta non sbagliare la lettura, qui il file deve
aprirsi in Word e in Excel senza messaggi di riparazione. Le due cose
stanno separate perche' un errore nella scrittura non deve far dubitare
della lettura.

CHE COSA SI SCRIVE DAVVERO

Un `.docx` con paragrafi (il primo puo' essere un titolo in grassetto), un
`.xlsx` con uno o piu' fogli, intestazione in grassetto, larghezza delle
colonne calcolata sul contenuto e celle che possono essere formule, e un
`.pdf` impaginato dal generatore che c'era gia' (`pdf_mini`).

I PDF NON SI AGGIORNANO, GLI ALTRI SI

`aggiungi` mette paragrafi in coda a un `.docx` e righe in coda al primo
foglio di un `.xlsx`, senza toccare il resto del file. Un PDF invece non
ha un "dopo": si riscrive da capo, e dirlo e' meglio che produrre un file
in cui meta' del contenuto e' sparita.

I NUMERI RESTANO NUMERI

In un foglio di calcolo una cella "1.234,56" scritta come testo non si
somma. Qui un valore numerico finisce come numero (`<v>`), una stringa
come testo inline: e' la differenza fra un foglio che si puo' usare e uno
che sembra giusto e non calcola.

LE FORMULE

Una stringa che comincia con `=` diventa una formula vera (`<f>`), e il
workbook chiede a Excel di ricalcolare all'apertura (`fullCalcOnLoad`):
senza quel flag il file mostrerebbe celle vuote finche' l'utente non tocca
qualcosa, e sembrerebbe rotto. I nomi delle funzioni nel file sono quelli
inglesi (`SUM`, `AVERAGE`): e' il formato, non una preferenza — la
traduzione la fa Excel quando mostra la formula.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml

# Tetti: un file enorme non e' un documento, e' un errore di chiamata.
MAX_PARAGRAFI = 5000
MAX_RIGHE = 20000
MAX_COLONNE = 200
MAX_FOGLI = 50
MAX_FORMULA = 2000

_NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_XML_TESTA = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'

# Due soli stili: normale e grassetto. Il secondo e' quello della riga
# d'intestazione, e vale 1 (`s="1"`) nelle celle.
_STILI = (
    _XML_TESTA
    + f'<styleSheet xmlns="{_NS_S}">'
      '<fonts count="2">'
      '<font><sz val="11"/><name val="Calibri"/></font>'
      '<font><b/><sz val="11"/><name val="Calibri"/></font>'
      "</fonts>"
      '<fills count="2">'
      '<fill><patternFill patternType="none"/></fill>'
      '<fill><patternFill patternType="gray125"/></fill>'
      "</fills>"
      '<borders count="1"><border/></borders>'
      '<cellStyleXfs count="1">'
      '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
      "</cellStyleXfs>"
      '<cellXfs count="2">'
      '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
      '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" '
      'applyFont="1"/>'
      "</cellXfs>"
      '<cellStyles count="1">'
      '<cellStyle name="Normal" xfId="0" builtinId="0"/>'
      "</cellStyles>"
      "</styleSheet>")


def _zip(percorso: str | Path, parti: dict[str, str | bytes]) -> Path:
    """Scrive lo zip in modo atomico.

    Un `.docx` troncato non si apre e non si ripara: si scrive su un
    temporaneo nella stessa cartella e si sostituisce solo alla fine.
    """
    destinazione = Path(percorso)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(dir=str(destinazione.parent),
                                      suffix=destinazione.suffix)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporaneo, "w", zipfile.ZIP_DEFLATED) as z:
            for nome, contenuto in parti.items():
                z.writestr(nome, contenuto)
        os.replace(temporaneo, destinazione)
    except Exception:
        try:
            os.unlink(temporaneo)
        except OSError:
            pass
        raise
    return destinazione


# ------------------------------------------------------------------ docx

def _paragrafo(testo: str, grassetto: bool = False) -> str:
    rpr = "<w:rPr><w:b/></w:rPr>" if grassetto else ""
    return (f'<w:p><w:r>{rpr}<w:t xml:space="preserve">'
            f'{_xml(str(testo or ""))}</w:t></w:r></w:p>')


def scrivi_docx(percorso: str | Path, titolo: str = "",
                paragrafi: Any = None) -> Path:
    """Scrive un .docx con un titolo (facoltativo) e i paragrafi indicati.

    `paragrafi` e' una lista di stringhe: una riga vuota e' una riga
    vuota nel documento, e una riga che comincia con "- " resta com'e'
    (un elenco puntato vero richiede numerazione, che qui non c'e': il
    testo e' meglio di un elenco numerato sbagliato).
    """
    righe = [str(p) for p in (paragrafi or [])]
    if len(righe) > MAX_PARAGRAFI:
        raise ValueError(f"troppi paragrafi: {len(righe)} (massimo "
                         f"{MAX_PARAGRAFI})")
    corpo = []
    if titolo:
        corpo.append(_paragrafo(titolo, grassetto=True))
    corpo.extend(_paragrafo(r) for r in righe)
    document = (
        _XML_TESTA
        + f'<w:document xmlns:w="{_NS_W}"><w:body>'
        + "".join(corpo)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
          '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
          'w:left="1134" w:header="708" w:footer="708" w:gutter="0"/>'
          "</w:sectPr></w:body></w:document>")
    tipi = (
        _XML_TESTA
        + f'<Types xmlns="{_NS_CT}">'
          '<Default Extension="rels" ContentType="application/'
          'vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.wordprocessingml.document'
          '.main+xml"/></Types>')
    relazioni = (
        _XML_TESTA
        + f'<Relationships xmlns="{_NS_REL}"><Relationship Id="rId1" '
          'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
          'relationships/officeDocument" Target="word/document.xml"/>'
          "</Relationships>")
    return _zip(percorso, {
        "[Content_Types].xml": tipi,
        "_rels/.rels": relazioni,
        "word/document.xml": document,
    })


# ------------------------------------------------------------------ xlsx

def _colonna(numero: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    fuori = ""
    while numero > 0:
        numero, resto = divmod(numero - 1, 26)
        fuori = chr(65 + resto) + fuori
    return fuori


def _cella(riferimento: str, valore: Any, stile: str = "") -> str:
    """Una cella: numero se e' un numero, testo se e' testo, formula se `=`.

    Un `None` (o una stringa vuota) resta una cella vuota invece di un
    testo vuoto, che in Excel e' una cosa diversa.
    """
    attributo = f' s="{stile}"' if stile else ""
    if valore is None or valore == "":
        # La cella vuota non si scrive, ma lo stile (intestazione) si': la
        # colonna resta larga anche dove l'intestazione e' vuota.
        return f'<c r="{riferimento}"{attributo}/>' if stile else ""
    if isinstance(valore, bool):
        return (f'<c r="{riferimento}"{attributo} t="inlineStr"><is><t>'
                f'{_xml("VERO" if valore else "FALSO")}</t></is></c>')
    if isinstance(valore, (int, float)):
        return f'<c r="{riferimento}"{attributo}><v>{valore}</v></c>'
    if isinstance(valore, (dt.date, dt.datetime)):
        return (f'<c r="{riferimento}"{attributo} t="inlineStr"><is><t>'
                f'{_xml(valore.isoformat())}</t></is></c>')
    testo = str(valore)
    if testo.startswith("=") and len(testo) > 1:
        corpo = testo[1:].strip()
        if len(corpo) > MAX_FORMULA:
            raise ValueError(f"formula troppo lunga in {riferimento}: "
                             f"{len(corpo)} caratteri (massimo "
                             f"{MAX_FORMULA})")
        # Niente `<v>`: il valore lo calcola Excel all'apertura, perche' il
        # workbook lo chiede con fullCalcOnLoad. Scrivere uno zero qui
        # vorrebbe dire mostrare uno zero fino al primo ricalcolo.
        return f'<c r="{riferimento}"{attributo}><f>{_xml(corpo)}</f></c>'
    return (f'<c r="{riferimento}"{attributo} t="inlineStr"><is>'
            f'<t xml:space="preserve">{_xml(testo)}</t></is></c>')


def _testo_cella(valore: Any) -> str:
    if valore is None:
        return ""
    if isinstance(valore, (dt.date, dt.datetime)):
        return valore.isoformat()
    return str(valore)


def _larghezze(righe: list[list[Any]]) -> list[int]:
    """La larghezza di ogni colonna, sui caratteri che ci sono dentro."""
    if not righe:
        return []
    quante = max(len(r) for r in righe)
    larghezze = []
    for i in range(quante):
        massimo = max((len(_testo_cella(r[i])) if i < len(r) else 0)
                      for r in righe)
        # Sotto 9 una colonna di numeri sembra un errore; sopra 60 il
        # foglio diventa illeggibile e si scorre per niente.
        larghezze.append(max(9, min(60, massimo + 2)))
    return larghezze


def _xml_foglio(righe: list[list[Any]], intestazione: bool) -> str:
    xml_righe = []
    for numero, riga in enumerate(righe, 1):
        celle = []
        for i, valore in enumerate(riga, 1):
            stile = "1" if (intestazione and numero == 1) else ""
            celle.append(_cella(f"{_colonna(i)}{numero}", valore, stile))
        xml_righe.append(f'<row r="{numero}">{"".join(celle)}</row>')
    viste = ""
    if intestazione and len(righe) > 1:
        # La riga d'intestazione resta ferma: su un foglio di ore di 300
        # righe, senza questo, dopo tre schermate non sai piu' che colonna
        # stai leggendo.
        viste = ('<sheetViews><sheetView workbookViewId="0">'
                 '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
                 'state="frozen"/>'
                 '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
                 "</sheetView></sheetViews>")
    colonne = ""
    larghezze = _larghezze(righe)
    if larghezze:
        colonne = "<cols>" + "".join(
            f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(larghezze, 1)) + "</cols>"
    return (
        _XML_TESTA
        + f'<worksheet xmlns="{_NS_S}" xmlns:r="{_NS_R}">'
        + viste + colonne
        + f'<sheetData>{"".join(xml_righe)}</sheetData></worksheet>')


def _nome_foglio(nome: str, gia: list[str], indice: int) -> str:
    """Un nome valido e unico: Excel rifiuta `[]:*?/\\` e oltre 31 caratteri."""
    pulito = re.sub(r"[\[\]:*?/\\]", "-", str(nome or "").strip())[:31]
    if not pulito:
        pulito = f"Foglio{indice}"
    base, n = pulito, 2
    while pulito.lower() in {g.lower() for g in gia}:
        coda = f" {n}"
        pulito = base[:31 - len(coda)] + coda
        n += 1
    return pulito


def _pulisci_fogli(righe: Any, foglio: str, fogli: Any) -> list[dict[str, Any]]:
    """La lista dei fogli da scrivere, con i tetti controllati."""
    grezzi: list[dict[str, Any]] = []
    if fogli:
        for i, voce in enumerate(fogli, 1):
            if isinstance(voce, dict):
                grezzi.append({"nome": voce.get("nome") or f"Foglio{i}",
                               "righe": voce.get("righe") or []})
            else:
                grezzi.append({"nome": f"Foglio{i}", "righe": voce or []})
    else:
        grezzi.append({"nome": foglio or "Foglio1", "righe": righe or []})
    if len(grezzi) > MAX_FOGLI:
        raise ValueError(f"troppi fogli: {len(grezzi)} (massimo {MAX_FOGLI})")
    fuori: list[dict[str, Any]] = []
    nomi: list[str] = []
    for i, voce in enumerate(grezzi, 1):
        dati = [list(r) for r in (voce["righe"] or [])]
        if len(dati) > MAX_RIGHE:
            raise ValueError(f"troppe righe nel foglio '{voce['nome']}': "
                             f"{len(dati)} (massimo {MAX_RIGHE})")
        for indice, riga in enumerate(dati, 1):
            if len(riga) > MAX_COLONNE:
                raise ValueError(f"foglio '{voce['nome']}', riga {indice}: "
                                 f"{len(riga)} colonne (massimo "
                                 f"{MAX_COLONNE})")
        nome = _nome_foglio(voce["nome"], nomi, i)
        nomi.append(nome)
        fuori.append({"nome": nome, "righe": dati})
    return fuori


def scrivi_xlsx(percorso: str | Path, righe: Any = None,
                foglio: str = "Foglio1", *,
                fogli: Any = None, intestazione: bool = True) -> Path:
    """Scrive un .xlsx con una riga per lista di valori.

    `righe` e' una lista di liste e vale per un foglio solo; con `fogli`
    (lista di `{"nome": ..., "righe": ...}`) se ne scrivono quanti
    servono. `intestazione=True` mette in grassetto e blocca la prima
    riga: e' quello che rende il file un foglio invece di un elenco.
    """
    elenco = _pulisci_fogli(righe, foglio, fogli)
    parti: dict[str, str] = {"xl/styles.xml": _STILI}
    voci_libro: list[str] = []
    voci_tipi: list[str] = []
    voci_rel: list[str] = []
    for i, voce in enumerate(elenco, 1):
        voci_libro.append(f'<sheet name="{_xml(voce["nome"])}" sheetId="{i}" '
                          f'r:id="rId{i}"/>')
        voci_tipi.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>')
        voci_rel.append(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats'
            '.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>')
        parti[f"xl/worksheets/sheet{i}.xml"] = _xml_foglio(voce["righe"],
                                                           intestazione)
    stile_id = len(elenco) + 1
    voci_rel.append(
        f'<Relationship Id="rId{stile_id}" Type="http://schemas.openxmlformats'
        '.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
    # fullCalcOnLoad: le formule scritte senza valore calcolato devono
    # comparire appena il file si apre, non dopo un tocco.
    workbook = (
        _XML_TESTA
        + f'<workbook xmlns="{_NS_S}" xmlns:r="{_NS_R}"><sheets>'
        + "".join(voci_libro)
        + '</sheets><calcPr calcId="171027" fullCalcOnLoad="1"/></workbook>')
    relazioni_wb = (
        _XML_TESTA
        + f'<Relationships xmlns="{_NS_REL}">'
        + "".join(voci_rel) + "</Relationships>")
    tipi = (
        _XML_TESTA
        + f'<Types xmlns="{_NS_CT}">'
          '<Default Extension="rels" ContentType="application/'
          'vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/'
          'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(voci_tipi) + "</Types>")
    relazioni = (
        _XML_TESTA
        + f'<Relationships xmlns="{_NS_REL}"><Relationship Id="rId1" '
          'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
          'relationships/officeDocument" Target="xl/workbook.xml"/>'
          "</Relationships>")
    parti.update({
        "[Content_Types].xml": tipi,
        "_rels/.rels": relazioni,
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": relazioni_wb,
    })
    return _zip(percorso, parti)


# ------------------------------------------------------------------ pdf

def _cella_tabella(valore: Any) -> str:
    """Una cella Markdown: il `|` dentro il testo romperebbe la tabella."""
    return str("" if valore is None else valore).replace("|", "/").strip()


def scrivi_pdf(percorso: str | Path, titolo: str = "",
               paragrafi: Any = None, righe: Any = None) -> Path:
    """Scrive un .pdf impaginato: titolo, paragrafi e una tabella facoltativa.

    Il generatore e' `pdf_mini`, che c'era gia' e non era raggiungibile da
    nessun tool: il modello lo nominava e l'utente non poteva ottenerlo.
    Il testo passa da una codifica a larghezza singola (WinAnsi), quindi
    l'euro diventa `EUR` e i caratteri fuori tabella diventano spazi: e'
    un limite del font incorporato, non un bug da scoprire leggendo.
    """
    corpo = [str(p) for p in (paragrafi or [])]
    if len(corpo) > MAX_PARAGRAFI:
        raise ValueError(f"troppi paragrafi: {len(corpo)} (massimo "
                         f"{MAX_PARAGRAFI})")
    if righe:
        dati = [list(r) for r in righe]
        if len(dati) > MAX_RIGHE:
            raise ValueError(f"troppe righe nella tabella: {len(dati)} "
                             f"(massimo {MAX_RIGHE})")
        colonne = max(len(r) for r in dati)
        if colonne > MAX_COLONNE:
            raise ValueError(f"tabella con {colonne} colonne (massimo "
                             f"{MAX_COLONNE})")
        dati = [r + [""] * (colonne - len(r)) for r in dati]
        tabella = ["| " + " | ".join(_cella_tabella(v) for v in r) + " |"
                   for r in dati]
        # La riga di trattini e' il separatore che `pdf_mini` si aspetta
        # per capire che la prima riga e' un'intestazione.
        tabella.insert(1, "| " + " | ".join("---" for _ in range(colonne))
                       + " |")
        corpo.append("\n".join(tabella))
    from .pdf_mini import text_to_pdf

    return _scrivi_bytes(percorso, text_to_pdf("\n\n".join(corpo), titolo))


def _scrivi_bytes(percorso: str | Path, dati: bytes) -> Path:
    """Scrittura atomica di byte: un PDF troncato non si apre, come un docx."""
    destinazione = Path(percorso)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(dir=str(destinazione.parent),
                                      suffix=destinazione.suffix or ".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dati)
        os.replace(temporaneo, destinazione)
    except Exception:
        try:
            os.unlink(temporaneo)
        except OSError:
            pass
        raise
    return destinazione


# ---------------------------------------------------------------- aggiungi

def _parti_office(percorso: Path) -> dict[str, bytes]:
    """Le parti di uno zip Office, o un errore che dice cosa non va."""
    if not percorso.is_file():
        raise ValueError(f"non trovo il file da aggiornare: {percorso.name}")
    try:
        with zipfile.ZipFile(percorso) as z:
            return {nome: z.read(nome) for nome in z.namelist()}
    except zipfile.BadZipFile as e:
        raise ValueError(
            f"{percorso.name}: non e' un documento Office (non e' uno zip "
            f"valido: {e})") from None


def aggiungi_docx(percorso: str | Path, paragrafi: Any) -> dict[str, Any]:
    """Mette paragrafi in coda a un .docx esistente.

    L'inserimento e' testuale, prima di `<w:sectPr>`: riscrivere l'albero
    XML con ElementTree cambierebbe i prefissi dei namespace, e Word — che
    e' tollerante sul contenuto — non lo e' sui prefissi che non riconosce.
    """
    destinazione = Path(percorso)
    righe = [str(p) for p in (paragrafi or [])]
    if not righe:
        raise ValueError("niente da aggiungere: `paragrafi` e' vuoto")
    parti = _parti_office(destinazione)
    grezzo = parti.get("word/document.xml")
    if grezzo is None:
        raise ValueError(
            f"{destinazione.name}: e' uno zip ma non un documento Word "
            f"(manca word/document.xml)")
    testo = grezzo.decode("utf-8", errors="surrogateescape")
    if "xmlns:w=" not in testo:
        raise ValueError(
            f"{destinazione.name}: struttura non riconosciuta (il namespace "
            f"Word non e' dichiarato su w:document)")
    punti = testo.rfind("<w:sectPr")
    if punti < 0:
        punti = testo.rfind("</w:body>")
    if punti < 0:
        raise ValueError(
            f"{destinazione.name}: non trovo il corpo del documento dove "
            f"inserire i paragrafi")
    nuovo = testo[:punti] + "".join(_paragrafo(r) for r in righe) + testo[punti:]
    parti["word/document.xml"] = nuovo.encode("utf-8", errors="surrogateescape")
    _zip(destinazione, parti)
    return {"file": str(destinazione), "aggiunti": len(righe),
            "tipo": "paragrafi"}


def aggiungi_xlsx(percorso: str | Path, righe: Any) -> dict[str, Any]:
    """Aggiunge righe in coda al primo foglio di un .xlsx esistente.

    Le righe nuove sono scritte a mano (`<row>` con il numero successivo):
    il resto del foglio — stili, larghezze, formule, altre colonne — non
    viene toccato, e i numeri restano numeri.
    """
    destinazione = Path(percorso)
    dati = [list(r) for r in (righe or [])]
    if not dati:
        raise ValueError("niente da aggiungere: `righe` e' vuoto")
    if len(dati) > MAX_RIGHE:
        raise ValueError(f"troppe righe: {len(dati)} (massimo {MAX_RIGHE})")
    for indice, riga in enumerate(dati, 1):
        if len(riga) > MAX_COLONNE:
            raise ValueError(f"riga {indice}: {len(riga)} colonne (massimo "
                             f"{MAX_COLONNE})")
    parti = _parti_office(destinazione)
    fogli = sorted(nome for nome in parti
                   if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", nome))
    if not fogli:
        raise ValueError(
            f"{destinazione.name}: e' uno zip ma non un foglio Excel "
            f"(manca xl/worksheets/sheet1.xml)")
    testo = parti[fogli[0]].decode("utf-8", errors="surrogateescape")
    ultima = max((int(m) for m in re.findall(r'<row[^>]*\br="(\d+)"', testo)),
                 default=0)
    nuove = []
    for scarto, riga in enumerate(dati, 1):
        numero = ultima + scarto
        celle = "".join(_cella(f"{_colonna(i)}{numero}", valore)
                        for i, valore in enumerate(riga, 1))
        nuove.append(f'<row r="{numero}">{celle}</row>')
    if "</sheetData>" not in testo:
        raise ValueError(
            f"{destinazione.name}: il foglio non ha una sezione dati "
            f"riconoscibile (manca </sheetData>)")
    testo = testo.replace("</sheetData>", "".join(nuove) + "</sheetData>", 1)
    parti[fogli[0]] = testo.encode("utf-8", errors="surrogateescape")
    _zip(destinazione, parti)
    return {"file": str(destinazione), "aggiunti": len(dati),
            "tipo": "righe"}


def aggiungi(percorso: str | Path, formato: str = "", **campi: Any) -> dict[str, Any]:
    """Aggiunge a un file esistente: righe nel foglio, paragrafi nel testo."""
    destinazione = Path(percorso)
    scelto = (formato or destinazione.suffix.lstrip(".") or "").lower()
    if scelto == "docx":
        return aggiungi_docx(destinazione, campi.get("paragrafi"))
    if scelto == "xlsx":
        return aggiungi_xlsx(destinazione, campi.get("righe"))
    if scelto == "pdf":
        raise ValueError(
            "un PDF non si aggiorna: non ha un 'dopo' dove scrivere. "
            "Riscrivilo da capo con `office` (azione 'scrivi').")
    raise ValueError(
        f"formato non aggiornabile: '{scelto or destinazione.suffix}'. Si "
        f"aggiunge a .docx e .xlsx.")


def scrivi(percorso: str | Path, formato: str = "", **campi: Any) -> Path:
    """Lo smistamento per estensione, con l'errore che spiega."""
    destinazione = Path(percorso)
    scelto = (formato or destinazione.suffix.lstrip(".") or "").lower()
    if scelto == "docx":
        return scrivi_docx(destinazione, campi.get("titolo") or "",
                           campi.get("paragrafi"))
    if scelto == "xlsx":
        return scrivi_xlsx(destinazione, campi.get("righe"),
                           campi.get("foglio") or "Foglio1",
                           fogli=campi.get("fogli"),
                           intestazione=campi.get("intestazione", True))
    if scelto == "pdf":
        return scrivi_pdf(destinazione, campi.get("titolo") or "",
                          campi.get("paragrafi"), campi.get("righe"))
    raise ValueError(
        f"formato non supportato: '{scelto or destinazione.suffix}'. Si "
        f"scrivono .docx, .xlsx e .pdf; per il testo semplice `write_file`.")
