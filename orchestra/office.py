"""Il testo di un .docx, .xlsx o .pptx, senza dipendenze.

Un file Office e' uno zip di XML: non serve Word, non serve python-docx,
e non serve installare niente. Basta `zipfile` e `xml.etree`. Questa e'
la ragione per cui vale la pena farlo qui invece di aggiungere una
libreria per tre formati che leggiamo in una direzione sola.

COSA SI PRENDE

Il testo, e basta: paragrafi in ordine, celle di una tabella come righe
separate da `|`, un foglio per volta con il suo nome. Niente stili,
niente immagini, niente formule (di una formula si legge il valore
calcolato, se c'e': il risultato e' quello che serve a chi legge).

COSA NON SI PRENDE

Un foglio con 200.000 celle e' un foglio che non entra in un messaggio.
Si tronca e lo si dice, invece di mandare 8 MB al modello e ricevere un
errore che sembra di rete.

L'XML e' input non fidato: si legge con ElementTree, che non esegue
niente, e si ferma alle dimensioni dichiarate. Un file che dice di essere
un .docx e non lo e' solleva ValueError con il motivo, non un
Traceback illeggibile.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

# Oltre questo il testo non e' piu' un allegato: e' un documento che va
# letto nella cartella di lavoro, con read_file, a pezzi.
MAX_CARATTERI = 150_000

ESTENSIONI = {"docx", "xlsx", "pptx"}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


class OfficeError(ValueError):
    """Un file Office che non si riesce a leggere. Il messaggio spiega."""


def estensione(nome: str) -> str:
    """`docx`/`xlsx`/`pptx` se il nome lo dichiara, altrimenti ""."""
    m = re.search(r"\.([A-Za-z0-9]+)$", nome or "")
    ext = m.group(1).lower() if m else ""
    return ext if ext in ESTENSIONI else ""


def estrai(nome: str, dati: bytes) -> tuple[str, str]:
    """Ritorna (descrizione del tipo, testo).

    Solleva OfficeError se il file non e' quello che il nome dichiara o
    se il formato non e' leggibile. Non tocca il disco.
    """
    ext = estensione(nome)
    if not ext:
        raise OfficeError(f"{nome}: non e' un file Office")
    try:
        z = zipfile.ZipFile(io.BytesIO(dati))
    except zipfile.BadZipFile:
        raise OfficeError(
            f"{nome}: non e' un archivio Office valido (lo zip e' rotto o "
            f"il file non e' un .{ext})") from None
    try:
        if ext == "docx":
            testo, tipo = _docx(z), "un documento Word"
        elif ext == "xlsx":
            testo, tipo = _xlsx(z), "un foglio Excel"
        else:
            testo, tipo = _pptx(z), "una presentazione PowerPoint"
    except (KeyError, ET.ParseError, OSError, ValueError) as e:
        raise OfficeError(
            f"{nome}: non riesco a leggere il contenuto (un .{ext} valido "
            f"ha le parti XML che mi aspetto): {e}") from None
    finally:
        z.close()
    testo = testo.strip()
    if not testo:
        raise OfficeError(
            f"{nome}: il file si apre ma non contiene testo. Se il "
            f"contenuto e' tutto in immagini, serve un modello con la "
            f"visione: converti le pagine in PNG.")
    if len(testo) > MAX_CARATTERI:
        testo = (testo[:MAX_CARATTERI]
                 + f"\n\n... (troncato: il file ha piu' di "
                   f"{MAX_CARATTERI} caratteri)")
    return tipo, testo


def _xml(z: zipfile.ZipFile, nome: str) -> ET.Element:
    return ET.fromstring(z.read(nome))


def _docx(z: zipfile.ZipFile) -> str:
    root = _xml(z, "word/document.xml")
    righe: list[str] = []
    for p in root.iter(_W + "p"):
        pezzi: list[str] = []
        for nodo in p.iter():
            tag = nodo.tag
            if tag == _W + "t":
                pezzi.append(nodo.text or "")
            elif tag == _W + "tab":
                pezzi.append("\t")
            elif tag in (_W + "br", _W + "cr"):
                pezzi.append("\n")
        riga = "".join(pezzi).rstrip()
        # Un paragrafo vuoto in Word e' spaziatura, non contenuto: si
        # tengono una riga sola tra i blocchi, non dieci.
        if riga:
            righe.append(riga)
        elif righe and righe[-1] != "":
            righe.append("")
    return "\n".join(righe)


def _xlsx(z: zipfile.ZipFile) -> str:
    condivise: list[str] = []
    try:
        radice = _xml(z, "xl/sharedStrings.xml")
        for si in radice.iter(_S + "si"):
            condivise.append("".join(t.text or "" for t in si.iter(_S + "t")))
    except KeyError:
        pass  # un foglio senza stringhe condivise e' legittimo

    fogli = sorted(n for n in z.namelist()
                   if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    if not fogli:
        raise KeyError("nessun foglio in xl/worksheets/")
    nomi = _nomi_fogli(z)
    blocchi: list[str] = []
    for i, nome_foglio in enumerate(fogli):
        radice = ET.fromstring(z.read(nome_foglio))
        righe: list[str] = []
        for row in radice.iter(_S + "row"):
            celle: list[str] = []
            for c in row.iter(_S + "c"):
                tipo = c.get("t") or ""
                if tipo == "s":
                    v = c.find(_S + "v")
                    try:
                        celle.append(condivise[int(v.text or "0")])
                    except (IndexError, TypeError, ValueError):
                        celle.append("")
                elif tipo == "inlineStr":
                    celle.append("".join(t.text or ""
                                         for t in c.iter(_S + "t")))
                else:
                    v = c.find(_S + "v")
                    valore = v.text if v is not None and v.text else ""
                    if not valore:
                        # Una formula scritta da noi non ha il valore
                        # calcolato (lo fa Excel aprendo il file): senza
                        # questo ramo la cella sembrerebbe vuota, e chi
                        # rilegge crederebbe di aver perso la formula.
                        f = c.find(_S + "f")
                        if f is not None and (f.text or "").strip():
                            valore = "=" + f.text.strip()
                    celle.append(valore)
            if any(x.strip() for x in celle):
                righe.append(" | ".join(x.strip() for x in celle))
        titolo = nomi[i] if i < len(nomi) else f"Foglio {i + 1}"
        if righe:
            blocchi.append(f"### {titolo}\n" + "\n".join(righe))
    return "\n\n".join(blocchi)


def _nomi_fogli(z: zipfile.ZipFile) -> list[str]:
    try:
        radice = _xml(z, "xl/workbook.xml")
    except KeyError:
        return []
    # Gli sheet nell'ordine in cui Excel li mostra; il nome e' quello che
    # l'utente vede, e senza di lui due fogli sembrano lo stesso.
    return [s.get("name") or "" for s in radice.iter(_S + "sheet")]


def _pptx(z: zipfile.ZipFile) -> str:
    diapositive = sorted(
        (n for n in z.namelist()
         if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
        key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)),
    )
    if not diapositive:
        raise KeyError("nessuna diapositiva in ppt/slides/")
    blocchi: list[str] = []
    for n, nome_slide in enumerate(diapositive, 1):
        radice = ET.fromstring(z.read(nome_slide))
        righe: list[str] = []
        for p in radice.iter(_A + "p"):
            testo = "".join(t.text or "" for t in p.iter(_A + "t")).strip()
            if testo:
                righe.append(testo)
        if righe:
            blocchi.append(f"### Diapositiva {n}\n" + "\n".join(righe))
    return "\n\n".join(blocchi)
