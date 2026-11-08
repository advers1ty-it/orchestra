"""Il tool `image_gen`: generare o modificare un'immagine e mostrarla in chat.

Perche' un tool e non una risposta del modello: un modello linguistico non
disegna. La generazione e' una chiamata separata a un endpoint di immagini, e
la risposta e' un file. Questo tool fa la chiamata, scrive il file nel
progetto e restituisce un'anteprima alla UI, cosi' l'utente vede il risultato
senza doverlo cercare su disco.

La modifica e' lo stesso gesto con un'immagine in piu': `riferimento` puo'
essere un percorso, una data URL, oppure `ultimo` per l'immagine appena
allegata alla chat. Il ponte per `ultimo` sta in `attachments`, che ricorda
le immagini dell'ultimo messaggio utente.

Cosa NON fa: non allega l'immagine al messaggio del modello. Un'immagine in un
messaggio `role="tool"` non e' accettata da tutti i provider OpenAI-compatibili
e costerebbe circa 1100 token per essere rivista. Il modello ha scritto lui il
prompt: gli basta il percorso.
"""

from __future__ import annotations

import base64
from pathlib import Path

from .. import attachments as _att
from .. import image_gen as ig
from .. import montaggio
from ..types import Tool, ToolResult

# Il limite degli allegati e' 12 MB; il riferimento non deve poter essere
# piu' grande di cosi'. Un file da 200 MB in memoria e' un blocco, non una
# modifica.
MAX_RIFERIMENTO_MB = 12

_PAROLE_ULTIMO = {"ultimo", "ultima", "last", "ultimo-allegato"}


def _root_progetto() -> Path:
    """La cartella di lavoro attiva, con lo stesso confine degli altri tool."""
    try:
        from . import _root

        return _root()
    except Exception:  # noqa: BLE001 - senza root si usa la directory corrente
        return Path.cwd()


def _da_data_url(valore: str) -> tuple[bytes, str]:
    testa, _, b64 = valore.partition(",")
    if not b64 or ";base64" not in testa:
        raise ig.ImageGenError(
            "immagine di riferimento non valida: serve una data URL base64."
        )
    try:
        dati = base64.b64decode(b64, validate=False)
    except (ValueError, TypeError) as e:
        raise ig.ImageGenError(f"immagine di riferimento non decodificabile: {e}") from e
    mime = _att.mime_immagine(dati)
    if not mime:
        raise ig.ImageGenError(
            "il riferimento non e' un'immagine riconoscibile (PNG, JPEG, "
            "WebP)."
        )
    return dati, mime


def _riferimento(valore: str) -> tuple[bytes, str] | None:
    """Risolvere `riferimento` in (byte, MIME), o None se non c'e'."""
    v = (valore or "").strip()
    if not v:
        return None
    if v.lower() in _PAROLE_ULTIMO:
        v = _att.ultima_immagine()
        if not v:
            raise ig.ImageGenError(
                "non c'e' nessuna immagine allegata da modificare. Allega una "
                "foto nella chat, oppure passa un percorso in `riferimento`."
            )
    if v.startswith("data:"):
        return _da_data_url(v)

    from ._guard import _safe_path

    try:
        percorso = _safe_path(v)
    except (ValueError, PermissionError) as e:
        # Il gate ha gia' detto cosa serve: riportarlo cosi' com'e' e'
        # meglio che trasformarlo in un errore generico del tool.
        raise ig.ImageGenError(str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise ig.ImageGenError(f"percorso non valido: {v}") from e
    if not percorso.is_file():
        raise ig.ImageGenError(f"non trovo l'immagine: {v}")
    try:
        dati = percorso.read_bytes()
    except OSError as e:
        raise ig.ImageGenError(f"non leggo {v}: {e}") from e
    if len(dati) > MAX_RIFERIMENTO_MB * 1024 * 1024:
        raise ig.ImageGenError(
            f"{v}: {len(dati) // (1024 * 1024)} MB, il limite per la modifica "
            f"e' {MAX_RIFERIMENTO_MB} MB."
        )
    mime = _att.mime_immagine(dati)
    if not mime:
        raise ig.ImageGenError(
            f"{v} non e' un'immagine riconoscibile (PNG, JPEG, WebP)."
        )
    return dati, mime


def _maschera(valore: str, zone, morbido: int,
              rif: tuple[bytes, str] | None) -> tuple[bytes, str] | None:
    """La maschera: costruita dalle `zone`, o presa da un file gia' pronto.

    Le due strade esistono perche' sono due utenti diversi: chi dice "cancella
    la scritta in basso a destra" non ha un PNG da dare, e chi l'ha gia'
    disegnato in un editor non vuole che glielo si ricalcoli.
    """
    v = (valore or "").strip()
    if isinstance(zone, dict):
        # Un oggetto singolo invece di un elenco: errore facile da fare, e
        # non c'e' ambiguita' su cosa intendesse.
        zone = [zone]
    if not zone and not v:
        return None
    if rif is None:
        raise ig.ImageGenError(
            "la maschera dice dove ridisegnare, ma manca l'immagine da "
            "modificare: passa `riferimento` (o allega la foto e usa `ultimo`)."
        )
    if zone:
        # La misura la decide l'immagine: chiedere all'utente di indovinare i
        # pixel di una maschera sarebbe un modo per farla sbagliare sempre.
        dati = montaggio.maschera(rif[0], zone, morbido=morbido)
        return dati, "image/png"
    pronta = _riferimento(v)
    larghezza, altezza = montaggio.dimensioni(rif[0])
    montaggio.controlla_maschera(pronta[0], larghezza, altezza)
    return pronta


def tool_image_gen() -> Tool:
    def handler(prompt: str = "", provider: str = "", modello: str = "",
                dimensione: str = "", nome_file: str = "",
                riferimento: str = "", maschera: str = "", zone=None,
                morbido: int = 0, elenco_modelli: bool = False) -> ToolResult:
        if elenco_modelli:
            # L'elenco non costa nulla e non genera niente: e' il modo per
            # scegliere uno slug invece di indovinarlo. Il catalogo e'
            # quello di OpenRouter, l'unico provider che ne espone uno.
            try:
                voci = ig.modelli_immagine()
            except ig.ImageGenError as e:
                return ToolResult(text=f"ERRORE: {e}")
            if not voci:
                return ToolResult(text="ERRORE: il catalogo OpenRouter e' vuoto.")
            righe = []
            for voce in voci[:60]:
                extra = (" (accetta immagini di riferimento)"
                         if voce["riferimento"] else "")
                righe.append(f"- {voce['id']} — {voce['nome']}{extra}")
            resto = len(voci) - len(righe)
            coda = (f"\n...e altri {resto}." if resto > 0 else "")
            return ToolResult(text=(
                f"Modelli immagine su OpenRouter ({len(voci)}):\n"
                + "\n".join(righe) + coda
                + "\nPer usarne uno: provider=\"openrouter\", modello=\"<id>\"."
            ))
        try:
            rif = _riferimento(riferimento)
            mas = _maschera(maschera, zone, morbido, rif)
            img = ig.genera(
                prompt,
                provider=provider,
                modello=modello,
                dimensione=dimensione,
                cartella=_root_progetto(),
                nome_file=nome_file,
                riferimento=rif,
                maschera=mas,
            )
        except (ig.ImageGenError, montaggio.MontaggioError) as e:
            return ToolResult(text=f"ERRORE: {e}")
        except OSError as e:
            return ToolResult(text=f"ERRORE: non leggo l'immagine: {e}")

        # Il percorso relativo e' quello che l'utente riconosce; l'assoluto
        # non aggiunge niente dentro il progetto.
        percorso = str(img.percorso)
        try:
            percorso = str(img.percorso.relative_to(_root_progetto()))
        except ValueError:
            pass
        verbo = ("modificata dentro la maschera" if mas
                 else "modificata" if rif else "generata")
        # Il contenuto e' sintetico e va detto: e' l'art. 50(2) dell'AI
        # Act, e vale anche quando il file e' marcato, perche' la
        # marcatura dentro il PNG non la vede chi guarda la chat.
        meta = (f" Marcata come sintetica in {img.metadati.name}."
                if img.metadati else "")
        return ToolResult(
            text=(f"Immagine {verbo}: {percorso} ({img.kb} KB, "
                  f"{img.provider}/{img.modello}).{meta} Mostrala "
                  f"all'utente citando quel percorso, e scrivi che e' "
                  f"generata da un'IA."),
            anteprime=[img.data_url()],
        )

    return Tool(
        name="image_gen",
        description=(
            "Generates an image from a text prompt, or edits an existing "
            "image, with the configured provider (OpenAI, Google or "
            "OpenRouter). Saves the result into immagini/ in the project. "
            "To edit, pass `riferimento`: a path in the project, a data URL, "
            "or `ultimo` for the image the user just attached. For "
            "inpainting (change ONLY one area, leave the rest untouched) "
            "pass `zone`: rectangles or ellipses in pixels or percentages, "
            "and the tool builds the mask itself. Inpainting works only "
            "with OpenAI; with Google and OpenRouter the tool says so "
            "instead of starting. With `elenco_modelli` it lists the "
            "OpenRouter image models, so one can be picked with `modello`. "
            "It spends money or provider credit: use it when the user asks "
            "to create or transform an image, not to describe an "
            "attachment. Without a key configured the tool says so: in "
            "that case propose local generation with the `invokeai` skill."
        ),
        schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What the image must show, or which edit "
                                   "to apply when there is a `riferimento`. "
                                   "English usually works better.",
                },
                "riferimento": {
                    "type": "string",
                    "description": "Image to edit: path (relative to the "
                                   "project), data URL, or `ultimo` for the "
                                   "image attached last in the chat. Omit it "
                                   "to generate from scratch.",
                },
                "provider": {
                    "type": "string",
                    "enum": ["openai", "google", "openrouter"],
                    "description": "Forces a provider. When omitted, the "
                                   "one with a configured key is used.",
                },
                "modello": {
                    "type": "string",
                    "description": "Image model of the provider. On "
                                   "OpenRouter it is the catalog slug, for "
                                   "example openai/gpt-image-2: see it with "
                                   "`elenco_modelli`. Omit for the default.",
                },
                "dimensione": {
                    "type": "string",
                    "description": "OpenAI: 1024x1024, 1536x1024, 1024x1536 "
                                   "or auto. Google and OpenRouter: aspect "
                                   "ratios such as 1:1, 16:9.",
                },
                "nome_file": {
                    "type": "string",
                    "description": "File name without extension. When "
                                   "omitted it is derived from the prompt.",
                },
                "zone": {
                    "type": "array",
                    "description": "Inpainting: the areas the model may "
                                   "redraw, and nothing else. OpenAI only "
                                   "(with Google and OpenRouter the tool says "
                                   "so and spends nothing). Requires "
                                   "`riferimento`.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tipo": {"type": "string",
                                     "enum": ["rettangolo", "ellisse"],
                                     "description": "rettangolo "
                                                    "(rectangle) or "
                                                    "ellisse (ellipse).",
                                     "default": "rettangolo"},
                            "x": {"type": ["integer", "string"],
                                  "description": "Left edge: pixels or "
                                                 "percentage (\"20%\")."},
                            "y": {"type": ["integer", "string"],
                                  "description": "Top edge: pixels or "
                                                 "percentage."},
                            "larghezza": {"type": ["integer", "string"],
                                          "description": "Width: pixels or "
                                                         "percentage."},
                            "altezza": {"type": ["integer", "string"],
                                        "description": "Height: pixels or "
                                                       "percentage."},
                        },
                        "required": ["x", "y", "larghezza", "altezza"],
                    },
                },
                "maschera": {
                    "type": "string",
                    "description": "A ready-made inpainting mask: path of "
                                   "a PNG with transparency or a data URL. "
                                   "Transparent = area to redraw, same size "
                                   "as the image. Alternative to `zone`.",
                },
                "morbido": {
                    "type": "integer",
                    "description": "Pixels of blur on the zone edges "
                                   "(0 = hard edge). Useful when the area "
                                   "around the zone is one flat color.",
                },
                "elenco_modelli": {
                    "type": "boolean",
                    "description": "When true, generates nothing: lists the "
                                   "OpenRouter image models with their "
                                   "slug. No cost.",
                },
            },
            "required": ["prompt"],
        },
        handler=handler,
    )
