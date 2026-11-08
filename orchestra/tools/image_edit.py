"""Il tool `image_edit`: montare su un'immagine, senza rigenerarla.

Perche' un tool separato da `image_gen`: sono due gesti diversi e l'utente
si accorge della differenza. `image_gen` chiama un modello, che ridisegna
tutto: un logo torna sbagliato, un prezzo torna con altre cifre. Questo qui
incolla i file veri e disegna il testo vero, e i pixel che non tocca
restano quelli dell'originale. Un prezzo e un logo corretti non sono un
caso di "generazione", sono un montaggio.

Funziona con JPEG, PNG e WebP. Un JPEG in ingresso resta un JPEG in
uscita, quindi la foto non si trasforma in un PNG enorme; se serve la
trasparenza si chiede `formato="png"`.

Le immagini si leggono con la stessa guardia di `image_gen`
(`_riferimento`): percorso dentro il progetto, data URL, oppure `ultimo`
per l'allegato appena mandato in chat. Un `font` indicato dal modello
passa dallo stesso confine degli altri percorsi.
"""

from __future__ import annotations

from .. import image_gen as ig
from .. import montaggio
from ..types import Tool, ToolResult
from .image_gen import _riferimento, _root_progetto


def _num(valore, predefinito: int) -> int:
    try:
        return int(float(str(valore).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return predefinito


def tool_image_edit() -> Tool:
    def handler(immagine: str = "", operazioni: list | None = None,
                nome_file: str = "", formato: str = "",
                qualita=95) -> ToolResult:
        sorgente = (immagine or "").strip() or "ultimo"
        try:
            base = _riferimento(sorgente)
            if base is None:
                raise montaggio.MontaggioError(
                    "serve un'immagine di partenza: passa `immagine` con un "
                    "percorso, una data URL, o `ultimo` per l'allegato in chat."
                )
            dati, mime = base

            # Le immagini da incollare si risolvono qui, dove c'e' il gate
            # dei permessi: il motore di montaggio riceve byte e basta.
            if isinstance(operazioni, list):
                for indice, op in enumerate(operazioni, start=1):
                    if not isinstance(op, dict):
                        continue
                    if str(op.get("tipo") or "").strip().lower() == "testo":
                        font = str(op.get("font") or "").strip()
                        if font:
                            from ._guard import _safe_path

                            try:
                                op["font"] = str(_safe_path(font))
                            except (ValueError, PermissionError) as e:
                                raise montaggio.MontaggioError(str(e)) from e

            img = montaggio.monta(
                dati, mime, operazioni,
                cartella=_root_progetto(),
                nome_file=nome_file,
                formato=formato,
                qualita=_num(qualita, 95),
                risolvi=lambda v: _riferimento(v)[0],
            )
        except (montaggio.MontaggioError, ig.ImageGenError) as e:
            # `_riferimento` e' condiviso con `image_gen`: parla con i suoi
            # errori, e un percorso mancante deve restare un messaggio per
            # l'utente, non un'eccezione che esce dal tool.
            return ToolResult(text=f"ERRORE: {e}")
        except (ValueError, PermissionError) as e:
            # Le guardie di percorso hanno gia' detto cosa serve: riportare
            # il loro messaggio e' meglio di un errore generico del tool.
            return ToolResult(text=f"ERRORE: {e}")
        except OSError as e:
            return ToolResult(text=f"ERRORE: non leggo l'immagine: {e}")

        percorso = str(img.percorso)
        try:
            percorso = str(img.percorso.relative_to(_root_progetto()))
        except ValueError:
            pass
        note = ("\n" + "\n".join(f"- {n}" for n in img.note)) if img.note else ""
        return ToolResult(
            text=(
                f"Immagine montata: {percorso} ({img.larghezza}x{img.altezza}, "
                f"{img.formato}, {img.operazioni} operazioni, {img.kb} KB). "
                f"L'originale non e' stato toccato. I pixel fuori dalle zone "
                f"montate sono quelli veri, non rigenerati.{note}\n"
                f"Mostrala all'utente citando quel percorso. Se il risultato "
                f"non e' dove lo volevi, rifai il montaggio con coordinate "
                f"diverse: costa niente e non consuma credito."
            ),
            anteprime=[img.data_url()],
        )

    return Tool(
        name="image_edit",
        description=(
            "Composites onto an existing image without regenerating it: "
            "pastes a PNG logo (keeping its transparency), draws text, crops, "
            "resizes. Pixels outside the touched areas stay exactly as they "
            "were, so a logo and a price stay correct. Works with JPEG, PNG "
            "and WebP; the output keeps the input format. Saves into "
            "immagini/ and shows a preview. This is the right tool for text, "
            "prices, logos, watermarks and frames on a photo the user "
            "attached: for those do NOT use `image_gen`, which redraws "
            "everything and invents the letters. It costs nothing: no key, "
            "no credit. Coordinates accept pixels or percentages (\"50%\") "
            "and apply to the image already straightened according to EXIF."
        ),
        schema={
            "type": "object",
            "properties": {
                "immagine": {
                    "type": "string",
                    "description": "Starting image: path relative to the "
                                   "project, data URL, or `ultimo` for the "
                                   "image attached last in the chat "
                                   "(default).",
                },
                "operazioni": {
                    "type": "array",
                    "description": "The operations, in order. Each object "
                                   "has `tipo`. Example: [{\"tipo\":\"incolla\","
                                   "\"immagine\":\"logo.png\",\"x\":\"82%\","
                                   "\"y\":\"4%\",\"larghezza\":\"16%\"},"
                                   "{\"tipo\":\"testo\",\"testo\":\"€540\","
                                   "\"x\":\"50%\",\"y\":\"86%\","
                                   "\"dimensione\":96,\"grassetto\":true,"
                                   "\"ancora\":\"mm\",\"riquadro\":\"#d40000\","
                                   "\"margine\":24}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tipo": {
                                "type": "string",
                                "enum": list(montaggio.OPERAZIONI),
                                "description": "One of the names in the "
                                               "enum: ritaglia (crop), "
                                               "ridimensiona (resize), "
                                               "incolla (paste), testo "
                                               "(text).",
                            },
                            "x": {
                                "type": "string",
                                "description": "Horizontal position: pixels "
                                               "(120) or percentage (\"50%\").",
                            },
                            "y": {
                                "type": "string",
                                "description": "Vertical position, same as `x`.",
                            },
                            "larghezza": {
                                "type": "string",
                                "description": "Crop/resize: width in pixels "
                                               "or % of the original. Paste: "
                                               "how wide the logo must be.",
                            },
                            "altezza": {
                                "type": "string",
                                "description": "Same as `larghezza` for "
                                               "height. Give only one and the "
                                               "proportions are kept.",
                            },
                            "scala": {
                                "type": "string",
                                "description": "Resize: \"50%\" or 0.5.",
                            },
                            "ancora": {
                                "type": "string",
                                "description": "Which point of the paste/text "
                                               "lands on x,y: two letters, "
                                               "horizontal l/m/r and vertical "
                                               "a/m/b. \"la\" is top left "
                                               "(default), \"mm\" the center, "
                                               "\"rb\" bottom right.",
                            },
                            "immagine": {
                                "type": "string",
                                "description": "Paste: the file to paste "
                                               "(path, data URL or "
                                               "`ultimo`). A PNG with "
                                               "transparency stays "
                                               "transparent.",
                            },
                            "opacita": {
                                "type": "string",
                                "description": "Paste: 1-100, for a logo "
                                               "used as a watermark.",
                            },
                            "testo": {
                                "type": "string",
                                "description": "Text: the string to draw. "
                                               "\\n starts a new line.",
                            },
                            "dimensione": {
                                "type": "integer",
                                "description": "Text: font height in pixels "
                                               "(default 64).",
                            },
                            "colore": {
                                "type": "string",
                                "description": "Text: text color, `#rrggbb` "
                                               "(default white).",
                            },
                            "grassetto": {
                                "type": "boolean",
                                "description": "Text: use a system bold "
                                               "font, when available.",
                            },
                            "font": {
                                "type": "string",
                                "description": "Text: path of a .ttf or .otf "
                                               "inside the project, when an "
                                               "exact font is needed.",
                            },
                            "riquadro": {
                                "type": "string",
                                "description": "Text: background color "
                                               "behind the text (e.g. "
                                               "\"#d40000\") to keep it "
                                               "readable on a photo.",
                            },
                            "margine": {
                                "type": "integer",
                                "description": "Text: pixels of padding "
                                               "between text and box "
                                               "(default 18).",
                            },
                            "raggio": {
                                "type": "integer",
                                "description": "Text: rounded corners of the "
                                               "box (default 14).",
                            },
                            "bordo": {
                                "type": "integer",
                                "description": "Text: thickness of the outline "
                                               "around the letters.",
                            },
                            "colore_bordo": {
                                "type": "string",
                                "description": "Text: outline color "
                                               "(default black).",
                            },
                        },
                        "required": ["tipo"],
                    },
                },
                "nome_file": {
                    "type": "string",
                    "description": "File name without extension. Default: "
                                   "montaggio.",
                },
                "formato": {
                    "type": "string",
                    "enum": ["", "jpg", "png", "webp"],
                    "description": "Output format. Empty = same as the "
                                   "input. Use `png` when transparency is "
                                   "needed: a JPEG cannot keep it.",
                },
                "qualita": {
                    "type": "integer",
                    "description": "JPEG/WebP quality, 1-100 (default 95). "
                                   "Low = smaller file, more artifacts.",
                },
            },
            "required": ["operazioni"],
        },
        handler=handler,
    )
