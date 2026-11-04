"""Gli allegati Office: .docx, .xlsx, .pptx letti come testo.

I file sono costruiti qui, come zip di XML minimi ma validi: un test che
scaricasse un .docx da internet non girerebbe offline, e un test che
usasse un binario opaco non direbbe perche' fallisce.

Il difetto che si previene: un .docx allegato veniva rifiutato con
"formato non riconosciuto" benche' sia uno zip di XML che si legge senza
dipendenze. E il caso opposto — un file che si spaccia per .docx — deve
dire cos'e', non esplodere.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

os.environ.setdefault("ORCHESTRA_HOME",
                      tempfile.mkdtemp(prefix="orchestra_office_"))

from orchestra import attachments, office  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def zip_di(parti: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, testo in parti.items():
            z.writestr(nome, testo)
    return buf.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def docx(*paragrafi: str) -> bytes:
    corpo = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragrafi)
    return zip_di({
        "word/document.xml":
            f'<?xml version="1.0"?><w:document {W}><w:body>'
            f"{corpo}</w:body></w:document>",
    })


def xlsx() -> bytes:
    return zip_di({
        "xl/workbook.xml":
            f'<workbook {S}><sheets><sheet name="Vendite" sheetId="1"/>'
            f"</sheets></workbook>",
        "xl/sharedStrings.xml":
            f'<sst {S}><si><t>Mese</t></si><si><t>Totale</t></si>'
            f"<si><t>Gennaio</t></si></sst>",
        "xl/worksheets/sheet1.xml":
            f'<worksheet {S}><sheetData>'
            f'<row r="1"><c r="A1" t="s"><v>0</v></c>'
            f'<c r="B1" t="s"><v>1</v></c></row>'
            f'<row r="2"><c r="A2" t="s"><v>2</v></c>'
            f'<c r="B2"><v>120</v></c></row>'
            f"</sheetData></worksheet>",
    })


def pptx() -> bytes:
    def slide(testo: str) -> str:
        return (f'<p:sld xmlns:p="http://schemas.openxmlformats.org/'
                f'presentationml/2006/main" {A}><a:p><a:r><a:t>{testo}'
                f"</a:t></a:r></a:p></p:sld>")

    return zip_di({
        "ppt/slides/slide1.xml": slide("Titolo della prima"),
        "ppt/slides/slide2.xml": slide("Punto due"),
    })


print("\n== un .docx si legge come testo ==")

a = attachments.allega("contratto.docx", docx("Primo paragrafo", "Secondo"))
check("e' testo, non un rifiuto", a.kind == "testo", a.kind)
check("il primo paragrafo c'e'", "Primo paragrafo" in a.testo, a.testo)
check("il secondo paragrafo c'e'", "Secondo" in a.testo, a.testo)
check("i paragrafi sono su righe diverse",
      "Primo paragrafo" in a.testo.splitlines()[0], a.testo)
check("non costa come un'immagine", a.token_stimati < 100,
      str(a.token_stimati))

print("\n== un .xlsx porta i valori e il nome del foglio ==")

a = attachments.allega("vendite.xlsx", xlsx())
check("e' testo", a.kind == "testo", a.kind)
check("il nome del foglio c'e'", "Vendite" in a.testo, a.testo)
check("le stringhe condivise sono risolte",
      "Gennaio" in a.testo and "Totale" in a.testo, a.testo)
check("i numeri ci sono", "120" in a.testo, a.testo)
check("una riga e' una riga", "Gennaio | 120" in a.testo, a.testo)

print("\n== un .pptx conserva l'ordine delle diapositive ==")

a = attachments.allega("deck.pptx", pptx())
check("e' testo", a.kind == "testo", a.kind)
check("la prima diapositiva c'e'", "Titolo della prima" in a.testo, a.testo)
check("la seconda c'e'", "Punto due" in a.testo, a.testo)
check("l'ordine e' quello giusto",
      a.testo.index("Titolo") < a.testo.index("Punto"), a.testo)

print("\n== un file che mente viene detto per quello che e' ==")

# Un PNG con l'estensione sbagliata NON si legge come Office: il magic
# number vince sul nome, come per tutti gli altri allegati, e diventa
# un'immagine. Il test lo fissa perche' e' una decisione, non un caso.
prova = b"\x89PNG\r\n\x1a\n" + b"0" * 100
a = attachments.allega("finto.docx", prova)
check("un PNG chiamato .docx resta un'immagine", a.kind == "image", a.kind)
check("con il MIME vero, non quello dell'estensione",
      a.mime == "image/png", a.mime)

try:
    attachments.allega("rotto.docx", zip_di({"altro.txt": "niente"}))
    check("uno zip senza document.xml viene rifiutato", False)
except attachments.AttachmentError as e:
    check("uno zip senza document.xml viene rifiutato", True)
    check("l'errore dice cosa manca", "document" in str(e).lower(), str(e))

print("\n== un'estensione Office non e' un testo qualunque ==")

try:
    attachments.allega("foglio.xlsx", b"non sono uno zip")
    check("un .xlsx non zip viene rifiutato", False)
except attachments.AttachmentError as e:
    check("un .xlsx non zip viene rifiutato", True)

print("\n== il modulo diretto dice la stessa cosa ==")

check("estensione riconosciuta", office.estensione("A.DOCX") == "docx")
check("estensione ignota", office.estensione("a.txt") == "")
try:
    office.estrai("vuoto.docx", docx(""))
    check("un documento senza testo e' un errore", False)
except office.OfficeError:
    check("un documento senza testo e' un errore", True)

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
