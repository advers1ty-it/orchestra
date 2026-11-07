"""Il catalogo e le misure: elenco modelli, punteggi, benchmark, prova
manuale, council, prior, routing.

I gestori sono metodi della classe `RotteModelli`, che `Rotte` compone
insieme alle altre. Le rotte si dichiarano con `@rotta` accanto al codice
che le serve; la tabella e il dispatch stanno in `rotte.py` e in
`webapp.Handler._instrada`.
"""

from __future__ import annotations

import time
import urllib.parse
from typing import Any

from .rotte import rotta


# Le rotte: percorso e metodo nel decoratore, il corpo
# sotto. Il commento sopra ogni gestore dice perche' esiste.
class RotteModelli:
    @rotta("GET", "/api/routing")
    def _r_get_routing(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        # Stato dell'instradamento automatico (il POST sta in do_POST).
        if self.app.session is None:
            self._json({"error": "nessuna sessione"}, 409)
            return
        self._json({"routing": bool(
            getattr(self.app.session, "_routing_attivo", False))})

    @rotta("GET", "/api/models")
    def _r_get_models(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        self._models()

    @rotta("GET", "/api/bench/status")
    def _r_get_bench_status(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        self._json({
            "running": self.app._bench["running"],
            # il log si puo' troncare: e' roba da leggere. I
            # numeri no: sono il conto, e troncarli trasforma
            # "sta lavorando" in "fermo" senza che nulla sia
            # fermo.
            "log": self.app._bench["log"][-60:],
            "finiti": self.app._bench.get("finiti", 0),
            "modelli_visti": self.app._bench.get("modelli", []),
            "result": self.app._bench["result"],
            "models": self.app._bench.get("models", []),
                            # secondi dall'ultimo passo, non dall'avvio: e' quello
                            # che distingue "sta lavorando" da "e' bloccato". Un
                            # benchmark lento e uno fermo hanno la stessa identica
                            # UI per sempre, e uno dei due ti fa aspettare inutilmente.
                            "fermo_da": round(time.monotonic()
                                              - self.app._bench.get("last_progress", 0.0)),
        })

    @rotta("GET", "/api/council/status")
    def _r_get_council_status(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        self._json(self.app.council_status())

    @rotta("GET", "/api/council/roster")
    def _r_get_council_roster(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        self._json({"seats": self.app.council_roster()})

    @rotta("GET", "/api/council/pdf")
    def _r_get_council_pdf(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        self._council_pdf()

    @rotta("GET", "/api/prior")
    def _r_get_prior(self, path: str, body: dict[str, Any],
                     s: Any) -> None:
            # Copertura del prior esterno. Non e' il benchmark: e' un
            # parere. Darlo per primo evita di fidarsi di numeri che
            # descrivono un'altra harness.
            try:
                from . import prior as prior_mod
                priors, msg = prior_mod.scarica(catalogo=self.app.catalog.models)
                self._json({"messaggio": msg,
                            "copertura": prior_mod.copertura(priors, self.app.catalog.models)})
            except Exception as e:  # noqa: BLE001
                self._json({"messaggio": f"prior non disponibile: {e}", "copertura": {}})

    @rotta("GET", "/api/modelli")
    def _r_get_modelli(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        # I modelli di un provider SPECIFICO, non di quello attivo.
        # Serve per la select del pannello Opzioni: scegliendo
        # "Groq" nel menu, la lista deve cambiare subito, non
        # continuare a mostrare i modelli di OpenRouter.
        q = ""
        if "provider=" in self.path:
            q = urllib.parse.unquote_plus(
                self.path.split("provider=", 1)[1].split("&")[0]).strip()
        if not q:
            q = self.app.env.get("ORCHESTRA_PROVIDER", "openrouter")
        from .providers import KNOWN_PROVIDERS
        if q not in KNOWN_PROVIDERS:
            self._json({"error": f"provider sconosciuto: {q}"}, 400)
            return
        # catalogo in memoria per provider: cambiarne uno non deve
        # far riscaricare gli altri a ogni passaggio della select
        cache = getattr(self.app, "_catalog_per_provider", None)
        if cache is None:
            cache = self.app._catalog_per_provider = {}
        if q not in cache:
            from .catalog import Catalog
            try:
                cache[q] = Catalog.fetch(q)
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 502)
                return
        cat = cache[q]
        if cat is None or not cat.models:
            self._json({"error": f"nessun modello disponibile da {q}"}, 404)
            return
        out = [{"id": p.info.id, "short": p.info.short,
                "free": p.info.is_free,
                "context": p.info.context_length or 0,
                "prompt_price": p.info.prompt_price,
                "tool_calling": p.info.supports_tools,
                "scores": dict(p.scores or {})}
               for p in sorted(cat.models.values(), key=lambda m: m.info.id)]
        ignoti = 0
        conta = getattr(cat, "ignoti_sui_tool", None)
        if callable(conta):
            ignoti = len(conta())
        self._json({"provider": q, "modelli": out,
                    "gratuiti": len(cat.free()),
                    "tool_calling_ignoti": ignoti})

    @rotta("GET", "/api/locali")
    def _r_get_locali(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        # Separato perche' e' lento per costruzione: si interrogano
        # motori in ascolto su localhost e una porta chiusa puo'
        # costare un timeout. In parallelo, non in fila.
        from .providers import NO_KEY_PROVIDERS, local_models_multi
        trovati = local_models_multi(sorted(NO_KEY_PROVIDERS),
                                     self.app.env, timeout=1.2)
        self._json({"locali": {k: [m["id"] for m in v]
                               for k, v in trovati.items() if v}})

    @rotta("GET", "/api/categorie")
    def _r_get_categorie(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        # L'elenco delle categorie con quante task ha ciascuna e
        # quante sono state misurate. La UI non deve tenere
        # costanti: una lista invecchiata fa mostrare "4/6" quando le
        # categorie sono nove, e nessuno se ne accorge.
        from .benchmark import tasks_for
        from .catalog import CATEGORIES, CATEGORY_LABEL
        cat_ = self.app.catalog
        misurate = set()
        if cat_ is not None:
            for prof in cat_.models.values():
                for c, v in (prof.scores or {}).items():
                    if isinstance(v, (int, float)):
                        misurate.add(c)
        out = []
        for c in CATEGORIES:
            try:
                n = len(tasks_for(c))
            except Exception:  # noqa: BLE001
                n = 0
            out.append({"id": c, "label": CATEGORY_LABEL.get(c, c),
                        "tasks": n, "misurata": c in misurate})
        # `totale_categorie` e `totale_task` sono due numeri
        # diversi, e prima c'era un solo `totale` che poteva
        # significare entrambi. Il frontend lo mostrava come "4/6"
        # contando le categorie: se qualcuno lo avesse usato per
        # contare i test, avrebbe detto 9 invece di 15 senza che
        # nulla sembrasse rotto.
        misurabili = [c for c in out if c["tasks"] > 0]
        self._json({
            "categorie": out,
            "misurate": len(misurate),
            "totale_categorie": len(CATEGORIES),
            "categorie_misurabili": len(misurabili),
            "totale_task": sum(c["tasks"] for c in out),
        })

    @rotta("GET", "/api/capabilities")
    def _r_get_capabilities(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        cat = self.app.catalog
        if cat is None:
            self._json({"error": getattr(self.app, "_catalog_error", "catalogo non disponibile")}, 503)
            return
        # solo i punteggi misurati: "non lo so" non si trasforma in uno
        # zero, altrimenti la UI mostrerebbe una tabella piena di
        # modelli con 0.00 che non sono misurati ma sconosciuti
        self._json({"measured": {mid: p.scores for mid, p in cat.models.items() if p.scores}})

    @rotta("POST", "/api/routing")
    def _r_post_routing(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # POST {attivo: bool}: interruttore dell'instradamento
        # automatico (lo stato si legge in GET).
        if self.app.session is None:
            self._json({"error": "nessuna sessione"}, 409)
            return
        attivo = bool((body.get("attivo") if isinstance(body, dict) else None))
        try:
            self.app.session.instradamento_attivo(attivo)
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 400)
            return
        # La scelta va anche su disco: le scelte manuali di modello
        # spengono l'instradamento e scrivono "off". Senza questa riga,
        # riaccenderlo qui non servirebbe a niente al prossimo avvio —
        # l'interruttore tornerebbe spento e sembrerebbe rotto.
        avviso = ""
        try:
            from . import keys as keys_mod
            from .percorsi import ENV_PATH
            valore = "on" if attivo else "off"
            self.app.env["ORCHESTRA_ROUTING"] = valore
            avviso = keys_mod.scrivi_o_avviso(
                ENV_PATH, "ORCHESTRA_ROUTING", valore)
        except Exception as e:  # noqa: BLE001
            avviso = str(e)
        risposta = {"ok": True, "routing": bool(
            getattr(self.app.session, "_routing_attivo", False))}
        if avviso:
            # E' successo proprio qui: l'interruttore rispondeva "ok" e
            # al riavvio era di nuovo com'era prima.
            risposta["avviso"] = ("Applicato, ma non salvato per il prossimo "
                                  f"avvio: {avviso}")
        self._json(risposta)

    @rotta("POST", "/api/bench")
    def _r_post_bench(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        sample = body.get("sample", 3)
        try:
            sample = max(1, min(8, int(sample)))
        except (TypeError, ValueError):
            sample = 3
        category = body.get("category") or None
        if category == "all":
            category = None
        # lista scelta a mano dalla UI. Se manca, il server campiona
        # come prima: il campione automatico resta il default per lo
        # script e per chi non ha ancora aperto il pannello.
        scelti = body.get("models")
        if scelti is not None and not isinstance(scelti, list):
            self._json({"error": "models deve essere una lista di id"}, 400)
            return
        if isinstance(scelti, list) and len(scelti) > 60:
            self._json({"error": "troppi modelli: massimo 60 per volta"}, 400)
            return
        try:
            res = self.app.start_benchmark(sample=sample, category=category,
                                           models=scelti or None)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return
        self._json(res)

    @rotta("POST", "/api/council/start")
    def _r_post_council_start(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        body = body if isinstance(body, dict) else {}
        decision = (body.get("decision") or "").strip()
        seats = body.get("seats")
        try:
            rounds = int(body.get("rounds", 3))
        except (TypeError, ValueError):
            rounds = 3
        rounds = max(1, min(3, rounds))
        try:
            res = self.app.start_council(decision, seats=seats, rounds=rounds)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return
        self._json(res)

    @rotta("POST", "/api/prova")
    def _r_post_prova(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        # Prova manuale: un prompt, un modello, tutta la trascrizione.
        # Diversa dal benchmark: qui non c'e' un punteggio, c'e' la
        # risposta. Serve a capire PERCHE' un modello perde un task,
        # cosa scrive e quali tool chiama.
        prompt = (body.get("prompt") or "").strip()
        model = (body.get("model") or "").strip()
        if not prompt:
            self._json({"error": "scrivi un compito"}, 400)
            return
        if not model:
            self._json({"error": "scegli un modello"}, 400)
            return
        if len(prompt) > 8000:
            self._json({"error": "prompt troppo lungo (max 8000 caratteri)"}, 400)
            return
        try:
            from .benchmark import run_manual
            res = run_manual(
                prompt,
                provider_name=self.app.env.get("ORCHESTRA_PROVIDER", "openrouter"),
                model=model, env=self.app.env)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return
        self._json(res.to_dict())
