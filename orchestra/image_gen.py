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
import json
import math
import os
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

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


def _post_multipart(url: str, campi: dict, nome_file: str, mime: str,
                    dati_file: bytes, intestazioni: dict,
                    provider: str) -> dict:
    """Una richiesta multipart/form-data, senza dipendenze.

    OpenAI vuole il file come parte `image`, non come base64 nel JSON. Il
    confine lo genera `uuid`: deve essere unico, o un pezzo di file che
    contiene la stessa stringa spezza la richiesta.
    """
    confine = "----orchestra" + uuid.uuid4().hex
    parti: list[bytes] = []
    for nome, valore in campi.items():
        parti.append(
            f'--{confine}\r\nContent-Disposition: form-data; name="{nome}"'
            f'\r\n\r\n{valore}\r\n'.encode("utf-8"))
    parti.append(
        (f'--{confine}\r\nContent-Disposition: form-data; name="image"; '
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
                   riferimento: tuple[bytes, str] | None = None) -> Immagine:
    token = chiave("openai", env)
    if not token:
        raise ImageGenError(
            "manca OPENAI_API_KEY. Mettila nel pannello Opzioni (chiavi), "
            "oppure genera in locale con la skill `invokeai`."
        )
    nome_modello = (modello or env.get("ORCHESTRA_IMAGE_MODEL", "")
                   or MODELLI["openai"])
    dim = _dimensione_openai(dimensione)
    if riferimento:
        dati_rif, mime_rif = riferimento
        estensione = _ESTENSIONI.get(mime_rif.lower(), "")
        if not estensione:
            raise ImageGenError(
                f"formato non supportato per la modifica: {mime_rif}. "
                f"Usa PNG, JPEG o WebP."
            )
        campi = {"model": nome_modello, "prompt": prompt}
        if dim:
            campi["size"] = dim
        dati = _post_multipart(
            ENDPOINT_EDITS, campi, f"riferimento.{estensione}",
            mime_rif, dati_rif, {"Authorization": f"Bearer {token}"},
            "openai")
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
                   riferimento: tuple[bytes, str] | None = None) -> Immagine:
    token = chiave("google", env)
    if not token:
        raise ImageGenError(
            "manca GEMINI_API_KEY. Mettila nel pannello Opzioni (chiavi), "
            "oppure genera in locale con la skill `invokeai`."
        )
    nome = modello or env.get("ORCHESTRA_IMAGE_MODEL", "") or MODELLI["google"]
    parti: list[dict] = [{"text": prompt}]
    if riferimento:
        dati_rif, mime_rif = riferimento
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
    if re.fullmatch(r"\d{1,2}:\d{1,2}", proporzioni):
        corpo["generationConfig"] = {"imageConfig": {"aspectRatio": proporzioni}}
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
                       riferimento: tuple[bytes, str] | None = None) -> Immagine:
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
    if riferimento:
        dati_rif, mime_rif = riferimento
        if not _ESTENSIONI.get(mime_rif.lower(), ""):
            raise ImageGenError(
                f"formato non supportato per la modifica: {mime_rif}. "
                f"Usa PNG, JPEG o WebP."
            )
        corpo["input_references"] = [{
            "type": "image_url",
            "image_url": {"url": f"data:{mime_rif};base64,"
                                 + base64.b64encode(dati_rif).decode("ascii")},
        }]
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
           riferimento: tuple[bytes, str] | None = None) -> Immagine:
    """Genera un'immagine e la salva nella cartella indicata.

    `cartella` e' la base (di solito la root del progetto). L'immagine finisce
    in `<cartella>/immagini/`, che e' il posto in cui l'utente la cerca.

    Con `riferimento` (byte, MIME) l'immagine viene modificata invece che
    creata da zero: il prompt descrive la modifica. I provider usano strade
    diverse (OpenAI un endpoint `/images/edits`, Google lo stesso
    generateContent con l'immagine fra le parti), ma il risultato e' lo
    stesso: un file in `immagini/`.
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
    if scelto == "openai":
        img = _genera_openai(testo, modello.strip(), dimensione, env,
                             riferimento)
    elif scelto == "openrouter":
        img = _genera_openrouter(testo, modello.strip(), dimensione, env,
                                 riferimento)
    else:
        img = _genera_google(testo, modello.strip(), dimensione, env,
                             riferimento)

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
    try:
        img.percorso.write_bytes(img.dati)
    except OSError as e:
        raise ImageGenError(f"non riesco a scrivere {img.percorso}: {e}") from e
    return img
