"""La salute dell'installazione: chiavi, autenticazione Nous, dipendenze,
diagnostica, profili dei tool.

I gestori sono metodi della classe `RotteSistema`, che `Rotte` compone
insieme alle altre. Le rotte si dichiarano con `@rotta` accanto al codice
che le serve; la tabella e il dispatch stanno in `rotte.py` e in
`webapp.Handler._instrada`.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import threading
from typing import Any

from .percorsi import ENV_PATH
from .providers import load_env
from .rotte import rotta
# /api/chiavi mostra anche il budget configurato, perche' e' la pagina in
# cui si decide quanto spendere: l'helper sta con la rotta del budget.
from .rotte_chat import _budget_per_pannello


# Le rotte: percorso e metodo nel decoratore, il corpo
# sotto. Il commento sopra ogni gestore dice perche' esiste.
class RotteSistema:
    @rotta("GET", "/api/dipendenze/stato")
    def _r_get_dipendenze_stato(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        import importlib.util, importlib.metadata, shutil, os as _os, sys as _sys
        deps = []
        # ddgs (ricerca web) — find_spec non importa il modulo (niente cache)
        if importlib.util.find_spec("ddgs") is not None:
            try:
                ver = importlib.metadata.version("ddgs")
            except Exception:
                ver = "?"
            deps.append({"nome": "ddgs", "stato": "ok",
                         "versione": ver, "via": "pip"})
        else:
            deps.append({"nome": "ddgs", "stato": "da installare", "via": "pip"})
        # faster-whisper (STT server)
        if importlib.util.find_spec("faster_whisper") is not None:
            try:
                ver = importlib.metadata.version("faster-whisper")
            except Exception:
                ver = "?"
            deps.append({"nome": "faster-whisper", "stato": "ok",
                         "versione": ver, "via": "pip"})
        else:
            deps.append({"nome": "faster-whisper", "stato": "da installare", "via": "pip"})
        cf = shutil.which("cloudflared")
        if not cf:
            for cand in (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
                         r"C:\Program Files\cloudflared\cloudflared.exe"):
                if _os.path.exists(cand):
                    cf = cand
                    break
        if cf:
            deps.append({"nome": "cloudflared", "stato": "ok",
                         "versione": "installato", "via": "winget",
                         "path": cf})
        else:
            deps.append({"nome": "cloudflared", "stato": "da installare", "via": "winget"})
        self._json({"python": _sys.version.split()[0], "deps": deps})
        return

    @rotta("GET", "/api/tools/profile")
    def _r_get_tools_profile(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        from .tools import _PROFILI
        prof = getattr(self.app.session.agent.config, "tool_profile", None)
        reg = self.app.session.agent.registry
        self._json({
            "profile": (prof or "none"),
            "valid": sorted(_PROFILI.keys()) + ["auto", "none"],
            "active": [t.name for t in reg.active],
            "total": len(reg.all_names()),
        })

    @rotta("GET", "/api/nous/auth/disconnect")
    def _r_get_nous_auth_disconnect(self, path: str, body: dict[str, Any],
                                    s: Any) -> None:
        # Scollega: dimentica il token device-flow. La chiave manuale
        # in .env non si tocca (e' configurazione, non collegamento).
        from . import nous_auth
        try:
            tolto = nous_auth.rimuovi_auth(self.app.env)
        except Exception:
            tolto = False
        self.app._nous_flow = None
        self._json({"ok": True, "disconnected": bool(tolto)})
        return

    @rotta("GET", "/api/nous/auth/status")
    def _r_get_nous_auth_status(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from . import nous_auth
        token, base = nous_auth.get_nous_credentials(self.app.env)
        if token:
            self.app._nous_flow = None
            # se l'app era ferma per mancanza chiave, la connessione
            # a Nous la sblocca: si passa al provider nous e si crea
            # la sessione qui (stesso percorso di create() in caso ok).
            if not (self.app.ready and self.app.session is not None):
                self.app.env["ORCHESTRA_PROVIDER"] = "nous"
                try:
                    from . import keys as keys_mod
                    keys_mod.scrivi(ENV_PATH, "ORCHESTRA_PROVIDER", "nous")
                except Exception:
                    pass
                try:
                    self.app.session = self.app._make_session(
                        "nous", self.app.env.get("ORCHESTRA_MODEL", ""))
                    self.app.ready = self.app.session is not None
                    if self.app.ready:
                        self.app._collega_recupero_tool()
                        self.app._collega_delega()
                        self.app._ripara_modello_iniziale()
                        try:
                            self.app.allinea_finestra()
                        except Exception:
                            pass
                        self.app.error = ""
                except Exception as e:
                    self.app.ready = False
                    self.app.error = str(e)
            self._json({"connected": True, "base": base})
            return
        flow = getattr(self.app, "_nous_flow", None)
        if not flow:
            self._json({"connected": False, "flow": None})
            return
        dev = flow.get("device") or {}
        self._json({
            "connected": False,
            "verification_url": dev.get("verification_uri_complete"),
            "user_code": dev.get("user_code"),
            "error": flow.get("error"),
            "done": bool(flow.get("done", False)),
        })
        return

    @rotta("GET", "/api/chiavi")
    def _r_get_chiavi(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        # Solo stato, mai valori. La chiave non esce mai da qui:
        # questa risposta finisce nella cronologia del browser e
        # in qualunque log in mezzo.
        from . import keys as keys_mod
        from .providers import NO_KEY_PROVIDERS
        cat_ = self.app.catalog
        # Nous non ha una chiave da scrivere: si collega via Orchestra.
        # Senza questa riga il badge dice "nessuna chiave" anche quando
        # si e' collegati — e chi legge cerca una chiave che non esiste.
        servizi_gratis = []
        for _sg in keys_mod.FREE_SERVICES:
            if _sg.get("id") == "nous":
                try:
                    from . import nous_auth as _na
                    _tok, _base = _na.get_nous_credentials(self.app.env)
                except Exception:
                    _tok = None
                _sg = dict(_sg)
                _sg["connesso"] = bool(_tok)
            servizi_gratis.append(_sg)
        # Niente motori locali qui: sono una richiesta di rete a
        # localhost che puo' costare un timeout, e le chiavi non
        # devono aspettarle. Vengono in /api/locali, che il browser
        # chiede per conto suo.
        self._json({
            "chiavi": keys_mod.stato(ENV_PATH, self.app.env),
            "servizi_gratis": servizi_gratis,
            "nota_gratis": keys_mod.NOTA_FREE,
            "catalogo": {
                "modelli": len(cat_.models) if cat_ is not None else 0,
                "gratuiti": len(cat_.free()) if cat_ is not None else 0,
            },
            "motori": sorted(NO_KEY_PROVIDERS),
            "provider": self.app.env.get("ORCHESTRA_PROVIDER", ""),
            "model": self.app.env.get("ORCHESTRA_MODEL", ""),
            "reasoning": self.app.env.get("ORCHESTRA_REASONING", ""),
            "tool_profile": (getattr(self.app.session.agent.config,
                                "tool_profile", None)
                       if self.app.session is not None else None),
            "budget": _budget_per_pannello(self.app.env),
            # Il progetto attivo. Va nello stato e non solo in un
            # endpoint dedicato: la UI deve poterlo mostrare senza
            # fare una richiesta in piu' a ogni aggiornamento, e il
            # modello deve sapere in che progetto e'.
            "progetto": (getattr(self.app.session, "progetto", "")
                         if self.app.session is not None else ""),
            "max_iterations": (self.app.session.agent.config.max_iterations
                               if self.app.session is not None else 12),
            # Tetto di orologio del turno, in secondi: e' lo stesso numero
            # che ferma il loop. Il pannello lo mostra in minuti, perche'
            # "15" si legge e "900" si calcola. Zero = nessun limite.
            "max_secondi_turno": (float(getattr(
                self.app.session.agent.config, "max_secondi_turno", 0) or 0)
                if self.app.session is not None else 0.0),
            "context_limit": (self.app.session.agent.config.context_limit
                              if self.app.session is not None else 120000),
            })

    @rotta("POST", "/api/dipendenze/stato")
    def _r_post_dipendenze_stato(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        import importlib.util, importlib.metadata, shutil, os as _os, sys as _sys
        deps = []
        # ddgs (ricerca web)
        if importlib.util.find_spec("ddgs") is not None:
            try:
                ver = importlib.metadata.version("ddgs")
            except Exception:
                ver = "?"
            deps.append({"nome": "ddgs", "stato": "ok",
                         "versione": ver, "via": "pip"})
        else:
            deps.append({"nome": "ddgs", "stato": "da installare", "via": "pip"})
        # faster-whisper (STT server)
        if importlib.util.find_spec("faster_whisper") is not None:
            try:
                ver = importlib.metadata.version("faster-whisper")
            except Exception:
                ver = "?"
            deps.append({"nome": "faster-whisper", "stato": "ok",
                         "versione": ver, "via": "pip"})
        else:
            deps.append({"nome": "faster-whisper", "stato": "da installare", "via": "pip"})
        # cloudflared (tunnel)
        cf = shutil.which("cloudflared")
        if not cf:
            for cand in (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
                         r"C:\Program Files\cloudflared\cloudflared.exe"):
                if _os.path.exists(cand):
                    cf = cand
                    break
        if cf:
            deps.append({"nome": "cloudflared", "stato": "ok",
                         "versione": "installato", "via": "winget",
                         "path": cf})
        else:
            deps.append({"nome": "cloudflared", "stato": "da installare", "via": "winget"})
        self._json({"python": _sys.version.split()[0], "deps": deps})
        return

    @rotta("POST", "/api/dipendenze/installa")
    def _r_post_dipendenze_installa(self, path: str, body: dict[str, Any],
                                    s: Any) -> None:
        import sys as _sys, subprocess
        nome = (body.get("nome") if isinstance(body, dict) else None) or ""
        nome = nome.strip().lower()
        # cloudflared via winget
        if nome == "cloudflared":
            try:
                r = subprocess.run(
                    ["winget", "install", "--id", "Cloudflare.cloudflared", "-e",
                     "--silent", "--accept-package-agreements",
                     "--accept-source-agreements"],
                    text=True, capture_output=True, timeout=300)
                self._json({
                    "ok": r.returncode == 0,
                    "returncode": r.returncode,
                    "output": ((r.stdout or "") + (r.stderr or ""))[-1800:],
                })
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return
        # pip packages
        pkg = None
        if nome in ("ddgs",):
            pkg = "ddgs"
        elif nome in ("faster-whisper", "faster_whisper", "whisper"):
            pkg = "faster-whisper"
        if pkg:
            try:
                r = subprocess.run(
                    [_sys.executable, "-m", "pip", "install", pkg],
                    text=True, capture_output=True, timeout=300)
                self._json({
                    "ok": r.returncode == 0,
                    "returncode": r.returncode,
                    "output": ((r.stdout or "") + (r.stderr or ""))[-1800:],
                })
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return
        self._json({"error": "dipendenza sconosciuta: " + nome}, 400)
        return

    @rotta("POST", "/api/diagnosi/stato")
    def _r_post_diagnosi_stato(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        self._json({
            "comandi": [
                {"id": "doctor", "desc": "Verifica config e connessione"},
                {"id": "model-list", "desc": "Lista modelli supportati"},
                {"id": "bench-show", "desc": "Mostra task del benchmark"},
                {"id": "dipendenze", "desc": "Stato dipendenze opzionali"},
            ]
        })
        return

    @rotta("POST", "/api/diagnosi/run")
    def _r_post_diagnosi_run(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        cmd_id = (body.get("comando") if isinstance(body, dict) else None) or ""
        import sys as _sys, subprocess
        from pathlib import Path as _P
        root = _P(__file__).resolve().parents[1]
        if cmd_id == "doctor":
            args = [_sys.executable, "-m", "orchestra.cli", "doctor"]
        elif cmd_id == "model-list":
            args = [_sys.executable, "-m", "orchestra.cli", "model", "--list"]
        elif cmd_id == "bench-show":
            args = [_sys.executable, "-m", "orchestra.cli", "bench", "--show"]
        elif cmd_id == "dipendenze":
            # riuso lo stato deps esistente
            cur = root / "requirements.txt"
            self._json({"comando": cmd_id, "output": str(cur), "ok": cur.exists()})
            return
        else:
            self._json({"error": "comando non consentito"}, 400)
            return
        try:
            r = subprocess.run(args, cwd=str(root), text=True,
                              capture_output=True, timeout=150)
            out = (str(r.stdout or "") + chr(10) + str(r.stderr or "")).strip()[-4000:]
            self._json({"ok": r.returncode == 0,
                        "returncode": r.returncode, "output": out})
            return
        except subprocess.TimeoutExpired:
            self._json({"error": "timeout 150s"}, 504)
            return
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return

    @rotta("POST", "/api/tools/profile")
    def _r_post_tools_profile(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        from .tools import applica_profilo, profilo_per_testo, _PROFILI
        cfg = self.app.session.agent.config
        val = (body.get("profile") if isinstance(body, dict) else None)
        val = (val or "").strip() if isinstance(val, str) else ""
        if val in ("", "none"):
            # "nessun profilo" NON vuol dire "tutti i tool": vuol dire
            # che il registro resta com'e'. Il profilo e' lo stato di
            # un insieme di tool, e "nessuno" non e' un insieme.
            cfg.tool_profile = None
        elif val == "auto":
            cfg.tool_profile = "auto"
            # L'auto si specializza al primo turno con il testo
            # dell'utente: `profilo_per_testo` sceglie in base a
            # quello che sta per succedere.
        else:
            if val not in _PROFILI:
                self._json({"error": f"profilo sconosciuto: {val}. " +
                                     f"Validi: {', '.join(sorted(_PROFILI))}"}, 400)
                return
            cfg.tool_profile = val
            applica_profilo(self.app.session.agent.registry, val)
        self._json({
            "ok": True,
            "profile": cfg.tool_profile or "none",
            "active": [t.name for t in
                       self.app.session.agent.registry.active],
        })
        return

    @rotta("POST", "/api/nous/auth/start")
    def _r_post_nous_auth_start(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from . import nous_auth
        # force=True richiede una riconnessione voluta: senza, chi e'
        # gia' collegato non puo' piu' rifare il flusso, perche' il primo
        # controllo del token risponde "connected" e il bottone
        # "Ricollega" non farebbe mai nulla. Scaduto o revocato il token,
        # force e' l'unico modo per ripartire senza toccare i file.
        forza = str(body.get("force") or "").lower() in ("1", "true", "yes", "si")
        token, base = nous_auth.get_nous_credentials(self.app.env)
        if token and not forza:
            self._json({"ok": True, "connected": True, "base": base})
            return
        if forza and token:
            try:
                nous_auth.rimuovi_auth(self.app.env)
            except Exception:
                pass
        flow = getattr(self.app, "_nous_flow", None)
        if flow and not flow.get("done") and not flow.get("error"):
            dev = flow["device"]
            self._json({"ok": True, "connected": False,
                       "verification_url": dev["verification_uri_complete"],
                       "user_code": dev["user_code"]})
            return
        try:
            dev = nous_auth.request_device_code(env=self.app.env)
        except Exception as ex:
            self._json({"error": str(ex)}, 502)
            return
        flow = {"device": dev, "done": False, "error": None, "auth": None}
        self.app._nous_flow = flow
        def _run():
            try:
                flow["auth"] = nous_auth.complete_device_flow(dev)
                flow["done"] = True
            except Exception as ex:
                flow["error"] = str(ex)
                flow["done"] = True
        threading.Thread(target=_run, daemon=True).start()
        self._json({"ok": True, "connected": False,
                   "verification_url": dev["verification_uri_complete"],
                   "user_code": dev["user_code"]})
        return

    @rotta("POST", "/api/chiavi")
    def _r_post_chiavi(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        # Scrive una chiave. Whitelist obbligatoria: senza, un POST
        # scriverebbe qualsiasi riga nel .env e avremmo dato una
        # scrittura arbitraria su disco a chiunque raggiunga la porta.
        from . import keys as keys_mod
        k = (body.get("chiave") or "").strip()
        v = body.get("valore")
        v = "" if v is None else str(v)
        if not k:
            self._json({"error": "indica quale chiave"}, 400)
            return
        ok, msg = keys_mod.scrivi(ENV_PATH, k, v)
        if not ok:
            self._json({"error": msg}, 400)
            return
        # ricarichiamo l'ambiente: senza, la chiave appena salvata
        # non verrebbe usata fino al prossimo avvio, e l'utente
        # proverebbe a chiamare e riceverebbe 401
        self.app.env.clear()
        self.app.env.update(load_env(ENV_PATH))
        self.app.env.setdefault("ORCHESTRA_PROVIDER", "openrouter")
        # la risposta porta solo lo stato, mai il valore
        # se la sessione mancava e abbiamo ora la chiave per il
        # provider attivo, si riprova ad avviarla: niente riavvio
        # server necessario, e l'utente vede la chat diventare viva.
        if not self.app.ready:
            prov = self.app.env.get("ORCHESTRA_PROVIDER", "openrouter")
            from .providers import KNOWN_PROVIDERS
            _, kenv, _ = KNOWN_PROVIDERS.get(prov, ("", "", ""))
            if not kenv or (kenv == k and v) or self.app.env.get(kenv):
                try:
                    self.app.session = self.app._make_session(
                        prov, self.app.env.get("ORCHESTRA_MODEL", ""))
                    self.app.ready = self.app.session is not None
                    if self.app.ready:
                        self.app._collega_recupero_tool()
                        self.app._collega_delega()
                        self.app._ripara_modello_iniziale()
                        try:
                            self.app.allinea_finestra()
                        except Exception:
                            pass
                        self.app.error = ""
                except Exception as e:
                    self.app.ready = False
                    self.app.error = str(e)
        self._json({"ok": True, "messaggio": msg,
                                "chiavi": keys_mod.stato(ENV_PATH, self.app.env),
                                "ready": self.app.ready})
