"""Tool scarica: portare un file dal web dentro il progetto.

Perché esiste
-------------
`web_leggi` legge una pagina e la restituisce come testo, ma un PDF, uno
zip o un'immagine non si possono salvare con quello. L'unica strada era
`curl` nella shell, che non passa né dalle guardie SSRF di `web_leggi` né
dal confine dei percorsi dei tool file: due controlli aggirati con un
comando, e il file poteva finire ovunque.

Qui il download usa le stesse guardie di `web_leggi` (`_rete_locale`,
`_RedirectPubblico`, `_peer_pubblico`, `TETTO_RISPOSTA_BYTE`) e scrive
solo con `_safe_path`: un host locale o un redirect verso la rete locale
non restituisce niente, un file oltre il tetto non viene scritto, e la
destinazione resta dentro la cartella di lavoro (o passa dal gate, se
fuori).

Cosa non è
----------
Non è un browser e non segue JavaScript: prende i byte che il server
manda. Non indovina il nome del file: la destinazione la decide chi
chiama, così non c'è un secondo modo di scegliere un percorso.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

from ..types import Tool
from ._guard import _root, _safe_path
from .web import (
    TETTO_RISPOSTA_BYTE,
    _RedirectPubblico,
    _peer_pubblico,
    _rete_locale,
)


def tool_scarica() -> Tool:
    """Scarica un file dal web e lo salva in un percorso del progetto."""

    def handler(url: str = "", path: str = "") -> str:
        u = (url or "").strip()
        if not u:
            return "Quale indirizzo? Serve un URL."
        if not (path or "").strip():
            return "Dove salvo? Serve un percorso dentro il progetto."

        p_url = urlparse(u)
        if p_url.scheme not in ("http", "https"):
            # Come `web_leggi`: un `file://` qui sarebbe un modo di
            # leggere il disco saltando read_file e il suo gate.
            return (f"Schema non ammesso: {p_url.scheme or '(nessuno)'}. "
                    f"Solo http e https.")
        host = p_url.hostname or ""
        if _rete_locale(host):
            return (
                f"Indirizzo di rete locale bloccato: {host}. `scarica` "
                f"prende solo file da siti pubblici: un servizio su "
                f"localhost o sulla rete di casa non e' un file da "
                f"scaricare. Se il file e' gia' nel progetto, usa "
                f"`read_file`."
            )

        # Il confine dei percorsi vale PRIMA della rete: se la
        # destinazione e' fuori dalla root, il gate deve poter dire di
        # no senza che sia gia' partita una richiesta.
        p = _safe_path(path, "scrivere")
        if p.exists() and p.is_dir():
            return f"È UNA DIRECTORY: {path} (scarica salva un file)"

        req = urllib.request.Request(u, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Orchestra/1.0)",
            "Accept": "*/*",
        })
        opener = urllib.request.build_opener(_RedirectPubblico)
        try:
            with opener.open(req, timeout=25) as resp:
                if not _peer_pubblico(resp):
                    return ("La connessione e' finita su un indirizzo di "
                            "rete locale: download bloccato (possibile "
                            "DNS rebinding).")
                finale = urljoin(u, resp.geturl())
                # Il redirect e' gia' stato validato da _RedirectPubblico,
                # ma il controllo sull'URL finale resta: un handler del
                # provider puo' cambiare l'host senza passare da li'.
                if _rete_locale(urlparse(finale).hostname or ""):
                    return (f"La pagina ha portato a un indirizzo di rete "
                            f"locale ({urlparse(finale).hostname}), "
                            f"download bloccato.")

                # Se il server dichiara una dimensione oltre il tetto,
                # non serve scaricare niente per scoprirlo.
                lunghezza = resp.headers.get("Content-Length")
                if lunghezza:
                    try:
                        annunciata = int(lunghezza)
                    except (TypeError, ValueError):
                        annunciata = 0
                    if annunciata > TETTO_RISPOSTA_BYTE:
                        return (
                            f"FILE TROPPO GRANDE: il server dichiara "
                            f"{annunciata} byte, il limite e' "
                            f"{TETTO_RISPOSTA_BYTE}. Nessun file scritto."
                        )

                # Un byte in piu' del tetto: basta a distinguere un file
                # che ci sta da uno che va tagliato. Il tetto e' lo
                # stesso di web_leggi, non un numero nuovo da tenere
                # allineato a mano.
                #
                # Si legge a blocchi, non con una `read` sola: `read(n)`
                # promette "fino a n byte", e una lettura corta su una
                # connessione lenta produrrebbe un file troncato che
                # sembra completo. Il ciclo si ferma a EOF o al tetto+1.
                pezzi = bytearray()
                while len(pezzi) <= TETTO_RISPOSTA_BYTE:
                    quanti = min(64 * 1024,
                                 TETTO_RISPOSTA_BYTE + 1 - len(pezzi))
                    pezzo = resp.read(quanti)
                    if not pezzo:
                        break
                    pezzi.extend(pezzo)
                dati = bytes(pezzi)
                tipo = (resp.headers.get("Content-Type")
                        or "application/octet-stream").split(";", 1)[0].strip()
        except urllib.error.HTTPError as e:
            return f"Download fallito: {e.code} {e.reason}. URL: {u}"
        except Exception as e:  # noqa: BLE001 - la rete non deve uccidere il turno
            return f"Non riesco a scaricare {u}: {type(e).__name__}: {e}"

        if len(dati) > TETTO_RISPOSTA_BYTE:
            return (
                f"FILE TROPPO GRANDE: oltre {TETTO_RISPOSTA_BYTE} byte. "
                f"Nessun file scritto. Se il file e' piu' piccolo, il "
                f"server ha mandato piu' byte del dichiarato o un "
                f"contenuto compresso: `scarica` non lo decompone."
            )

        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        # Checkpoint prima della scrittura, come write_file: se il file
        # esisteva, la versione vecchia e' l'unica copia da cui tornare.
        try:
            from ..checkpoint import registra

            registra(p, _root(), "scaricamento")
        except Exception:  # noqa: BLE001
            pass
        from ..scrittura import scrivi_bytes

        try:
            scrivi_bytes(p, dati)
        except OSError as e:
            return f"SCRITTURA FALLITA: {path}: {e} (il file non e' stato toccato)"
        verb = "aggiornato" if existed else "creato"
        return f"File scaricato ({verb}): {path} ({len(dati)} byte, {tipo})"

    return Tool(
        name="scarica",
        description=(
            "Downloads a file (any content type) from an http/https URL "
            "and saves it inside the project. It uses the same SSRF checks "
            "and byte limit as web_leggi (public hosts only, redirects and "
            "peer checked, max 1,200,000 bytes) and the same path boundary "
            "as write_file. Use it instead of curl in the shell. The "
            "destination is overwritten if it exists, with a checkpoint."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "http or https address to download.",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Destination file path relative to the project root, "
                        "or ABSOLUTE: a path outside the root asks the user "
                        "for permission. Overwritten if it exists."
                    ),
                },
            },
            "required": ["url", "path"],
        },
        handler=handler,
    )
