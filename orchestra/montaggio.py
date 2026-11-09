"""Montare su un'immagine: testo, logo, ritaglio, ridimensionamento.

PERCHE' QUESTO MODULO ESISTE

`image_gen` risponde a "inventa un'immagine" e a "trasformala": chiama un
modello generativo, che ridisegna tutti i pixel. La conseguenza e' che un
logo esistente torna con le lettere sbagliate e un prezzo scritto torna con
le cifre reinventate — non per un difetto del provider, ma perche' quella
e' la natura del gesto. "Aggiungi il prezzo e il logo che ho gia'" non e'
un gesto generativo: e' un montaggio.

Qui i pixel li mette una libreria di immagini, non un modello. La foto di
partenza resta la foto di partenza: fuori dalle zone toccate i pixel sono
identici, byte per byte, e il logo che si incolla e' il file del logo.
Nessuna rete, nessuna chiave, nessun costo, nessun testo inventato.

JPG, PNG, WEBP

Un JPEG non ha trasparenza, un PNG si'. Si legge tutto in RGBA e si
ricodifica nel formato di partenza per default: JPEG entra, JPEG esce (con
qualita' 95, o quella chiesta), quindi la foto resta una foto JPEG e non
diventa un PNG da 30 MB. Un JPEG non puo' pero' conservare la trasparenza:
se il risultato ne ha bisogno si chiede `formato="png"`.

L'orientamento EXIF si applica PRIMA di toccare qualsiasi cosa. Una foto
del telefono e' spesso larga nei pixel e verticale a schermo, e le
coordinate che l'utente vede — "il prezzo in basso" — valgono
sull'immagine raddrizzata, non sui byte grezzi. Senza questo passaggio un
testo finirebbe ruotato di 90 gradi e nessuno capirebbe perche'.

COSA NON SI MARCA

`image_gen` marca i suoi output come contenuto sintetico (AI Act, art.
50(2)) perche' li genera un modello. Qui il contenuto non e' sintetico: e'
la foto dell'utente, con sopra il logo dell'utente e il testo che ha
chiesto. Marcare quel file come "generato da IA" sarebbe un metadato
falso, e su un'immagine commerciale e' un danno, non una tutela.
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from .image_gen import _nome_libero, _slug

# Oltre questo un'immagine non e' una foto: e' un fotomosaico o un file
# costruito per far esplodere la memoria. Pillow di suo avvisa a ~89
# megapixel: qui si rifiuta prima, con un messaggio che dice quanto era
# grande.
LIMITE_PIXEL = 60_000_000

# Il limite degli allegati, come per `image_gen`: oltre non e' un'immagine
# da montare, e' un trasferimento di file.
MAX_BYTE = 12 * 1024 * 1024

_ESTENSIONI = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}

_FORMATI = {
    "jpg": "JPEG", "jpeg": "JPEG", "png": "PNG",
    "webp": "WEBP",
}

# Le operazioni ammesse. Un elenco esplicito serve a due cose: dire subito
# "questa operazione non esiste" invece di ignorarla in silenzio, e poter
# scrivere nel messaggio d'errore l'elenco giusto.
OPERAZIONI = ("ritaglia", "ridimensiona", "incolla", "testo")

# I font di sistema da provare quando l'utente non ne indica uno.
#
# Si leggono direttamente, senza passare dal gate dei permessi: sono
# risorse del sistema, non dati dell'utente, e chiedere l'autorizzazione
# per disegnare la parola "prezzo" sarebbe una domanda assurda a ogni
# immagine. Un font indicato dall'utente, invece, passa dal gate come ogni
# altro percorso.
_FONT_BOLD = (
    "arialbd.ttf", "segoeuib.ttf", "calibrib.ttf", "impact.ttf",
    "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf",
)
_FONT_REGOLARE = (
    "arial.ttf", "segoeui.ttf", "calibri.ttf",
    "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "NotoSans-Regular.ttf",
)

_DIR_FONT = (
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/noto"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
)


class MontaggioError(RuntimeError):
    """Montaggio non riuscito. Il messaggio dice cosa correggere."""


@dataclass
class Montaggio:
    """Un'immagine montata, gia' scritta su disco."""

    dati: bytes
    mime: str
    percorso: Path
    formato: str
    larghezza: int
    altezza: int
    operazioni: int = 0
    # Cosa e' stato corretto invece di rifiutato: un ritaglio ridotto ai
    # bordi, una coordinata portata dentro l'immagine. Vuoto quando il
    # risultato e' esattamente quello chiesto.
    note: list[str] = field(default_factory=list)

    @property
    def kb(self) -> int:
        return max(1, len(self.dati) // 1024)

    def data_url(self) -> str:
        import base64

        b64 = base64.b64encode(self.dati).decode("ascii")
        return f"data:{self.mime};base64,{b64}"


def _pillow():
    """Pillow, con un errore che dice cosa fare se manca.

    Il resto di Orchestra e' standard library: una dipendenza che manca non
    deve far esplodere l'applicazione all'import, deve fermare questo tool
    e dire come rimediare.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps  # noqa: F401
    except ImportError as e:  # pragma: no cover - dipende dall'ambiente
        raise MontaggioError(
            "manca Pillow, la libreria che monta le immagini. "
            "Installala con `pip install Pillow` (e' in requirements.txt). "
            "Senza, `image_gen` continua a funzionare, ma il montaggio "
            "deterministico no."
        ) from e
    return Image, ImageDraw, ImageFont, ImageOps


def _controlla_byte(dati: bytes) -> None:
    if not dati:
        raise MontaggioError("immagine vuota: 0 byte.")
    if len(dati) > MAX_BYTE:
        raise MontaggioError(
            f"immagine troppo grande: {len(dati) // (1024 * 1024)} MB, "
            f"il limite e' {MAX_BYTE // (1024 * 1024)} MB."
        )


def apri(dati: bytes, *, cosa: str = "immagine"):
    """Byte → immagine RGBA, raddrizzata secondo l'EXIF."""
    Image, _ImageDraw, _ImageFont, ImageOps = _pillow()
    _controlla_byte(dati)
    try:
        im = Image.open(io.BytesIO(dati))
    except Image.UnidentifiedImageError as e:
        raise MontaggioError(
            f"{cosa}: non e' un'immagine leggibile (serve PNG, JPEG o WebP). "
            f"Un PDF o un SVG vanno convertiti prima."
        ) from e
    except Exception as e:  # noqa: BLE001 - il file e' comunque illeggibile
        raise MontaggioError(f"{cosa}: non riesco ad aprirla: {e}") from e

    # La dimensione e' nota dal solo header: si controlla PRIMA di
    # decodificare i pixel, o il limite arriva quando la memoria e' gia'
    # stata spesa.
    if im.width * im.height > LIMITE_PIXEL:
        raise MontaggioError(
            f"{cosa}: {im.width}x{im.height} = "
            f"{im.width * im.height // 1_000_000} MP, il limite e' "
            f"{LIMITE_PIXEL // 1_000_000} MP."
        )
    try:
        im.load()
    except Image.DecompressionBombError as e:  # pragma: no cover
        raise MontaggioError(f"{cosa}: immagine troppo grande da decodificare.") from e
    except OSError as e:
        raise MontaggioError(f"{cosa}: immagine danneggiata o troncata: {e}") from e

    # EXIF prima di tutto: le coordinate valgono sull'immagine che si vede.
    try:
        im = ImageOps.exif_transpose(im) or im
    except Exception:  # noqa: BLE001 - un EXIF rotto non deve buttare via la foto
        pass
    return im.convert("RGBA")


def _numero(valore, nome: str) -> float:
    """Un numero da JSON, da stringa, o da percentuale."""
    if isinstance(valore, bool) or valore is None:
        raise MontaggioError(f"{nome}: serve un numero o una percentuale (es. \"50%\").")
    if isinstance(valore, str):
        v = valore.strip()
        if v.endswith("%"):
            try:
                return float(v[:-1].replace(",", ".")) / 100.0
            except ValueError as e:
                raise MontaggioError(f"{nome}: {valore!r} non e' una percentuale.") from e
        try:
            valore = float(v.replace(",", "."))
        except ValueError as e:
            raise MontaggioError(f"{nome}: {valore!r} non e' un numero.") from e
    try:
        numero = float(valore)
    except (TypeError, ValueError) as e:
        raise MontaggioError(f"{nome}: {valore!r} non e' un numero.") from e
    if math.isnan(numero) or math.isinf(numero):
        raise MontaggioError(f"{nome}: {valore!r} non e' un numero finito.")
    return numero


def _coord(valore, dimensione: int, nome: str) -> int:
    """Una coordinata in pixel. Una stringa con `%` e' una frazione."""
    if isinstance(valore, str) and valore.strip().endswith("%"):
        grezzo = _numero(valore, nome)
        return int(round(grezzo * dimensione))
    grezzo = _numero(valore, nome)
    # Il 5% di un'immagine larga 50 px e' 2.5: arrotondare va bene, ma non
    # si scende sotto zero.
    return max(0, int(round(grezzo)))


def _misura(valore, base: int, nome: str) -> int:
    """Una larghezza/altezza in pixel, o una percentuale della base."""
    if isinstance(valore, str) and valore.strip().endswith("%"):
        valore = _numero(valore, nome)
        return max(1, int(round(valore * base)))
    n = int(round(_numero(valore, nome)))
    if n <= 0:
        raise MontaggioError(f"{nome}: deve essere maggiore di zero, non {n}.")
    return n


def _colore(valore, nome: str):
    """Un colore Pillow da `#rrggbb`, un nome, o `rgba(...)`."""
    Image, _d, _f, _o = _pillow()
    from PIL import ImageColor

    if isinstance(valore, str) and not valore.strip():
        raise MontaggioError(f"{nome}: colore vuoto.")
    try:
        rgb = ImageColor.getrgb(str(valore).strip())
    except ValueError as e:
        raise MontaggioError(
            f"{nome}: {valore!r} non e' un colore. Usa `#rrggbb` o un nome "
            f"(`white`, `black`)."
        ) from e
    return rgb + (255,) if len(rgb) == 3 else rgb


def _font(dimensione: int, grassetto: bool, percorso: str = ""):
    """Il font per il testo: quello chiesto, uno di sistema, o il default."""
    _Image, _ImageDraw, ImageFont, _ImageOps = _pillow()
    if percorso:
        try:
            return ImageFont.truetype(str(percorso), dimensione)
        except OSError as e:
            raise MontaggioError(
                f"font non caricabile: {percorso} ({e}). Serve un .ttf o .otf."
            ) from e
    for nome in (_FONT_BOLD if grassetto else _FONT_REGOLARE):
        for cartella in _DIR_FONT:
            candidato = cartella / nome
            try:
                if candidato.is_file():
                    return ImageFont.truetype(str(candidato), dimensione)
            except OSError:
                continue
    # Ultima spiaggia: il font incluso in Pillow. Non e' bello, ma il testo
    # esce, invece di un errore che chiede all'utente di installare font.
    try:
        return ImageFont.load_default(size=dimensione)
    except TypeError:  # pragma: no cover - Pillow < 10.1
        return ImageFont.load_default()


def _ritaglia(im, op, note: list[str]):
    larghezza, altezza = im.size
    x = _coord(op.get("x", 0), larghezza, "ritaglia.x")
    y = _coord(op.get("y", 0), altezza, "ritaglia.y")
    w = _misura(op.get("larghezza", larghezza), larghezza, "ritaglia.larghezza")
    h = _misura(op.get("altezza", altezza), altezza, "ritaglia.altezza")
    if x >= larghezza or y >= altezza:
        raise MontaggioError(
            f"ritaglio fuori dall'immagine: x={x}, y={y} su "
            f"{larghezza}x{altezza}. Le coordinate partono da 0,0 in alto "
            f"a sinistra."
        )
    destra = min(larghezza, x + w)
    basso = min(altezza, y + h)
    if destra != x + w or basso != y + h:
        note.append(
            f"ritaglio ridotto ai bordi: {destra - x}x{basso - y} invece di "
            f"{w}x{h} (l'immagine e' {larghezza}x{altezza})."
        )
    return im.crop((x, y, destra, basso))


def _ridimensiona(im, op, note: list[str]):
    Image, _d, _f, _o = _pillow()
    larghezza, altezza = im.size
    scala = op.get("scala")
    if scala not in (None, ""):
        fattore = _numero(scala, "ridimensiona.scala")
        if isinstance(scala, str) and scala.strip().endswith("%"):
            fattore = _numero(scala, "ridimensiona.scala")  # gia' frazione
        elif fattore > 3:  # "50" scritto senza %: si intende 50%
            fattore = fattore / 100.0
        if fattore <= 0:
            raise MontaggioError(f"ridimensiona.scala: deve essere positiva, non {scala!r}.")
        nuova = (max(1, int(round(larghezza * fattore))),
                 max(1, int(round(altezza * fattore))))
    else:
        w = op.get("larghezza")
        h = op.get("altezza")
        if w in (None, "") and h in (None, ""):
            raise MontaggioError(
                "ridimensiona: serve `larghezza`, `altezza` o `scala` "
                "(es. \"50%\")."
            )
        if w not in (None, ""):
            nuova_w = _misura(w, larghezza, "ridimensiona.larghezza")
        else:
            nuova_w = 0
        if h not in (None, ""):
            nuova_h = _misura(h, altezza, "ridimensiona.altezza")
        else:
            nuova_h = 0
        # Con una sola misura si conservano le proporzioni: e' quello che
        # serve quasi sempre, e allungare la foto sarebbe una scelta
        # dell'utente travisata.
        if nuova_w and nuova_h:
            nuova = (nuova_w, nuova_h)
        elif nuova_w:
            nuova = (nuova_w, max(1, int(round(nuova_w * altezza / larghezza))))
        else:
            nuova = (max(1, int(round(nuova_h * larghezza / altezza))), nuova_h)
    if nuova == im.size:
        note.append(f"ridimensiona senza effetto: era gia' {im.size[0]}x{im.size[1]}.")
        return im
    return im.resize(nuova, Image.Resampling.LANCZOS)


def _scontorna(logo, colore, tolleranza: float, sfumatura: int):
    """Toglie un fondo uniforme e restituisce quanta parte e' sparita.

    Perche' serve: un JPEG col fondo bianco incollato su un poster scuro non
    e' "un logo con un po' di margine", e' un rettangolo bianco. Mandare
    l'utente su remove.bg per un fondo bianco uniforme e' fargli fare a mano
    un lavoro che sappiamo fare: ogni pixel vicino al colore di fondo diventa
    trasparente, con un bordo sfumato per non lasciare scalini.
    """
    from PIL import Image, ImageChops, ImageFilter

    rgb = logo.convert("RGB")
    distanza = ImageChops.difference(rgb, Image.new("RGB", logo.size, colore))
    distanza = distanza.convert("L")
    # `tolleranza` e' in percentuale: 0 vuol dire "solo il colore esatto",
    # 100 "qualsiasi cosa". La fascia alta e' quella che ammorbidisce il
    # confine, e sta 24 valori sopra la soglia.
    bassa = max(0, min(255, int(round(tolleranza * 2.55))))
    alta = min(255, bassa + 24)
    if alta <= bassa:
        mappa = distanza.point(lambda d: 255 if d > bassa else 0)
    else:
        mappa = distanza.point(
            lambda d: 0 if d <= bassa
            else 255 if d >= alta
            else int(round((d - bassa) * 255 / (alta - bassa))))
    if sfumatura > 0:
        mappa = mappa.filter(ImageFilter.GaussianBlur(sfumatura))
    logo.putalpha(ImageChops.multiply(logo.getchannel("A"), mappa))
    istogramma = mappa.histogram()
    tolti = sum(istogramma[:8])
    totale = max(1, logo.width * logo.height)
    return logo, round(100.0 * tolti / totale, 1)


def _ombra_su(im, logo, x: int, y: int, distanza: int,
             opacita: float = 0.45) -> None:
    """Un'ombra morbida sotto il logo.

    Un ritaglio incollato senza ombra sembra un adesivo appoggiato sopra; con
    l'ombra il bordo irregolare si legge come parte della scena. Si disegna
    sulla base nella posizione finale, cosi' le coordinate del logo restano
    quelle che l'utente ha chiesto.
    """
    from PIL import Image, ImageFilter

    nero = Image.new("RGBA", logo.size, (0, 0, 0, int(round(255 * opacita))))
    strato = Image.new("RGBA", im.size, (0, 0, 0, 0))
    strato.paste(nero, (x + distanza, y + distanza), logo.getchannel("A"))
    strato = strato.filter(ImageFilter.GaussianBlur(max(1.0, distanza / 2.0)))
    im.alpha_composite(strato)


def _incolla(im, op, note: list[str], risolvi):
    """Incolla un'altra immagine, con la sua trasparenza."""
    Image, _d, _f, _o = _pillow()
    grezzo = op.get("immagine")
    if not grezzo:
        raise MontaggioError("incolla: serve `immagine` (percorso, data URL o `ultimo`).")
    if isinstance(grezzo, (bytes, bytearray)):
        # Byte gia' in mano a chi chiama: non c'e' niente da risolvere, e
        # chiedere un percorso sarebbe un giro inutile.
        sorgente = bytes(grezzo)
    else:
        if risolvi is None:
            raise MontaggioError(
                "incolla: nessun lettore di immagini disponibile "
                "(chiamata interna senza `risolvi`)."
            )
        sorgente = risolvi(str(grezzo))
    logo = apri(sorgente, cosa=f"incolla.immagine ({grezzo})")

    # Lo scontorno si fa prima di ridimensionare: l'alfa viene riscalato
    # insieme ai pixel e il bordo resta morbido anche rimpicciolendo.
    if op.get("scontorna") not in (None, "", False):
        colore = _colore(op.get("colore_sfondo") or "#ffffff",
                         "incolla.colore_sfondo")
        tolleranza = _numero(op.get("tolleranza", 18) or 0,
                             "incolla.tolleranza")
        if not 0 <= tolleranza <= 100:
            raise MontaggioError(
                f"incolla.tolleranza: va da 0 a 100, non {op.get('tolleranza')!r}."
            )
        sfumatura = int(_numero(op.get("sfumatura", 1) or 0,
                                "incolla.sfumatura"))
        if sfumatura < 0:
            raise MontaggioError("incolla.sfumatura: non puo' essere negativa.")
        logo, tolti = _scontorna(logo, colore, tolleranza, sfumatura)
        note.append(
            f"incolla: sfondo tolto ({tolti}% dell'immagine e' diventato "
            f"trasparente). Se ha mangiato anche il soggetto, abbassa "
            f"`tolleranza`."
        )

    larghezza, altezza = im.size
    if op.get("larghezza") not in (None, ""):
        nuova_w = _misura(op["larghezza"], larghezza, "incolla.larghezza")
        nuova_h = max(1, int(round(logo.height * nuova_w / logo.width)))
        logo = logo.resize((nuova_w, nuova_h), Image.Resampling.LANCZOS)
    elif op.get("altezza") not in (None, ""):
        nuova_h = _misura(op["altezza"], altezza, "incolla.altezza")
        nuova_w = max(1, int(round(logo.width * nuova_h / logo.height)))
        logo = logo.resize((nuova_w, nuova_h), Image.Resampling.LANCZOS)

    opacita = op.get("opacita")
    if opacita not in (None, ""):
        valore = _numero(opacita, "incolla.opacita")
        # "50%" arriva gia' come 0.5 da `_numero`; un 50 secco e' 50%.
        if not (isinstance(opacita, str) and opacita.strip().endswith("%")) \
                and valore > 1:
            valore = valore / 100.0
        if not 0 < valore <= 1:
            raise MontaggioError(
                f"incolla.opacita: va da 1 a 100 (o da 0 a 1), non {opacita!r}."
            )
        canale = logo.getchannel("A").point(lambda a: int(a * valore))
        logo.putalpha(canale)

    if logo.width > larghezza or logo.height > altezza:
        nota = (f"incolla: il logo {logo.width}x{logo.height} e' piu' grande "
                f"dell'immagine {larghezza}x{altezza}.")
        note.append(nota)

    ancora = str(op.get("ancora") or "la").strip().lower()
    x, y = _posizione(im, logo.size, op, ancora, "incolla")
    # Un incollaggio parziale e' meglio di un errore: si taglia la parte
    # che esce, e lo si dice.
    if x + logo.width > larghezza or y + logo.height > altezza or x < 0 or y < 0:
        note.append("incolla: la parte che usciva dall'immagine e' stata tagliata.")
    ombra = int(_numero(op.get("ombra", 0) or 0, "incolla.ombra"))
    if ombra < 0:
        raise MontaggioError("incolla.ombra: non puo' essere negativa.")
    if ombra:
        _ombra_su(im, logo, x, y, ombra)
    im.alpha_composite(logo, dest=(max(0, x), max(0, y)))
    return im


def _ancora_offset(ancora: str, contenitore: tuple[int, int],
                   misura: tuple[int, int]) -> tuple[int, int]:
    """Dove cade il punto di ancoraggio, secondo la convenzione Pillow.

    `la` = sinistra-alto, `mm` = centro, `rd` = destra-basso. E' la stessa
    sintassi di Pillow per il testo, e vale anche per il logo: cosi' una
    sola cosa da imparare.
    """
    if len(ancora) != 2 or ancora[0] not in "lmr" or ancora[1] not in "amtb":
        raise MontaggioError(
            f"ancora {ancora!r} non valida: usa due lettere, una per "
            f"orizzontale (l, m, r) e una per verticale (a, m, b). "
            f"Esempio: \"mm\" per il centro, \"rb\" per l'angolo in basso a "
            f"destra."
        )
    w, h = misura
    x = {"l": 0, "m": -w // 2, "r": -w}[ancora[0]]
    y = {"a": 0, "m": -h // 2, "b": -h}[ancora[1]]
    return x, y


def _posizione(im, misura: tuple[int, int], op: dict, ancora: str,
               nome: str) -> tuple[int, int]:
    """La posizione dell'angolo in alto a sinistra, data l'ancora."""
    larghezza, altezza = im.size
    x = _coord(op.get("x", 0), larghezza, f"{nome}.x")
    y = _coord(op.get("y", 0), altezza, f"{nome}.y")
    dx, dy = _ancora_offset(ancora, (larghezza, altezza), misura)
    return x + dx, y + dy


def _testo(im, op, note: list[str]):
    _Image, ImageDraw, _ImageFont, _o = _pillow()
    testo = str(op.get("testo") or "")
    if not testo.strip():
        raise MontaggioError("testo: serve `testo` (la stringa da disegnare).")
    dimensione = _misura(op.get("dimensione", 64), min(im.size), "testo.dimensione")
    colore = _colore(op.get("colore") or "#ffffff", "testo.colore")
    grassetto = bool(op.get("grassetto", False))
    percorso_font = str(op.get("font") or "").strip()
    font = _font(dimensione, grassetto, percorso_font)

    ancora = str(op.get("ancora") or "la").strip().lower()
    # L'ancora del testo la valida Pillow; la si valida prima qui per dare
    # un messaggio uguale a quello del logo.
    _ancora_offset(ancora, im.size, (0, 0))
    interlinea = int(round(dimensione * 0.28))

    disegno = ImageDraw.Draw(im)
    larghezza, altezza = im.size
    x = _coord(op.get("x", 0), larghezza, "testo.x")
    y = _coord(op.get("y", 0), altezza, "testo.y")

    bordo = int(_numero(op.get("bordo", 0) or 0, "testo.bordo"))
    if bordo < 0:
        raise MontaggioError("testo.bordo: non puo' essere negativo.")
    colore_bordo = _colore(op.get("colore_bordo") or "#000000", "testo.colore_bordo")

    try:
        riquadro = disegno.multiline_textbbox(
            (x, y), testo, font=font, anchor=ancora, align="center",
            spacing=interlinea, stroke_width=bordo,
        )
    except ValueError as e:
        raise MontaggioError(f"testo: {e}") from e

    margine = int(_numero(op.get("margine", 18) or 0, "testo.margine"))
    sfondo = op.get("riquadro")
    if sfondo not in (None, ""):
        colore_sfondo = _colore(sfondo, "testo.riquadro")
        raggio = int(_numero(op.get("raggio", 14) or 0, "testo.raggio"))
        disegno.rounded_rectangle(
            (riquadro[0] - margine, riquadro[1] - margine,
             riquadro[2] + margine, riquadro[3] + margine),
            radius=max(0, raggio), fill=colore_sfondo,
        )

    disegno.multiline_text(
        (x, y), testo, font=font, fill=colore, anchor=ancora,
        align="center", spacing=interlinea,
        stroke_width=bordo, stroke_fill=colore_bordo,
    )
    if riquadro[0] < 0 or riquadro[1] < 0 or riquadro[2] > larghezza or riquadro[3] > altezza:
        note.append(
            f"testo: parte esce dall'immagine ({larghezza}x{altezza}); "
            f"sposta le coordinate o riduci `dimensione`."
        )
    return im


def _formato_di(mime: str, chiesto: str) -> tuple[str, str]:
    """(formato Pillow, estensione) dal formato chiesto o dal MIME."""
    if chiesto and str(chiesto).strip():
        chiave = str(chiesto).strip().lower().lstrip(".")
        if chiave not in _FORMATI:
            raise MontaggioError(
                f"formato {chiesto!r} non supportato: usa jpg, png o webp."
            )
        formato = _FORMATI[chiave]
        return formato, "jpg" if formato == "JPEG" else formato.lower()
    estensione = _ESTENSIONI.get((mime or "").lower(), "png")
    return _FORMATI[estensione], estensione


def _codifica(im, formato: str, qualita: int) -> tuple[bytes, str]:
    Image, _d, _f, _o = _pillow()
    if formato == "JPEG":
        # Un JPEG non ha canale alfa: si appiattisce sul bianco, che e'
        # l'unico fondo sensato se l'immagine era trasparente. Su una foto
        # vera il canale alfa e' 255 ovunque, quindi non cambia niente.
        fondo = Image.new("RGB", im.size, (255, 255, 255))
        fondo.paste(im, mask=im.getchannel("A"))
        buf = io.BytesIO()
        fondo.save(buf, format="JPEG", quality=max(1, min(100, qualita)))
        return buf.getvalue(), "image/jpeg"
    if formato == "WEBP":
        buf = io.BytesIO()
        im.save(buf, format="WEBP", quality=max(1, min(100, qualita)),
                lossless=False)
        return buf.getvalue(), "image/webp"
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), "image/png"


def monta(base: bytes, mime: str, operazioni, *, cartella: str | Path = "",
          nome_file: str = "", formato: str = "", qualita: int = 95,
          risolvi=None) -> Montaggio:
    """Applica le operazioni alla base e scrive il risultato.

    `risolvi` converte il campo `immagine` di un'operazione `incolla` in
    byte: lo passa il tool, perche' la lettura di un file passa dal gate dei
    permessi e questo modulo, da solo, non deve saperne niente.

    L'immagine di partenza non viene toccata: si scrive sempre un file
    nuovo, con un nome libero, nella cartella `immagini/`.
    """
    if operazioni is None:
        raise MontaggioError(
            "servono le `operazioni`: cosa devo fare all'immagine? "
            f"Le operazioni ammesse sono {', '.join(OPERAZIONI)}. "
            "Un elenco vuoto vale come conversione di formato."
        )
    if not isinstance(operazioni, list):
        raise MontaggioError("`operazioni` deve essere un elenco.")

    im = apri(base, cosa="immagine di partenza")
    note: list[str] = []
    fatte = 0

    for indice, op in enumerate(operazioni, start=1):
        if not isinstance(op, dict):
            raise MontaggioError(f"operazione {indice}: deve essere un oggetto con `tipo`.")
        tipo = str(op.get("tipo") or "").strip().lower()
        if tipo not in OPERAZIONI:
            raise MontaggioError(
                f"operazione {indice}: tipo {tipo!r} sconosciuto. "
                f"Ammesse: {', '.join(OPERAZIONI)}."
            )
        if tipo == "ritaglia":
            im = _ritaglia(im, op, note)
        elif tipo == "ridimensiona":
            im = _ridimensiona(im, op, note)
        elif tipo == "incolla":
            im = _incolla(im, op, note, risolvi)
        else:
            im = _testo(im, op, note)
        fatte += 1

    formato_finale, estensione = _formato_di(mime, formato)
    dati, mime_finale = _codifica(im, formato_finale, int(qualita))

    base_cartella = Path(cartella) if str(cartella or "").strip() else Path.cwd()
    destinazione = base_cartella / "immagini"
    try:
        destinazione.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MontaggioError(f"non riesco a creare {destinazione}: {e}") from e

    nome = _slug(nome_file or "montaggio")
    percorso = _nome_libero(destinazione, nome, estensione)
    try:
        percorso.write_bytes(dati)
    except OSError as e:
        raise MontaggioError(f"non riesco a scrivere {percorso}: {e}") from e

    return Montaggio(
        dati=dati, mime=mime_finale, percorso=percorso, formato=formato_finale,
        larghezza=im.width, altezza=im.height, operazioni=fatte, note=note,
    )


def maschera(base: bytes, zone, *, morbido: int = 0) -> bytes:
    """La maschera per l'inpainting: PNG trasparente dove si puo' ridisegnare.

    La convenzione e' quella di OpenAI: il PNG ha la stessa misura
    dell'immagine, ed e' **trasparente** nelle zone che il modello puo'
    cambiare; tutto il resto resta opaco, cioe' intoccabile. Costruirla qui
    invece di chiedere all'utente di disegnarla in un editor e' la
    differenza fra una funzione usabile e una funzione che nessuno usa.

    Ogni zona e' un oggetto con `tipo` (`rettangolo` o `ellisse`), `x`, `y`,
    `larghezza`, `altezza`: pixel oppure percentuali ("50%"). `morbido`
    sfuma il bordo di quei pixel, cosi' la cucitura non si vede.
    """
    Image, ImageDraw, _f, _o = _pillow()
    from PIL import ImageFilter

    im = apri(base, cosa="immagine da mascherare")
    larghezza, altezza = im.size
    if not isinstance(zone, list) or not zone:
        raise MontaggioError(
            "servono le `zone`: in quali punti il modello puo' ridisegnare? "
            "Ogni zona ha `tipo` (rettangolo o ellisse), `x`, `y`, "
            "`larghezza`, `altezza`, in pixel o percentuali."
        )
    if isinstance(morbido, bool) or not isinstance(morbido, (int, float)) or morbido < 0:
        raise MontaggioError("`morbido`: serve un numero di pixel >= 0 (0 = bordo netto).")

    # 255 = opaco = non toccare; 0 = trasparente = ridisegna.
    alpha = Image.new("L", (larghezza, altezza), 255)
    disegno = ImageDraw.Draw(alpha)
    for indice, zona in enumerate(zone, start=1):
        if not isinstance(zona, dict):
            raise MontaggioError(
                f"zona {indice}: deve essere un oggetto con `x`, `y`, "
                f"`larghezza`, `altezza`."
            )
        forma = str(zona.get("tipo") or "rettangolo").strip().lower()
        if forma not in ("rettangolo", "ellisse"):
            raise MontaggioError(
                f"zona {indice}: tipo {forma!r} sconosciuto. Usa `rettangolo` "
                f"o `ellisse`."
            )
        x = _coord(zona.get("x", 0), larghezza, f"zona {indice}.x")
        y = _coord(zona.get("y", 0), altezza, f"zona {indice}.y")
        quanto = _misura(zona.get("larghezza", "100%"), larghezza,
                         f"zona {indice}.larghezza")
        alto = _misura(zona.get("altezza", "100%"), altezza,
                       f"zona {indice}.altezza")
        # Una zona che sborda si taglia ai bordi: e' quello che l'utente
        # intendeva. Una zona che cade tutta fuori e' invece un errore di
        # coordinate, e restituire una maschera vuota lo nasconderebbe.
        sinistra, sopra = max(0, x), max(0, y)
        destra = min(larghezza, x + quanto)
        sotto = min(altezza, y + alto)
        if destra <= sinistra or sotto <= sopra:
            raise MontaggioError(
                f"zona {indice}: cade fuori dall'immagine "
                f"({larghezza}x{altezza}). Controlla `x` e `y`."
            )
        riquadro = [sinistra, sopra, destra - 1, sotto - 1]
        if forma == "ellisse":
            disegno.ellipse(riquadro, fill=0)
        else:
            disegno.rectangle(riquadro, fill=0)

    if morbido:
        alpha = alpha.filter(ImageFilter.GaussianBlur(float(morbido)))

    uscita = Image.new("RGBA", (larghezza, altezza), (0, 0, 0, 255))
    uscita.putalpha(alpha)
    buf = io.BytesIO()
    uscita.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def controlla_maschera(dati: bytes, larghezza: int, altezza: int) -> None:
    """Verifica una maschera gia' pronta prima di spendere una chiamata.

    Il provider rifiuterebbe comunque una maschera sbagliata, ma con un 400
    che parla di parametri: meglio dirlo qui, dove si sa quale delle tre
    regole non e' rispettata (PNG, trasparenza, stessa misura).
    """
    Image, _d, _f, _o = _pillow()
    if not dati:
        raise MontaggioError("maschera vuota: 0 byte.")
    # OpenAI accetta maschere fino a 4 MB; oltre, la richiesta viene
    # rifiutata dopo essere partita.
    if len(dati) > 4 * 1024 * 1024:
        raise MontaggioError(
            f"maschera troppo grande: {len(dati) // (1024 * 1024)} MB, "
            f"il limite e' 4 MB."
        )
    try:
        im = Image.open(io.BytesIO(dati))
    except Exception as e:  # noqa: BLE001 - il file e' comunque illeggibile
        raise MontaggioError(f"la maschera non e' un'immagine leggibile: {e}") from e
    if im.format != "PNG":
        raise MontaggioError(
            f"la maschera deve essere un PNG con trasparenza, non {im.format}. "
            f"Le zone generate da `image_gen` sono gia' PNG."
        )
    if "A" not in im.getbands():
        raise MontaggioError(
            "la maschera non ha trasparenza: in un PNG la zona da ridisegnare "
            "e' quella trasparente. Salvala con il canale alfa."
        )
    if im.size != (larghezza, altezza):
        raise MontaggioError(
            f"la maschera e' {im.width}x{im.height}, ma l'immagine e' "
            f"{larghezza}x{altezza}: devono avere la stessa misura."
        )


def dimensioni(dati: bytes) -> tuple[int, int]:
    """La dimensione dell'immagine senza montare niente.

    Serve al tool per dire al modello su che base sta lavorando: senza le
    misure vere, ogni coordinata e' un'indovinata.
    """
    im = apri(dati)
    return im.width, im.height
