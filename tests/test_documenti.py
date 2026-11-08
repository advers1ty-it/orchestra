"""I buchi trovati controllando i tool, uno per uno.

Questo file non prova una funzione nuova: prova che i sette difetti trovati
in revisione restino chiusi. Ognuno aveva la stessa forma — il sistema
sapeva una cosa e ne diceva un'altra:

1. un PDF con testo dichiarato "scansionato" perche' mancava `pypdf` (e
   perche' `attachments.py` usava `io` senza importarlo, dentro un
   `except Exception` che inghiottiva il NameError);
2. `read_file` che restituiva 4.800 caratteri di struttura PDF come se
   fossero righe di testo, e un PNG come caratteri casuali;
3. un .txt cp1252 con gli accenti trasformati in U+FFFD in silenzio;
4. `edit_file` che riscriveva i fine riga di tutto il file (CRLF → LF);
5. `_root()` dei tool che puntava dentro il pacchetto invece che alla
   cartella di lavoro;
6. `cron` e `mcp` fuori da ogni profilo, `pieno` compreso;
7. `screenshot_view` — l'unico modo di vedere un'immagine — descritto
   come "screenshot" e senza il gate dei permessi.

I fixture sono costruiti qui: un PDF con xref valida (un PDF senza
`startxref` non e' un PDF, e provarlo sarebbe provare il fixture), un
.docx e un .xlsx con i namespace veri, un PNG di un pixel.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Il test stampa accenti veri: su una console Windows cp1252 `print`
# solleverebbe UnicodeEncodeError, e il fallimento sembrerebbe del codice
# provato invece che del terminale.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

WORK = tempfile.mkdtemp(prefix="orchestra_doc_")
os.environ["ORCHESTRA_ROOT"] = WORK

from orchestra import attachments, office  # noqa: E402
from orchestra.tools import _PROFILI, _root, default_registry  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def pdf_con_testo(testo: str) -> bytes:
    """Un PDF di una pagina, con vero testo e con la tabella xref."""
    flusso = f"BT /F1 14 Tf 72 700 Td ({testo}) Tj ET".encode()
    oggetti = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length %d>>stream\n" % len(flusso) + flusso + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    posizioni = []
    for i, corpo in enumerate(oggetti, 1):
        posizioni.append(len(out))
        out += b"%d 0 obj\n" % i + corpo + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(oggetti) + 1)
    out += b"0000000000 65535 f \n"
    for p in posizioni:
        out += b"%010d 00000 n \n" % p
    out += (b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n"
            % (len(oggetti) + 1, xref))
    return bytes(out)


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def docx_con_testo(testo: str) -> bytes:
    import io as _io

    b = _io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>{testo}'
                   f'</w:t></w:r></w:p></w:body></w:document>')
    return b.getvalue()


def xlsx_con_listino(prezzo: str) -> bytes:
    import io as _io

    b = _io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml",
                   f'<workbook xmlns="{S}"><sheets><sheet name="Listino" '
                   f'sheetId="1"/></sheets></workbook>')
        z.writestr("xl/worksheets/sheet1.xml",
                   f'<worksheet xmlns="{S}"><sheetData><row><c t="inlineStr">'
                   f'<is><t>iPhone 128 GB {prezzo}</t></is></c></row>'
                   f'</sheetData></worksheet>')
    return b.getvalue()


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000154a24f5f0000000049454e44ae42"
    "6082"
)


def scrivi(nome: str, dati: bytes) -> str:
    with open(os.path.join(WORK, nome), "wb") as f:
        f.write(dati)
    return nome


PDF = scrivi("fattura.pdf", pdf_con_testo("Totale 540 euro - Ricambi originali"))
DOCX = scrivi("offerta.docx", docx_con_testo("Prezzo 540 euro, disponibile"))
XLSX = scrivi("listino.xlsx", xlsx_con_listino("540"))
PNG = scrivi("logo.png", PNG_1PX)
CP = scrivi("clienti.txt", "Perché è così: € 540\n".encode("cp1252"))
UTF = scrivi("nota.md", "Perché è così: € 540\n".encode("utf-8"))

r = default_registry()
leggi = r.get("read_file").handler

print("\n[1] Un PDF con testo si legge, e il testo è quello")
att = attachments.allega(PDF, pdf_con_testo("Totale 540 euro"))
check("l'allegato porta il testo", "540" in (att.testo or ""), att.testo)
check("e non le immagini", att.immagini == [], str(att.immagini[:1]))
check("il numero di pagine è quello vero", att.pagine == 1, str(att.pagine))
out = leggi(PDF)
check("read_file estrae il testo", "540" in out and "%PDF" not in out, out[:120])
check("e dice da dove viene", "estratto dal PDF" in out, out[:120])

print("\n[2] Se manca pypdf, l'errore dice la verità")
salvato = sys.modules.get("pypdf")
sys.modules["pypdf"] = None  # import pypdf -> ImportError
try:
    testo, _pagine, motivo = attachments._leggi_pdf(pdf_con_testo("Totale 540"))
finally:
    if salvato is None:
        sys.modules.pop("pypdf", None)
    else:
        sys.modules["pypdf"] = salvato
check("senza pypdf il testo non c'è", testo == "", testo[:40])
check("ma il motivo è la libreria", "pypdf" in motivo, motivo)
check("e dice cosa fare", "pip install" in motivo, motivo)
check("non accusa il file di essere scansionato",
      "scansionat" not in motivo.lower(), motivo)

print("\n[3] Office e immagini: il testo giusto, o il tool giusto")
out = leggi(DOCX)
check("dal .docx esce il testo", "540" in out and "Prezzo" in out, out[:120])
out = leggi(XLSX)
check("dal .xlsx esce la cella", "540" in out, out[:120])
check("e il nome del foglio", "Listino" in out, out[:120])
out = leggi(PNG)
check("su un PNG non mostra caratteri casuali",
      "\ufffd" not in out and len(out) < 400, out[:120])
check("e manda a screenshot_view", "screenshot_view" in out, out[:160])
check("senza fingere di averlo letto", "non testo" in out or "non è testo" in out,
      out[:160])

print("\n[4] Il testo non UTF-8 non si corrompe più")
out = leggi(CP)
check("gli accenti ci sono", "Perché è così: € 540" in out, out)
check("nessun carattere di sostituzione", "\ufffd" not in out, out)
check("e lo dice: cp1252", "cp1252" in out, out[:80])
out = leggi(UTF)
check("un UTF-8 corretto non ha la nota", "non UTF-8" not in out, out[:80])
check("ma il contenuto è identico", "Perché è così: € 540" in out, out)

print("\n[5] edit_file conserva i fine riga del file")
CRLF = os.path.join(WORK, "win.py")
with open(CRLF, "wb") as f:
    f.write(b"riga uno\r\nvalore = 540\r\nriga tre\r\n")
esito = r.get("edit_file").handler(path=CRLF, trova="valore = 540",
                                   sostituisci="valore = 600")
with open(CRLF, "rb") as f:
    dopo = f.read()
check("la sostituzione è avvenuta", "valore = 600" in dopo.decode(), esito)
check("il file è ancora tutto CRLF", b"\r\n" in dopo and b"\n" not in dopo.replace(b"\r\n", b""),
      repr(dopo))
check("e le righe sono le stesse di prima", dopo.count(b"\r\n") == 3, repr(dopo))

with open(CRLF, "wb") as f:
    f.write(b"def f():\r\n    return 1\r\n\r\ndef g():\r\n    return 2\r\n")
# Il modello copia da read_file, che mostra i \n: la ricerca multilinea
# deve combaciare lo stesso.
esito = r.get("edit_file").handler(path=CRLF, trova="    return 1\n\ndef g():",
                                   sostituisci="    return 10\n\ndef g():")
with open(CRLF, "rb") as f:
    dopo = f.read()
check("una stringa multilinea copiata da read_file combacia",
      b"return 10" in dopo, esito)
check("e i fine riga restano CRLF",
      b"\r\n" in dopo and b"\n" not in dopo.replace(b"\r\n", b""), repr(dopo))

print("\n[6] La root dei tool è la cartella di lavoro")
check("_root() non è la cartella del pacchetto",
      str(_root()).rstrip("\\/") != os.path.join(
          os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orchestra"),
      str(_root()))
check("_root() è ORCHESTRA_ROOT",
      os.path.normcase(str(_root())) == os.path.normcase(WORK),
      f"{_root()} != {WORK}")
vedi = r.get("screenshot_view").handler(PNG)
check("con un percorso RELATIVO l'immagine si vede",
      len(vedi.immagini) == 1, vedi.text[:120])
check("e il testo la descrive", "immagine" in vedi.text.lower() or "png" in vedi.text.lower(),
      vedi.text[:120])
vedi = r.get("screenshot_view").handler(PDF)
check("sul PDF restituisce il testo, non un rifiuto",
      "540" in vedi.text and not vedi.immagini, vedi.text[:160])

# Fuori dalla cartella di lavoro: senza nessuno a cui chiedere (CLI,
# test) la risposta è no, e non deve arrivare l'immagine.
fuori = tempfile.mkdtemp(prefix="orchestra_fuori_")
try:
    p_fuori = os.path.join(fuori, "privato.png")
    with open(p_fuori, "wb") as f:
        f.write(PNG_1PX)
    no = r.get("screenshot_view").handler(p_fuori)
    check("fuori dal root non legge senza permesso",
          no.immagini == [], f"ha mandato l'immagine: {no.immagini[:1]}")
    check("e lo spiega", "fuori" in no.text.lower() or "permesso" in no.text.lower(),
          no.text[:160])
finally:
    shutil.rmtree(fuori, ignore_errors=True)

print("\n[7] I profili contengono quello che promettono")
check("cron è nel profilo pieno", "cron" in _PROFILI["pieno"])
check("mcp è nel profilo pieno", "mcp" in _PROFILI["pieno"])
check("calculate resta nel profilo skill", "calculate" in _PROFILI["skill"],
      "un profilo alto non deve togliere capacità")
check("screenshot_view sta dove sta image_edit",
      all("screenshot_view" in _PROFILI[p] for p in ("base", "ricerca", "skill", "pieno")),
      str({p: "screenshot_view" in _PROFILI[p] for p in _PROFILI}))
mancanti = set(r.all_names()) - _PROFILI["pieno"]
check("il profilo pieno ha TUTTI i tool registrati", not mancanti,
      f"fuori dal profilo pieno: {sorted(mancanti)}")

# Il profilo "auto" sceglie dalla PROSSIMA mossa, non dalla prima parola
# che combacia. La regola che lo rende verificabile: il profilo scelto
# contiene i tool che il testo richiede. Se non li contiene, l'agente
# risponde "tool inesistente" a un compito che ha letto per intero.
from orchestra.tools import profilo_per_testo  # noqa: E402

for testo, atteso, tool in (
    ("apri https://esempio.it e dimmi cosa c'e'", "pieno", "browser_apri"),
    ("clicca il pulsante Accedi sul sito", "pieno", "browser_click"),
    ("spegni la finestra del desktop", "pieno", "computer_click"),
    ("ogni giorno alle 8 fai il riepilogo", "pieno", "cron"),
    ("usa la skill del deploy per pubblicare", "skill", "skill_leggi"),
    ("cerca sul web quanto costa", "ricerca", "web_cerca"),
    ("sistema il bug in src/app.py", "base", "read_file"),
    ("genera un'immagine di un gatto", "base", "image_gen"),
):
    scelto = profilo_per_testo(testo)
    check(f"auto: {testo[:34]!r} -> {atteso}", scelto == atteso, scelto)
    check(f"  e {tool} c'e'", tool in _PROFILI[scelto],
          f"{scelto} non ha {tool}")

print("\n[8] Il contratto dice cosa sanno fare, in inglese")
descr = r.get("screenshot_view").description.lower()
check("screenshot_view parla di immagini, non solo di schermi",
      "image" in descr or "photo" in descr, descr[:120])
check("e nomina il percorso relativo", "relativ" in descr, descr[:120])
descr = r.get("read_file").description.lower()
check("read_file dice che legge i PDF", "pdf" in descr, descr[:140])
check("e manda le immagini a screenshot_view", "screenshot_view" in descr, descr[:140])

# Il contratto lo legge il modello, quindi e' in inglese (le descrizioni
# in italiano dentro uno schema inglese erano la regola prima, non
# l'eccezione). Queste due invarianti sono quelle che si rompono in
# silenzio: un parametro senza descrizione il modello lo riempie a caso
# o lo omette, e un carattere corrotto e' una parola che non esiste.
SENZA = [(t.name, k) for t in r.active
         for k, v in (t.schema.get("properties") or {}).items()
         if not (v.get("description") or "").strip()]
check("ogni parametro di ogni tool ha una descrizione", not SENZA,
      f"senza descrizione: {SENZA[:8]}")
CORROTTI = [(t.name, k) for t in r.active
            for k, v in ([(None, {"description": t.description})]
                         + list((t.schema.get("properties") or {}).items()))
            if "\ufffd" in (v.get("description") or "")]
check("nessuna descrizione contiene caratteri corrotti", not CORROTTI,
      f"corrotti: {CORROTTI[:8]}")
IT = (" leggi ", " legge ", " scrive ", " percorso", " riga ", " esegue ",
      " cerca ", " restituisce ", " apre ", " elenca ")
ITALIANE = [t.name for t in r.active
            if any(w in (t.description or "").lower() for w in IT)]
check("le descrizioni dei tool sono in inglese", not ITALIANE,
      f"ancora in italiano: {ITALIANE}")

print("\n[9] edit_file lavora nella codifica del file, e sui binari si ferma")
CP2 = scrivi("anagrafica.txt", "Perché è così: € 540\n".encode("cp1252"))
esito = r.get("edit_file").handler(path=CP2, trova="540", sostituisci="600")
with open(os.path.join(WORK, CP2), "rb") as f:
    byte_dopo = f.read()
check("il cp1252 resta cp1252 (é è una sola lettera, 0xE9)",
      b"Perch\xe9 \xe8 cos\xec: \x80 600" in byte_dopo, repr(byte_dopo))
check("e non è stato convertito in UTF-8", b"\xc3\xa9" not in byte_dopo,
      repr(byte_dopo))
check("read_file lo rilegge uguale", "Perché è così: € 600" in leggi(CP2),
      leggi(CP2))

BOMN = scrivi("bom.txt", b"\xef\xbb\xbfriga uno\n")
r.get("edit_file").handler(path=BOMN, trova="uno", sostituisci="due")
with open(os.path.join(WORK, BOMN), "rb") as f:
    con_bom = f.read()
check("il BOM non si perde modificando", con_bom.startswith(b"\xef\xbb\xbf") and b"due" in con_bom,
      repr(con_bom))

prima = PNG_1PX
esito = r.get("edit_file").handler(path=PNG, trova="a", sostituisci="b")
with open(os.path.join(WORK, PNG), "rb") as f:
    check("su un PNG il file non viene toccato", f.read() == prima)
check("e l'errore dice cos'è davvero", "immagine PNG" in esito, esito)
check("non lo chiama 'binario?' senza sapere", "binario?" not in esito, esito)

with open(os.path.join(WORK, "vuoto.txt"), "w", encoding="utf-8"):
    pass

shutil.rmtree(WORK, ignore_errors=True)

print("\n" + "=" * 62)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
