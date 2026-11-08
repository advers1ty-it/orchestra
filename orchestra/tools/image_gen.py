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
            "Genera un'immagine da un prompt di testo, oppure modifica "
            "un'immagine esistente, con il provider configurato (OpenAI, "
            "Google o OpenRouter). Salva il risultato in immagini/ nel "
            "progetto. Per modificare, passa `riferimento`: un percorso del "
            "progetto, una data URL, oppure `ultimo` per l'immagine appena "
            "allegata dall'utente. Per l'inpainting (cambiare SOLO una zona, "
            "lasciando intatto il resto) passa `zone`: rettangoli o ellissi "
            "in pixel o percentuali, e la maschera la costruisce il tool. "
            "L'inpainting funziona solo con OpenAI; con Google e OpenRouter "
            "il tool lo dice invece di partire. Con `elenco_modelli` elenca i "
            "modelli immagine di OpenRouter, per sceglierne uno con "
            "`modello`. Costa denaro o credito sul provider: usalo quando "
            "l'utente chiede di creare o trasformare un'immagine, non per "
            "descrivere un allegato. Se nessuna chiave e' configurata, il "
            "tool lo dice: in quel caso proponi la generazione locale con la "
            "skill `invokeai`."
        ),
        schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Cosa deve mostrare l'immagine, o quale "
                                   "modifica applicare se c'e' un "
                                   "riferimento. In inglese di solito rende "
                                   "meglio.",
                },
                "riferimento": {
                    "type": "string",
                    "description": "Immagine da modificare: percorso (relativo "
                                   "al progetto), data URL, oppure `ultimo` "
                                   "per l'ultima immagine allegata in chat. "
                                   "Ometti per generare da zero.",
                },
                "provider": {
                    "type": "string",
                    "enum": ["openai", "google", "openrouter"],
                    "description": "Forza un provider. Se omesso si usa "
                                   "quello con la chiave configurata.",
                },
                "modello": {
                    "type": "string",
                    "description": "Modello di immagini del provider. Su "
                                   "OpenRouter e' lo slug del catalogo, per "
                                   "esempio openai/gpt-image-2: guardalo con "
                                   "`elenco_modelli`. Ometti per il "
                                   "predefinito.",
                },
                "dimensione": {
                    "type": "string",
                    "description": "OpenAI: 1024x1024, 1536x1024, 1024x1536 "
                                   "o auto. Google e OpenRouter: proporzioni "
                                   "come 1:1, 16:9.",
                },
                "nome_file": {
                    "type": "string",
                    "description": "Nome del file senza estensione. Se "
                                   "omesso si ricava dal prompt.",
                },
                "zone": {
                    "type": "array",
                    "description": "Inpainting: le zone in cui il modello puo' "
                                   "ridisegnare, e nient'altro. Solo con "
                                   "OpenAI (per Google e OpenRouter il tool lo "
                                   "dice e non spende). Richiede "
                                   "`riferimento`.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tipo": {"type": "string",
                                     "enum": ["rettangolo", "ellisse"]},
                            "x": {"type": ["integer", "string"]},
                            "y": {"type": ["integer", "string"]},
                            "larghezza": {"type": ["integer", "string"]},
                            "altezza": {"type": ["integer", "string"]},
                        },
                        "required": ["x", "y", "larghezza", "altezza"],
                    },
                },
                "maschera": {
                    "type": "string",
                    "description": "Maschera gia' pronta per l'inpainting: "
                                   "percorso di un PNG con trasparenza o data "
                                   "URL. Trasparente = zona da ridisegnare, "
                                   "stessa misura dell'immagine. Alternativa a "
                                   "`zone`.",
                },
                "morbido": {
                    "type": "integer",
                    "description": "Pixels di sfumatura dei bordi delle zone "
                                   "(0 = bordo netto). Utile quando attorno "
                                   "alla zona c'e' un colore uniforme.",
                },
                "elenco_modelli": {
                    "type": "boolean",
                    "description": "Se true, non genera niente: elenca i "
                                   "modelli immagine di OpenRouter con il loro "
                                   "slug. Nessun costo.",
                },
            },
            "required": ["prompt"],
        },
        handler=handler,
    )
