"""Il turno: mandare un messaggio, fermarlo, rispondere a una domanda,
allegare, e le impostazioni che riguardano il prossimo turno (modello,
provider, reasoning, iterazioni, budget).

I gestori sono metodi della classe `RotteChat`, che `Rotte` compone
insieme alle altre. Le rotte si dichiarano con `@rotta` accanto al codice
che le serve; la tabella e il dispatch stanno in `rotte.py` e in
`webapp.Handler._instrada`.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from . import __version__
from .percorsi import ENV_PATH
from .rotte import rotta


def _budget_per_pannello(env: dict[str, str]) -> dict[str, Any]:
    """I limiti salvati, con i nomi che il pannello Budget usa.

    Separata da /api/budget perche' il pannello deve mostrare quello che
    c'e' adesso, non quello che si sta per salvare. Se non c'e' niente di
    configurato torna tutti None: i campi restano vuoti, che e' la verita',
    invece di mostrare i valori di default come se fossero stati scelti.
    """
    import json as _json
    raw = (env.get("ORCHESTRA_BUDGET") or "").strip()
    vuoto = {"task_tokens": None, "task_cost": None, "task_iters": None,
             "sess_tokens": None, "sess_cost": None, "sess_reqs": None,
             "day_cost": None, "month_cost": None}
    if not raw:
        return vuoto
    try:
        d = _json.loads(raw)
    except ValueError:
        return vuoto
    return {k: d.get(k) for k in vuoto}


# Le rotte: percorso e metodo nel decoratore, il corpo
# sotto. Il commento sopra ogni gestore dice perche' esiste.
class RotteChat:
    @rotta("GET", "/api/state")
    def _r_get_state(self, path: str, body: dict[str, Any],
                     s: Any) -> None:
        # Lo stato deve rispondere anche senza sessione: e' cosi'
        # che la UI scopre di dover chiedere una chiave.
        if self.app.session is None or not self.app.ready:
            self._json({"ready": False, "error": self.app.error or "server non pronto",
                        "version": __version__,
                        "model": self.app.env.get("ORCHESTRA_MODEL", ""),
                        "provider": self.app.env.get("ORCHESTRA_PROVIDER", ""),
                        "busy": False,
                        # Anche senza sessione il pannello deve mostrare
                        # il limite configurato: altrimenti, prima di
                        # mettere una chiave, il campo sembra spento e
                        # l'utente "scopre" il limite solo dopo.
                        "max_secondi_turno": self._secondi_turno_config(),
                        "remote": self._info_remoto()})
            return
        s = self._need_session()
        if s is None:
            return
        snap = s.snapshot()
        snap["ready"] = self.app.ready
        snap["error"] = self.app.error
        snap["version"] = __version__
        # Il modello e il provider sono quelli della sessione VIVA,
        # non quelli salvati in .env: un bot ha i suoi, e leggerli
        # dall'ambiente mostrava nel menu il modello sbagliato mentre
        # la chat usava quello giusto.
        snap["model"] = s.modello_in_uso() or self.app.env.get(
            "ORCHESTRA_MODEL", "")
        snap["provider"] = self.app.provider_attivo()
        snap["bot"] = self.app.bot_attivo()
        snap["remote"] = self._info_remoto()
        self._json(snap)

    def _secondi_turno_config(self) -> float:
        """Il tetto di orologio configurato, letto dove e' vero.

        Prima la sessione (che puo' averlo cambiato a caldo), poi il
        `.env` (che e' quello che vale al prossimo avvio). Un valore
        storto non deve far cadere `/api/state`: si risponde zero, che
        significa "nessun limite", e il campo dell'UI lo dice.
        """
        try:
            cfg = getattr(getattr(self.app.session, "agent", None),
                          "config", None)
            if cfg is not None:
                return float(getattr(cfg, "max_secondi_turno", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        try:
            return float(self.app.env.get("ORCHESTRA_MAX_SECONDI_TURNO", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @rotta("GET", "/api/stt/status")
    def _r_get_stt_status(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        from . import stt as _stt
        self._json(_stt.stato())

    @rotta("GET", "/api/stream")
    def _r_get_stream(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        self._sse()

    @rotta("POST", "/api/allega")
    def _r_post_allega(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        self._allega(s, body)

    @rotta("POST", "/api/send")
    def _r_post_send(self, path: str, body: dict[str, Any],
                     s: Any) -> None:
        text = (body.get("text") or "").strip()
        scope = (body.get("scope") or "").strip() or None
        allegati, problema = self._dal_registro(
            body.get("allegati") or [])
        if problema:
            self._json({"error": problema}, 400)
            return
        if not text and not allegati:
            self._json({"error": "messaggio vuoto"}, 400)
            return
        # Self-correzione: l'utente può chiedere che il lavoro venga
        # VERIFICATO prima di accettarlo. `verifica` è una lista di
        # nomi di controlli oggettivi; li traduciamo nei verificatori
        # veri e li attacchiamo al config del giro. Senza lista,
        # nessuna verifica: i task conversazionali restano intatti.
        verifica_nomi = body.get("verifica") or []
        if verifica_nomi:
            self._imposta_verifica(verifica_nomi)
        else:
            self.app.session.agent.config.verifica_compito = None
        ok = s.send(text, allegati, scope=scope)
        if ok:
            # Gli allegati vivono per un messaggio. Senza questo,
            # premendo Invio due volte la stessa foto parte due
            # volte: e l'utente che vuole sapere "perche' l'ha
            # fatta due volte?" riceve due risposte identiche e
            # pensa a un bug.
            # _svuota_allegati sta sul Handler e svuota il
            # registro dell'app. Chiamarlo sull'app dava
            # AttributeError: la pulizia era sulla classe sbagliata,
            # e ogni invio faceva cadere la connessione — che il
            # browser legge come "Failed to fetch", lo stesso
            # errore di prima ma con una causa nuova.
            self._svuota_allegati()
        if not ok:
            # l'agente sta lavorando: l'UI deve saperlo e non far partire
            # una richiesta che verrebbe silenziosamente persa
            self._json({"error": "occupato: attendi la fine del turno o annulla",
                        "busy": True}, 409)
            return
        # Il conto in token torna QUI e non viene stimato dal
        # browser: il server sa quante pagine ha il PDF e quante
        # immagini sono, e una stima fatta a monte sarebbe una
        # stima diversa dalla verita'. Non serve dopo, serve subito.
        self._json({
            "ok": True,
            "id": [self._registra(a) for a in allegati],
            "allegati": [{"nome": a.nome, "kind": a.kind,
                          "immagini": len(a.immagini),
                          "token": a.token_stimati} for a in allegati],
            "token": sum(a.token_stimati for a in allegati),
        })

    @rotta("POST", "/api/steer")
    def _r_post_steer(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        testo = (body.get("testo") or "").strip()
        if not testo:
            self._json({"error": "testo vuoto"}, 400)
            return
        if len(testo) > 2000:
            self._json({"error": "troppo lungo (max 2000 caratteri)"}, 400)
            return
        if not s.busy:
            # La UI nasconde la barra quando il turno finisce, ma una
            # richiesta in volo o un client esterno possono arrivare
            # qui lo stesso. Accodare adesso significherebbe farla
            # leggere al prossimo turno, sulla domanda sbagliata.
            self._json({"error": "nessun turno in corso da guidare"}, 409)
            return
        ok = s.steer(testo)
        if not ok:
            if not s.busy:
                self._json({"error": "il turno e' appena finito: "
                                     "guida non inviata"}, 409)
            else:
                self._json({"error": "coda steer piena (max 5)"}, 400)
            return
        self._json({"ok": True})

    @rotta("POST", "/api/cancel")
    def _r_post_cancel(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        self._json({"ok": s.cancel()})

    @rotta("POST", "/api/stt/install")
    def _r_post_stt_install(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import stt as _stt
        _stt.avvia_installazione()
        self._json({"ok": True, **_stt.stato()})

    @rotta("POST", "/api/transcribe")
    def _r_post_transcribe(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        import base64 as _b64
        from . import stt as _stt
        audio_b64 = (body.get("audio") or "").strip()
        if not audio_b64:
            self._json({"error": "audio mancante"}, 400); return
        try:
            raw = _b64.b64decode(audio_b64)
        except Exception:
            self._json({"error": "audio non valido"}, 400); return
        if not _stt.disponibile():
            self._json({"error": "whisper non installato",
                        "installable": True}, 503); return
        try:
            testo = _stt.trascrivi(raw, body.get("filename") or "audio.webm")
            self._json({"text": testo})
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)

    @rotta("POST", "/api/reset")
    def _r_post_reset(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        try:
            s.reset()
            self._json({"ok": True})
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)

    @rotta("POST", "/api/piano")
    def _r_post_piano(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        # Modalita' piano: si accende e si spegne, non si "concede
        # una volta". Un flag che vale per il turno sarebbe un
        # permesso travestito, e l'utente non saprebbe piu' in che
        # stato si trova.
        attivo = bool(body.get("attivo", True))
        try:
            s.imposta_piano(attivo)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json({"ok": True, "attivo": attivo})

    @rotta("POST", "/api/system")
    def _r_post_system(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            self._json({"error": "prompt vuoto"}, 400)
            return
        s.set_system_prompt(prompt)
        self._json({"ok": True})

    @rotta("POST", "/api/model")
    def _r_post_model(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        model_id = (body.get("model") or "").strip()
        if not model_id:
            self._json({"error": "modello vuoto"}, 400)
            return
        try:
            self.app.switch_model(model_id)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except Exception as e:  # noqa: BLE001 - chiave o provider
            self._json({"error": f"{type(e).__name__}: {e}"}, 400)
            return
        # Scelta manuale: da qui il modello resta. L'instradamento
        # automatico risceglierebbe a ogni invio (spesso il vecchio),
        # rendendo il menu una decorazione: si spegne, e si riaccende
        # dal pannello Benchmark.
        routing = True
        if self.app.session is not None:
            try:
                self.app.session.instradamento_attivo(False)
                routing = False
            except Exception:
                pass
        self._json({"ok": True, "model": model_id, "routing": routing})

    @rotta("POST", "/api/permesso/prova")
    def _r_post_permesso_prova(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        # Fa partire una domanda di permesso vera, senza spendere
        # token e senza dipendere da quello che un modello decide di
        # fare. Serve per due motivi: per verificare che il canale
        # funzioni prima di fidarsi dell'agente con il disco, e
        # perche' i test end-to-end altrimenti possono solo sperare
        # che il modello sbagli — e quando non sbaglia il test passa
        # senza aver provato niente.
        #
        # La cartella proposta e' la Documenti dell'utente: fuori dal
        # root di sicuro, e non sensibile, quindi la domanda deve
        # comparire e le tre scelte devono funzionare.
        #
        # Accetta pero' una cartella a scelta. Non per gli utenti —
        # per i test: rispondere "mai" a Documents lo mette negli
        # negati per sempre, e ogni verifica successiva su quella
        # cartella viene negata all'istante senza domanda. Il primo
        # test e' fallito per questo, e aveva ragione a fallire: non
        # per un bug, perche' si stava sabotando da solo.
        richiesta_cartella = body.get("cartella")
        if richiesta_cartella:
            target = str(richiesta_cartella)
        else:
            casa = os.path.expanduser("~")
            target = os.path.join(casa, "Documents")
            if not os.path.isdir(target):
                target = casa
        gate = self.app.gate
        if gate is None:
            self._json({"error": "gate non attivo"}, 503)
            return
        from .permissions import Richiesta
        r = Richiesta(
            id=f"prova{time.time():.0f}",
            percorso=target, azione="leggere",
            dettaglio="prova manuale, nessun file viene letto",
            motivo="verifica del canale dei permessi")
        # Diagnosi incorporata: se la domanda non arriva, la risposta
        # dice PERCHE' (valutazione, canale assente, errore) invece
        # di un "non funziona" muto.
        esito: dict[str, Any] = {"valuta": None, "ha_chiedi": None,
                                 "chiesto": False, "risposta": None,
                                 "errore": None}
        def _prova_thread() -> None:
            # passa da chiedi_all_utente con l'id che gia' conosciamo:
            # e' l'unico percorso che registra la domanda in attesa,
            # ed e' quello che usa davvero un tool. Chiamando chiedi a
            # mano si verificherebbe meta' del canale.
            try:
                esito["valuta"] = gate.valuta(r.percorso, r.azione,
                                              r.dettaglio)
                esito["ha_chiedi"] = gate.chiedi is not None
                ok = gate.chiedi_all_utente(r.percorso, r.azione, r.dettaglio,
                                            richiesta_id=r.id)
                esito["chiesto"] = True
                esito["risposta"] = bool(ok)
            except Exception as e:  # noqa: BLE001
                esito["errore"] = f"{type(e).__name__}: {e}"
                from .permissions import _log_permesso
                _log_permesso(f"prova fallita: {type(e).__name__}: {e}")

        threading.Thread(
            target=_prova_thread, args=(), daemon=True,
            name="orchestra-permesso-prova").start()
        # aspetta che la domanda sia in attesa, non che il thread sia
        # partito: e' la differenza fra "ha chiesto" e "ha gridato
        # nel vuoto"
        in_atting = False
        for _ in range(60):
            with gate._lock:
                in_atting = r.id in gate._attesa
            if in_atting:
                break
            time.sleep(0.05)
        self._json({"ok": True, "id": r.id, "percorso": target,
                    "in_attesa": in_atting, "diagnosi": esito})

    @rotta("POST", "/api/permesso")
    def _r_post_permesso(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        # La risposta a una domanda di permesso. Quattro scelte, e
        # nient'altro: "una_volta", "sessione", "sempre", "mai". Una scelta
        # sconosciuta viene trattata come "mai" — se il pulsante non
        # e' arrivato, il caso sicuro e' negare.
        rid = (body.get("id") or "").strip()
        scelta = (body.get("scelta") or "mai").strip()
        if not rid:
            self._json({"error": "manca l'id della richiesta"}, 400)
            return
        if scelta not in ("una_volta", "sessione", "sempre", "mai"):
            self._json({"error": f"scelta non valida: {scelta}"}, 400)
            return
        gate = self.app.gate
        if gate is None:
            self._json({"error": "gate non attivo"}, 503)
            return
        if not gate.rispondi(rid, scelta):
            self._json({"error": "nessuna domanda in attesa con quell'id"}, 404)
            return
        self._json({"ok": True, "stato": gate.stato()})

    @rotta("POST", "/api/risposta")
    def _r_post_risposta(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        # La risposta a una domanda di `ask_user`. Testo libero, una
        # sola volta: la prima risposta vince e la domanda sparisce
        # dall'attesa, cosi' un secondo invio non la sovrascrive.
        rid = (body.get("id") or "").strip()
        testo = str(body.get("testo") or "").strip()
        if not rid:
            self._json({"error": "manca l'id della domanda"}, 400)
            return
        if not testo:
            self._json({"error": "la risposta e' vuota"}, 400)
            return
        from . import domande as domande_mod

        if not domande_mod.rispondi(rid, testo):
            self._json(
                {"error": "nessuna domanda in attesa con quell'id "
                          "(scaduta o gia' risposta)"}, 404)
            return
        self._json({"ok": True})

    @rotta("POST", "/api/permessi")
    def _r_post_permessi(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        # Lo stato dei permessi: cosa e' concesso, cosa e' negato,
        # cosa scade. Serve a poter revocare, e a non dare l'idea che
        # "per questa sessione" voglia dire "per sempre".
        gate = self.app.gate
        if gate is None:
            self._json({"error": "gate non attivo"}, 503)
            return
        if body.get("revoca"):
            revocato = gate.revoca(str(body.get("revoca")))
            self._json({"ok": revocato, "stato": gate.stato()})
            return
        self._json(gate.stato())

    @rotta("POST", "/api/provider")
    def _r_post_provider(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        p = (body.get("provider") or "").strip()
        if not p:
            self._json({"error": "indica il provider"}, 400)
            return
        try:
            risultato = self.app.switch_provider(p)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except (ValueError, KeyError) as e:
            self._json({"error": str(e)}, 400)
            return
        # si rimanda anche il modello scelto: se quello vecchio non
        # esiste sul servizio nuovo, l'utente deve sapere che si e'
        # cambiato sotto i piedi, non scoprirlo dalla prima risposta
        # che arriva da un altro servizio
        risposta = {"ok": True, "provider": p}
        if risultato:
            risposta.update(risultato)
        self._json(risposta)

    @rotta("POST", "/api/reasoning")
    def _r_post_reasoning(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        # Livello di reasoning dall'UI. L'endpoint era sparito in un
        # `git checkout` di emergenza e non era mai stato committato:
        # il pannello mandava POST che tornavano 404, e la select
        # sembrava rotta. Ricreato qui, da zero.
        #
        # Non si ricrea la sessione: `agent.config.reasoning_level` è
        # letto a ogni chiamata nel retry loop, quindi basta
        # aggiornarlo. Ricreare la sessione rischiava la conversazione
        # per un'impostazione che è solo un parametro per chiamata.
        from .reasoning import REASONING_LEVELS
        r = (body.get("reasoning") or "").strip()
        if r and r not in REASONING_LEVELS:
            self._json({"error": f"livello sconosciuto: {r}. "
                                 f"Validi: {', '.join(REASONING_LEVELS)}"}, 400)
            return
        if self.app.session.busy:
            self._json({"error": "l'agente sta lavorando: "
                                 "attendi o annulla prima"}, 409)
            return
        from . import keys as keys_mod
        keys_mod.scrivi(ENV_PATH, "ORCHESTRA_REASONING", r)
        self.app.env["ORCHESTRA_REASONING"] = r
        self.app.session.agent.config.reasoning_level = r or None
        self._json({"ok": True, "reasoning": r})

    @rotta("POST", "/api/iterazioni")
    def _r_post_iterazioni(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        # Max iterazioni del loop, dall'UI. Stesso schema di
        # /api/reasoning: valida, persiste, applica live.
        # Minimo 1 — sotto non ha senso — massimo 200, oltre il quale
        # un loop che non ha finito non finirà: sta girando in tondo,
        # e il tetto giusto è il breaker degli errori, non questo.
        try:
            n = int(body.get("max_iterations"))
        except (TypeError, ValueError):
            self._json({"error": "numero non valido"}, 400)
            return
        n = max(1, min(n, 200))
        if self.app.session.busy:
            self._json({"error": "l'agente sta lavorando: "
                                 "attendi o annulla prima"}, 409)
            return
        from . import keys as keys_mod
        keys_mod.scrivi(ENV_PATH, "ORCHESTRA_MAX_ITERS", str(n))
        self.app.env["ORCHESTRA_MAX_ITERS"] = str(n)
        self.app.session.agent.config.max_iterations = n
        self._json({"ok": True, "max_iterations": n})

    @rotta("POST", "/api/tempo-turno")
    def _r_post_tempo_turno(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        # Tetto di orologio del turno, dall'UI. Stesso schema di
        # /api/iterazioni: valida, persiste, applica live.
        #
        # Zero e' un valore legittimo e vuol dire "nessun limite": e'
        # una scelta, non un campo vuoto, e va salvata come le altre.
        # Il massimo (24 ore) non e' un tetto tecnico ma un errore di
        # battitura: chi scrive 900 al posto di 15 minuti pensa di aver
        # messo un quarto d'ora e ha messo mezza giornata.
        try:
            sec = float(body.get("max_secondi_turno"))
        except (TypeError, ValueError):
            self._json({"error": "numero non valido"}, 400)
            return
        if sec < 0:
            self._json({"error": "il tempo non puo' essere negativo"}, 400)
            return
        sec = min(sec, 86_400.0)
        if self.app.session.busy:
            self._json({"error": "l'agente sta lavorando: "
                                 "attendi o annulla prima"}, 409)
            return
        from . import keys as keys_mod
        # Il .env vuole un intero leggibile: "900", non "900.0". Un
        # float qui funziona ma rende illeggibile il file che l'utente
        # apre a mano quando vuole capire perche' i turni si fermano.
        testo = str(int(sec)) if float(sec).is_integer() else f"{sec:g}"
        # `scrivi` dice no quando la chiave non e' nella lista delle
        # scrivibili: ignorarlo voleva dire rispondere "salvato" a un
        # valore che al riavvio non c'era piu' — il limite spariva in
        # silenzio, che per un tetto di sicurezza e' il difetto peggiore.
        ok, messaggio = keys_mod.scrivi(
            ENV_PATH, "ORCHESTRA_MAX_SECONDI_TURNO", testo)
        if not ok:
            self._json({"error": messaggio or "salvataggio non riuscito"}, 500)
            return
        self.app.env["ORCHESTRA_MAX_SECONDI_TURNO"] = testo
        self.app.session.agent.config.max_secondi_turno = sec
        self._json({"ok": True, "max_secondi_turno": sec})

    @rotta("POST", "/api/budget")
    def _r_post_budget(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        # Salva configurazione budget. Persiste in .env come JSON:
        # senza, il limite valeva fino al riavvio e poi si perdeva --
        # che per un limite di spesa e' il contrario di un limite.
        import json as _json_mod
        from .budget import budget_guard, BudgetLimits

        # I limiti sono tutti e sette OBBLIGATORI: se il pannello ne
        # manda uno a zero o vuoto — e zero vuol dire "nessun limite",
        # che è quello che l'utente ha scritto — il campo arrivava
        # None e `check_limits` faceva `int > None`, che è il TypeError
        # che si vedeva in chat.
        #
        # Zero non è "non detto": è "illimitato", ed è una scelta
        # legittima. Per questo i campi tornano 0 e non None — e
        # `check_limits` salta il confronto quando il limite è zero.
        def parse_int(v):
            try:
                return max(0, int(v))
            except (TypeError, ValueError):
                return 0

        def parse_float(v):
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                return 0.0

        limiti = BudgetLimits(
            max_tokens_per_task=parse_int(body.get("task_tokens")),
            max_cost_usd_per_task=parse_float(body.get("task_cost")),
            max_iterations_per_task=parse_int(body.get("task_iters")),
            max_tokens_per_session=parse_int(body.get("sess_tokens")),
            max_cost_usd_per_session=parse_float(body.get("sess_cost")),
            max_requests_per_session=parse_int(body.get("sess_reqs")),
            max_cost_usd_per_day=parse_float(body.get("day_cost")),
            max_cost_usd_per_month=parse_float(body.get("month_cost")),
        )
        session_id = (self.app.env.get("ORCHESTRA_PROVIDER", "openrouter")
                      + "_" + self.app.env.get("ORCHESTRA_MODEL", "unknown"))
        budget_guard().get_or_create_session(session_id, limiti)

        budget_json = _json_mod.dumps({
            "task_tokens": limiti.max_tokens_per_task,
            "task_cost": limiti.max_cost_usd_per_task,
            "task_iters": limiti.max_iterations_per_task,
            "sess_tokens": limiti.max_tokens_per_session,
            "sess_cost": limiti.max_cost_usd_per_session,
            "sess_reqs": limiti.max_requests_per_session,
            "day_cost": limiti.max_cost_usd_per_day,
            "month_cost": limiti.max_cost_usd_per_month,
        })
        from . import keys as keys_mod
        keys_mod.scrivi(ENV_PATH, "ORCHESTRA_BUDGET", budget_json)
        self.app.env["ORCHESTRA_BUDGET"] = budget_json
        self._json({"ok": True, "messaggio": "Budget salvato"})

    @rotta("POST", "/api/budget/reset")
    def _r_post_budget_reset(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        from .budget import budget_guard
        from . import keys as keys_mod
        budget_guard()._instance = None
        keys_mod.scrivi(ENV_PATH, "ORCHESTRA_BUDGET", "")
        self.app.env.pop("ORCHESTRA_BUDGET", None)
        self._json({"ok": True, "messaggio": "Budget riportato ai valori di default"})

    @rotta("POST", "/api/annulla")
    def _r_post_annulla(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # L'undo delle scritture: rimette l'ultimo file com'era.
        # Non tocca la conversazione, quindi non serve una sessione
        # viva: il registro e' su disco e sopravvive al riavvio.
        try:
            voce = self.app.annulla_modifica()
        except (ValueError, RuntimeError) as e:
            self._json({"ok": False, "error": str(e)}, 400); return
        self._json({"ok": True, **voce})
