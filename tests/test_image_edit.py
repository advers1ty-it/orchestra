"""Montaggio deterministico: JPG/PNG/WebP, logo con alfa, testo, ritagli.

Il punto di questi check non e' che Pillow sappia disegnare (lo sappiamo):
e' che la foto di partenza NON venga rigenerata. Quindi si confrontano i
pixel fuori dalle zone montate prima e dopo, e si verifica che il logo
incollato sia il file del logo, non una sua imitazione.

Si usano immagini costruite qui, senza rete: un JPEG vero (salvato da
Pillow) e un PNG con un buco trasparente.
"""

import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from orchestra import montaggio as mo  # noqa: E402
from orchestra.tools import applica_profilo, default_registry  # noqa: E402
from orchestra.tools import image_edit as mod_edit  # noqa: E402
from orchestra.tools.image_edit import tool_image_edit  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


TMP = tempfile.mkdtemp(prefix="orchestra-montaggio-")

from PIL import Image  # noqa: E402


def jpeg_di_prova(larghezza=400, altezza=300, colore=(30, 90, 160)):
    """Un JPEG vero: serve a verificare che il giro JPG->JPG funzioni."""
    im = Image.new("RGB", (larghezza, altezza), colore)
    # Una riga di pixel diversi, per poter dire "questi pixel non sono
    # stati toccati" invece di guardare un colore uniforme.
    for x in range(larghezza):
        im.putpixel((x, 0), (255, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def png_logo(larghezza=60, altezza=60):
    """Un PNG con trasparenza: meta' rosso, meta' trasparente."""
    im = Image.new("RGBA", (larghezza, altezza), (0, 0, 0, 0))
    for y in range(altezza // 2):
        for x in range(larghezza):
            im.putpixel((x, y), (220, 20, 20, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


JPEG = jpeg_di_prova()
PNG = png_logo()

print("\n[1] Un JPEG entra e resta un JPEG")
m = mo.monta(JPEG, "image/jpeg", [], cartella=TMP, nome_file="base")
check("il formato e' JPEG", m.formato == "JPEG", m.formato)
check("l'estensione e' .jpg", m.percorso.suffix == ".jpg", m.percorso.name)
check("il file esiste", m.percorso.is_file(), str(m.percorso))
check("sta in immagini/", m.percorso.parent.name == "immagini")
check("la dimensione e' quella vera", (m.larghezza, m.altezza) == (400, 300),
      f"{m.larghezza}x{m.altezza}")

letto = Image.open(m.percorso)
check("il file salvato si riapre come JPEG", letto.format == "JPEG", letto.format)
check("e ha la stessa dimensione", letto.size == (400, 300), str(letto.size))

print("\n[2] Un JPEG non serviva rigenerarlo: vengono uguali (o quasi)")
# Una ri-codifica JPEG cambia i pixel di poco: si guarda il colore medio
# della zona lontana dal bordo, dove non c'e' niente da disegnare.
prima = Image.open(io.BytesIO(JPEG)).convert("RGB")
dopo = letto.convert("RGB")
px_prima = prima.getpixel((200, 150))
px_dopo = dopo.getpixel((200, 150))
distanza = max(abs(a - b) for a, b in zip(px_prima, px_dopo))
check("il pixel centrale e' lo stesso colore (tolleranza JPEG)", distanza <= 6,
      f"{px_prima} -> {px_dopo}")

print("\n[3] Testo e logo: il resto della foto non si muove")
ops = [
    {"tipo": "testo", "testo": "€540", "x": "50%", "y": "80%",
     "dimensione": 48, "grassetto": True, "ancora": "mm",
     "colore": "#ffffff", "riquadro": "#d40000", "margine": 16},
    {"tipo": "incolla", "immagine": PNG, "x": "96%", "y": "4%",
     "larghezza": "14%", "ancora": "ra"},
]
m2 = mo.monta(JPEG, "image/jpeg", ops, cartella=TMP, nome_file="promo",
              risolvi=lambda v: PNG)
check("il montaggio e' riuscito", m2.percorso.is_file(), str(m2.percorso))
check("due operazioni registrate", m2.operazioni == 2, str(m2.operazioni))
check("l'altezza e' cambiata? No: 400x300", (m2.larghezza, m2.altezza) == (400, 300))
check("nessuna nota di correzione", not m2.note, str(m2.note))

out = Image.open(m2.percorso).convert("RGB")
# In alto a destra c'e' il logo (meta' rossa): il pixel deve essere rosso.
r, g, b = out.getpixel((382, 20))
check("il logo e' stato incollato", r > 150 and g < 80 and b < 80, f"{(r, g, b)}")
# In basso al centro il riquadro del prezzo, sotto le cifre.
r, g, b = out.getpixel((200, 272))
check("il riquadro del testo c'e'", r > 150 and g < 80, f"{(r, g, b)}")
# Il pixel lontano da tutto deve restare il colore della foto.
r, g, b = out.getpixel((60, 200))
check("il resto della foto non e' stato ridisegnato", abs(r - 30) <= 8 and abs(g - 90) <= 8,
      f"{(r, g, b)}")

print("\n[4] L'originale non viene toccato, e non si sovrascrive")
m3 = mo.monta(JPEG, "image/jpeg", ops, cartella=TMP, nome_file="promo",
              risolvi=lambda v: PNG)
check("un secondo montaggio non sovrascrive il primo",
      m3.percorso != m2.percorso, f"{m2.percorso.name} vs {m3.percorso.name}")
check("e il primo esiste ancora", m2.percorso.is_file())
check("la cartella immagini ha piu' file", len(list(Path(m2.percorso.parent).glob('*'))) >= 3)

print("\n[5] Ritaglio e ridimensionamento")
m4 = mo.monta(JPEG, "image/jpeg", [
    {"tipo": "ritaglia", "x": 100, "y": 50, "larghezza": 200, "altezza": 100},
], cartella=TMP, nome_file="crop")
check("il ritaglio ha la misura chiesta", (m4.larghezza, m4.altezza) == (200, 100),
      f"{m4.larghezza}x{m4.altezza}")

m5 = mo.monta(JPEG, "image/jpeg", [
    {"tipo": "ridimensiona", "larghezza": 200},
], cartella=TMP, nome_file="scala")
check("con una sola misura le proporzioni restano",
      (m5.larghezza, m5.altezza) == (200, 150), f"{m5.larghezza}x{m5.altezza}")

m6 = mo.monta(JPEG, "image/jpeg", [
    {"tipo": "ridimensiona", "scala": "50%"},
], cartella=TMP, nome_file="meta")
check("la scala percentuale vale", (m6.larghezza, m6.altezza) == (200, 150),
      f"{m6.larghezza}x{m6.altezza}")

print("\n[6] Un ritaglio che esce viene ridotto, e lo dice")
m7 = mo.monta(JPEG, "image/jpeg", [
    {"tipo": "ritaglia", "x": 350, "y": 250, "larghezza": 500, "altezza": 500},
], cartella=TMP, nome_file="bordo")
check("il ritaglio e' stato ridotto ai bordi", (m7.larghezza, m7.altezza) == (50, 50),
      f"{m7.larghezza}x{m7.altezza}")
check("e c'e' una nota che lo spiega", bool(m7.note), str(m7.note))

print("\n[7] PNG: la trasparenza si conserva se il formato lo permette")
trasparente = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
buf = io.BytesIO()
trasparente.save(buf, format="PNG")
m8 = mo.monta(buf.getvalue(), "image/png", [
    {"tipo": "testo", "testo": "ok", "x": "50%", "y": "50%", "ancora": "mm"},
], cartella=TMP, nome_file="alfa")
check("l'uscita e' PNG", m8.formato == "PNG", m8.formato)
check("il canale alfa e' ancora li'",
      Image.open(m8.percorso).mode == "RGBA", Image.open(m8.percorso).mode)

print("\n[8] Un JPEG non conserva la trasparenza: si appiattisce")
m9 = mo.monta(buf.getvalue(), "image/png", [
    {"tipo": "testo", "testo": "ok", "x": "50%", "y": "50%", "ancora": "mm"},
], cartella=TMP, nome_file="jpeg-da-png", formato="jpg")
check("il formato chiesto vince", m9.formato == "JPEG", m9.formato)
check("e il file non ha alfa", Image.open(m9.percorso).mode == "RGB",
      Image.open(m9.percorso).mode)

print("\n[9] Gli errori dicono cosa correggere")
prove = [
    ("operazione sconosciuta", [{"tipo": "sfoca"}], "sconosciuto"),
    ("testo senza testo", [{"tipo": "testo", "x": 10, "y": 10}], "testo"),
    ("ancora inventata", [{"tipo": "testo", "testo": "x", "ancora": "zz"}], "ancora"),
    ("colore inventato", [{"tipo": "testo", "testo": "x", "colore": "blu-marcio"}],
     "colore"),
    ("operazioni mancanti", None, "operazioni"),
]
for nome, ops_prova, atteso in prove:
    try:
        mo.monta(JPEG, "image/jpeg", ops_prova, cartella=TMP, nome_file="err")
        check(nome, False, "nessun errore")
    except mo.MontaggioError as e:
        check(nome, atteso in str(e).lower(), str(e))

print("\n[10] Cosa non e' un'immagine viene rifiutato")
for nome, dati, atteso in [
    ("un PDF", b"%PDF-1.4\n" + b"0" * 100, "immagine"),
    ("un file vuoto", b"", "vuota"),
]:
    try:
        mo.monta(dati, "application/pdf", [{"tipo": "ridimensiona", "larghezza": 10}],
                 cartella=TMP, nome_file="no")
        check(nome, False, "nessun errore")
    except mo.MontaggioError as e:
        check(nome, atteso in str(e).lower(), str(e))

print("\n[11] Il tool: anteprima, profili, registro")
tool = tool_image_edit()
check("il nome e' image_edit", tool.name == "image_edit", tool.name)
check("lo schema chiede le operazioni", "operazioni" in tool.schema["required"])
# La root del test e' TMP: i percorsi si risolvono li'.
os.environ["ORCHESTRA_ROOT"] = TMP
esito = tool.handler(immagine="non-esiste.png",
                     operazioni=[{"tipo": "ridimensiona", "larghezza": 100}])
check("un percorso mancante e' un errore leggibile",
      "ERRORE" in esito.text and "non trovo" in esito.text.lower(), esito.text[:160])

# Il percorso vero passa dal confine del progetto: si scrive l'allegato in
# TMP e si legge dal tool con la root puntata li'.
# `image_gen` scrive nella cartella del pacchetto: qui si punta il montaggio
# a TMP, o il test sporcherebbe il repository con `immagini/`.
mod_edit._root_progetto = lambda: Path(TMP)
Path(TMP, "foto.jpg").write_bytes(JPEG)
esito2 = tool.handler(immagine="foto.jpg", operazioni=[
    {"tipo": "testo", "testo": "DISPONIBILE", "x": "50%", "y": "50%",
     "dimensione": 40, "ancora": "mm"},
], nome_file="da-tool")
check("il montaggio dal tool riesce", "Immagine montata" in esito2.text, esito2.text[:200])
check("e porta un'anteprima", len(esito2.anteprime) == 1)
check("l'anteprima e' una data URL",
      str(esito2.anteprime[0]).startswith("data:image/"), str(esito2.anteprime[0])[:40])

reg = default_registry()
check("image_edit e' registrato", "image_edit" in reg.all_names())
for profilo in ("base", "ricerca", "skill", "pieno"):
    reg2 = default_registry()
    applica_profilo(reg2, profilo)
    check(f"attivo nel profilo {profilo}", "image_edit" in reg2.nomi_attivi(),
          str(sorted(reg2.nomi_attivi()))[:160])

shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 60)
print(f"  PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
    sys.exit(1)
print("=" * 60)
