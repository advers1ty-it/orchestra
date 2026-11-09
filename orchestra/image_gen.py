"""Generare immagini con le API dei provider che l'utente ha gia' configurato.

Il perche' di questo modulo: un modello linguistico sa scrivere un prompt, ma
non e' lui a disegnare. La generazione e' una chiamata a parte, su un endpoint
diverso da quello della chat, e la risposta non e' testo: e' un'immagine. Senza
questo pezzo, "scegli un modello con la generazione immagini" produce una
richiesta di chat che non genera niente.

Le API qui sotto sono volutamente diverse e non si finge il contrario: OpenAI
vuole `model` nel corpo e restituisce `data[0].b64_json`; Google vuole il
modello nel percorso e restituisce le parti dentro `candidates[0]`; OpenRouter
ha una sua `/api/v1/images` che unifica generazione e modifica e in cambio
accetta i suoi slug e le sue proporzioni. Un adapter per provider, come per la
chat.

Nessuna dipendenza nuova: `urllib` della standard library basta, come per il
resto di Orchestra. E nessuna chiave in chiaro: si leggono dall'ambiente e dal
`.env` che il pannello Opzioni scrive gia'.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import marcatura
from .providers import load_env

# Lo stesso .env che legge il resto dell'applicazione.
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# Un'immagine puo' metterci decine di secondi: i modelli di qualita' non sono
# istantanei, e un timeout da chat (30 s) taglierebbe una richiesta che stava
# per riuscire.
TIMEOUT = 180

# Oltre questo il prompt non e' piu' un prompt: e' un testo incollato, e i
# provider lo troncano o lo rifiutano. Si ferma prima e lo si dice.
MAX_PROMPT = 4000

# Quante immagini di riferimento si possono mandare in una richiesta. Il
# tetto vero lo decide il modello, non l'API: Gemini 3.1 Flash Image
# ("Nano Banana 2") ne accetta 14, Gemini 2.5 Flash Image 3, GPT Image 16.
# Quattordici e' il massimo che il catalogo dichiara, e fermarsi li' evita
# una richiesta che il provider rifiuterebbe comunque.
MAX_RIFERIMENTI = 14

# Oltre questa somma di byte i riferimenti si riducono prima di partire: tre
# foto a piena risoluzione in una data URL base64 sono peso che il modello non
# usa (le riporta comunque a una misura di lavoro), si pagano come token di
# ingresso e possono far rispondere 413.
LIMITE_BYTES_RIFERIMENTI = 3 * 1024 * 1024
LATO_RIFERIMENTO = 1536

# I modelli predefiniti, verificati sulla documentazione ufficiale. Sono
# costanti e non stringhe sparse nel codice: quando un provider ne ritira uno,
# c'e' un posto solo da cambiare.
MODELLI = {
    "openai": "gpt-image-2.5-sunburst",
    "google": "gemini-nano-banana-2.1",
    # OpenRouter non serve un modello suo: serve uno dei modelli di immagini
    # del suo catalogo. Gemini 3.1 Flash Image e' una scelta equilibrata e
    # accetta immagini di riferimento; si puo' cambiare con `modello` o
    # ORCHESTRA_IMAGE_MODEL.
    "openrouter": "google/gemini-3.1-flash-image",
}

# Dove si chiede l'immagine. Sono gli endpoint di GENERAZIONE, non quelli
# OpenAI-compatibili della chat: `providers.KNOWN_PROVIDERS` porta
# `/v1beta/openai`, che per un'immagine non serve.
ENDPOINT = {
    "openai": "https://api.openai.com/v1/images/generations",
    "google": "https://generativelanguage.googleapis.com/v1/models/{modello}:generateContent",
    # L'API immagini dedicata di OpenRouter: una sola forma per generare e
    # modificare, con `input_references` per l'immagine di partenza.
    "openrouter": "https://openrouter.ai/api/v1/images",
}

# La modifica di un'immagine, su OpenAI, e' un endpoint diverso e vuole
# multipart/form-data: il file non sta in JSON. Su Google e' lo stesso
# generateContent, con l'immagine fra le parti.
ENDPOINT_EDITS = "https://api.openai.com/v1/images/edits"

# La documentazione Google mostra la generazione immagini su `/v1/`, mentre
# il riferimento generale di GenerateContent usa `/v1beta/`. Non e' chiaro
# quale versione sia abilitata per ogni progetto: se `/v1/` risponde 404 si
# riprova qui, invece di dire all'utente che il modello non esiste.
ENDPOINT_GOOGLE_BETA = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{modello}:generateContent"
)

# Il catalogo dei modelli immagine di OpenRouter: non costa niente
# interrogarlo e dice, per ogni modello, se accetta un'immagine in ingresso.
ENDPOINT_MODELLI = "https://openrouter.ai/api/v1/images/models"

# Le chiavi accettate, nell'ordine in cui si sceglie quando l'utente non dice
# il provider: prima OpenAI, poi Google. Un utente con entrambe le chiavi puo'
# scegliere con il parametro `provider`, o con ORCHESTRA_IMAGE_PROVIDER.
CHIAVI = {
    "openai": ("OPENAI_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
}

# Come si chiama un provider quando lo scrive una persona.
ALIAS = {
    "openai": "openai",
    "gpt": "openai",
    "gpt-image": "openai",
    "google": "google",
    "gemini": "google",
    "nano-banana": "google",
    "openrouter": "openrouter",
    "router": "openrouter",
    "or": "openrouter",
}

# I livelli di risoluzione che le API conoscono. Non sono pixel: ogni
# provider li traduce nelle proprie misure, e per questo un "1K" non si
# converte in una dimensione da mandare altrove. Google si ferma a 1K/2K/4K;
# OpenRouter in piu' accetta 512 e 1.5K.
RISOLUZIONI = ("512", "1K", "1.5K", "2K", "4K")

_ESTENSIONI = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}


class ImageGenError(RuntimeError):
    """Generazione non riuscita. Il messaggio dice cosa fare, non solo cosa e'.

    `status` e' il codice HTTP quando c'e': serve a distinguere un 404 da
    un prompt rifiutato senza dover leggere il testo dell'errore.
    """

    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Immagine:
    """Un'immagine generata, gia' scritta su disco."""

    dati: bytes
    mime: str
    percorso: Path
    provider: str
    modello: str
    # Il sidecar `.ai.json`, quando e' stato scritto. None se il disco non
    # lo ha permesso: l'immagine c'e' lo stesso.
    metadati: Path | None = None

    @property
    def kb(self) -> int:
        return max(1, len(self.dati) // 1024)

    def data_url(self) -> str:
        """La stessa forma degli allegati: `data:image/png;base64,...`."""
        b64 = base64.b64encode(self.dati).decode("ascii")
        return f"data:{self.mime};base64,{b64}"


def ambiente() -> dict[str, str]:
    """Le chiavi disponibili: prima il `.env`, poi l'ambiente del processo.

    L'ambiente vince, come in `webapp.py`: una variabile esportata a mano deve
    poter correggere il file senza modificarlo.
    """
    env = load_env(ENV_PATH)
    env.update(os.environ)
    return env


def chiave(provider: str, env: dict[str, str] | None = None) -> str:
    env = env if env is not None else ambiente()
    for nome in CHIAVI.get(provider, ()):
        valore = (env.get(nome) or "").strip()
        if valore:
            return valore
    return ""


def provider_disponibile(preferito: str = "",
                         env: dict[str, str] | None = None) -> str:
    """Quale provider usare, o "" se non ce n'e' nessuno configurato.

    Un provider chiesto esplicitamente vince anche se la chiave manca: e' un
    errore da dire ("manca OPENAI_API_KEY"), non una scelta silenziosa di un
    altro servizio — che sarebbe una spesa che l'utente non ha autorizzato.

    Se nessuno lo chiede, si preferisce il provider della chat: chi usa
    OpenRouter per parlare ai modelli ha gia' quella chiave, e usare un'altra
    API di nascosto sarebbe una seconda spesa da un'altra parte.
    """
    env = env if env is not None else ambiente()
    esplicito = (preferito or env.get("ORCHESTRA_IMAGE_PROVIDER", "") or "").strip()
    if esplicito:
        return ALIAS.get(esplicito.lower(), esplicito.lower())
    chat = (env.get("ORCHESTRA_PROVIDER", "") or "").strip().lower()
    if chat in MODELLI and chiave(chat, env):
        return chat
    for provider in MODELLI:
        if chiave(provider, env):
            return provider
    return ""


def _get_json(url: str, intestazioni: dict, provider: str) -> dict:
    testa = {"User-Agent": "Mozilla/5.0 (compatible; orchestra/0.1)"}
    testa.update(intestazioni)
    req = urllib.request.Request(url, headers=testa, method="GET")
    return _richiedi(req, provider)


def modelli_immagine(env: dict[str, str] | None = None) -> list[dict]:
    """Il catalogo dei modelli immagine di OpenRouter, normalizzato.

    Perche' passa da qui invece di lasciare che l'agente indovini un nome: i
    modelli dei provider hanno slug che cambiano (`google/gemini-2.5-flash-image`,
    `black-forest-labs/flux.2-pro`, `bytedance-seed/seedream-4.5`), e un nome
    sbagliato costa una richiesta e un 404. Il catalogo e' la fonte ufficiale
    e dice anche quali accettano un'immagine di riferimento.
    """
    env = env if env is not None else ambiente()
    intestazioni = {}
    token = chiave("openrouter", env)
    if token:
        intestazioni["Authorization"] = f"Bearer {token}"
    dati = _get_json(ENDPOINT_MODELLI, intestazioni, "openrouter")
    voci = []
    for voce in dati.get("data") or []:
        if not isinstance(voce, dict):
            continue
        identificativo = str(voce.get("id") or "").strip()
        if not identificativo:
            continue
        architettura = voce.get("architecture")
        ingressi = ((architettura or {}).get("input_modalities")
                    if isinstance(architettura, dict) else None) or []
        parametri = voce.get("supported_parameters")
        voci.append({
            "id": identificativo,
            "nome": str(voce.get("name") or identificativo),
            "riferimento": "image" in [str(i).lower() for i in ingressi],
            "parametri": sorted(parametri) if isinstance(parametri, dict) else [],
        })
    return voci


def _errore_http(provider: str, code: int, dettaglio: str) -> ImageGenError:
    """Un errore HTTP tradotto in cosa fare.

    Il codice da solo non basta: 401 e 429 hanno la stessa forma e richiedono
    due azioni opposte (cambiare la chiave, aspettare).
    """
    nome = {"openai": "OpenAI", "google": "Google AI Studio",
            "openrouter": "OpenRouter"}.get(provider, provider)
    pulito = " ".join((dettaglio or "").split())[:300]
    if code == 401:
        testo = (f"{nome}: chiave non valida o scaduta (401). "
                 f"Controllala nel pannello Opzioni.")
    elif code == 403:
        testo = (f"{nome}: la chiave non ha accesso a questo modello (403). "
                 f"Verifica che il progetto abbia l'API abilitata.")
    elif code == 402:
        testo = (f"{nome}: credito insufficiente (402). Le immagini si "
                 f"pagano sul saldo del conto, non con il piano gratuito: "
                 f"ricarica da openrouter.ai/credits.")
    elif code == 404:
        testo = (f"{nome}: modello non trovato (404). Controlla il nome in "
                 f"`modello`, o scegline uno dal catalogo del provider.")
    elif code == 429:
        testo = (f"{nome}: quota o limite di richieste raggiunto (429). "
                 f"Riprova piu' tardi o controlla il credito.")
    elif code == 400:
        testo = (f"{nome}: richiesta rifiutata (400: prompt o parametri non "
                 f"validi). Prova un prompt piu' semplice o un'altra dimensione.")
        if "reference" in pulito.lower():
            # Il tetto dei riferimenti e' una proprieta' del modello, non
            # dell'API: lo stesso corpo su un altro modello passa. Dirlo
            # solo quando il dettaglio ne parla, o sembrerebbe un consiglio
            # sempre valido.
            testo += (" Se il dettaglio parla di immagini di riferimento: "
                      "questo modello ne accetta meno di quelle che hai "
                      "mandato. Scegline un altro con `elenco_modelli`, o "
                      "togli quelle che il prompt non nomina.")
    elif code >= 500:
        testo = f"{nome}: errore del servizio ({code}). Riprova fra poco."
    else:
        testo = f"{nome}: HTTP {code}."
    if pulito:
        testo += f" Dettaglio: {pulito}"
    return ImageGenError(testo, status=code)


def _richiedi(req: urllib.request.Request, provider: str) -> dict:
    """Manda la richiesta e torna il JSON, con gli errori gia' tradotti."""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            grezzo = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        dettaglio = ""
        try:
            dettaglio = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - il corpo d'errore e' un extra
            pass
        raise _errore_http(provider, e.code, dettaglio) from e
    except urllib.error.URLError as e:
        raise ImageGenError(
            f"rete non raggiungibile: {e.reason}. La generazione ha bisogno "
            f"di connessione; il resto di Orchestra funziona anche offline."
        ) from e
    try:
        dati = json.loads(grezzo)
    except json.JSONDecodeError as e:
        raise ImageGenError(
            f"risposta non JSON da {provider}: {grezzo[:200]}"
        ) from e
    if not isinstance(dati, dict):
        raise ImageGenError(f"risposta inattesa da {provider}: {grezzo[:200]}")
    # Alcuni gateway rispondono 200 con l'errore nel corpo.
    errore = dati.get("error")
    if errore:
        messaggio = errore if isinstance(errore, str) else json.dumps(errore)[:300]
        raise ImageGenError(f"{provider}: {messaggio}")
    return dati


def _post_json(url: str, corpo: dict, intestazioni: dict,
               provider: str) -> dict:
    body = json.dumps(corpo).encode("utf-8")
    testa = {"Content-Type": "application/json",
             "User-Agent": "Mozilla/5.0 (compatible; orchestra/0.1)"}
    testa.update(intestazioni)
    req = urllib.request.Request(url, data=body, headers=testa, method="POST")
    return _richiedi(req, provider)


def _post_multipart(url: str, campi: dict, allegati: list[tuple],
                    intestazioni: dict, provider: str) -> dict:
    """Una richiesta multipart/form-data, senza dipendenze.

    Ogni allegato e' `(nome_campo, nome_file, mime, byte)`: di solito c'e'
    solo `image`, ma l'inpainting ne vuole due, `image` e `mask`. Il confine
    lo genera `uuid`: deve essere unico, o un pezzo di file che contiene la
    stessa stringa spezza la richiesta.
    """
    confine = "----orchestra" + uuid.uuid4().hex
    parti: list[bytes] = []
    for nome, valore in campi.items():
        parti.append(
            f'--{confine}\r\nContent-Disposition: form-data; name="{nome}"'
            f'\r\n\r\n{valore}\r\n'.encode("utf-8"))
    for campo, nome_file, mime, dati_file in allegati:
        parti.append(
            (f'--{confine}\r\nContent-Disposition: form-data; name="{campo}"; '
             f'filename="{nome_file}"\r\nContent-Type: {mime}\r\n\r\n')
            .encode("utf-8"))
        parti.append(dati_file)
        parti.append(b"\r\n")
    parti.append(f"--{confine}--\r\n".encode("utf-8"))
    corpo = b"".join(parti)
    testa = {
        "Content-Type": f"multipart/form-data; boundary={confine}",
        "User-Agent": "Mozilla/5.0 (compatible; orchestra/0.1)",
    }
    testa.update(intestazioni)
    req = urllib.request.Request(url, data=corpo, headers=testa, method="POST")
    return _richiedi(req, provider)


def _risoluzione(valore: str, provider: str) -> str:
    """Il livello di risoluzione normalizzato, o "" se non c'e'.

    Chiedere un livello a un provider che non ce l'ha e' un errore esplicito e
    non un parametro buttato via: chi ha scritto `risoluzione="4K"` crede di
    ricevere un'immagine da stampa, e un 1K silenzioso e' peggio di un no.
    """
    r = str(valore or "").strip().upper().replace(" ", "")
    if r in ("", "AUTO"):
        return ""
    if r == "0.5K":
        r = "512"
    if r not in RISOLUZIONI:
        raise ImageGenError(
            f"risoluzione non riconosciuta: {valore!r}. I livelli sono "
            f"{', '.join(RISOLUZIONI)}: 512 e' il piu' piccolo, 4K il piu' "
            f"grande."
        )
    if provider == "openai":
        raise ImageGenError(
            "OpenAI non ha livelli di risoluzione: usa `dimensione` "
            "(1024x1024, 1536x1024, 1024x1536). `risoluzione` vale per "
            "Google e per OpenRouter."
        )
    if provider == "google" and r not in ("1K", "2K", "4K"):
        raise ImageGenError(
            f"Google accetta 1K, 2K o 4K, non {r}: il livello 512 e' solo di "
            f"OpenRouter."
        )
    return r


def _dimensione_openai(dimensione: str) -> str:
    """La dimensione solo se e' una che l'API accetta, altrimenti niente.

    Mandare un valore inventato fa rispondere 400 e il messaggio parla di
    parametri, non di dimensione: meglio omettere e lasciare il default.
    """
    d = (dimensione or "").strip().lower()
    if d in ("auto", "portrait", "landscape", "square"):
        return {"square": "1024x1024", "portrait": "1024x1536",
                "landscape": "1536x1024"}.get(d, "auto")
    if re.fullmatch(r"\d{2,5}x\d{2,5}", d):
        return d
    return ""


def _immagine_da_openai(dati: dict, modello: str) -> Immagine:
    """L'immagine in una risposta OpenAI: stessa forma per generare e
    modificare, quindi la lettura sta in un posto solo."""
    voci = dati.get("data") or []
    prima = voci[0] if voci and isinstance(voci[0], dict) else {}
    b64 = prima.get("b64_json") or ""
    if not b64:
        # I modelli GPT Image restituiscono sempre base64. Un `url` qui
        # significa un modello vecchio o un gateway diverso: si scarica, ma
        # solo se e' davvero un'immagine.
        url = prima.get("url") or ""
        if url:
            return _scarica(url, "openai", modello)
        raise ImageGenError(
            "OpenAI non ha restituito un'immagine. "
            f"Risposta: {json.dumps(dati)[:300]}"
        )
    try:
        grezzi = base64.b64decode(b64, validate=False)
    except (ValueError, TypeError) as e:
        raise ImageGenError(f"immagine base64 non decodificabile: {e}") from e
    return Immagine(grezzi, "image/png", Path(), "openai", modello)


def _genera_openai(prompt: str, modello: str, dimensione: str,
                   env: dict[str, str],
                   riferimenti: list[tuple[bytes, str]] | None = None,
                   maschera: tuple[bytes, str] | None = None) -> Immagine:
    if maschera and not riferimenti:
        raise ImageGenError(
            "una maschera da sola non basta: serve anche l'immagine da "
            "modificare (`riferimento`)."
        )
    token = chiave("openai", env)
    if not token:
        raise ImageGenError(
            "manca OPENAI_API_KEY. Mettila nel pannello Opzioni (chiavi), "
            "oppure genera in locale con la skill `invokeai`."
        )
    nome_modello = (modello or env.get("ORCHESTRA_IMAGE_MODEL", "")
                   or MODELLI["openai"])
    dim = _dimensione_openai(dimensione)
    if riferimenti:
        campi = {"model": nome_modello, "prompt": prompt}
        if dim:
            campi["size"] = dim
        # Con piu' immagini OpenAI vuole il campo ripetuto `image[]`: un
        # solo `image` con tre file resta una richiesta con un file solo.
        campo = "image[]" if len(riferimenti) > 1 else "image"
        allegati = []
        for indice, (dati_rif, mime_rif) in enumerate(riferimenti, start=1):
            estensione = _ESTENSIONI.get(mime_rif.lower(), "")
            if not estensione:
                raise ImageGenError(
                    f"formato non supportato per la modifica: {mime_rif}. "
                    f"Usa PNG, JPEG o WebP."
                )
            nome_rif = (f"riferimento.{estensione}" if len(riferimenti) == 1
                        else f"riferimento-{indice}.{estensione}")
            allegati.append((campo, nome_rif, mime_rif, dati_rif))
        if maschera:
            dati_mas, mime_mas = maschera
            if mime_mas.lower() != "image/png":
                raise ImageGenError(
                    f"la maschera deve essere un PNG con trasparenza, non "
                    f"{mime_mas}: la zona da ridisegnare e' quella trasparente."
                )
            if len(dati_mas) > 4 * 1024 * 1024:
                raise ImageGenError(
                    f"maschera troppo grande: {len(dati_mas) // (1024 * 1024)} "
                    f"MB, il limite e' 4 MB."
                )
            allegati.append(("mask", "maschera.png", mime_mas, dati_mas))
        dati = _post_multipart(
            ENDPOINT_EDITS, campi, allegati,
            {"Authorization": f"Bearer {token}"}, "openai")
    else:
        corpo: dict = {"model": nome_modello, "prompt": prompt}
        if dim:
            corpo["size"] = dim
        dati = _post_json(ENDPOINT["openai"], corpo,
                          {"Authorization": f"Bearer {token}"}, "openai")
    return _immagine_da_openai(dati, nome_modello)


def _parte_immagine(parti: list) -> tuple[bytes, str] | None:
    """La prima parte immagine di una risposta Gemini, o None.

    La chiave e' `inlineData` in JSON (camelCase) ma alcuni endpoint la
    scrivono `inline_data`: leggerle entrambe costa una riga e evita un
    "nessuna immagine" che sembra un modello rotto.
    """
    for parte in parti:
        if not isinstance(parte, dict):
            continue
        inline = parte.get("inlineData") or parte.get("inline_data")
        if not isinstance(inline, dict):
            continue
        dati = inline.get("data") or ""
        mime = (inline.get("mimeType") or inline.get("mime_type")
                or "image/png")
        if not dati:
            continue
        try:
            return base64.b64decode(dati, validate=False), str(mime)
        except (ValueError, TypeError):
            continue
    return None


def _genera_google(prompt: str, modello: str, dimensione: str,
                   env: dict[str, str],
                   riferimenti: list[tuple[bytes, str]] | None = None,
                   risoluzione: str = ""
                   ) -> Immagine:
    token = chiave("google", env)
    if not token:
        raise ImageGenError(
            "manca GEMINI_API_KEY. Mettila nel pannello Opzioni (chiavi), "
            "oppure genera in locale con la skill `invokeai`."
        )
    nome = modello or env.get("ORCHESTRA_IMAGE_MODEL", "") or MODELLI["google"]
    parti: list[dict] = [{"text": prompt}]
    for dati_rif, mime_rif in (riferimenti or []):
        if not _ESTENSIONI.get(mime_rif.lower(), ""):
            raise ImageGenError(
                f"formato non supportato per la modifica: {mime_rif}. "
                f"Usa PNG, JPEG o WebP."
            )
        parti.append({"inlineData": {
            "mimeType": mime_rif,
            "data": base64.b64encode(dati_rif).decode("ascii"),
        }})
    corpo: dict = {"contents": [{"parts": parti}]}
    # Le proporzioni, per i modelli che le accettano. Una dimensione in pixel
    # non si traduce: meglio non mandare niente che mandare un campo rifiutato.
    proporzioni = (dimensione or "").strip()
    image_config: dict = {}
    if re.fullmatch(r"\d{1,2}:\d{1,2}", proporzioni):
        image_config["aspectRatio"] = proporzioni
    if risoluzione:
        # `imageSize` e' il nome che Google da' al livello (1K/2K/4K): senza,
        # ogni modello resta alla sua misura predefinita, che per un poster
        # da stampa e' troppo poca.
        image_config["imageSize"] = risoluzione
    if image_config:
        corpo["generationConfig"] = {"imageConfig": image_config}
    intestazioni = {"x-goog-api-key": token}
    try:
        dati = _post_json(ENDPOINT["google"].format(modello=nome), corpo,
                          intestazioni, "google")
    except ImageGenError as e:
        # Solo il 404: la versione dell'API sbagliata non e' un prompt
        # rifiutato, e ritentare un 400 significherebbe pagare due volte
        # una richiesta che non puo' riuscire.
        if e.status != 404:
            raise
        dati = _post_json(ENDPOINT_GOOGLE_BETA.format(modello=nome), corpo,
                          intestazioni, "google")
    candidate = (dati.get("candidates") or [{}])[0] or {}
    contenuto = candidate.get("content") or {}
    parti = contenuto.get("parts") or []
    trovata = _parte_immagine(parti)
    if trovata is None:
        testo = " ".join(
            str(p.get("text") or "") for p in parti if isinstance(p, dict)
        ).strip()
        motivo = (candidate.get("finishReason") or "").strip()
        dettaglio = testo or motivo or json.dumps(dati)[:300]
        raise ImageGenError(
            "Google non ha restituito un'immagine. "
            f"Forse il modello ha rifiutato il prompt: {dettaglio}"
        )
    grezzi, mime = trovata
    estensione = _ESTENSIONI.get(mime.lower(), "png")
    # Il mime viene normalizzato con l'estensione scelta: se il provider dice
    # qualcosa che non conosciamo, il file e la data URL devono comunque
    # dichiarare lo stesso formato, o il browser non lo mostra.
    mime = {"png": "image/png", "jpg": "image/jpeg",
            "webp": "image/webp"}[estensione]
    return Immagine(grezzi, mime, Path(), "google", nome)


def _lista_riferimenti(riferimento) -> list[tuple[bytes, str]]:
    """I riferimenti in una lista, comunque arrivino.

    La prima forma era una sola immagine, `(byte, MIME)`, e resta valida:
    un elenco di quelle e' l'aggiunta. Il caso singolo si riconosce dal
    primo elemento, cosi' chi chiamava ieri non deve cambiare niente.
    """
    if not riferimento:
        return []
    if (isinstance(riferimento, tuple) and len(riferimento) == 2
            and isinstance(riferimento[0], (bytes, bytearray))):
        return [(bytes(riferimento[0]), str(riferimento[1]))]
    voci: list[tuple[bytes, str]] = []
    for voce in riferimento:
        if not voce:
            continue
        voci.append((bytes(voce[0]), str(voce[1])))
    return voci


def _riduci_riferimenti(riferimenti: list[tuple[bytes, str]]
                        ) -> list[tuple[bytes, str]]:
    """Riferimenti piu' leggeri, quando sono pesanti.

    Tre foto a piena risoluzione dentro una richiesta JSON sono base64 su
    base64: si pagano come token di ingresso e si rischia un 413, mentre il
    modello le riporta comunque a una misura di lavoro. Si accorcia il lato
    lungo e si ricodifica, tenendo il formato: un PNG resta PNG perche' puo'
    avere la trasparenza, e diventare JPEG la butterebbe via.
    """
    if not riferimenti:
        return riferimenti
    if sum(len(dati) for dati, _mime in riferimenti) <= LIMITE_BYTES_RIFERIMENTI:
        return riferimenti
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow e' fra le dipendenze
        return riferimenti
    ridotti: list[tuple[bytes, str]] = []
    for dati, mime in riferimenti:
        try:
            with Image.open(io.BytesIO(dati)) as im:
                im.load()
                if max(im.size) <= LATO_RIFERIMENTO:
                    ridotti.append((dati, mime))
                    continue
                im.thumbnail((LATO_RIFERIMENTO, LATO_RIFERIMENTO),
                             Image.LANCZOS)
                uscita = io.BytesIO()
                if mime.lower() in ("image/jpeg", "image/jpg"):
                    im.convert("RGB").save(uscita, "JPEG", quality=88,
                                           optimize=True)
                    ridotti.append((uscita.getvalue(), "image/jpeg"))
                else:
                    if im.mode not in ("RGB", "RGBA"):
                        im = im.convert("RGBA")
                    im.save(uscita, "PNG", optimize=True)
                    ridotti.append((uscita.getvalue(), "image/png"))
        except Exception:  # noqa: BLE001 - un file strano passa com'era
            ridotti.append((dati, mime))
    return ridotti


def _forma_openrouter(dimensione: str) -> dict:
    """La dimensione nel dialetto di OpenRouter.

    Solo `aspect_ratio`. I pixel espliciti (`size`) li accettano pochi
    modelli e gli altri rispondono 400: perfino `openai/gpt-image-2` sul
    catalogo non li dichiara. Il rapporto invece c'e' quasi sempre, e da una
    taglia in pixel si ricava riducendola (1024x1536 -> 2:3).
    """
    d = (dimensione or "").strip().lower()
    if not d or d == "auto":
        return {}
    rapporti = {"1024x1024": "1:1", "1536x1024": "3:2",
                "1024x1536": "2:3", "1792x1024": "16:9",
                "1024x1792": "9:16"}
    if d in rapporti:
        return {"aspect_ratio": rapporti[d]}
    if re.fullmatch(r"\d{1,2}:\d{1,2}", d):
        return {"aspect_ratio": d}
    pixel = re.fullmatch(r"(\d{2,5})x(\d{2,5})", d)
    if pixel:
        try:
            larghezza, altezza = int(pixel.group(1)), int(pixel.group(2))
        except ValueError:  # pragma: no cover - la regex lo esclude
            return {}
        if larghezza <= 0 or altezza <= 0:
            return {}
        divisore = math.gcd(larghezza, altezza)
        rapporto = f"{larghezza // divisore}:{altezza // divisore}"
        # I rapporti estremi (37:1 da 3700x100) non esistono nei cataloghi:
        # meglio lasciare che il provider scelga il suo default.
        a, _, b = rapporto.partition(":")
        if int(a) <= 21 and int(b) <= 21:
            return {"aspect_ratio": rapporto}
    return {}


def _genera_openrouter(prompt: str, modello: str, dimensione: str,
                       env: dict[str, str],
                       riferimenti: list[tuple[bytes, str]] | None = None,
                       risoluzione: str = ""
                       ) -> Immagine:
    token = chiave("openrouter", env)
    if not token:
        raise ImageGenError(
            "manca OPENROUTER_API_KEY. Mettila nel pannello Opzioni (chiavi). "
            "Attenzione: su OpenRouter nessun modello di immagini ha una "
            "variante gratuita, quindi la generazione usa il credito del "
            "conto."
        )
    nome = (modello or env.get("ORCHESTRA_IMAGE_MODEL", "")
            or MODELLI["openrouter"])
    corpo: dict = {"model": nome, "prompt": prompt, "n": 1}
    corpo.update(_forma_openrouter(dimensione))
    if risoluzione:
        # `resolution` e' il livello ("1K", "2K", "4K"): OpenRouter lo
        # traduce per il provider che serve la richiesta. Non tutti i modelli
        # del catalogo lo dichiarano, e chi non lo accetta rifiuta la
        # richiesta invece di ignorarla: il messaggio d'errore lo dira'.
        corpo["resolution"] = risoluzione
    if riferimenti:
        # `input_references` e' una lista anche quando l'immagine e' una
        # sola: l'ordine conta, perche' il prompt nomina "la prima" e "le
        # altre" e il modello non ha altri modi per sapere quale sia la
        # base da modificare e quale il logo da inserire.
        voci = []
        for dati_rif, mime_rif in riferimenti:
            if not _ESTENSIONI.get(mime_rif.lower(), ""):
                raise ImageGenError(
                    f"formato non supportato per la modifica: {mime_rif}. "
                    f"Usa PNG, JPEG o WebP."
                )
            voci.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_rif};base64,"
                                     + base64.b64encode(dati_rif).decode("ascii")},
            })
        corpo["input_references"] = voci
    intestazioni = {"Authorization": f"Bearer {token}"}
    # Le stesse intestazioni facoltative della chat: servono a OpenRouter per
    # attribuire il traffico, e senza non cambia niente nel risultato.
    intestazioni["HTTP-Referer"] = (
        env.get("OPENROUTER_HTTP_REFERER")
        or "https://github.com/advers1ty-it/orchestra")
    intestazioni["X-OpenRouter-Title"] = (
        env.get("OPENROUTER_APP_TITLE") or "Orchestra")
    dati = _post_json(ENDPOINT["openrouter"], corpo, intestazioni, "openrouter")
    voci = dati.get("data") or []
    prima = voci[0] if voci and isinstance(voci[0], dict) else {}
    b64 = prima.get("b64_json") or ""
    if not b64:
        raise ImageGenError(
            "OpenRouter non ha restituito un'immagine. "
            f"Risposta: {json.dumps(dati)[:300]}"
        )
    # `media_type` c'e' quasi sempre, ma la documentazione dice che puo'
    # mancare: in quel caso il default e' PNG. Un parametro dopo il `;`
    # (`image/png; charset=...`) non fa parte del formato.
    mime = str(prima.get("media_type") or "image/png").split(";")[0].strip()
    if mime.lower() == "image/svg+xml":
        # I modelli di vettorializzazione (Recraft) restituiscono SVG vero:
        # salvarlo come .png produrrebbe un file che nessun programma apre.
        # Il browser lo mostra in un'anteprima, quindi il giro funziona.
        estensione = "svg"
    else:
        estensione = _ESTENSIONI.get(mime.lower(), "")
        if not estensione:
            raise ImageGenError(
                f"OpenRouter ha restituito un formato non supportato: {mime}. "
                f"Riprova con un altro modello, o chiedi un PNG con "
                f"`output_format` quando il modello lo accetta."
            )
        mime = {"png": "image/png", "jpg": "image/jpeg",
                "webp": "image/webp"}[estensione]
    try:
        grezzi = base64.b64decode(b64, validate=False)
    except (ValueError, TypeError) as e:
        raise ImageGenError(f"immagine base64 non decodificabile: {e}") from e
    return Immagine(grezzi, mime, Path(), "openrouter", nome)


def _scarica(url: str, provider: str, modello: str) -> Immagine:
    """Scarica un'immagine da un URL restituito dal provider."""
    req = urllib.request.Request(url, headers={"User-Agent": "orchestra/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            grezzi = resp.read()
            mime = (resp.headers.get("Content-Type") or "image/png").split(";")[0]
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise ImageGenError(f"non riesco a scaricare l'immagine generata: {e}") from e
    if not grezzi:
        raise ImageGenError("il provider ha restituito un'immagine vuota.")
    return Immagine(grezzi, mime, Path(), provider, modello)


def _slug(prompt: str) -> str:
    """Un nome di file leggibile, ricavato dal prompt.

    Senza questo, la cartella diventa un elenco di timestamp e per ritrovare
    l'immagine giusta bisogna aprirle tutte.
    """
    basso = re.sub(r"[^a-z0-9]+", "-", prompt.lower().strip())
    basso = basso.strip("-")[:40].strip("-")
    return basso or "immagine"


def _nome_libero(cartella: Path, base: str, estensione: str) -> Path:
    """Un nome che non sovrascrive niente.

    Sovrascrivere l'immagine di ieri perche' il prompt somiglia e' il tipo di
    perdita che si nota una settimana dopo. Un suffisso -2 costa niente.
    """
    candidato = cartella / f"{base}.{estensione}"
    contatore = 2
    while candidato.exists():
        candidato = cartella / f"{base}-{contatore}.{estensione}"
        contatore += 1
    return candidato


def genera(prompt: str, *, provider: str = "", modello: str = "",
           dimensione: str = "", cartella: str | Path = "",
           nome_file: str = "", env: dict[str, str] | None = None,
           riferimento: tuple[bytes, str] | list[tuple[bytes, str]] | None = None,
           maschera: tuple[bytes, str] | None = None,
           risoluzione: str = "") -> Immagine:
    """Genera un'immagine e la salva nella cartella indicata.

    `cartella` e' la base (di solito la root del progetto). L'immagine finisce
    in `<cartella>/immagini/`, che e' il posto in cui l'utente la cerca.

    Con `riferimento` (byte, MIME, oppure un elenco di quelli) l'immagine
    viene modificata invece che creata da zero: il prompt descrive la
    modifica. Piu' riferimenti servono quando la scena va ricomposta e non
    solo ritoccata — il poster da tenere, il logo vero, la foto del prodotto
    vero — e l'ordine e' il modo in cui il prompt li nomina: il primo e' la
    base, gli altri sono riferimenti. I provider usano strade diverse (OpenAI
    un endpoint `/images/edits`, Google lo stesso generateContent con le
    immagini fra le parti, OpenRouter `input_references`), ma il risultato e'
    lo stesso: un file in `immagini/`.

    Con `risoluzione` si chiede un livello (1K, 2K, 4K) invece di una misura
    in pixel: e' l'unico modo per avere un 4K vero dai modelli Google, che
    altrimenti restano alla loro misura predefinita. OpenAI non ha livelli e
    lo dice; Google non accetta 512.

    Con `maschera` (PNG, byte) la modifica e' limitata alle zone trasparenti
    della maschera: e' l'inpainting vero, non un "prova a non toccare il
    resto". Solo OpenAI ha un parametro per questo: chiederlo a Google o
    OpenRouter e' un errore esplicito, non una richiesta che parte e torna
    diversa.
    """
    testo = (prompt or "").strip()
    if not testo:
        raise ImageGenError("serve un prompt: cosa deve mostrare l'immagine?")
    if len(testo) > MAX_PROMPT:
        raise ImageGenError(
            f"prompt troppo lungo ({len(testo)} caratteri): il massimo e' "
            f"{MAX_PROMPT}. Riducilo a cosa deve mostrare l'immagine."
        )
    env = env if env is not None else ambiente()
    riferimenti = _lista_riferimenti(riferimento)
    if len(riferimenti) > MAX_RIFERIMENTI:
        raise ImageGenError(
            f"{len(riferimenti)} immagini di riferimento: il massimo e' "
            f"{MAX_RIFERIMENTI}. I modelli ne accettano meno (Gemini 2.5 "
            f"Flash Image tre, Gemini 3.1 Flash Image quattordici): togli "
            f"quelle che il prompt non nomina."
        )
    riferimenti = _riduci_riferimenti(riferimenti)
    scelto = provider_disponibile(provider, env)
    if scelto not in MODELLI:
        configurati = [p for p in MODELLI if chiave(p, env)]
        if scelto:
            raise ImageGenError(
                f"provider immagini sconosciuto: {scelto!r}. Usa 'openai', "
                f"'google' o 'openrouter'."
            )
        raise ImageGenError(
            "nessuna chiave per generare immagini. Aggiungi OPENAI_API_KEY, "
            "GEMINI_API_KEY o OPENROUTER_API_KEY nel pannello Opzioni; in "
            "alternativa la skill `invokeai` genera in locale senza chiave."
            + (f" Trovate: {', '.join(configurati)}." if configurati else "")
        )
    # Un provider chiesto e senza chiave non vuol dire "nessuna chiave": qui
    # si dice quale manca e quale c'e'. Senza questa distinzione l'errore
    # faceva concludere al modello che immagini e chiavi fossero fuori uso,
    # e la risposta all'utente era "mancano le chiavi API" con OpenRouter
    # configurato e funzionante.
    if not chiave(scelto, env):
        variabili = " o ".join(CHIAVI.get(scelto, ()))
        altre = [p for p in MODELLI if chiave(p, env)]
        nota = ""
        if altre:
            disponibili = " o ".join(
                f"{CHIAVI.get(p, ('',))[0]} ({p})" for p in altre)
            nota = (f" Al momento c'e' {disponibili}: richiama il tool senza "
                    f"`provider` e uso quella.")
        raise ImageGenError(
            f"manca {variabili}, la chiave di {scelto}, che hai chiesto "
            f"esplicitamente. Mettila nel pannello Opzioni (chiavi), oppure "
            f"togli `provider` e lascia scegliere il provider configurato."
            + nota
        )
    if maschera and scelto != "openai":
        raise ImageGenError(
            "la maschera per l'inpainting la accetta solo OpenAI: Google e "
            "OpenRouter non hanno una modifica per regione. Usa "
            "provider=\"openai\" con OPENAI_API_KEY, oppure togli la "
            "maschera e descrivi la zona nel prompt. Per coprire qualcosa "
            "senza modello c'e' `image_edit`. Nessun credito e' stato "
            "speso."
        )
    risoluzione = _risoluzione(risoluzione, scelto)
    if scelto == "openai":
        img = _genera_openai(testo, modello.strip(), dimensione, env,
                             riferimenti, maschera)
    elif scelto == "openrouter":
        img = _genera_openrouter(testo, modello.strip(), dimensione, env,
                                 riferimenti, risoluzione)
    else:
        img = _genera_google(testo, modello.strip(), dimensione, env,
                             riferimenti, risoluzione)

    base = Path(cartella) if str(cartella or "").strip() else Path.cwd()
    destinazione = base / "immagini"
    try:
        destinazione.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ImageGenError(f"non riesco a creare {destinazione}: {e}") from e
    estensione = ("svg" if img.mime.lower() == "image/svg+xml"
                  else _ESTENSIONI.get(img.mime.lower(), "png"))
    nome = _slug(testo)
    if nome_file and nome_file.strip():
        nome = _slug(Path(nome_file.strip()).stem)
    img.percorso = _nome_libero(destinazione, nome, estensione)
    # Marcatura del contenuto sintetico (Reg. UE 2024/1689, art. 50(2)).
    # Il PNG la porta dentro il file; qualunque formato porta il sidecar,
    # che e' la parte leggibile senza decodificare i pixel.
    img.dati = marcatura.marca_png(
        img.dati, marcatura.testo(provider=img.provider, modello=img.modello))
    try:
        img.percorso.write_bytes(img.dati)
    except OSError as e:
        raise ImageGenError(f"non riesco a scrivere {img.percorso}: {e}") from e
    try:
        img.metadati = marcatura.scrivi_metadati(
            img.percorso, prompt=testo, provider=img.provider,
            modello=img.modello, mime=img.mime,
            nel_file=img.dati.startswith(b"\x89PNG"))
    except OSError:
        # Un metadato che non si scrive non deve buttare via l'immagine:
        # il tool lo dice nel risultato, e il file resta.
        img.metadati = None
    return img
