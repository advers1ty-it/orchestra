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
            "Monta su un'immagine esistente senza rigenerarla: incolla un "
            "logo PNG (con la sua trasparenza), scrive testo, ritaglia, "
            "ridimensiona. I pixel fuori dalle zone toccate restano quelli "
            "dell'originale, quindi un logo e un prezzo restano corretti. "
            "Funziona con JPEG, PNG e WebP; l'uscita ha lo stesso formato "
            "dell'ingresso. Salva in immagini/ e mostra l'anteprima. "
            "E' il tool giusto per testi, prezzi, loghi, filigrane, cornici "
            "su una foto che l'utente ha allegato: per quelle cose NON usare "
            "`image_gen`, che ridisegna tutto e inventa le lettere. Non costa "
            "niente: nessuna chiave, nessun credito. Le coordinate accettano "
            "pixel oppure percentuali (\"50%\") e valgono sull'immagine gia' "
            "raddrizzata secondo l'EXIF."
        ),
        schema={
            "type": "object",
            "properties": {
                "immagine": {
                    "type": "string",
                    "description": "Immagine di partenza: percorso relativo "
                                   "al progetto, data URL, oppure `ultimo` "
                                   "per l'ultima immagine allegata in chat "
                                   "(default).",
                },
                "operazioni": {
                    "type": "array",
                    "description": "Le operazioni, in ordine. Ogni oggetto ha "
                                   "`tipo`. Esempio: [{\"tipo\":\"incolla\","
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
                                "description": "ritaglia, ridimensiona, "
                                               "incolla o testo.",
                            },
                            "x": {
                                "type": "string",
                                "description": "Posizione orizzontale: pixel "
                                               "(120) o percentuale (\"50%\").",
                            },
                            "y": {
                                "type": "string",
                                "description": "Posizione verticale, come `x`.",
                            },
                            "larghezza": {
                                "type": "string",
                                "description": "ritaglia/ridimensiona: "
                                               "larghezza in pixel o % della "
                                               "base. incolla: quanto deve "
                                               "essere largo il logo.",
                            },
                            "altezza": {
                                "type": "string",
                                "description": "Come `larghezza` per "
                                               "l'altezza. Se ne dai una sola, "
                                               "le proporzioni si conservano.",
                            },
                            "scala": {
                                "type": "string",
                                "description": "ridimensiona: \"50%\" o 0.5.",
                            },
                            "ancora": {
                                "type": "string",
                                "description": "Quale punto di incolla/testo "
                                               "cade su x,y: due lettere, "
                                               "orizzontale l/m/r e verticale "
                                               "a/m/b. \"la\" e' in alto a "
                                               "sinistra (default), \"mm\" il "
                                               "centro, \"rb\" in basso a "
                                               "destra.",
                            },
                            "immagine": {
                                "type": "string",
                                "description": "incolla: il file da "
                                               "incollare (percorso, data URL "
                                               "o `ultimo`). Un PNG con "
                                               "trasparenza resta "
                                               "trasparente.",
                            },
                            "opacita": {
                                "type": "string",
                                "description": "incolla: 1-100, per un logo "
                                               "in filigrana.",
                            },
                            "testo": {
                                "type": "string",
                                "description": "testo: la stringa da "
                                               "disegnare. \\n va a capo.",
                            },
                            "dimensione": {
                                "type": "integer",
                                "description": "testo: altezza del carattere "
                                               "in pixel (default 64).",
                            },
                            "colore": {
                                "type": "string",
                                "description": "testo: colore del testo, "
                                               "`#rrggbb` (default bianco).",
                            },
                            "grassetto": {
                                "type": "boolean",
                                "description": "testo: usa un font bold di "
                                               "sistema, se disponibile.",
                            },
                            "font": {
                                "type": "string",
                                "description": "testo: percorso di un .ttf o "
                                               ".otf nel progetto, se serve un "
                                               "font preciso.",
                            },
                            "riquadro": {
                                "type": "string",
                                "description": "testo: colore dello sfondo "
                                               "dietro al testo (es. "
                                               "\"#d40000\"), per renderlo "
                                               "leggibile sulla foto.",
                            },
                            "margine": {
                                "type": "integer",
                                "description": "testo: pixel di spazio fra "
                                               "testo e riquadro (default 18).",
                            },
                            "raggio": {
                                "type": "integer",
                                "description": "testo: angoli arrotondati del "
                                               "riquadro (default 14).",
                            },
                            "bordo": {
                                "type": "integer",
                                "description": "testo: spessore del contorno "
                                               "attorno alle lettere.",
                            },
                            "colore_bordo": {
                                "type": "string",
                                "description": "testo: colore del contorno "
                                               "(default nero).",
                            },
                        },
                        "required": ["tipo"],
                    },
                },
                "nome_file": {
                    "type": "string",
                    "description": "Nome del file senza estensione. Default: "
                                   "montaggio.",
                },
                "formato": {
                    "type": "string",
                    "enum": ["", "jpg", "png", "webp"],
                    "description": "Formato di uscita. Vuoto = come "
                                   "l'ingresso. Usa `png` se serve la "
                                   "trasparenza: un JPEG non la conserva.",
                },
                "qualita": {
                    "type": "integer",
                    "description": "Qualita' JPEG/WebP, 1-100 (default 95). "
                                   "Bassa = file leggero, piu' artefatti.",
                },
            },
            "required": ["operazioni"],
        },
        handler=handler,
    )
