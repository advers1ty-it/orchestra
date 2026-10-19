"""Collegamento Nous Research via OAuth device-code.

Niente API key da incollare: Orchestra apre il browser, Nous da un codice
da confermare, e al termine Orchestra riceve il JWT che dà accesso all'inference
API. Il token (con refresh token) vive in `orchestra/nous_auth.json`, fuori
dal .env, e viene rinnovato automaticamente quando sta per scadere.

Un eventuale `NOUS_API_KEY` nell'ambiente ha comunque la precedenza: serve
per chi preferisce incollare un bearer token manualmente.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PORTAL_BASE_URL = "https://portal.nousresearch.com"
INFERENCE_DEFAULT = "https://inference-api.nousresearch.com/v1"
CLIENT_ID = "orchestra"
# Client in prestito finche' «orchestra» non e' registrato sul portale.
# E' un identificativo pubblico, non un segreto; la pagina di conferma
# citera' Hermes invece di Orchestra. Quando il nostro client viene
# abilitato, basta togliere questa riga e default torna «orchestra».
CLIENT_PRESTITO = "hermes-cli"
SCOPE = "inference:invoke"
SKEW_SECONDS = 120


def client_id_attivo(env: dict[str, str] | None = None) -> str:
    """Quale client_id presentare a Nous.

    Il portale accetta solo client registrati: finche' «orchestra» non
    lo e', chi distribuisce puo' impostare NOUS_CLIENT_ID senza toccare
    il codice. Il default resta, cosi' il giorno in cui viene abilitato
    funziona senza aggiornare niente.
    """
    env = env or {}
    return str(env.get("NOUS_CLIENT_ID") or os.environ.get("NOUS_CLIENT_ID")
               or CLIENT_PRESTITO).strip() or CLIENT_PRESTITO


def _errore_umano(status: int, payload: dict[str, Any], client_id: str) -> str:
    if isinstance(payload, dict) and payload.get("error") == "invalid_client":
        return (f"Nous non riconosce questa installazione (client '{client_id}' "
                "non registrato sul portale). Finche' il collegamento diretto "
                "non e' abilitato, usa un token manuale: Opzioni → Servizi → "
                "«Nous Research (token manuale)».")
    return f"Nous device-code fallito (HTTP {status}): {payload}"


def auth_file_path(env: dict[str, str] | None = None) -> Path:
    """Dove teniamo il collegamento a Nous.

    Nella cartella dati di Orchestra, come gli altri file di stato: un
    token di accesso non e' codice e non ha senso vivere nel repo, dove
    finirebbe in un commit o in una copia dell'albero. L'override resta,
    per chi deve puntare altrove.
    """
    env = env or {}
    for key in ("NOUS_AUTH_PATH", "ORCHESTRA_NOUS_AUTH_PATH"):
        val = env.get(key) or os.environ.get(key)
        if val:
            return Path(val)
    from .dati import percorso
    return Path(percorso("nous_auth.json"))


def load_auth(env: dict[str, str] | None = None) -> tuple[dict[str, Any] | None, Path]:
    p = auth_file_path(env)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, p
    if not isinstance(data, dict) or not data.get("access_token"):
        return None, p
    return data, p


def rimuovi_auth(env: dict[str, str] | None = None) -> bool:
    """Toglie il collegamento a Nous. Restituisce True se c'era qualcosa.

    E' la via per riconnettersi quando il token e' scaduto o revocato
    fuori da Orchestra: senza, il controllo del token in /auth/start
    rispondeva sempre "connected" e il flusso non si poteva mai ripetere.
    Non solleva mai: se il file non c'e' o non si puo' scrivere, e' False.
    """
    p = auth_file_path(env)
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    txt = value.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _expires_soon(auth: dict[str, Any], skew: int = SKEW_SECONDS) -> bool:
    dt = _parse_dt(auth.get("expires_at"))
    if dt is None:
        return True
    now = datetime.now(timezone.utc)
    return dt <= now + timedelta(seconds=skew)


def _refresh(auth: dict[str, Any], path: Path) -> dict[str, Any]:
    portal = str(auth.get("portal_base_url") or PORTAL_BASE_URL).rstrip("/")
    client_id = str(auth.get("client_id") or CLIENT_ID).strip()
    refresh_token = str(auth.get("refresh_token") or "").strip()
    if not refresh_token:
        return auth
    url = f"{portal}/api/oauth/token"
    body = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "client_id": client_id}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "x-nous-refresh-token": refresh_token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "Orchestra/0.2 (+nous-oauth)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise ValueError("refresh senza access_token")
    now = datetime.now(timezone.utc)
    auth["access_token"] = payload["access_token"]
    auth["refresh_token"] = payload.get("refresh_token") or refresh_token
    auth["token_type"] = payload.get("token_type") or auth.get("token_type") or "Bearer"
    auth["scope"] = payload.get("scope") or auth.get("scope")
    auth["obtained_at"] = now.isoformat()
    try:
        auth["expires_at"] = (
            now + timedelta(seconds=int(payload.get("expires_in", 3600)))
        ).isoformat()
    except (TypeError, ValueError):
        auth["expires_at"] = (now + timedelta(seconds=3600)).isoformat()
    if payload.get("inference_base_url"):
        auth["inference_base_url"] = payload["inference_base_url"]
    path.write_text(json.dumps(auth, indent=2, ensure_ascii=False), encoding="utf-8")
    return auth


def refresh_forzato(env: dict[str, str] | None = None) -> str | None:
    """Rinnova il token Nous adesso, senza guardare la scadenza.

    Serve a chi ha appena preso un 401: il token in memoria e' morto
    ma quello sul disco dice di essere ancora valido (orologi, skew,
    revoche). Non solleva mai: torna il token nuovo o None, e il
    chiamante decide (di solito: riprova una volta, poi errore vero).

    Con NOUS_API_KEY manuale non fa niente: quella chiave non si
    rinnova, se e' sbagliata e' sbagliata.
    """
    env = env or {}
    if str(env.get("NOUS_API_KEY") or os.environ.get("NOUS_API_KEY", "")).strip():
        return None
    auth, path = load_auth(env)
    if not auth or not str(auth.get("refresh_token") or "").strip():
        return None
    try:
        auth = _refresh(auth, path)
    except Exception:
        return None
    return str(auth.get("access_token") or "").strip() or None


def get_nous_credentials(env: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """Restituisce (token, base_url) oppure (None, None). Non solleva mai."""
    env = env or {}
    manual = str(
        env.get("NOUS_API_KEY") or os.environ.get("NOUS_API_KEY", "")
    ).strip()
    if manual:
        base = str(
            env.get("NOUS_INFERENCE_BASE_URL")
            or os.environ.get("NOUS_INFERENCE_BASE_URL")
            or env.get("ORCHESTRA_NOUS_URL")
            or os.environ.get("ORCHESTRA_NOUS_URL")
            or INFERENCE_DEFAULT
        ).strip().rstrip("/")
        return manual, base

    auth, path = load_auth(env)
    if not auth:
        return None, None
    if _expires_soon(auth):
        try:
            auth = _refresh(auth, path)
        except Exception:
            pass
    token = str(auth.get("access_token") or "").strip()
    if not token:
        return None, None
    base = str(
        env.get("NOUS_INFERENCE_BASE_URL")
        or os.environ.get("NOUS_INFERENCE_BASE_URL")
        or env.get("ORCHESTRA_NOUS_URL")
        or os.environ.get("ORCHESTRA_NOUS_URL")
        or auth.get("inference_base_url")
        or INFERENCE_DEFAULT
    ).strip().rstrip("/")
    return token, base


def _post_form(url: str, data: dict[str, str], timeout: float = 15) -> tuple[int, dict[str, Any]]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "Orchestra/0.2 (+nous-oauth)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        return e.code, payload if isinstance(payload, dict) else {}


def request_device_code(
    portal_url: str = PORTAL_BASE_URL,
    client_id: str | None = None,
    scope: str = SCOPE,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Chiede il device-code a Nous. Non apre il browser, non blocca."""
    if not client_id:
        client_id = client_id_attivo(env)
    portal = portal_url.rstrip("/")
    status, device = _post_form(
        f"{portal}/api/oauth/device/code",
        {"client_id": client_id, "scope": scope},
    )
    if status != 200 or not isinstance(device, dict):
        raise RuntimeError(_errore_umano(status, device, client_id))
    for field in ("device_code", "user_code", "verification_uri", "verification_uri_complete", "expires_in", "interval"):
        if field not in device:
            raise RuntimeError(f"Risposta Nous incompleta: manca {field}")
    # comodo per chi chiama: conserviamo il portal e il client qui dentro
    device = dict(device)
    device["_portal"] = portal
    device["_client_id"] = client_id
    return device


def complete_device_flow(device: dict[str, Any]) -> dict[str, Any]:
    """Fa polling finche' l'utente conferma, poi salva il token. Blocca."""
    portal = str(device.get("_portal") or PORTAL_BASE_URL).rstrip("/")
    client_id = str(device.get("_client_id") or CLIENT_ID)
    verification_url = str(device["verification_uri_complete"])
    # portal potrebbe differire da quello del device: qui usiamo quello di device
    device_code = str(device["device_code"])
    expires_in = int(device["expires_in"])
    interval = int(device["interval"])

    deadline = time.time() + max(1, expires_in)
    current_interval = max(1, min(interval, 1))
    while time.time() < deadline:
        time.sleep(current_interval)
        status, payload = _post_form(
            f"{portal}/api/oauth/token",
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
        )
        if status == 200 and isinstance(payload, dict) and payload.get("access_token"):
            now = datetime.now(timezone.utc)
            try:
                expires = int(payload.get("expires_in", 3600))
            except (TypeError, ValueError):
                expires = 3600
            auth = {
                "_schema": 1,
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token"),
                "token_type": payload.get("token_type") or "Bearer",
                "scope": payload.get("scope") or SCOPE,
                "client_id": client_id,
                "portal_base_url": portal,
                "inference_base_url": payload.get("inference_base_url") or INFERENCE_DEFAULT,
                "expires_at": (now + timedelta(seconds=expires)).isoformat(),
                "obtained_at": now.isoformat(),
            }
            path = auth_file_path()
            path.write_text(json.dumps(auth, indent=2, ensure_ascii=False), encoding="utf-8")
            return auth

        error_code = ""
        description = ""
        if isinstance(payload, dict):
            error_code = str(payload.get("error") or "")
            description = str(payload.get("error_description") or "")

        if error_code == "authorization_pending":
            continue
        if error_code == "slow_down":
            current_interval = min(current_interval + 1, 30)
            continue
        if status in (408, 429) or status >= 500:
            time.sleep(min(current_interval * 2, 60))
            continue
        if error_code in ("access_denied", "expired_token"):
            raise RuntimeError(
                f"Nous OAuth interrotto: {error_code}"
                + (f" — {description}" if description else "")
            )
        raise RuntimeError(
            f"Nous OAuth: HTTP {status} {error_code}"
            + (f" — {description}" if description else "")
        )

    raise RuntimeError(
        "Tempo scaduto per la conferma del codice Nous. "
        "Riprova: python -m orchestra.cli auth nous"
    )


def login(portal_url: str = PORTAL_BASE_URL, open_browser: bool = True,
          env: dict[str, str] | None = None) -> dict[str, Any]:
    """Avvia il flusso device-code Nous. Blocca finche' l'utente conferma o scade."""
    portal = portal_url.rstrip("/")
    device = request_device_code(portal_url=portal, env=env)

    verification_url = str(device["verification_uri_complete"])
    user_code = str(device["user_code"])

    print()
    print("Per collegare Nous Research:")
    print(f"  1. Apri: {verification_url}")
    print(f"  2. Se richiesto, inserisci il codice: {user_code}")
    if open_browser:
        try:
            opened = webbrowser.open(verification_url)
            if opened:
                print("     (browser aperto automaticamente)")
            else:
                print("     (apri il link a mano nel browser)")
        except Exception:
            print("     (apri il link a mano nel browser)")
    print()

    auth = complete_device_flow(device)
    print("Collegato a Nous Research.")
    return auth

def status(env: dict[str, str] | None = None) -> str:
    token, base = get_nous_credentials(env)
    if token:
        return f"connesso ({base})"
    return "non collegato: esegui `python -m orchestra.cli auth nous`"
