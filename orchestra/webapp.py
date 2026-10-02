"""Server HTTP locale per la UI web.

Server stdlib, nessuna dipendenza. Tre endpoint:

    GET  /               l'interfaccia
    GET  /api/stream     SSE: gli eventi dell'agente in tempo reale
    GET  /api/state      snapshot dello stato
    POST /api/send       {text}       invia un messaggio
    POST /api/allega     {files}      allega foto o PDF, dice il costo
    POST /api/cancel     arresta il turno in corso
    POST /api/reset      nuova conversazione
    POST /api/system     {prompt}     cambia le istruzioni di sistema

Perche' SSE e non WebSocket: lo stream e' di sola lettura, va in un senso
solo, e SSE si reconnecta da solo. WebSocket aggiungerebbe una
dipendenza per zero guadagno.

Nota di sicurezza: ascolta su 127.0.0.1 e non ha autenticazione. Va bene
per uso locale, NON va esposto su una rete. C'e' un controllo esplicito
all'avvio perche' sbagliarlo significa esporre le chiavi API.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .agent import LoopConfig
from .providers import (ProviderError, ambiente, build_provider,
                         load_env)
from .prompt_figlio import PROMPT_FIGLIO
from .session import Session
from .tools import SYSTEM_PROMPT, default_registry

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")

UI_PATH = os.path.join(HERE, "web", "index.html")

CARTELLA_CESTINO = ".cestino"

MAX_BODY = 64 * 1024  # un prompt non occupa 64KB: oltre e' un errore

# Un allegato e' una cosa diversa da un prompt. Il limite dei 64KB
# sopra vale per i messaggi scritti; un file da 12 MB in base64 sono
# 16, e con quel tetto non passava NESSUN file. Il browser si
# limitava a dire "Failed to fetch", che e' un errore di rete: la
# richiesta non e' mai arrivata al server, si e' interrotta a
# meta' strada e non c'e' nessun modo di sapere perche'.
#
# Due limiti, due scopi: uno protegge da un prompt assurdo, l'altro
# da un allegato che non entra. Un unico numero per i due e' un numero
# che non protegge nessuno dei due.
MAX_ALLEGATO = 20 * 1024 * 1024   # 20 MB: 12 di file + base64 + margine
MAX_ALLEGATO_FILE_MB = 12         # il tetto che l'utente vede prima




class OrchestraApp:
    """Lo stato del server, condiviso fra i thread.

    ThreadingHTTPServer crea un thread per richiesta, quindi tutto quello
    che tocciamo qui deve essere o immutabile o protetto. La Session ha gia'
    i propri lock; questo oggetto contiene solo la sessione.
    """

    def __init__(self, env: dict[str, str], session: Session | None = None) -> None:
        self.env = env
        # Allegati già validati, per id. Vivono finche' il messaggio non
        # parte: sono in memoria, non su disco. E il motivo per cui il
        # browser manda il file una volta sola invece di due.
        #
        # Sta qui e non nella classe Handler perche' un dizionario creato
        # come attributo di classe e' condiviso da tutte le richieste: se
        # _registra scrive dentro quello e la pulizia ne crea uno nuovo,
        # quello nuovo lo vede solo la richiesta che lo ha creato, e
        # quello vecchio resta con dentro tutti gli id. Il secondo Invio
        # riusava l'allegato del primo, senza che nulla lo dicesse.
        self._registro_allegati: dict[str, Any] = {}
        # la sessione può arrivare già costruita (dal create, che deve poter
        # catturare l'errore del provider) o essere costruita qui. Il punto
        # è che TUTTE le istanze passano da qui: prima `create()` usava
        # __new__ e saltava __init__, e gli attributi mancavano a runtime
        # con un AttributeError che emergeva solo al primo /api/models.
        self.session = session if session is not None else self._make_session(
            env.get("ORCHESTRA_PROVIDER", "openrouter"),
            env.get("ORCHESTRA_MODEL", ""),
        )
        self.delega_attiva = False
        self.ready = True
        self.error = ""
        # Gate dei permessi: l'unico posto dove l'utente puo' autorizzare
        # un accesso fuori dalla cartella di lavoro. Vive sull'app perche'
        # deve sopravvivere fra una richiesta e l'altra: il tool che
        # chiede gira in un thread, la risposta arriva su un altro.
        self.gate = self._make_gate()
        # il catalogo viene caricato pigramente: `/models` lo chiede, la
        # chat no. Caricarlo all'avvio aggiungerebbe una chiamata di rete a
        # ogni start, anche quando l'utente vuole solo chattare.
        self._catalog: Any = None
        self._catalog_tried = False
        self._catalog_error: str = ""
        # stato del benchmark lanciato dalla UI
        self._bench: dict[str, Any] = {"running": False, "log": [], "result": None}

    def _make_gate(self) -> Any:
        """Il gate che chiede all'utente, collegato agli eventi SSE.

        La domanda viaggia come un evento normale: il tool che si ferma e'
        in un thread, e senza SSE l'utente non saprebbe che c'e' una
        domanda in attesa. La risposta arriva su /api/permesso.
        """
        from .permissions import Gate, Richiesta, Risposta
        from .tools import set_permission_gate

        def chiedi(r: Richiesta) -> Risposta:
            # self.session.emit NON esiste: l'emittente e' il bridge, e
            # chiamare il metodo sbagliato solleva AttributeError. Con un
            # except generico intorno, l'errore di programmazione finiva
            # per essere letto come "l'utente ha detto no": il popup non
            # compariva e il tool veniva negato subito, senza che nulla
            # lo dicesse. Stavolta si chiama quello giusto, e se
            # fallisce lo si vede.
            bridge = self.session.bridge
            bridge.emit("permission_request", {
                "id": r.id, "percorso": r.percorso, "azione": r.azione,
                "dettaglio": r.dettaglio, "motivo": r.motivo,
                "root": str(self.gate_root()),
            })
            # aspetta la risposta. Il tool e' bloccato nel frattempo: e'
            # il prezzo della conferma, ed e' giusto che lo sia.
            import time as _t
            attesa = 0.0
            while attesa < 300:
                gate = self.gate
                if gate is None:
                    return Risposta("mai")
                with gate._lock:
                    risposta = gate._risposte.get(r.id)
                if risposta is not None:
                    return risposta
                _t.sleep(0.05)
                attesa += 0.05
            # nessuna risposta in cinque minuti: si nega. Un permesso
            # che scade da solo e' un permesso che qualcuno ha lasciato
            # aperto: negare e' la scelta che non ti surprises.
            return Risposta("mai")

        gate = Gate(chiedi=chiedi)
        set_permission_gate(gate)
        return gate

    def gate_root(self) -> Any:
        from .tools import _root
        return _root()

    @property
    def catalog(self) -> Any:
        """Catalogo dei modelli, caricato alla prima richiesta."""
        if not self._catalog_tried:
            self._catalog_tried = True
            try:
                from .catalog import Catalog

                self._catalog = Catalog.fetch(self.env.get("ORCHESTRA_PROVIDER", "openrouter"))
            except Exception as e:  # noqa: BLE001 - l'UI mostra l'errore
                self._catalog = None
                self._catalog_error = str(e)
        return self._catalog

    def switch_provider(self, provider_name: str) -> None:
        """Cambia il provider predefinito e ricarica il catalogo.

        Stesso vincolo di switch_model: durante un turno non si cambia,
        o la conversazione si troverebbe a metà fra due provider diversi.
        La chiave deve gia' esistere: cambiare provider non e' un modo
        per aggirare la configurazione, quindi se manca la chiave si
        dice subito e in chiaro.
        """
        if self.session.busy:
            raise RuntimeError("l'agente sta lavorando: attendi o annulla prima")

        from .providers import KNOWN_PROVIDERS, NO_KEY_PROVIDERS, base_url_for

        if provider_name not in KNOWN_PROVIDERS:
            raise ValueError(f"provider sconosciuto: {provider_name}")
        key_env = KNOWN_PROVIDERS[provider_name][1]
        if key_env and not (self.env.get(key_env) or load_env(ENV_PATH).get(key_env)):
            raise ValueError(f"manca la chiave {key_env} per {provider_name}")

        self.env["ORCHESTRA_PROVIDER"] = provider_name
        # il catalogo appartiene al provider: tenere quello vecchio
        # mostrerebbe i modelli sbagliati nella select
        self._catalog = None
        self._catalog_tried = False
        from . import keys as keys_mod
        keys_mod.scrivi(ENV_PATH, "ORCHESTRA_PROVIDER", provider_name)
        # l'indirizzo viene risolto qui: se il provider e' valido ma
        # l'override nell'env e' malformato, e' meglio accorgersene
        # adesso che alla prima richiesta, con un errore di rete
        if not base_url_for(provider_name, self.env):
            raise ValueError(f"indirizzo non valido per {provider_name}")

        # Il modello in uso va verificato: cambiando servizio, quasi
        # nessun id sopravvive. Un id come "vendor/modello-grande" puo'
        # esistere su OpenRouter e non su Groq, e allora la combinazione
        # e' impossibile: la select mostra il modello nuovo servizio ma
        # l'agente continua a chiamare il vecchio, e la prima richiesta
        # muore con un errore che sembra di rete.
        #
        # Non si lascia cosi'. Si sceglie un modello che quel servizio
        # ha davvero, e si DICE quale: un cambio silenzioso lascia
        # l'utente convinto di stare usando il modello che ha scelto.
        modello_vecchio = self.env.get("ORCHESTRA_MODEL", "")
        scelto = self._modello_per_servizio(provider_name, modello_vecchio)
        if scelto:
            self.switch_model(scelto)
        return {
            "provider": provider_name,
            "modello": scelto or modello_vecchio,
            "modello_cambiato": bool(scelto and scelto != modello_vecchio),
        }

    def _modello_per_servizio(self, provider_name: str,
                              attuale: str,
                              escluso: str = "") -> str | None:
        """Un modello che questo servizio ha davvero, o None se non si puo' sapere.

        L'ordine di preferenza non e' arbitrario: prima i gratuiti con
        il tool-calling, perche' sono gli unici che si possono provare
        senza pensarci; poi gli altri con i tool; poi, se proprio non
        c'e' niente, il primo disponibile. Un agente senza tool-calling
        non e' Orchestra: puo' rispondere, ma non lavorare.

        `escluso` serve per il recupero: un modello appena morto non
        viene riproposto come sostituto di se stesso.
        """
        cat = self.catalog  # forza il ricaricamento: l'abbiamo svuotato
        if cat is None or not getattr(cat, "models", None):
            # catalogo non disponibile: non si sceglie a caso. Si lascia
            # com'e' e si dice che non e' stato verificato.
            return None

        profili = cat.models
        # L'esclusione viene PRIMA del "tieni quello di adesso": se il
        # modello corrente e' proprio quello appena morto, restituirlo
        # qui fa riprovare lo stesso identico modello che ha appena
        # fallito, e il recovery non recupera niente.
        if attuale in profili and attuale != escluso:
            return attuale

        # i fatti stanno in .info: is_free, supports_tools, prezzi.
        # Scriverli sul profilo direbbe "quello che penso", e al primo
        # cambio servizio — proprio quando serve — un AttributeError.
        def ordina(mid: str) -> tuple:
            prof = profili[mid]
            # UNA definizione di "gratis": quella del ModelInfo. Qui il
            # prezzo era confrontato con "> 0", e openrouter/auto ha
            # prezzo -1 ("variabile", non "gratis"): finiva ordinato
            # come se fosse gratuito e diventava il default. Due
            # definizioni che non concordano producono una scelta che
            # nessuno dei due voleva.
            gratis = prof.info.is_free
            prezzo = prof.info.prompt_price or 0.0
            # I modelli MISURATI vengono prima di tutto il resto, e
            # gratis-paga all'interno di ciascun gruppo. Un modello
            # misurato ha gia' girato un task con i tool: e' una prova,
            # non una congettura. Senza questo, "gratuito" vuol dire
            # "gratuito e magari un modello audio": un provider puo'
            # elencare whisper e i modelli di guardia, che non fanno
            # chat e non si accorgono di esserne elencati.
            misurato = 0 if prof.scores else 1
            return (misurato, not gratis, max(prezzo, 0.0), mid)

        def gratis_con_tool(p) -> bool:
            # Solo i True. Un None — il provider non lo dichiara — non
            # e' "adatto per principio": e' sconosciuto, e su uno
            # sconosciuto non si fa affidamento. Prima entrava, e per
            # un servizio come Groq finiva a scegliere whisper.
            return p.info.supports_tools is True

        def con_tool(p) -> bool:
            return p.info.supports_tools is True

        candidati = [m for m in profili if m != escluso]
        # Se il servizio non dichiara niente, nessun filtro e' utile:
        # si passa al terzo, che non pretende nulla.
        for filtro in (gratis_con_tool, con_tool, lambda p: True):
            scelti = [m for m in candidati if filtro(profili[m])]
            if scelti:
                return sorted(scelti, key=ordina)[0]
        return None

    def _collega_recupero_tool(self) -> None:
        """Collega alla sessione i due pezzi che dipendono dal provider.

        Li fornisce l'app perche' la Session non sa cosa sia un
        catalogo: sa solo che un turno e' morto e che bisogna
        riprovare. Chi decide QUALE modello provare sta qui.
        """
        if self.session is None:
            return

        def scegli(morto: str) -> str | None:
            # prima si scrive il fatto: il provider ha detto che quel
            # modello non regge i tool, e questo e' un fatto, non una
            # congettura. Rimane scritto anche dopo un riavvio.
            cat = self.catalog
            if cat is not None:
                cat.segnala_senza_tool(morto)
            return self._modello_per_servizio(
                self.env.get("ORCHESTRA_PROVIDER", "openrouter"),
                self.env.get("ORCHESTRA_MODEL", ""),
                escluso=morto,
            )

        def cambia(mid: str) -> bool:
            try:
                # switch_model vieta il cambio a sessione occupata, per non
                # lasciare la conversazione a meta' fra due modelli. Qui il
                # cambio e' voluto e sicuro — il vecchio e' morto — quindi
                # si scavalca il controllo, non per disattenzione ma perche'
                # il caso e' esattamente quello che il controllo vieta.
                # `busy` e' una property: non si assegna, si tocca il
                # campo che la alimenta.
                _salva_busy = self.session._busy
                self.session._busy = False
                try:
                    self.switch_model(mid)
                finally:
                    self.session._busy = _salva_busy
                return True
            except (ValueError, RuntimeError, ProviderError, KeyError):
                return False

        def instrada(prima_richiesta: str) -> str | None:
            """Il PRIMO modello, scelto sui punteggi. None se non si puo'.

            Chiama routing.instrada, che non conosce la Sessione: il
            motore di scelta e' uno solo e testato da solo, e la
            Sessione gli passa solo la richiesta. Se la scelta fosse
            dentro questa funzione, il classifier non si potrebbe
            verificare senza una sessione viva — che e' esattamente
            come i punteggi hanno finito per non essere usati da
            nessuno.
            """
            from .routing import instrada as _instrada
            cat = self.catalog
            if cat is None or not getattr(cat, "models", None):
                return None
            scelta = _instrada(cat, prima_richiesta)
            # la scelta si scrive SEMPRE, anche quando coincide con
            # quello che gia' si usa: "perche' ha scelto questo" e' la
            # domanda che si fa davanti a un instradamento, e senza
            # risposta sembra che non sia successo niente
            try:
                self.session.bridge.emit(
                    "routing", **{
                        "modello": scelta.modello or "",
                        "categoria": scelta.categoria,
                        "punteggio": scelta.punteggio,
                        "prove": scelta.prove,
                        "motivo": scelta.motivo,
                        "scartati": scelta.scartati[:3],
                        "spiegazione": scelta.spiega(),
                    })
            except Exception:
                pass
            if scelta.modello is None:
                return None
            if scelta.modello == self.env.get("ORCHESTRA_MODEL", ""):
                return None      # gia' quello: non toccare la sessione
            return scelta.modello

        self.session._scegli_primo = instrada
        # Si accende qui, e non in send(): il gancio e' l'unico posto
        # dove si sa che il catalogo esiste. Accenderlo altrove
        # significherebbe instradare con un catalogo che potrebbe non
        # essere ancora stato caricato.
        if hasattr(self.session, "instradamento_attivo"):
            self.session.instradamento_attivo(True)
        self.session._scegli_sostituto = scegli
        self.session._cambia_modello = cambia

    def _ripara_modello_iniziale(self) -> None:
        """Se il modello salvato non esiste su questo servizio, lo corregge.

        Non e' un caso teorico: la configurazione su disco puo' essere
        rimasta con una combinazione impossibile — il servizio e' stato
        cambiato quando il codello non sapeva ancora che i modelli non
        sopravvivono al cambio. All'avvio si rileva e si sistema, altrimenti
        la prima richiesta muore con un errore che sembra di rete e non
        c'e' niente nella UI che lo spieghi.

        Silenzioso quando tutto e' regolare: la riparazione e' una
        correzione, non un avvenimento. Se pero' tocca il modello, lo
        dice, perche' e' una scelta che l'utente non ha fatto.
        """
        if self.session is None:
            return
        provider_name = self.env.get("ORCHESTRA_PROVIDER", "openrouter")
        modello = self.env.get("ORCHESTRA_MODEL", "")
        if not modello:
            return
        cat = self.catalog
        if cat is None or not getattr(cat, "models", None):
            return          # non lo sappiamo: non si tocca niente
        if modello in cat.models:
            return          # la combinazione e' valida

        sostituto = self._modello_per_servizio(provider_name, modello)
        if not sostituto:
            self.error = (
                f"il modello '{modello}' non esiste su {provider_name} e "
                f"non c'e' nessun alternativa nel catalogo"
            )
            return
        try:
            self.switch_model(sostituto)
        except (ValueError, RuntimeError, ProviderError, KeyError) as e:
            self.error = f"modello iniziale non valido ({modello}): {e}"
            return
        self.error = (
            f"il modello '{modello}' non esiste su {provider_name}: "
            f"uso '{sostituto}'. Cambialo dal menu in alto."
        )

    def switch_model(self, model_id: str) -> None:
        """Cambia il modello dell'agent in uso.

        Solleva RuntimeError se l'agente sta lavorando: cambiarlo a metà
        turno lascerebbe la conversazione con messaggi di due modelli
        diversi e un contesto che non ha senso.

        Valida contro il catalogo. `build_provider` accetterebbe QUALSIASI
        stringa — costruisce un client valido che fallisce solo alla
        prima chiamata, con un errore che sembra un problema di rete. Un
        id sbagliato in una select non è un errore plausibile da accettare
        in silenzio.
        """
        if self.session.busy:
            raise RuntimeError("l'agente sta lavorando: attendi o annulla prima")

        cat = self.catalog
        if cat is not None and cat.models and model_id not in cat.models:
            raise ValueError(
                f"modello sconosciuto: {model_id}. "
                f"Disponibili: {', '.join(sorted(cat.models)[:5])}…"
            )

        from .providers import build_provider

        provider_name = self.env.get("ORCHESTRA_PROVIDER", "openrouter")
        env = ambiente(ENV_PATH)
        prov = build_provider(provider_name, model=model_id, env=env)
        self.session.agent.provider = prov
        self.env["ORCHESTRA_MODEL"] = model_id

    def start_benchmark(self, *, sample: int = 3, category: str | None = None,
                        throttle: float = 3.0,
                        models: list[str] | None = None) -> dict[str, Any]:
        """Lancia il benchmark in background e restituisce subito.

        Non blocca: l'UI mostra l'avanzamento via /api/bench/status. Un
        benchmark dura minuti e un server che aspetta è un server morto.
        """
        if self._bench["running"]:
            raise RuntimeError("un benchmark è già in corso")

        cat = self.catalog
        if cat is None or not cat.models:
            raise RuntimeError("catalogo non disponibile")

        if models:
            # lista scelta a mano dalla UI: nessun campionamento. E'
            # la via normale perche' con 396 modelli la scelta e' di chi
            # guarda, non del server. Ma solo id che esistono davvero:
            # un id inventato fallirebbe a meta' del benchmark.
            sconosciuti = [m for m in models if m not in cat.models]
            if sconosciuti:
                raise RuntimeError(
                    "modelli sconosciuti: " + ", ".join(sconosciuti[:5]))
            ids = list(dict.fromkeys(models))
            if not ids:
                raise RuntimeError("nessun modello selezionato")
        else:
            # il campione viene dai modelli gratuiti con tool-calling, sparsi
            # sulla finestra di contesto: primo, uno medio, uno con contesto
            # grande. Non e' casuale perche' il confronto deve essere leggibile.
            free = sorted(cat.free(), key=lambda p: p.info.id)
            if not free:
                raise RuntimeError("nessun modello gratuito con tool-calling")
            free.sort(key=lambda p: -(p.info.context_length or 0))
            step = max(1, len(free) // max(1, sample))
            ids = [m.info.id for m in free[::step]][:sample]

        self._bench = {"running": True, "log": [], "result": None,
                       "started": time.time(), "models": ids}

        def worker() -> None:
            from .benchmark import  (  # noqa: PLC0415, salva_punteggi
                render_table, run_task, summarize, tasks_for, perché,
            )

            tasks = tasks_for(category)
            if not tasks:
                self._bench["log"].append(f"categoria sconosciuta: {category}")
                self._bench["running"] = False
                return
            results = []
            stop = False
            try:
                for mid in ids:
                    if stop:
                        break
                    name = cat.models[mid].info.short if mid in cat.models else mid
                    self._bench["log"].append(f"== {name} ==")
                    for t in tasks:
                        r = run_task(t, provider_name=self.env.get("ORCHESTRA_PROVIDER", "openrouter"),
                                     model=mid, env=dict(os.environ, **self.env),
                                     max_iterations=10)
                        results.append(r)
                        if r.unusable:
                            # il provider lo riserva ad altri client: inutile
                            # continuare e tenerlo nel confronto
                            self._bench["log"].append(f"  {t.id}: non raggiungibile")
                            stop = True
                            break
                        state = "ok" if r.passed else ("errore" if r.error else "fail")
                        self._bench["log"].append(
                            f"  {t.id}: {state}"
                            + (f" — {perché(r)}" if not r.passed else "")
                        )
                        if throttle:
                            time.sleep(throttle)
                summary = summarize(results)
                # salva_punteggi scrive i punteggi sul catalogo.
                # Sta in una funzione perche' qui dentro non era
                # raggiungibile da nessun test, ed e' il posto dove
                # due bug hanno vissuto senza essere visti.
                salva_punteggi(cat, summary)
                try:
                    cat.save()
                except Exception:
                    pass
                self._bench["result"] = {
                    "table": render_table(summary, cat),
                    "per_model": summary["per_model"],
                    "unusable": summary.get("unusable_models", []),
                    # il numero unico: calcolato qui e non nel
                    # frontend, altrimenti se ne avrebbe due versioni
                    # e divergerebbero
                    "punteggio_unico": summary.get("punteggio_unico"),
                }
            except Exception as e:  # noqa: BLE001
                self._bench["log"].append(f"ERRORE: {type(e).__name__}: {e}")
            finally:
                self._bench["running"] = False

        from .benchmark import tasks_for

        # I task si risolvono PRIMA di avviare il thread. Servono due
        # cose: contarli nella risposta, e fallire subito su una categoria
        # ignota invece di partire e morire dentro il worker. Prima stava
        # solo dentro il worker, e la risposta al client lanciava
        # NameError: tasks_for, lasciando il benchmark segnato "in corso"
        # per sempre anche se il thread era gia' morto.
        tasks = tasks_for(category)
        if not tasks:
            raise RuntimeError(f"categoria sconosciuta: {category}")

        threading.Thread(target=worker, daemon=True, name="orchestra-bench").start()
        # totale esatto: la UI lo usa per la percentuale di avanzamento.
        # Senza questo il pannello puo' dire 'sta girando' ma non quanto manca.
        return {"ok": True, "models": ids, "tasks": len(tasks),
                "runs": len(ids) * len(tasks)}

    @staticmethod
    def _make_session(provider_name: str, model: str) -> Session:
        def num(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, default))
            except (TypeError, ValueError):
                return default

        # Solo il prompt di base: le skill le aggiunge l'Agent a ogni
        # turno, in Agent._aggiorna_prompt.
        #
        # Qui il contesto non e' disponibile, e non solo perche' questo
        # e' uno staticmethod: l'app non esiste ancora, viene costruita
        # proprio adesso con la sessione che stiamo restituendo.
        # Chiamare un metodo dell'app da qui faceva saltare ogni avvio
        # con NameError, presentato come un crash in create() — che e'
        # dove guardavo, e non dove era.
        return Session(
            provider=build_provider(provider_name, model=model,
                                    env=load_env(ENV_PATH) | os.environ),
            registry=default_registry(),
            system_prompt=SYSTEM_PROMPT,
            config=LoopConfig(max_iterations=12, context_limit=120_000,
                              keep_recent=8),
        )

    def _collega_delega(self) -> None:
        """Costruisce la fabbrica del figlio e registra il tool.

        Il figlio nasce QUI, non riusando l'agente del padre: ha il
        proprio provider, il proprio registro e la propria finestra.
        E il suo registro e' `default_registry()` rifatto da capo —
        quello del padre ha `delega` dentro, e se riusassimo quello il
        tetto di profondita' non esisterebbe. Difesa una: il registro
        nuovo. Difesa due: nessun codice registra `delega` sul figlio.
        Difesa tre: il Delegatore rifiuta comunque a profondita' 1.

        Tre difese per un tetto, e sembra esagerato. Non lo e': e
        l'unica cosa che tiene insieme un orchestratore che si
        autogenera, e se una delle tre cade le altre due lo dicono
        invece di lasciarlo andare.
        """
        app = self
        nome_provider = self.env.get("ORCHESTRA_PROVIDER", "openrouter")
        env_chiavi = ambiente(ENV_PATH)

        def fabbrica(obiettivo: str):
            # il modello del figlio lo sceglie il Delegatore, non qui:
            # e' una decisione per compito, e farla qui la farebbe
            # sbagliata perche' qui non si sa ancora qual e' il compito
            modello = ""
            if app.catalog is not None and getattr(app.catalog, "models", None):
                try:
                    from .routing import instrada as _instrada
                    scelta = _instrada(app.catalog, obiettivo)
                    modello = scelta.modello or ""
                except Exception:
                    modello = ""

            from .agent import Agent, LoopConfig
            return Agent(
                build_provider(nome_provider, model=modello, env=env_chiavi),
                default_registry(),          # NUOVO: senza 'delega'
                PROMPT_FIGLIO,
                LoopConfig(max_iterations=12, context_limit=60_000,
                           keep_recent=6),
                on_event=lambda kind, data: None,   # il figlio e' muto
            )

        self.session._fabbrica_figlio = fabbrica
        # il catalogo serve al tariffario del figlio: senza i prezzi del
        # modello che ha lavorato, il costo di una delega resta sconosciuto
        self.session._catalogo_per_costo = app.catalog
        self.delega_attiva = self.session.attiva_delega()

    @classmethod
    def create(cls) -> "OrchestraApp":
        """Costruisce l'app, o la mette in stato di errore se il provider
        non e' configurato. La UI deve poter mostrare l'errore invece di
        fallire all'avvio."""
        env = ambiente(ENV_PATH)
        try:
            app = cls(
                env,
                session=cls._make_session(
                    env.get("ORCHESTRA_PROVIDER", "openrouter"),
                    env.get("ORCHESTRA_MODEL", ""),
                ),
            )
            app._collega_recupero_tool()
            app._collega_delega()
            app._ripara_modello_iniziale()
            return app
        except (ProviderError, KeyError) as e:
            # l'app esiste anche senza sessione: /api/state deve poter
            # rispondere con l'errore, e la UI lo mostra
            app = cls(env, session=None)
            app.ready = False
            app.error = str(e)
            return app
            app.ready = False
            app.error = str(e)
            app.session = None  # type: ignore[assignment]
            return app


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app: OrchestraApp  # impostato dal server

    # silenzio: il log di ogni richiesta SSE èrumore
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    # -- helper ------------------------------------------------------------

    def _send_bytes(self, code: int, body: bytes, content_type: str) -> None:
        """Risposta con byte gia' pronti.

        Gli header sono identici per tutti i file statici: il tipo e' quello
        che il browser pretende per ciascuna risorsa (text/css per lo stile,
        text/javascript per lo script) e la lunghezza deve corrispondere ai
        byte inviati, altrimenti su HTTP/1.1 la connessione resta appiccicata
        e i file successivi non arrivano.
        """
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send_bytes(code, json.dumps(obj).encode("utf-8"),
                         "application/json; charset=utf-8")

    # I file restano separati su disco: ognuno ha una responsabilita' e
    # resta testabile da solo. Al browser arrivano in uno, perche' piu'
    # richieste significa piu' modi in cui la pagina resta a meta' — e con
    # un solo script inline (la versione monolitica) funzionava.
    BUNDLE_ORDER = ("core.js", "panels.js", "main.js")

    def _bundle(self) -> None:
        parts = []
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        for name in self.BUNDLE_ORDER:
            try:
                with open(os.path.join(web_dir, name), encoding="utf-8") as f:
                    parts.append("/* ==== %s ==== */\n%s" % (name, f.read()))
            except OSError:
                continue
        if not parts:
            self._json({"error": "nessun file javascript"}, 404)
            return
        body = "\n;\n".join(parts).encode("utf-8")
        self._send_bytes(200, body, "text/javascript; charset=utf-8")

    def _static(self, name: str, content_type: str) -> None:
        """Serve un file statico dalla cartella web/.

        Il nome viene controllato: solo [A-Za-z0-9._-], niente percorsi.
        Un parametro che arrivasse da fuori (`../webapp.py`) deve poter
        solo ottenere file della web/, mai altri.
        """
        if not all(c.isalnum() or c in "._-" for c in name):
            self._json({"error": "nome file non valido"}, 400)
            return
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", name)
        # doppia barriera: anche senza percorsi, il risultato deve stare
        # dentro web/
        if not os.path.abspath(path).startswith(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        ):
            self._json({"error": "non trovato"}, 404)
            return
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._json({"error": "non trovato"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # come per l'HTML: obbliga a riverificare. Senza, correggere un .js
        # e ricaricare non produceva nulla, e sembrava che le modifiche
        # non arrivassero al browser.
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, path: str) -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._json({"error": "UI non trovata"}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Senza questi il browser puo' servire una copia vecchia dalla
        # memoria e non lo dice: si vedeva una UI senza selettore modello
        # mentre il server era gia' aggiornato, e sembrava un bug del
        # codice. `no-cache` non impedisce di salvare, obbliga a
        # riverificare; `must-revalidate` chiude la porta al limbo.
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _body(self, *, per_allegato: bool = False) -> dict[str, Any]:
        # Il tetto dipende da cosa arriva. Un prompt e' testo scritto e
        # 64KB sono gia' generosi; un allegato in base64 e' un terzo
        # piu' grande del file, e 12 MB diventano 16.
        #
        # Prima il limite era uno solo, pensato per i prompt: nessun
        # file passava, e il browser diceva "Failed to fetch" senza
        # dire perche'. Un errore che sembra di rete quando il problema
        # e' una soglia e' il peggiore dei due, perche' fa perdere
        # tempo a cercare la rete.
        tetto = MAX_ALLEGATO if per_allegato else MAX_BODY
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return {}
        if n <= 0:
            return {}
        if n > tetto:
            # Si risponde DOPO aver letto (o svuotato) il corpo. Se si
            # risponde e si esce, la connessione si chiude con dati
            # ancora in arrivo e il client vede un errore di rete
            # invece di un 400 con la spiegazione.
            self._consuma_corpo(n)
            if per_allegato:
                raise ValueError(
                    f"richiesta troppo grande ({round(n / 1048576, 1)} MB, "
                    f"il limite e' {round(tetto / 1048576)} MB). "
                    f"Un allegato oltre i {MAX_ALLEGATO_FILE_MB} MB non "
                    f"passa: riduci la risoluzione, oppure metti il file "
                    f"nella cartella di lavoro e chiedi all'agente di "
                    f"leggerlo da li'."
                )
            raise ValueError(
                f"messaggio troppo grande ({round(n / 1024)} KB, il limite "
                f"e' {round(MAX_BODY / 1024)} KB)"
            )
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("JSON non valido")

    def _consuma_corpo(self, n: int) -> None:
        """Legge e butta il corpo, a pezzi.

        Serve per poter rispondere con un errore comprensibile: se il
        corpo resta nel socket e la connessione si chiude, il client
        vede un errore di rete e non sa che il problema era la
        dimensione.
        """
        letti = 0
        while letti < n:
            pezzo = self.rfile.read(min(65536, n - letti))
            if not pezzo:
                break
            letti += len(pezzo)

    def _need_session(self) -> Session | None:
        if not self.app.ready or self.app.session is None:
            self._json({"error": self.app.error or "server non pronto"}, 503)
            return None
        return self.app.session

    # -- GET ---------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - firma di BaseHTTPRequestHandler
        path = self.path.split("?")[0]
        if path == "/":
            self._html(UI_PATH)
        elif path == "/app.js":
            self._bundle()
        elif path.endswith(".js"):
            self._static(path[1:], "text/javascript; charset=utf-8")
        elif path.endswith(".css"):
            self._static(path[1:], "text/css; charset=utf-8")
        elif path.endswith(".html"):
            # serve le pagine di prova della diagnostica. Stesso
            # percorso dei file statici, quindi se questo funziona
            # sappiamo che il trasporto dei file e' a posto.
            self._static(path[1:], "text/html; charset=utf-8")
        elif path == "/api/skill/file":
            # Anche in GET: il pulsante "Apri" e' una lettura, non una
            # scrittura. Registrarle solo fra i POST faceva rispondere
            # 404 a una richiesta che il browser faceva in GET — e il
            # sintomo era "il pulsante non fa niente", che non dice
            # nulla del motivo.
            self._skill_file()
        elif path == "/api/skill":
            # Anche /api/skill in GET: il pannello la carica appena si
            # apre e non ha un corpo da mandare. Con la sola rotta
            # POST, il primo caricamento falliva e la sezione restava
            # muta per sempre, perche' nessun pulsante era premuto.
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            self._skill({"azione": (q.get("azione", [""]) or [""])[0]})
        elif path == "/api/state":
            s = self._need_session()
            if s is None:
                return
            snap = s.snapshot()
            snap["ready"] = self.app.ready
            snap["error"] = self.app.error
            snap["version"] = __version__
            snap["model"] = self.app.env.get("ORCHESTRA_MODEL", "")
            snap["provider"] = self.app.env.get("ORCHESTRA_PROVIDER", "")
            self._json(snap)
        elif path == "/api/stream":
            self._sse()
        elif path == "/api/models":
            self._models()
        elif path == "/api/bench/status":
            self._json({
                "running": self.app._bench["running"],
                "log": self.app._bench["log"][-60:],
                "result": self.app._bench["result"],
                "models": self.app._bench.get("models", []),
            })
        elif path == "/api/prior":
                # Copertura del prior esterno. Non e' il benchmark: e' un
                # parere. Darlo per primo evita di fidarsi di numeri che
                # descrivono un'altra harness.
                try:
                    from . import prior as prior_mod
                    priors, msg = prior_mod.scarica()
                    self._json({"messaggio": msg,
                                "copertura": prior_mod.copertura(priors, self.app.catalog.models)})
                except Exception as e:  # noqa: BLE001
                    self._json({"messaggio": f"prior non disponibile: {e}", "copertura": {}})
        elif path == "/api/modelli":
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
        elif path == "/api/chiavi":
            # Solo stato, mai valori. La chiave non esce mai da qui:
            # questa risposta finisce nella cronologia del browser e
            # in qualunque log in mezzo.
            from . import keys as keys_mod
            from .providers import NO_KEY_PROVIDERS
            cat_ = self.app.catalog
            # Niente motori locali qui: sono una richiesta di rete a
            # localhost che puo' costare un timeout, e le chiavi non
            # devono aspettarle. Vengono in /api/locali, che il browser
            # chiede per conto suo.
            self._json({
                "chiavi": keys_mod.stato(ENV_PATH, self.app.env),
                "servizi_gratis": keys_mod.FREE_SERVICES,
                "nota_gratis": keys_mod.NOTA_FREE,
                "catalogo": {
                    "modelli": len(cat_.models) if cat_ is not None else 0,
                    "gratuiti": len(cat_.free()) if cat_ is not None else 0,
                },
                "motori": sorted(NO_KEY_PROVIDERS),
                "provider": self.app.env.get("ORCHESTRA_PROVIDER", ""),
            })
        elif path == "/api/locali":
            # Separato perche' e' lento per costruzione: si interrogano
            # motori in ascolto su localhost e una porta chiusa puo'
            # costare un timeout. In parallelo, non in fila.
            from .providers import NO_KEY_PROVIDERS, local_models_multi
            trovati = local_models_multi(sorted(NO_KEY_PROVIDERS),
                                         self.app.env, timeout=1.2)
            self._json({"locali": {k: [m["id"] for m in v]
                                   for k, v in trovati.items() if v}})
        elif path == "/api/categorie":
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
        elif path == "/api/capabilities":
            cat = self.app.catalog
            if cat is None:
                self._json({"error": getattr(self.app, "_catalog_error", "catalogo non disponibile")}, 503)
                return
            # solo i punteggi misurati: "non lo so" non si trasforma in uno
            # zero, altrimenti la UI mostrerebbe una tabella piena di
            # modelli con 0.00 che non sono misurati ma sconosciuti
            self._json({"measured": {mid: p.scores for mid, p in cat.models.items() if p.scores}})
        else:
            self._json({"error": "non trovato"}, 404)

    def _models(self) -> None:
        """Elenco modelli con i punteggi misurati, per il selettore."""
        cat = self.app.catalog
        if cat is None:
            self._json({"error": getattr(self.app, "_catalog_error", "catalogo non disponibile")}, 503)
            return
        current = self.app.env.get("ORCHESTRA_MODEL", "")
        # il numero unico calcolato sui puntezzi SALVATI, cosi' la web UI
        # lo mostra anche a un giorno dal benchmark. Senza, la colonna
        # compariva solo durante il benchmark e poi spariva — e una
        # colonna che va e viene non serve a scegliere niente.
        try:
            from .punteggio import da_catalogo
            unici = (da_catalogo(cat.models) or {}).get("modelli") or {}
        except Exception:  # noqa: BLE001
            unici = {}
        out = []
        for p in sorted(cat.with_tools(), key=lambda x: x.info.id):
            out.append({
                "id": p.info.id,
                "short": p.info.short,
                "free": p.info.is_free,
                "context": p.info.context_length,
                "prompt_price": p.info.prompt_price,
                "scores": p.scores,
                # la base: quante volte passato e su quanti, per
                # categoria. Senza, la percentuale da sola nasconde se
                # un 50% sta su due test o su venti.
                "passi": getattr(p, "frazioni", {}),
                "task_per_cat": getattr(p, "task_per_cat", {}),
                "livelli": getattr(p, "livelli", {}),
                # il numero unico: ogni categoria pesa uguale, il
                # livello dentro la categoria conta di piu', e le
                # poche prove vengono dichiarate come poche.
                "punteggio_unico": unici.get(p.info.id),
                "current": p.info.id == current,
                # Dichiarato dal provider, o appreso da un 400 reale.
                # None vuol dire che il provider non lo dice: non e' un
                # "no", e la UI lo mostra come tale invece di fingere
                # certezze. Su uno sconosciuto non si fa affidamento,
                # ma non si nasconde nemmeno.
                "tool_calling": p.info.supports_tools,
            })
        ignoti = 0
        if cat is not None:
            # un catalogo finto o un wrapper non ha per forza questo
            # metodo: l'assenza non e' un errore, e' "non lo so", che
            # e' gia' un terzo esito
            conta = getattr(cat, "ignoti_sui_tool", None)
            if callable(conta):
                ignoti = len(conta())
        self._json({"models": out, "current": current,
                    "provider": self.app.env.get("ORCHESTRA_PROVIDER"),
                    "tool_calling_ignoti": ignoti})

    def _sse(self) -> None:
        """Stream degli eventi, formato SSE.

        Formato: `data: <json>\n\n`. Teniamo la connessione aperta e
        mandiamo un commento vuoto come keepalive: senza, il browser chiude
        dopo qualche decina di secondi.
        """
        s = self._need_session()
        if s is None:
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        # assicura che il browser riceva subito gli header
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            # Snapshot iniziale, cosi' la UI non parte vuota dopo un reload.
            # Deve avere un `seq` come tutti gli altri eventi: un client che
            # riconnette e chiede "riprendi dal seq N" altrimenti trova un
            # evento senza seq e non sa dove si era interrotto.
            self._sse_send({
                "seq": 0,
                "kind": "snapshot",
                "data": s.snapshot(),
                "ts": time.time(),
            })
            for item in s.bridge.stream(timeout=10.0):
                if item["kind"] == "keepalive":
                    self.wfile.write(b": ping\n\n")
                else:
                    self._sse_send(item)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            # il browser ha chiuso: normale, non e' un errore da loggare
            pass

    def _svuota_allegati(self) -> None:
        """Butta gli allegati in attesa.

        Dopo un messaggio inviato non valgono piu': senza questo,
        premendo Invio due volte la stessa foto parte due volte, e
        l'utente che riceve due risposte identiche pensa a un bug.
        """
        # getattr e non self.app._registro_allegati: questo server puo'
        # essere costruito senza passare da __init__ (lo fa un test, e
        # lo faceva anche create() prima che lo sistemassi), e allora
        # l'attributo non c'e'. Un invio che cade perche' manca un
        # dizionario vuoto e' il caso peggiore: non c'e' niente da
        # salvare, e pero' l'utente perde il messaggio.
        registro = getattr(self.app, "_registro_allegati", None)
        if registro is not None:
            registro.clear()

    def _registra(self, a: Any) -> str:
        """Memorizza un allegato e gli da' un id.

        L'id e' quello che viaggia a /api/send. Il file no: e' gia' qui,
        e rimandarlo significa fare due volte un viaggio di 12 MB.
        """
        import uuid
        ident = "al-" + uuid.uuid4().hex[:16]
        # Stessa difesa di sopra: un registro che non esiste viene
        # creato, non e' un errore. Caricare un file non puo' fallire
        # perche' manca un contenitore.
        if not hasattr(self.app, "_registro_allegati"):
            self.app._registro_allegati = {}
        self.app._registro_allegati[ident] = a
        return ident

    def _skill_file(self) -> None:
        """Il testo di una skill, per aprirla dal pannello.

        Il percorso che arriva e' relativo alla radice delle skill, non
        assoluto, e viene risolto dentro quella radice. Il motivo e'
        che questo endpoint non ha autenticazione e gira su localhost:
        accettare un percorso qualunque sarebbe una porta aperta verso
        il disco, e per leggere un file di testo non serve.

        Si passa per l'indice, che sa dove sta ogni skill: il nome e'
        l'unica cosa che arriva dal browser.
        """
        try:
            import orchestra.skills as sk
        except Exception:
            self._json({"error": "modulo skill non disponibile"}, 503)
            return
        nome = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query).get("nome", [""])[0]
        s = sk.Indice().get(nome)
        if not s:
            self._json({"error": f"nessuna skill chiamata {nome!r}"}, 404)
            return
        try:
            testo = open(s.percorso, encoding="utf-8").read()
        except OSError as e:
            self._json({"error": f"non riesco a leggere: {e}"}, 500)
            return
        # Anche i file che stanno dentro la skill: senza, "Apri"
        # mostrerebbe una procedura che rimanda a documenti che
        # restano irraggiungibili.
        allegati = []
        cartella = os.path.dirname(s.percorso)
        for dp, _dirs, files in os.walk(cartella):
            for f in files:
                if f == "SKILL.md" or f.endswith(".json"):
                    continue
                rel = os.path.relpath(os.path.join(dp, f), cartella)
                try:
                    allegati.append({
                        "nome": rel.replace(os.sep, "/"),
                        "testo": open(os.path.join(dp, f),
                                      encoding="utf-8", errors="replace").read(),
                    })
                except OSError:
                    continue
        self._json({"nome": s.nome, "contenuto": testo, "allegati": allegati})

    def _skill(self, body: dict[str, Any]) -> None:
        """Le skill: elenco, importazione, cancellazione.

        Tre cose in una rotta e non tre rotte perche' sono tre operazioni
        sulla stessa lista, e una schermata sola che le fa. Il motivo
        per cui stanno nel backend e non solo in JS e' che l'indice
        vive sul disco: il browser puo' mostrare quello che dice il
        server, ma non puo' decidere cosa esiste — altrimenti la lista
        a schermo e quella che l'agente vede possono divergere, e
        quella che conta e' la seconda.
        """
        try:
            import orchestra.skills as sk
        except Exception as e:
            self._json({"error": f"modulo skill non disponibile: {e}"}, 503)
            return
        azione = str(body.get("azione") or "elenca")
        indice = sk.Indice()

        if azione == "elenca":
            # Anche il cestino, sempre. Il frontend non lo ricava e non
            # lo ricava a parte: il primo caricamento del pannello
            # deve poter dire "3 da recuperare" senza una seconda
            # richiesta, e ogni risposta deve poterlo aggiornare senza
            # sapere quale azione sia stata.
            d = _skill_elenco(indice)
            d["cestino"] = _cestino_elenco(indice.radice)
            self._json(d)
            return

        if azione == "importa":
            cartella = str(body.get("cartella") or "").strip()
            if not cartella:
                self._json({"error": "serve la cartella dello store"}, 400)
                return
            n, nomi = indice.importa(cartella,
                                     categoria=str(body.get("categoria") or ""))
            # La lista dei nomi torna intera: con 103 skill, mostrare
            # i primi dodici e dire "altre 91" costringerebbe a
            # riaprire il pannello per contarle.
            self._json({"ok": True, "importate": n, "nomi": nomi,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "cestino":
            self._json({"ok": True, "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "ripristina":
            nome = str(body.get("nome") or "").strip()
            ok, perche = _skill_ripristina(indice, nome)
            if not ok:
                self._json({"error": perche}, 400)
                return
            self._json({"ok": True, "ripristinata": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "cancella_definitivo":
            nome = str(body.get("nome") or "").strip()
            ok, perche = _cestino_rimuovi(indice.radice, nome)
            if not ok:
                self._json({"error": perche}, 400)
                return
            self._json({"ok": True, "rimossa": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "svuota_cestino":
            n, errore = _cestino_svuota(indice.radice)
            if errore:
                self._json({"error": errore}, 500)
                return
            # Il cestino si rilegge invece di dichiararsi vuoto: se lo
            # svuotamento e' andato a meta' perche' c'era un file che
            # non si poteva toccare, una risposta che dice [] mente, e
            # l'utente crede di aver perso roba che invece c'e' ancora.
            self._json({"ok": True, "rimosse": n,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "cancella":
            nome = str(body.get("nome") or "").strip()
            rimosso = _skill_cancella(indice, nome)
            if not rimosso:
                self._json({"error": f"nessuna skill chiamata {nome!r}, "
                                     f"o non si puo' cancellare"}, 400)
                return
            # Il cestino torna qui e non in una richiesta separata:
            # e' l'azione che lo cambia, quindi e' la risposta che deve
            # dirti com'e' diventato.
            self._json({"ok": True, "rimossa": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        self._json({"error": f"azione sconosciuta: {azione}"}, 400)

    def _dal_registro(self, ids: list) -> tuple[list, str]:
        """Gli allegati gia' preparati, presi dal registro.

        Il file attraversa la rete UNA volta, a /api/allega, dove
        viene validato e si impara quanto costa. A /api/send arrivano
        solo gli id.

        Prima il browser mandava i data URL due volte: una per il
        conto, una per l'invio. Un file da 12 MB viaggiava 32 MB, e il
        secondo passaggio faceva fallire l'invio con "Failed to
        fetch" — un errore che sembra di rete e che invece era la
        nostra stessa richiesta, di nuovo troppo grande.
        """
        out = []
        for ident in ids:
            if not isinstance(ident, str):
                return [], "allegato non valido"
            if ident in self.app._registro_allegati:
                out.append(self.app._registro_allegati[ident])
                continue
            return [], ("questo allegato e' scaduto: rimettilo. "
                       "Gli allegati si tengono per un messaggio.")
        return out, ""

    def _prepara_allegati(self, dati: list) -> tuple[list, str]:
        """Quello che il browser ha mandato, diventa lista di Attachment.

        Il browser manda data URL, non file: rileggere il disco a ogni
        richiesta costerebbe un file da 12 MB in un JSON, che e' una
        richiesta che si rompe. Il base64 qui e' gia' fatto.

        Un solo percorso di validazione, lo stesso che fa `allega()` su
        un file vero: magic number, PDF con testo letto come testo, tetto
        sulle pagine. Se l'allegato dal browser passasse da un controllo
        che il file non fa, avremmo due porte con due regole diverse.
        """
        from .attachments import LIMITE_MB, allega
        import base64

        out: list = []
        for item in dati:
            nome = (item.get("nome") or "allegato").strip() or "allegato"
            url = item.get("data_url") or ""
            if "," not in url or not url.startswith("data:"):
                return [], f"{nome}: allegato malformato"
            # base64.b64decode, NON unquote_to_bytes: quest'ultimo
            # convertsce gli escape URL e lascia il base64 come testo.
            # Il risultato e' un "file" che inizia con i caratteri
            # iVBORw0 e non con la firma PNG — e il rifiuto dice
            # "formato non riconosciuto", che sembra un file corrotto
            # invece di un errore di decodifica.
            try:
                grezzo = base64.b64decode(url.split(",", 1)[1], validate=True)
            except Exception:  # noqa: BLE001
                return [], f"{nome}: base64 non valido"
            if len(grezzo) > LIMITE_MB * 1024 * 1024:
                return [], (f"{nome}: troppo grande, il limite e' "
                            f"{LIMITE_MB} MB")
            try:
                out.append(allega(nome, grezzo))
            except ValueError as e:   # AttachmentError
                return [], str(e)
        return out, ""

    def _allega(self, s: Any, body: dict[str, Any]) -> None:
        """POST /api/allega: dice subito quanto costeranno.

        Si manda il file PRIMA del messaggio, e si risponde con il conto
        in token. Un allegato da 12 MB diventa una richiesta da 40.000
        token: se lo scopri dalla risposta, e' troppo tardi e sembra un
        errore. Prima si sa, e si puo' dire "sono in troppi".

        Se il modello non legge le immagini si dice e si rifiuta. Non e'
        un dettaglio: un modello senza visione su una foto risponde con
        confidenza inventata, e quella la scopri quando hai gia' scritto
        il sito con i dati sbagliati.
        """
        allegati, problema = self._prepara_allegati(body.get("files") or [])
        if problema:
            self._json({"error": problema}, 400)
            return
        if s.busy:
            self._json({"error": "l'agente sta lavorando: aspetta la fine "
                                 "del turno o annulla"}, 409)
            return
        if any(a.immagini for a in allegati):
            cat = self.app.catalog
            modello = self.app.env.get("ORCHESTRA_MODEL", "")
            profilo = cat.models.get(modello) if cat is not None else None
            if profilo is not None and profilo.info.supports_vision is False:
                self._json({
                    "error": f"{modello} non legge le immagini. "
                             f"Cambia modello dal menu in alto, o allega "
                             f"un file di testo.",
                    "serve_visione": True,
                }, 400)
                return
        # Una sola risposta. Prima ce n'erano due in sequenza nella stessa
        # funzione: la vecchia, con "token_stimati", e quella nuova con
        # gli id. Il server rispondeva e poi ritornava — e restava la
        # prima, che non aveva gli id. Il frontend leggeva una risposta
        # senza id e non lo capiva: l'allegato restava "carico..."
        # per sempre e l'invio non sapeva a cosa riferirsi.
        self._json({
            "ok": True,
            "id": [self._registra(a) for a in allegati],
            "allegati": [{"nome": a.nome, "kind": a.kind,
                          "immagini": len(a.immagini),
                          "token": a.token_stimati} for a in allegati],
            "token": sum(a.token_stimati for a in allegati),
        })

    def _sse_send(self, item: dict[str, Any]) -> None:
        payload = json.dumps(item, default=str)
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))

    # -- POST --------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        s = self._need_session()
        if s is None:
            return
        try:
            # /api/allega e' l'unica rotta che puo' ricevere un file:
            # solo li si permette un corpo grande. Su /api/send il
            # tetto resta quello dei prompt, e gli allegati che vi
            # arrivano hanno gia' passato i controlli.
            body = self._body(per_allegato=(path == "/api/allega"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return

        if path == "/api/allega":
            self._allega(s, body)
        elif path == "/api/send":
            text = (body.get("text") or "").strip()
            allegati, problema = self._dal_registro(
                body.get("allegati") or [])
            if problema:
                self._json({"error": problema}, 400)
                return
            if not text and not allegati:
                self._json({"error": "messaggio vuoto"}, 400)
                return
            ok = s.send(text, allegati)
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
        elif path == "/api/cancel":
            self._json({"ok": s.cancel()})
        elif path == "/api/reset":
            try:
                s.reset()
                self._json({"ok": True})
            except RuntimeError as e:
                self._json({"error": str(e)}, 409)
        elif path == "/api/system":
            prompt = (body.get("prompt") or "").strip()
            if not prompt:
                self._json({"error": "prompt vuoto"}, 400)
                return
            s.set_system_prompt(prompt)
            self._json({"ok": True})
        elif path == "/api/model":
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
            self._json({"ok": True, "model": model_id})
        elif path == "/api/bench":
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
        elif path == "/api/permesso/prova":
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
            def _prova_thread() -> None:
                # passa da chiedi_all_utente con l'id che gia' conosciamo:
                # e' l'unico percorso che registra la domanda in attesa,
                # ed e' quello che usa davvero un tool. Chiamando chiedi a
                # mano si verificherebbe meta' del canale.
                try:
                    gate.chiedi_all_utente(r.percorso, r.azione, r.dettaglio,
                                           richiesta_id=r.id)
                except Exception as e:  # noqa: BLE001
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
                        "in_attesa": in_atting})
        elif path == "/api/permesso":
            # La risposta a una domanda di permesso. Tre scelte, e
            # nient'altro: "una_volta", "sessione", "mai". Una scelta
            # sconosciuta viene trattata come "mai" — se il pulsante non
            # e' arrivato, il caso sicuro e' negare.
            rid = (body.get("id") or "").strip()
            scelta = (body.get("scelta") or "mai").strip()
            if not rid:
                self._json({"error": "manca l'id della richiesta"}, 400)
                return
            if scelta not in ("una_volta", "sessione", "mai"):
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
        elif path == "/api/skill/file":
            self._skill_file()
        elif path == "/api/skill":
            self._skill(body)
        elif path == "/api/permessi":
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
        elif path == "/api/provider":
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
        elif path == "/api/chiavi":
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
            self._json({"ok": True, "messaggio": msg,
                        "chiavi": keys_mod.stato(ENV_PATH, self.app.env)})
        elif path == "/api/prova":
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
        else:
            self._json({"error": "non trovato"}, 404)
def _skill_elenco(indice) -> dict[str, Any]:
    """Le skill, raggruppate per origine e per categoria.

    Il raggruppamento non e' decorativo: sono due domande diverse che
    ti fa. "Cosa posso scaricare" e "cosa ha imparato l'agente" non
    hanno la stessa affidabilita' — le seconde sono affermazioni
    dello stesso agente che le ha prodotte, e portano con se' le
    prove perche' tu possa controllarle. Mischiate in un'unica lista
    non sapresti quale sia quale.
    """
    tutte = indice.tutte()
    scaricate = [s for s in tutte if s.origine != "generata"]
    generate = [s for s in tutte if s.origine == "generata"]

    def voce(s) -> dict[str, Any]:
        return {
            "nome": s.nome,
            "descrizione": s.descrizione,
            "categoria": s.categoria,
            "origine": s.origine,
            "prove": len(s.prove),
            "con_prove": s.con_prove,
            "usata": s.volte_usata,
            "caratteri": len(s.corpo),
            # Il percorso arriva per poterlo aprire, ma relativo alla
            # radice: un percorso assoluto nel payload finisce nella
            # pagina, e la pagina non deve dire dove sta il disco.
            "percorso": os.path.relpath(s.percorso, indice.radice),
        }

    categorie: dict[str, int] = {}
    for s in scaricate:
        categorie[s.categoria or "generale"] = \
            categorie.get(s.categoria or "generale", 0) + 1

    return {
        # Anche se _skill() lo aggiunge, qui il campo c'e' sempre: una
        # risposta che a volte ha il cestino e a volte no costringe il
        # frontend a controllare prima di leggere.
        "cestino": [],
        "totale": len(tutte),
        "scaricate": len(scaricate),
        "generate": len(generate),
        "categorie": [{"nome": k, "skill": v}
                      for k, v in sorted(categorie.items())],
        "lista_scaricate": [voce(s) for s in scaricate],
        "lista_generate": [voce(s) for s in generate],
        # Quante entrerebbero nel prompt se il contesto non ci fosse:
        # e' il numero che dice se il prompt e' oggi una riga sola o
        # venti, e cambia da solo quando importi.
        "nel_prompt_max": len(_nel_prompt(indice)),
    }


def _nel_prompt(indice) -> list[str]:
    """I nomi che entrerebbero nel prompt senza contesto.

    Il limite alto serve a capire se oggi stai guardando tre skill o
    ventiquattro: e' il numero che ti dice quanto costa un import,
    e lo dice prima e non dopo.

    La lista si riconosce dalla forma della riga — due spazi, un
    segno facoltativo, poi "nome: descrizione" — e non dal numero
    esatto di spazi. Con quello il parser contava zero righe quando
    l'indentazione cambiava, e il numero tornava 0 senza che nulla
    dicesse perche'. Era gia' successo con i selettori CSS.
    """
    import re
    import orchestra.skills as sk
    p = indice.prompt("", limite=sk.MAX_NEL_PROMPT)
    riga = re.compile(r"^\s{2,}[+\- ]\s+([A-Za-z0-9._-]+):\s")
    return [m.group(1) for m in (riga.match(l) for l in p.splitlines()) if m]


def _cestino_elenco(radice: str) -> list[dict[str, Any]]:
    """Cosa c'e' nel cestino.

    Senza questo, cancellare una skill e' un atto cieco: la UI dice
    "nel cestino" e non c'e' modo di vederlo ne' di recuperarlo. Il
    rischio non e' la perdita di un file, e' che l'utente smette di
    fidarsi del pulsante perche' non sa dove vanno le cose.

    Il nome resta quello della skill, non quello della cartella: e' il
    nome che l'utente conosce, e quello che gli serve per recuperarla.
    """
    import time
    base = os.path.join(radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return []
    fuori = []
    for ts in sorted(os.listdir(base), reverse=True):
        dentro = os.path.join(base, ts)
        if not os.path.isdir(dentro):
            continue
        try:
            quando = int(ts)
        except ValueError:
            quando = 0
        for nome in os.listdir(dentro):
            fuori.append({
                "nome": nome,
                "quando": quando,
                "data": time.strftime("%Y-%m-%d %H:%M",
                                      time.localtime(quando)) if quando else "?",
                "generata": os.path.isdir(
                    os.path.join(dentro, nome, ".generata")),
            })
    return fuori


def _skill_ripristina(indice, nome: str) -> tuple[bool, str]:
    """Rimette una skill dov'era.

    Torna nella sua categoria e nella sua origine, lette dal
    frontmatter: senza, la skill finirebbe sotto "generale" e perderebbe
    la distinzione tra scaricata e generata — che e' la cosa che conta
    quando poi la guardi dal pannello.

    Se una copia e' gia' attiva, la sovrascrive invece di rifiutare.
    Il rifiuto era un difetto: cancellare, rimettere, cancellare
    lascia piu' copie nel cestino, e il secondo ripristino si fermava
    con "gia' presente" mentre la skill che avevi rimosso tu era
    ancora li' — l'utente leggeva un errore dove aveva solo fatto le
    cose che gli avevi detto di fare.
    """
    import shutil
    import time
    import orchestra.skills as _sk
    base = os.path.join(indice.radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return False, "il cestino e' vuoto"
    candidati = []
    for ts in sorted(os.listdir(base), reverse=True):
        dentro = os.path.join(base, ts, nome)
        if os.path.isdir(dentro):
            candidati.append(dentro)
    if not candidati:
        return False, f"nel cestino non c'e' {nome!r}"
    sorgente = candidati[0]

    campi, _corpo = _sk._leggi(os.path.join(sorgente, "SKILL.md"))
    origine = campi.get("origine") or "scaricata"
    cartella = (_sk.CARTELLA_GENERATE if origine == "generata"
                else _sk.CARTELLA_SCARICATE)

    # La categoria e' il percorso RELATIVO alla radice delle skill, non
    # il percorso fino alla cartella. Il frontmatter la contiene gia',
    # ma puo' essere di una versione vecchia che scriveva il percorso
    # intero: leggendola cosi' e usando quella, rimettere due volte la
    # stessa skill produceva generale/giro-due/giro-due/giro-due, e la
    # copia attiva finiva dentro se stessa.
    #
    # Si taglia l'ultimo livello se coincide col nome della skill: e il
    # caso esattamente della copia annidata, e non ci si arriva per
    #logica, si arriva guardando cosa c'era su disco.
    parts = [p for p in (campi.get("categoria") or "generale").split("/")
             if p not in ("", ".", "..", os.sep)]
    while parts and parts[-1] == nome:
        parts.pop()
    if not parts:
        parts = ["generale"]
    categoria = parts
    dest = os.path.join(indice.radice, cartella, *categoria, nome)

    # La copia attiva, se c'e', va nel cestino invece di essere
    # sovrapposta: cosi' non si perde, e il cestino resta la sola
    # copia che il pulsante "cancella tutto" raggiunge.
    if os.path.isdir(dest):
        vecchia = os.path.join(base, str(int(time.time())))
        os.makedirs(vecchia, exist_ok=True)
        try:
            shutil.move(dest, os.path.join(vecchia, nome))
        except OSError as e:
            return False, f"non riesco a liberare il posto: {e}"

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        shutil.move(sorgente, dest)
    except OSError as e:
        return False, f"non riesco a rimetterla: {e}"
    indice._invalida()
    return True, ""


def _cestino_rimuovi(radice: str, nome: str) -> tuple[bool, str]:
    """Cancella una voce dal cestino, per sempre.

    Una voce sola. "Svuota tutto" e' un pulsante separato con una
    conferma separata: mettere le due cose insieme fa perdere roba
    che si voleva tenere. Cancellare dal cestino e' irreversibile, e
    il pulsante deve dirlo.
    """
    import shutil
    base = os.path.join(radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return False, "il cestino e' vuoto"
    for ts in sorted(os.listdir(base), reverse=True):
        dentro = os.path.join(base, ts, nome)
        if os.path.isdir(dentro):
            shutil.rmtree(dentro, ignore_errors=True)
            # svuota anche i timestamp rimasti vuoti, se sono vuoti
            tsdir = os.path.join(base, ts)
            try:
                if not os.listdir(tsdir):
                    os.rmdir(tsdir)
            except OSError:
                pass
            return True, ""
    return False, f"nel cestino non c'e' {nome!r}"


def _cestino_svuota(radice: str) -> tuple[int, str]:
    """Cancella davvero tutto quello che c'e' nel cestino."""
    import shutil
    base = os.path.join(radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return 0, ""
    n = 0
    try:
        for ts in os.listdir(base):
            dentro = os.path.join(base, ts)
            if os.path.isdir(dentro):
                n += len(os.listdir(dentro))
            shutil.rmtree(dentro, ignore_errors=True)
        os.rmdir(base)
    except OSError as e:
        return n, f"svuotato a meta': {e}"
    return n, ""


def _skill_cancella(indice, nome: str) -> bool:
    """Cancella una skill, mettendola nel cestino.

    Mette i file in una cartella `.cestino` accanto alle skill, non
    dentro la cartella della skill: messo dentro, sparisce dall'indice
    insieme al suo stesso cestino, e non si trova piu' da nessuna
    parte. Il sintomo era "la cancellazione funziona e la skill non c'e'
    piu'", che non dice che anche i file sono andati via con lei.

    Una skill cancellata per sbaglio non si ricostruisce, e se era
    scaricata l'unico modo per recuperarla e' un reimport di cento
    file. Il cestino e' una riga, e lo svuoto con un comando quando
    voglio davvero.
    """
    import shutil
    import time
    s = indice.get(nome)
    if not s:
        return False
    cartella = os.path.dirname(s.percorso)
    cestino = os.path.join(indice.radice, CARTELLA_CESTINO,
                           str(int(time.time())))
    os.makedirs(cestino, exist_ok=True)
    try:
        shutil.move(cartella, os.path.join(cestino, nome))
    except OSError:
        return False
    indice._invalida()
    return True


def serve(host: str = "127.0.0.1", port: int = 8737, *, open_browser: bool = True) -> None:
    app = OrchestraApp.create()
    Handler.app = app

    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"ATTENZIONE: ascolto su {host}, non su localhost.", file=sys.stderr)
        print("Il server non ha autenticazione: chi lo raggiunge puo' usare le "
              "tue chiavi API. Serve solo per test locali.", file=sys.stderr)
        # senza terminale non c'e' nessuno che possa confermare: rifiutiamo
        if not (sys.stdin and sys.stdin.isatty()):
            raise SystemExit("rifiuto di esporre fuori da localhost in modo non interattivo")
        if input("Continuo? [s/N] ").strip().lower() != "s":
            raise SystemExit("annullato")

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True

    url = f"http://{host}:{port}"
    print(f"\n  Orchestra {__version__}  ->  {url}\n")
    if not app.ready:
        print(f"  ATTENZIONE: {app.error}")
        print(f"  Configura orchestra/.env, poi riavvia.\n")
    else:
        print(f"  modello: {app.env.get('ORCHESTRA_MODEL')} "
              f"({app.env.get('ORCHESTRA_PROVIDER')})")
        print(f"  Ctrl+C per fermare\n")

    if open_browser and app.ready:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  fermo.")
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    serve()
