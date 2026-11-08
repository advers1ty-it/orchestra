"""Inpainting: la maschera, la sua costruzione, e il multipart con due file.

Tre cose possono rompersi qui, e nessuna si vede a occhio nel codice:

1. la convenzione dei colori (trasparente = ridisegna, opaco = non toccare);
2. la misura (una maschera piu' piccola dell'immagine fa un 400 dal provider);
3. il wire format (OpenAI vuole una seconda parte `mask`, non un base64 nel
   JSON).

Le prime due si verificano sui pixel, la terza sul corpo della richiesta con
`urlopen` finto: nessuna rete, nessuna chiave vera, nessun credito speso.
"""

import base64
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from orchestra import image_gen as ig  # noqa: E402
from orchestra import montaggio as mo  # noqa: E402
from orchestra.tools import image_gen as mod_gen  # noqa: E402
from orchestra.tools.image_gen import tool_image_gen  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


TMP = tempfile.mkdtemp(prefix="orchestra-inpaint-")

from PIL import Image  # noqa: E402


def jpeg_di_prova(larghezza=400, altezza=300):
    im = Image.new("RGB", (larghezza, altezza), (30, 90, 160))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


JPEG = jpeg_di_prova()
# Un PNG di un pixel: la risposta finta di OpenAI.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg=="
)
B64_PNG = base64.b64encode(PNG_1PX).decode("ascii")


def env(**valori):
    base = {"ORCHESTRA_IMAGE_PROVIDER": ""}
    base.update(valori)
    return base


print("\n[1] La maschera: trasparente dove si ridisegna, opaco altrove")
mask = mo.maschera(JPEG, [{"tipo": "rettangolo", "x": 300, "y": 200,
                           "larghezza": 80, "altezza": 60}])
im = Image.open(io.BytesIO(mask))
check("e' un PNG", im.format == "PNG", im.format)
check("ha il canale alfa", im.mode == "RGBA", im.mode)
check("ha la misura dell'immagine", im.size == (400, 300), str(im.size))
alpha = im.getchannel("A")
check("dentro la zona e' trasparente (0)", alpha.getpixel((340, 230)) == 0,
      str(alpha.getpixel((340, 230))))
check("fuori dalla zona e' opaco (255)", alpha.getpixel((50, 50)) == 255,
      str(alpha.getpixel((50, 50))))
check("il bordo della zona e' netto senza `morbido`",
      alpha.getpixel((299, 230)) == 255 and alpha.getpixel((301, 230)) == 0,
      f"{alpha.getpixel((299, 230))}/{alpha.getpixel((301, 230))}")

print("\n[2] Percentuali, ellisse, piu' zone, bordo sfumato")
mask2 = mo.maschera(JPEG, [
    {"tipo": "rettangolo", "x": "0%", "y": "0%", "larghezza": "10%",
     "altezza": "10%"},
    {"tipo": "ellisse", "x": "50%", "y": "50%", "larghezza": "20%",
     "altezza": "20%"},
])
a2 = Image.open(io.BytesIO(mask2)).getchannel("A")
check("la percentuale in alto a sinistra e' trasparente",
      a2.getpixel((20, 20)) == 0, str(a2.getpixel((20, 20))))
check("il centro dell'ellisse e' trasparente", a2.getpixel((240, 180)) == 0,
      str(a2.getpixel((240, 180))))
check("l'angolo dell'ellisse resta opaco", a2.getpixel((160, 110)) == 255,
      str(a2.getpixel((160, 110))))

sfumata = Image.open(io.BytesIO(mo.maschera(JPEG, [
    {"tipo": "rettangolo", "x": 300, "y": 200, "larghezza": 80,
     "altezza": 60}], morbido=8))).getchannel("A")
valori = [sfumata.getpixel((x, 230)) for x in range(290, 310)]
check("con `morbido` il bordo ha valori intermedi",
      any(0 < v < 255 for v in valori), str(valori))

print("\n[3] Zone sbagliate: errore che dice quale")
for nome, zone, atteso in [
    ("nessuna zona", [], "zone"),
    ("zona fuori dall'immagine",
     [{"x": 500, "y": 400, "larghezza": 50, "altezza": 50}], "fuori"),
    ("tipo di forma inventato",
     [{"tipo": "triangolo", "x": 10, "y": 10, "larghezza": 20,
       "altezza": 20}], "sconosciuto"),
]:
    try:
        mo.maschera(JPEG, zone)
        check(nome, False, "nessun errore")
    except mo.MontaggioError as e:
        check(nome, atteso in str(e).lower(), str(e))

print("\n[4] Una maschera pronta viene controllata prima di partire")
mo.controlla_maschera(mask, 400, 300)
check("una maschera buona passa", True)
rgb_png = io.BytesIO()
Image.new("RGB", (400, 300), (0, 0, 0)).save(rgb_png, format="PNG")
prove = [
    ("JPEG invece di PNG", JPEG, "non jpeg"),
    ("PNG senza trasparenza", rgb_png.getvalue(), "trasparen"),
    ("misura diversa", mask, "stessa misura"),
    ("file vuoto", b"", "vuota"),
]
for nome, dati, atteso in prove:
    try:
        mo.controlla_maschera(dati, 200, 150) if nome != "JPEG invece di PNG" \
            else mo.controlla_maschera(dati, 400, 300)
        check(nome, False, "nessun errore")
    except mo.MontaggioError as e:
        check(nome, atteso in str(e).lower(), str(e))

print("\n[5] Provider: la maschera e' solo OpenAI, e lo dice senza spendere")
chiamate = []


def rete_vietata(*a, **k):
    chiamate.append(a)
    raise AssertionError("nessuna richiesta doveva partire")


originale_post = ig._post_json
ig._post_json = rete_vietata
try:
    ig.genera("togli la scritta", provider="google",
              env=env(GEMINI_API_KEY="goog"), cartella=TMP,
              riferimento=(JPEG, "image/jpeg"), maschera=(mask, "image/png"))
    check("Google con maschera e' un errore", False, "nessun errore")
except ig.ImageGenError as e:
    check("Google con maschera e' un errore", "OpenAI" in str(e), str(e))
    check("e dice che non ha speso niente", "credito" in str(e).lower(), str(e)[:200])
check("nessuna richiesta di rete partita", not chiamate, str(len(chiamate)))
ig._post_json = originale_post

print("\n[6] Il multipart porta due file: image e mask")
catturato = {}


def finto_urlopen(req, timeout=0):
    catturato["url"] = req.full_url
    catturato["data"] = req.data or b""
    catturato["headers"] = dict(req.headers)

    class Risposta(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return Risposta(b'{"data": [{"b64_json": "' + B64_PNG.encode() + b'"}]}')


originale = ig.urllib.request.urlopen
ig.urllib.request.urlopen = finto_urlopen
try:
    img = ig.genera("togli la scritta in basso", env=env(OPENAI_API_KEY="sk-test"),
                    cartella=TMP, nome_file="pulita",
                    riferimento=(JPEG, "image/jpeg"),
                    maschera=(mask, "image/png"))
finally:
    ig.urllib.request.urlopen = originale

corpo = catturato.get("data") or b""
check("va su /images/edits", catturato.get("url") == ig.ENDPOINT_EDITS,
      str(catturato.get("url")))
check("c'e' il file image", b'name="image"; filename="riferimento.jpg"' in corpo)
check("c'e' il file mask", b'name="mask"; filename="maschera.png"' in corpo)
check("la maschera viaggia come PNG", b"Content-Type: image/png" in corpo)
check("i byte della maschera sono nel corpo", mask in corpo)
check("i byte dell'immagine sono nel corpo", JPEG[100:400] in corpo)
check("il campo prompt c'e'", b'name="prompt"' in corpo)
check("l'immagine e' stata salvata", Path(img.percorso).is_file(), str(img.percorso))

print("\n[7] Senza maschera il multipart resta com'era: un solo file")
catturato.clear()
ig.urllib.request.urlopen = finto_urlopen
try:
    ig.genera("rendilo blu", env=env(OPENAI_API_KEY="sk-test"), cartella=TMP,
              riferimento=(JPEG, "image/jpeg"))
finally:
    ig.urllib.request.urlopen = originale
corpo = catturato.get("data") or b""
check("il file image c'e'", b'name="image"; filename=' in corpo)
check("il file mask NON c'e'", b'name="mask"' not in corpo)

print("\n[8] Il tool costruisce la maschera dalle zone")
os.environ["ORCHESTRA_ROOT"] = TMP
os.environ["OPENAI_API_KEY"] = "sk-test"
mod_gen._root_progetto = lambda: Path(TMP)
Path(TMP, "foto.jpg").write_bytes(JPEG)

viste = []


def finto_multipart(url, campi, allegati, testa, provider):
    viste.append({"url": url, "campi": campi, "allegati": allegati})
    return {"data": [{"b64_json": B64_PNG}]}


originale_mp = ig._post_multipart
ig._post_multipart = finto_multipart
tool = tool_image_gen()
try:
    esito = tool.handler(
        prompt="sostituisci il prezzo con 490 euro",
        riferimento="foto.jpg",
        zone=[{"tipo": "rettangolo", "x": "60%", "y": "80%",
               "larghezza": "30%", "altezza": "15%"}],
        nome_file="prezzo-nuovo")
    check("il montaggio col modello riesce", "dentro la maschera" in esito.text,
          esito.text[:200])
    check("c'e' un'anteprima", len(esito.anteprime) == 1)
    nomi = [a[0] for a in viste[-1]["allegati"]] if viste else []
    check("al provider arrivano image e mask", nomi == ["image", "mask"], str(nomi))
    if viste:
        dati_mask = [a[3] for a in viste[-1]["allegati"] if a[0] == "mask"][0]
        m = Image.open(io.BytesIO(dati_mask))
        check("la maschera generata e' della misura della foto",
              m.size == (400, 300), str(m.size))
        check("ed e' PNG con alfa", m.format == "PNG" and m.mode == "RGBA",
              f"{m.format}/{m.mode}")
        check("la zona chiesta e' trasparente",
              m.getchannel("A").getpixel((350, 270)) == 0)
    check("nessun file di maschera lasciato nel progetto",
          not list(Path(TMP).glob("**/*maschera*")), "trovato un file")
finally:
    ig._post_multipart = originale_mp

print("\n[9] Il tool: maschera pronta, e i casi che devono fermarsi prima")
maschera_pronta = Path(TMP, "mask.png")
maschera_pronta.write_bytes(mask)
mod_gen._root_progetto = lambda: Path(TMP)
ig._post_multipart = finto_multipart
try:
    esito2 = tool.handler(prompt="cambia il colore", riferimento="foto.jpg",
                          maschera="mask.png")
    check("una maschera pronta viene usata", "dentro la maschera" in esito2.text,
          esito2.text[:200])

    esito_zone_senza_foto = tool.handler(prompt="cancella", zone=[
        {"x": 0, "y": 0, "larghezza": 10, "altezza": 10}])
    check("zone senza immagine: errore che spiega",
          "ERRORE" in esito_zone_senza_foto.text
          and "immagine" in esito_zone_senza_foto.text, esito_zone_senza_foto.text)

    esito_google = tool.handler(prompt="cancella", provider="google",
                                riferimento="foto.jpg", zone=[
                                    {"x": 0, "y": 0, "larghezza": 10,
                                     "altezza": 10}])
    check("Google con zone: errore su OpenAI",
          "ERRORE" in esito_google.text and "OpenAI" in esito_google.text,
          esito_google.text)

    piccola = Path(TMP, "piccola.png")
    piccola.write_bytes(mo.maschera(jpeg_di_prova(100, 100), [
        {"x": 0, "y": 0, "larghezza": 50, "altezza": 50}]))
    esito_misura = tool.handler(prompt="cambia", riferimento="foto.jpg",
                                maschera="piccola.png")
    check("maschera di misura sbagliata: errore chiaro",
          "ERRORE" in esito_misura.text
          and "stessa misura" in esito_misura.text, esito_misura.text)
finally:
    ig._post_multipart = originale_mp

shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 60)
print(f"  PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
    sys.exit(1)
print("=" * 60)
