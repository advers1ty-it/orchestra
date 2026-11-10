"""Il tool `immagine`: un solo ingresso per generare e per montare.

PERCHE' UNO E NON DUE

`image_gen` e `image_edit` erano due tool, e il contratto che il modello
legge li contava per 10.000 caratteri: un quarto di tutti gli strumenti
per una cosa sola. La divisione era giusta nel codice — un modello che
ridisegna e un montaggio che incolla i pixel veri sono due motori diversi
— ma sbagliata nell'elenco: il modello non sceglie fra due
implementazioni, sceglie fra due gesti, e il gesto si dice con una parola
(`azione`).

Quindi qui c'e' un solo ingresso e due strade:

- `azione="genera"`: chiama il modello. Serve per inventare, per
  ricomporre una scena attorno a file veri (`riferimenti`), e per
  ridisegnare UNA zona (`zone`, solo OpenAI).
- `azione="modifica"`: monta senza modello. Incolla il logo vero,
  disegna il testo vero, ritaglia, ridimensiona; i pixel fuori dalle zone
  toccate restano quelli dell'originale, e non costa niente.

I due motori restano dove sono (`tools/image_gen.py` e
`tools/image_edit.py`): spostare 600 righe per unire due nomi sarebbe
stato rischio senza guadagno. Cambia l'ingresso, non il comportamento.

L'INFERENZA C'E' MA NON E' LA REGOLA

Se `azione` manca, si deduce: `operazioni` vuol dire montaggio, `prompt`
vuol dire generazione. Serve ai vecchi punti di chiamata e alle prove; lo
schema pero' chiede `azione`, perche' un modello che la omette sta
scegliendo a caso fra due gesti che costano cose diverse.
"""

from __future__ import annotations

from typing import Any

from .. import montaggio
from ..types import Tool, ToolResult
from .image_edit import tool_image_edit
from .image_gen import tool_image_gen


def _schema_operazioni() -> dict[str, Any]:
    """Le operazioni di montaggio: nomi e campi, senza il romanzo.

    Le descrizioni sono state accorciate rispetto ai due tool separati —
    e' li' che stava buona parte dei 10.000 caratteri — ma ogni campo
    resta spiegato, perche' un parametro senza descrizione il modello lo
    riempie a caso.
    """
    return {
        "type": "array",
        "description": (
            "modifica: the operations, in order, each with `tipo`. Example: "
            "[{\"tipo\":\"incolla\",\"immagine\":\"logo.png\",\"x\":\"82%\","
            "\"y\":\"4%\",\"larghezza\":\"16%\",\"scontorna\":true},"
            "{\"tipo\":\"testo\",\"testo\":\"540 EUR\",\"x\":\"50%\","
            "\"y\":\"86%\",\"dimensione\":96,\"grassetto\":true,"
            "\"ancora\":\"mm\",\"riquadro\":\"#d40000\"}]"),
        "items": {
            "type": "object",
            "properties": {
                "tipo": {
                    "type": "string",
                    "enum": list(montaggio.OPERAZIONI),
                    "description": "ritaglia (crop), ridimensiona (resize), "
                                   "incolla (paste), testo (text).",
                },
                "x": {"type": "string", "description":
                      "Position: pixels (120) or percentage (\"50%\")."},
                "y": {"type": "string", "description":
                      "Vertical position, same forms as `x`."},
                "larghezza": {"type": "string", "description":
                              "Crop/resize: width in pixels or %. Paste: how "
                              "wide the pasted image must be."},
                "altezza": {"type": "string", "description":
                            "Same as `larghezza`; give only one to keep the "
                            "proportions."},
                "scala": {"type": "string", "description":
                          "Resize: \"50%\" or 0.5."},
                "ancora": {"type": "string", "description":
                           "Which point lands on x,y: horizontal l/m/r plus "
                           "vertical a/m/b (\"la\" top left, \"mm\" center, "
                           "\"rb\" bottom right)."},
                "immagine": {"type": "string", "description":
                             "Paste: the file to paste (path, data URL, "
                             "`ultimo`, `allegato:N`). PNG transparency is "
                             "kept."},
                "opacita": {"type": "string", "description":
                            "Paste: 1-100, for a logo used as a watermark."},
                "scontorna": {"type": "boolean", "description":
                              "Paste: cut out a flat background (white by "
                              "default) and keep the subject. Without it a "
                              "JPEG logo is a white rectangle on the poster."},
                "colore_sfondo": {"type": "string", "description":
                                  "scontorna: background color, #rrggbb."},
                "tolleranza": {"type": "integer", "description":
                               "scontorna: 0-100, how far from the background "
                               "color still counts as background (18)."},
                "sfumatura": {"type": "integer", "description":
                              "scontorna: pixels of soft edge (1)."},
                "ombra": {"type": "integer", "description":
                          "Paste: pixels of drop shadow; without one a cutout "
                          "looks like a sticker."},
                "testo": {"type": "string", "description":
                          "Text to draw; \\n starts a new line."},
                "dimensione": {"type": "integer", "description":
                               "Text: font height in pixels (64)."},
                "colore": {"type": "string", "description":
                           "Text: color, #rrggbb (white)."},
                "grassetto": {"type": "boolean", "description":
                              "Text: use a bold system font."},
                "font": {"type": "string", "description":
                         "Text: path of a .ttf/.otf inside the project."},
                "riquadro": {"type": "string", "description":
                             "Text: background box color (#d40000) to keep it "
                             "readable on a photo."},
                "margine": {"type": "integer", "description":
                            "Text: padding between text and box (18)."},
                "raggio": {"type": "integer", "description":
                           "Text: rounded corners of the box (14)."},
                "bordo": {"type": "integer", "description":
                          "Text: outline thickness around the letters."},
                "colore_bordo": {"type": "string", "description":
                                 "Text: outline color (black)."},
            },
            "required": ["tipo"],
        },
    }


def tool_immagine() -> Tool:
    # Gli handler veri restano quelli dei due moduli: qui si smista e basta.
    _genera = tool_image_gen().handler
    _monta = tool_image_edit().handler

    def handler(azione: str = "", prompt: str = "", riferimento: str = "",
                riferimenti=None, provider: str = "", modello: str = "",
                dimensione: str = "", risoluzione: str = "",
                nome_file: str = "", zone=None, maschera: str = "",
                morbido: int = 0, elenco_modelli: bool = False,
                immagine: str = "", operazioni: Any = None,
                formato: str = "", qualita: int = 95) -> ToolResult:
        scelta = (azione or "").strip().lower()
        if not scelta:
            # Vecchi punti di chiamata e prove: il gesto si capisce da cosa
            # e' stato passato.
            if operazioni:
                scelta = "modifica"
            elif prompt or riferimento or riferimenti or elenco_modelli:
                scelta = "genera"
        if scelta in ("genera", "crea", "genera_immagine", "create"):
            return _genera(prompt=prompt, provider=provider, modello=modello,
                           dimensione=dimensione, nome_file=nome_file,
                           riferimento=riferimento, riferimenti=riferimenti,
                           maschera=maschera, zone=zone, morbido=morbido,
                           risoluzione=risoluzione, elenco_modelli=elenco_modelli)
        if scelta in ("modifica", "monta", "incolla", "edit", "componi"):
            # `riferimento` e `immagine` sono la stessa domanda ("quale
            # immagine?"): chi arriva da `genera` usa il primo nome.
            return _monta(immagine=(immagine or riferimento), operazioni=operazioni,
                          nome_file=nome_file, formato=formato, qualita=qualita)
        return ToolResult(
            text=("ERRORE: serve `azione`. Usa \"genera\" per inventare o "
                  "ridisegnare con un modello, \"modifica\" per incollare "
                  "logo e testo veri senza rigenerare niente."))

    return Tool(
        name="immagine",
        description=(
            "Images, two gestures in one tool. `azione=\"genera\"` calls a "
            "generative model and redraws every pixel: for a new picture, or "
            "a scene rebuilt around real files (`riferimenti`: the first is "
            "the base, the others are named by position in `prompt`). It is "
            "also the only one that can repaint a single area (`zone`, "
            "OpenAI only) and the only one that spends credit. "
            "`azione=\"modifica\"` composites instead: pastes the real logo "
            "(PNG transparency kept, `scontorna` removes a flat background), "
            "draws the real text, crops, resizes — every other pixel stays "
            "the original, and it costs nothing. For a price, a logo or a "
            "watermark on a photo the user attached, always use `modifica`: "
            "a model invents the letters and the digits. Both write into "
            "immagini/ and show a preview; `ultimo` is the image attached "
            "last in the chat and `allegato:N` the Nth of the last message. "
            "`elenco_modelli` lists the OpenRouter image models without "
            "spending anything."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {
                    "type": "string",
                    "enum": ["genera", "modifica"],
                    "description": "genera (model: create or redraw) or "
                                   "modifica (composite real files, no model).",
                },
                "prompt": {
                    "type": "string",
                    "description": "genera: what the picture must show, or "
                                   "which change to apply when there is a "
                                   "`riferimento`. English usually works "
                                   "better.",
                },
                "riferimento": {
                    "type": "string",
                    "description": "The image to start from: path in the "
                                   "project, data URL, `ultimo`, or "
                                   "`allegato:N` (N from 1). Omit to "
                                   "generate from scratch.",
                },
                "riferimenti": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "genera: more images, the first being the "
                                   "base and the others referenced by "
                                   "position. Same forms as `riferimento`; "
                                   "the cap depends on the model.",
                },
                "provider": {
                    "type": "string",
                    "enum": ["openai", "google", "openrouter"],
                    "description": "Force a provider. Omit it: the one with a "
                                   "configured key is used, and forcing one "
                                   "without a key fails.",
                },
                "modello": {
                    "type": "string",
                    "description": "Model id of the provider (on OpenRouter "
                                   "the catalog slug, see `elenco_modelli`).",
                },
                "dimensione": {
                    "type": "string",
                    "description": "OpenAI: 1024x1024, 1536x1024, 1024x1536 "
                                   "or auto. Others: aspect ratio, e.g. 16:9.",
                },
                "risoluzione": {
                    "type": "string",
                    "enum": ["512", "1K", "1.5K", "2K", "4K"],
                    "description": "Output size tier; 4K is what a printed "
                                   "poster needs. Google and OpenRouter only "
                                   "(OpenAI says so instead of spending), and "
                                   "not every model accepts it.",
                },
                "nome_file": {
                    "type": "string",
                    "description": "File name without extension; derived from "
                                   "the prompt otherwise.",
                },
                "zone": {
                    "type": "array",
                    "description": "genera: the areas the model may redraw "
                                   "and nothing else (inpainting). OpenAI "
                                   "only; requires a reference image. Pixels "
                                   "or percentages.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tipo": {"type": "string",
                                     "enum": ["rettangolo", "ellisse"],
                                     "description": "rettangolo (rectangle) "
                                                    "or ellisse (ellipse).",
                                     "default": "rettangolo"},
                            "x": {"type": ["integer", "string"],
                                  "description": "Left edge."},
                            "y": {"type": ["integer", "string"],
                                  "description": "Top edge."},
                            "larghezza": {"type": ["integer", "string"],
                                          "description": "Width."},
                            "altezza": {"type": ["integer", "string"],
                                        "description": "Height."},
                        },
                        "required": ["x", "y", "larghezza", "altezza"],
                    },
                },
                "maschera": {
                    "type": "string",
                    "description": "genera: a ready-made mask (PNG with "
                                   "transparency, or data URL): transparent "
                                   "= area to redraw. Alternative to `zone`.",
                },
                "morbido": {
                    "type": "integer",
                    "description": "genera: pixels of blur on the zone edges "
                                   "(0 = hard).",
                },
                "elenco_modelli": {
                    "type": "boolean",
                    "description": "Lists the OpenRouter image models and "
                                   "generates nothing. No cost.",
                },
                "operazioni": _schema_operazioni(),
                "formato": {
                    "type": "string",
                    "enum": ["", "jpg", "png", "webp"],
                    "description": "modifica: output format; empty keeps the "
                                   "input one. Use png when transparency is "
                                   "needed.",
                },
                "qualita": {
                    "type": "integer",
                    "description": "modifica: JPEG/WebP quality, 1-100 (95).",
                },
            },
            "required": ["azione"],
        },
        handler=handler,
    )
