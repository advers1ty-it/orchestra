"""I gestori delle rotte HTTP.

Ogni metodo qui e' una rotta, dichiarata dal decoratore `@rotta` accanto al
codice che la serve: percorso, metodo e gestore in un punto solo. Lo
dispatch e il 404/405 stanno in `webapp.Handler._instrada`; la tabella in
`rotte.py`.

Perche' un mixin e non un modulo di funzioni: i gestori usano gli helper del
Handler (`_json`, `_need_session`, `_registra`) e devono restare metodi.
`Handler` eredita da questa classe, quindi per il resto del codice sono
metodi suoi come prima. La differenza e' che ora si possono leggere — e
spostare per dominio — senza attraversare il server.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
from typing import Any

from . import __version__
from .percorsi import ENV_PATH
from .providers import load_env
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


CARTELLA_CESTINO = ".cestino"


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


class Rotte:
    # -- Rotte GET: dalla tabella, una per gestore ------------------------
    @rotta("GET", "/api/skill/file")
    def _r_get_skill_file(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        # Anche in GET: il pulsante "Apri" e' una lettura, non una
        # scrittura. Registrarle solo fra i POST faceva rispondere
        # 404 a una richiesta che il browser faceva in GET — e il
        # sintomo era "il pulsante non fa niente", che non dice
        # nulla del motivo.
        self._skill_file()

    @rotta("GET", "/api/skill")
    def _r_get_skill(self, path: str, body: dict[str, Any],
                     s: Any) -> None:
        # Anche /api/skill in GET: il pannello la carica appena si
        # apre e non ha un corpo da mandare. Con la sola rotta
        # POST, il primo caricamento falliva e la sezione restava
        # muta per sempre, perche' nessun pulsante era premuto.
        q = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query)
        self._skill({"azione": (q.get("azione", [""]) or [""])[0]})

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

    @rotta("GET", "/api/stt/status")
    def _r_get_stt_status(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        from . import stt as _stt
        self._json(_stt.stato())

    @rotta("GET", "/api/remote/info")
    def _r_get_remote_info(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        self._json(self._info_remoto())

    @rotta("GET", "/api/remote/status")
    def _r_get_remote_status(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        self._json(self._api_remote_status({}))

    @rotta("GET", "/api/tracce")
    def _r_get_tracce(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        # Le tracce recenti: la diagnosi dopo il fatto. "Perché quel
        # task ha sbagliato" senza doverlo ripetere. I filtri sono
        # nella query e vengono applicati alla query SQL, non dopo:
        # un turno fallito di ieri non deve sparire dietro cinquanta
        # turni riusciti di oggi.
        import urllib.parse as _up

        from .traccia import ultime

        q = _up.parse_qs(_up.urlparse(self.path).query)
        esito = ((q.get("esito") or [""])[0] or "").strip() or None
        solo_errori = ((q.get("errori") or [""])[0] or "").strip() \
            in ("1", "true", "si", "sì")
        try:
            limite = int((q.get("limite") or ["50"])[0])
        except (TypeError, ValueError):
            limite = 50
        self._json({"tracce": ultime(limite=limite, esito=esito,
                                      solo_errori=solo_errori)})

    @rotta("GET", "/api/riepilogo")
    def _r_get_riepilogo(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        # L'ultimo riepilogo di turno: esito, file, token, costo.
        from . import riepilogo

        self._json({"riepilogo": riepilogo.ultimo()})

    @rotta("GET", "/api/diff")
    def _r_get_diff(self, path: str, body: dict[str, Any],
                    s: Any) -> None:
        # Le modifiche del turno in corso, con le righe cambiate.
        # Il confine lo segna l'Agent a inizio turno; qui si legge e
        # si calcola il diff al momento della richiesta, cosi' la
        # vista mostra lo stato vero del file, non quello di meta'
        # turno.
        from . import checkpoint

        self._json({"modifiche": checkpoint.modifiche_turno()})

    @rotta("GET", "/api/routing")
    def _r_get_routing(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        # Stato dell'instradamento automatico (il POST sta in do_POST).
        if self.app.session is None:
            self._json({"error": "nessuna sessione"}, 409)
            return
        self._json({"routing": bool(
            getattr(self.app.session, "_routing_attivo", False))})

    @rotta("GET", "/api/tracce/{id}")
    def _r_get_tracce_id(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        try:
            tid = int(path.rsplit("/", 1)[-1])
        except ValueError:
            self._json({"error": "id non valido"}, 400)
            return
        from .traccia import apri
        t = apri(tid)
        if t is None:
            self._json({"error": "traccia non trovata"}, 404)
            return
        self._json(t)

    @rotta("GET", "/api/storico")
    def _r_get_storico(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        # In GET perche' e' una lettura: il pannello lo carica da
        # solo quando si apre. Registrata solo fra i POST rispondeva
        # 404 a una richiesta che il browser faceva in GET -- e il
        # sintomo era "il pannello resta vuoto", che non dice niente
        # del motivo.
        try:
            elenco = (self.app._storico.elenco(limite=200)
                      if self.app._storico else [])
            self._json({
                "sessioni": elenco,
                "attiva": getattr(self.app.session, "_sessione_id", None),
            })
        except Exception as e:
            self._json({"error": str(e)}, 500)


    @rotta("GET", "/api/memoria")
    def _r_get_memoria(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        from .memoria import stato as stato_memoria
        fuori = stato_memoria()
        # Le statistiche dell'indice: quanti fatti sono morti. Sono il
        # motivo per cui l'indice esiste — non la velocità, che è
        # rumore, ma sapere cosa non serve più.
        try:
            from .memoria_indice import indice_memoria
            st = indice_memoria().statistiche()
            fuori["indice"] = {
                "totale": st["totale"],
                "mai_usati": st["mai_usati"],
                "in_scadenza": [x["testo"] for x in st["in_scadenza"]],
                "piu_usati": st["piu_usati"],
                "byte_file": st["byte_file"],
            }
        except Exception as e:
            fuori["indice"] = {"errore": str(e)}
        self._json(fuori)


    @rotta("GET", "/api/capacita")
    def _r_get_capacita(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # Skill e tool insieme, normalizzati. Due tab nella stessa
        # pagina, ma due moduli diversi: il frontend non deve saperlo.
        fuori: dict[str, Any] = {"skill": [], "tool": []}
        try:
            import orchestra.skills as sk
            d = _skill_elenco(sk.Indice())
            if d and not d.get("error"):
                lista = list(d.get("lista_scaricate") or [])
                lista += list(d.get("lista_generate") or [])
                for s in lista:
                    if not isinstance(s, dict):
                        continue
                    fuori["skill"].append({
                        "nome": s.get("nome", ""),
                        "descrizione": s.get("descrizione", ""),
                        "categoria": s.get("categoria", ""),
                        "tipo": "skill",
                    })
        except Exception:
            # Le skill non sono un requisito: senza, la pagina
            # mostra la tab dei tool e non una pagina vuota.
            pass
        try:
            for tool in (self.app.session.registry.active or []):
                fuori["tool"].append({
                    "nome": getattr(tool, "name", ""),
                    "descrizione": getattr(tool, "description", "") or "",
                    "categoria": "strumento",
                    "tipo": "tool",
                })
        except Exception:
            pass
        self._json(fuori)


    @rotta("GET", "/api/stream")
    def _r_get_stream(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        self._sse()

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

    @rotta("GET", "/api/goal/status")
    def _r_get_goal_status(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        import urllib.parse as _up
        parsed = _up.urlparse(self.path)
        gid = (_up.parse_qs(parsed.query).get("id") or [None])[0]
        from . import goal as goal_mod
        if gid:
            g = goal_mod.get(gid)
            if not g:
                self._json({"error": "goal sconosciuto"}, 404)
            else:
                self._json(g)
        else:
            self._json({"goals": goal_mod.list_goals()})

    @rotta("GET", "/api/goal/ready")
    def _r_get_goal_ready(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        from . import goal as goal_mod
        pronti = [g for g in goal_mod.list_goals()
                  if not goal_mod.motivo_non_pronto(g)]
        self._json({"pronti": pronti})

    @rotta("GET", "/api/scheduler/status")
    def _r_get_scheduler_status(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from . import goal as goal_mod
        self._json(goal_mod.scheduler_status())

    @rotta("GET", "/api/cron/jobs")
    def _r_get_cron_jobs(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        from . import cron as cron_mod
        self._json({"jobs": cron_mod.list_jobs()})

    @rotta("GET", "/api/cron/scheduler/status")
    def _r_get_cron_scheduler_status(self, path: str, body: dict[str, Any],
                                     s: Any) -> None:
        from . import cron as cron_mod
        self._json(cron_mod.scheduler_status())

    @rotta("GET", "/api/autostart/status")
    def _r_get_autostart_status(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from . import autostart as as_mod
        self._json({"disponibile": as_mod.disponibile(),
                    "attivo": as_mod.stato()})

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
            "context_limit": (self.app.session.agent.config.context_limit
                              if self.app.session is not None else 120000),
            })

    @rotta("GET", "/api/progetti")
    def _r_get_progetti(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # L'elenco dei progetti registrati, e quale e' attivo.
        # Va in GET e non in POST perche' e' una lettura, e la UI
        # lo chiede all'avvio per riempire la lista.
        self._json({"ok": True,
                    "progetti": self.app._elenco_progetti(),
                    "attivo": self.app._progetto_attivo()})

    @rotta("GET", "/api/identita")
    def _r_get_identita(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # Nome e persona dell'agente principale. Sta accanto a /api/bots
        # perche' il menu in testa ha bisogno di entrambi per dire chi
        # sta parlando quando non c'e' un bot attivo.
        self._json({"ok": True, **self.app.identita()})

    @rotta("GET", "/api/bots")
    def _r_get_bots(self, path: str, body: dict[str, Any],
                    s: Any) -> None:
        # I bot salvati, chi e' attivo, e i valori che servono al form
        # (provider validi, progetti registrati). Una lettura sola per
        # disegnare tutto il pannello: due richieste per una schermata
        # che si apre di rado sono due occasioni di restare a meta'.
        try:
            from .providers import KNOWN_PROVIDERS

            self._json({
                "ok": True,
                "bots": self.app.elenco_bot(),
                "attivo": self.app.bot_attivo(),
                # Il nome dell'agente principale serve al menu in
                # testa: senza, dopo averlo personalizzato il menu
                # continuerebbe a dire "agente principale".
                "principale": self.app.identita(),
                "providers": sorted(KNOWN_PROVIDERS),
                "progetti": [p.get("nome") for p in self.app._elenco_progetti()],
            })
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    @rotta("GET", "/api/lavori")
    def _r_get_lavori(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        # La coda durevole, in sola lettura. Il pannello Bot legge il
        # riassunto dentro /api/bots; questa rotta serve a chi vuole
        # vedere i singoli lavori (e ai test del motore).
        from . import lavori as lavori_mod
        import urllib.parse as _up

        # `urlparse` e non `split("?", 1)[1]`: la rotta deve
        # rispondere anche senza query, altrimenti un client che la
        # chiama “nuda” prende un IndexError invece dell'elenco.
        query = _up.parse_qs(_up.urlparse(self.path).query)
        tipo = (query.get("tipo") or [""])[0].strip() or None
        chiave = (query.get("chiave") or [""])[0].strip() or None
        try:
            limite = int((query.get("limite") or ["50"])[0])
        except (TypeError, ValueError):
            limite = 50
        self._json({"ok": True,
                    "lavori": lavori_mod.elenca(
                        tipo=tipo, chiave=chiave, limite=limite)})

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


    # -- Rotte POST: dalla tabella, una per gestore ------------------------
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

    @rotta("POST", "/api/remote/start")
    def _r_post_remote_start(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        self._json(self._api_remote_start(body))

    @rotta("POST", "/api/remote/stop")
    def _r_post_remote_stop(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        self._json(self._api_remote_stop(body))

    @rotta("POST", "/api/remote/status")
    def _r_post_remote_status(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        self._json(self._api_remote_status(body))

    @rotta("POST", "/api/remote/info")
    def _r_post_remote_info(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        self._json(self._info_remoto())

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

    @rotta("POST", "/api/storico")
    def _r_post_storico(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # Elenco delle conversazioni. Solo GET: la lista si scrive
        # da sola a fine turno, non c'e' niente da mandare.
        try:
            elenco = self.app._storico.elenco(limite=200) if self.app._storico else []
            self._json({
                "sessioni": elenco,
                "attiva": getattr(self.app.session, "_sessione_id", None),
            })
        except Exception as e:
            self._json({"error": str(e)}, 500)


    @rotta("POST", "/api/storico/cerca")
    def _r_post_storico_cerca(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        # Ricerca full-text nelle conversazioni passate. `sessioni` è
        # sempre presente, vuoto se non c'è query: la UI distingue
        # "sto cercando" da "sto guardando la lista".
        storico_db = self.app._storico
        q = (body.get("query") or "").strip()
        fuori: dict[str, Any] = {"query": q, "risultati": [], "sessioni": []}
        if q and storico_db is not None:
            try:
                fuori["risultati"] = storico_db.cerca(
                    q, limite=int(body.get("limite") or 30))
            except Exception as e:
                self._json({"error": str(e)}, 500)
                return
        else:
            try:
                fuori["sessioni"] = (storico_db.elenco(limite=200)
                                     if storico_db else [])
                fuori["attiva"] = getattr(self.app.session,
                                          "_sessione_id", None)
            except Exception as e:
                self._json({"error": str(e)}, 500)
                return
        self._json(fuori)


    @rotta("POST", "/api/storico/apri")
    def _r_post_storico_apri(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        # Apre una conversazione: sostituisce lo stato, non lo
        # accoda. 409 se il turno precedente sta ancora girando.
        try:
            sid = int(body.get("id"))
        except (TypeError, ValueError):
            self._json({"error": "id mancante o non valido"}, 400)
            return
        # Una conversazione appartiene all'identita' che l'ha scritta.
        # Caricarla in un'altra sessione la farebbe continuare dal bot
        # sbagliato, e il salvataggio successivo la lascerebbe col nome
        # del primo bot ma col contenuto del secondo: un misto che non
        # si puo' piu' separare.
        try:
            riga = self.app._storico.sessione(sid) if self.app._storico else None
            proprietario = str((riga or {}).get("bot") or "")
            if riga is not None \
                    and proprietario != (self.app.session.bot or ""):
                nome = proprietario or "l'agente principale"
                self._json({"error": f"questa conversazione appartiene a "
                                    f"{nome}: attivalo prima di aprirla"}, 409)
                return
            ok = self.app.session.carica_sessione(sid)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        if not ok:
            self._json({"error": "sessione non trovata"}, 404)
            return
        self._json({"ok": True, "snapshot": self.app.session.snapshot()})


    @rotta("POST", "/api/storico/elimina")
    def _r_post_storico_elimina(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        try:
            sid = int(body.get("id"))
        except (TypeError, ValueError):
            self._json({"error": "id mancante o non valido"}, 400)
            return
        attiva = getattr(self.app.session, "_sessione_id", None)
        if self.app._storico is not None:
            self.app._storico.elimina(sid)
        # Se era quella aperta, si riparte da una vuota: lasciarla
        # significherebbe scrivere su una riga che non esiste piu'.
        #
        # ATTENZIONE — qui cascava in un loop: crearne SUBITO una nuova
        # faceva ricomparire una riga in lista, la si eliminava, e lui
        # ne rifaceva un'altra, all'infinito. La sessione attiva NON
        # deve esistere per forza: se elimini l'ultima conversazione,
        # la lista resta vuota. La riga su cui scrivere la si creerà
        # al PROSSIMO messaggio, non adesso — `_salva_su_disco` lo fa
        # già quando serve davvero.
        if sid == attiva:
            self.app.session.reset()
            self.app.session._sessione_id = None
        self._json({"ok": True, "snapshot": self.app.session.snapshot()})


    @rotta("POST", "/api/storico/nuova")
    def _r_post_storico_nuova(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        # Nuova conversazione, senza toccare le vecchie.
        try:
            self.app.session.reset()
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json({"ok": True, "snapshot": self.app.session.snapshot()})


    @rotta("POST", "/api/memoria/cerca")
    def _r_post_memoria_cerca(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        # Ricerca FTS5 dalla UI. `conta_usi=False`: cercare per
        # controllare non vuol dire che il facto serva, e contarlo
        # inquinerebbe la statistica che dice cosa è morto.
        from .tools.memoria import memoria as mem
        from .memoria import stato as stato_memoria
        q = (body.get("query") or "").strip()
        progetto = (body.get("progetto") or "").strip()
        m = mem()
        fuori: dict[str, Any] = {"query": q, "progetto": progetto}
        try:
            righe = m.cerca(q, limite=int(body.get("limite") or 20),
                            conta_usi=False, progetto=progetto)
            fuori["risultati"] = [
                {"testo": r["testo"], "usi": r["usi"],
                 "importante": bool(r["importante"]),
                 "progetto": r.get("progetto", "")} for r in righe]
            st = m.statistiche()
            fuori["indice"] = {"totale": st["totale"],
                               "mai_usati": st["mai_usati"],
                               "byte_file": st["byte_file"]}
        except Exception:
            # il backend a file non ha `cerca`: si torna al filtro per
            # sottostringa, che è quello che faceva prima dell'indice
            if progetto:
                tutti = m.fatti_per_progetto(progetto)
            else:
                tutti = m.fatti() + m.importanti()
            ql = q.lower()
            fuori["risultati"] = [
                {"testo": f, "usi": 0, "importante": f in m.importanti(),
                 "progetto": progetto} for f in tutti if ql in f.lower()][:20]
            fuori["nota"] = "ricerca per sottostringa (indice non disponibile)"
        fuori.update(stato_memoria())
        self._json(fuori)


    @rotta("POST", "/api/memoria/aggiungi")
    def _r_post_memoria_aggiungi(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        # Aggiunge un fatto a mano, dalla barra laterale.
        #
        # Il progetto arriva dal corpo; se manca, si usa quello
        # attivo. Cosi un fatto scritto a mano mentre si lavora sul
        # sito ristorante finisce col suo etichetta senza che
        # l'utente debba ripeterlo ogni volta.
        from .memoria import memoria
        fatto = (body.get("fatto") or "").strip()
        if not fatto:
            self._json({"error": "fatto vuoto"}, 400)
            return
        progetto = (body.get("progetto")
                    or getattr(self.app.session, "progetto", "") or "").strip()
        nuovo = memoria().aggiungi(fatto, origine="manuale",
                                   progetto=progetto)
        from .memoria import stato as stato_memoria
        self._json({"ok": True, "nuovo": nuovo, **stato_memoria()})

    @rotta("POST", "/api/memoria")
    def _r_post_memoria(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        from .memoria import stato as stato_memoria
        self._json(stato_memoria())


    @rotta("POST", "/api/identita")
    def _r_post_identita(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        try:
            dati = self.app.salva_identita(
                body.get("nome") or "", body.get("persona") or "")
        except (OSError, ValueError) as e:
            self._json({"error": f"identita' non salvata: {e}"}, 400)
            return
        self._json({"ok": True, **dati})

    @rotta("POST", "/api/bots/crea")
    def _r_post_bots_crea(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        campi = {k: body.get(k) for k in
                 ("nome", "provider", "modello", "persona", "progetto",
                  "profilo", "parla_con", "policy") if k in body}
        try:
            b = self.app.crea_bot(**campi)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        self._json({"ok": True, "bot": b})

    @rotta("POST", "/api/bots/attiva")
    def _r_post_bots_attiva(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        try:
            risultato = self.app.attiva_bot(body.get("id"))
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        self._json(risultato)

    @rotta("POST", "/api/bots/aggiorna")
    def _r_post_bots_aggiorna(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        campi = {k: body.get(k) for k in
                 ("nome", "provider", "modello", "persona", "progetto",
                  "profilo", "parla_con", "policy") if k in body}
        try:
            b = self.app.aggiorna_bot(body.get("id"), **campi)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        if b is None:
            self._json({"error": "bot inesistente"}, 404)
            return
        self._json({"ok": True, "bot": b})

    @rotta("POST", "/api/bots/elimina")
    def _r_post_bots_elimina(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        try:
            fatto = self.app.elimina_bot(body.get("id"))
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        if not fatto:
            self._json({"error": "bot inesistente"}, 404)
            return
        self._json({"ok": True})

    @rotta("POST", "/api/bots/avvia")
    def _r_post_bots_avvia(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        # Un compito in background, senza cambiare l'identita' attiva.
        try:
            risultato = self.app.avvia_lavoro_bot(
                body.get("id"), body.get("testo") or "")
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        self._json(risultato)

    @rotta("POST", "/api/lavori/unisci")
    def _r_post_lavori_unisci(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        try:
            risultato = self.app.unisci_lavoro(body.get("id"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json(risultato)

    @rotta("POST", "/api/lavori/scarta")
    def _r_post_lavori_scarta(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        try:
            risultato = self.app.scarta_checkout_lavoro(body.get("id"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json(risultato)

    @rotta("POST", "/api/lavori/riprova")
    def _r_post_lavori_riprova(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        try:
            lavoro = self.app.riprova_lavoro(body.get("id"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json({"ok": True, "lavoro": lavoro})

    @rotta("POST", "/api/lavori/annulla")
    def _r_post_lavori_annulla(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        try:
            lavoro = self.app.annulla_lavoro(body.get("id"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json({"ok": True, "lavoro": lavoro})

    @rotta("POST", "/api/progetto")
    def _r_post_progetto(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        # POST {progetto: nome}: imposta il progetto attivo.
        # La risposta porta anche i progetti conosciuti (per il
        # datalist) e quanti fatti ne ha: e' quello che il campo
        # mostra sotto, e senza l'utente non sa se il progetto
        # esiste davvero o e' solo una parola.
        # Lettura vs scrittura: una POST senza la chiave "progetto"
        # (il frontend la manda vuota per rileggere lo stato) NON
        # deve cambiare il progetto attivo. Se la trattassimo come
        # "progetto = ''" azzereremmo il progetto a ogni refresh
        # della sidebar — ed e' esattamente il bug che faceva restare
        # la sidebar su "nessun progetto" anche dopo il riconoscimento
        # automatico.
        scrive = "progetto" in body and body.get("progetto") is not None
        if scrive:
            nome = str((body.get("progetto") or "")).strip()
            try:
                from . import progetti as _pr
                if nome and not _pr.percorso_di(nome):
                    return self._json({"error":
                                       f"progetto sconosciuto: {nome}"}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 400)
        else:
            nome = self.app._progetto_attivo()
        if self.app.session is None:
            return self._json({"error": "nessuna sessione"}, 409)
        if scrive:
            try:
                self.app.session.imposta_progetto(nome)
                if nome:
                    from . import progetti as _pr
                    _pr.tocca(nome)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 400)
        n_fatti = 0
        try:
            from .memoria import memoria
            n_fatti = len(memoria().fatti_per_progetto(nome))
        except Exception:  # noqa: BLE001
            n_fatti = 0
        return self._json({
            "ok": True,
            "attivo": nome,
            "n_fatti": n_fatti,
            # QUI i progetti sono NOMI, non dizionari: e' la lista
            # per il datalist del campo, che vuole stringhe. Il
            # GET /api/progetti invece restituisce i dizionari
            # interi, perche' li disegna. Due forme per lo stesso
            # campo, ma su due endpoint diversi — e i due consumatori
            # sono diversi.
            "progetti": [p.get("nome") for p in self.app._elenco_progetti()],
        })


    @rotta("POST", "/api/memoria/modifica")
    def _r_post_memoria_modifica(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        from .memoria import memoria
        vecchio = (body.get("vecchio") or "").strip()
        nuovo_testo = (body.get("nuovo") or "").strip()
        if not vecchio or not nuovo_testo:
            self._json({"error": "vecchio o nuovo vuoto"}, 400)
            return
        fatto = memoria().modifica(vecchio, nuovo_testo)
        from .memoria import stato as stato_memoria
        self._json({"ok": True, "modificato": fatto, **stato_memoria()})


    @rotta("POST", "/api/memoria/elimina")
    def _r_post_memoria_elimina(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from .memoria import memoria
        fatto = (body.get("fatto") or "").strip()
        if not fatto:
            self._json({"error": "fatto vuoto"}, 400)
            return
        tolto = memoria().elimina(fatto)
        from .memoria import stato as stato_memoria
        self._json({"ok": True, "tolto": tolto, **stato_memoria()})


    @rotta("POST", "/api/memoria/ottimizza")
    def _r_post_memoria_ottimizza(self, path: str, body: dict[str, Any],
                                  s: Any) -> None:
        dry_run = body.get("dry_run", True)
        giorni = int(body.get("giorni_grazia") or 30)
        progetto = (body.get("progetto")
                    or getattr(self.app.session, "progetto", "") or "").strip()
        unisci = bool(body.get("unisci", False))
        from .tools.memoria import memoria as mem
        m = mem()
        ott = getattr(m, "ottimizza_memoria", None)
        if not callable(ott):
            self._json({"error": "indice non disponibile"}, 400)
            return
        provider = None
        if unisci:
            try:
                provider = getattr(self.app.session.agent, "provider", None)
            except Exception:
                provider = None
        res = ott(provider=provider, dry_run=bool(dry_run),
                  giorni_grazia=giorni, progetto=progetto,
                  unisci=unisci and provider is not None)
        from .memoria import stato as stato_memoria
        res.update(stato_memoria())
        self._json(res)


    @rotta("POST", "/api/progetti/registra")
    def _r_post_progetti_registra(self, path: str, body: dict[str, Any],
                                  s: Any) -> None:
        self._json(self.app._api_progetti_registra(body))

    @rotta("POST", "/api/progetti/elimina")
    def _r_post_progetti_elimina(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        self._json(self.app._api_progetti_elimina(body))

    @rotta("POST", "/api/progetti/file")
    def _r_post_progetti_file(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        self._json(self.app._api_progetti_file(body))

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
        self._json({"ok": True, "routing": bool(
            getattr(self.app.session, "_routing_attivo", False))})

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

    @rotta("POST", "/api/skill/file")
    def _r_post_skill_file(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        self._skill_file()

    @rotta("POST", "/api/skill")
    def _r_post_skill(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        self._skill(body)

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

    @rotta("POST", "/api/goal/start")
    def _r_post_goal_start(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        objective = (body.get("objective") or "").strip() if isinstance(body, dict) else ""
        if not objective:
            self._json({"error": "objective richiesto"}, 400)
            return
        profile = (body.get("profile") or "auto").strip() if isinstance(body, dict) else "auto"
        max_iters = 60
        max_attempts = 1
        priority = 0
        not_before = None
        criteri = None
        recovery = None
        depends_on = None
        parent_id = None
        kind = "goal"
        consenti_parziale = False
        if isinstance(body, dict):
            try:
                max_iters = int(body.get("max_iterations") or 60)
                max_attempts = int(body.get("max_attempts") or 1)
                priority = int(body.get("priority") or 0)
            except (TypeError, ValueError):
                max_iters = 60
                max_attempts = 1
                priority = 0
            try:
                if body.get("not_before") is not None:
                    not_before = float(body.get("not_before"))
            except (TypeError, ValueError):
                not_before = None
            depends_on = body.get("depends_on")
            parent_id = (body.get("parent_id") or None)
            kind = (body.get("kind") or "goal")
            consenti_parziale = bool(body.get("consenti_parziale"))
            criteri = body.get("criteri")
            recovery = body.get("recovery")
        from . import goal as goal_mod
        try:
            gid = goal_mod.start_goal(
                objective, env=self.app.env, profile=profile,
                max_iterations=max_iters, parent_id=parent_id,
                depends_on=depends_on, priority=priority,
                not_before=not_before, kind=kind,
                max_attempts=max_attempts,
                consenti_parziale=consenti_parziale,
                criteri=criteri, recovery=recovery)
        except (RuntimeError, ValueError) as e:
            self._json({"error": f"goal non avviato: {e}"}, 409)
            return
        self._json({"ok": True, "id": gid})
        return

    @rotta("POST", "/api/goal/run-next")
    def _r_post_goal_run_next(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        from . import goal as goal_mod
        try:
            g = goal_mod.accoda_prossimo(env=self.app.env)
        except (RuntimeError, ValueError) as e:
            self._json({"error": f"scheduler: {e}"}, 409)
            return
        if not g:
            self._json({"ok": False, "error": "nessun goal pronto"})
            return
        self._json({"ok": True, "id": g.get("id")})
        return

    @rotta("POST", "/api/scheduler/start")
    def _r_post_scheduler_start(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        interval = 5.0
        if isinstance(body, dict) and body.get("interval") is not None:
            try:
                interval = float(body.get("interval"))
            except (TypeError, ValueError):
                interval = 5.0
        from . import goal as goal_mod
        ok = goal_mod.scheduler_start(env=self.app.env, interval=interval)
        if not ok:
            self._json({"ok": False, "error": "scheduler gia' attivo"})
            return
        self._json({"ok": True})
        return

    @rotta("POST", "/api/scheduler/stop")
    def _r_post_scheduler_stop(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        from . import goal as goal_mod
        goal_mod.scheduler_stop()
        self._json({"ok": True})
        return

    @rotta("POST", "/api/cron/create")
    def _r_post_cron_create(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import cron as cron_mod
        try:
            nome = (body.get("nome") or "").strip() if isinstance(body, dict) else ""
            schedule = (body.get("schedule") or "").strip() if isinstance(body, dict) else ""
            action_type = (body.get("action_type") or "goal").strip() if isinstance(body, dict) else "goal"
            if action_type == "shell":
                action = {"command": (body.get("command") or "").strip() if isinstance(body, dict) else ""}
            else:
                action = {
                    "objective": (body.get("objective") or "").strip() if isinstance(body, dict) else "",
                    "profile": (body.get("profile") or "auto").strip() if isinstance(body, dict) else "auto",
                }
            enabled = True
            if isinstance(body, dict) and body.get("enabled") is not None:
                enabled = bool(body.get("enabled"))
            job = cron_mod.crea(nome, schedule, action_type, action, enabled=enabled)
        except (ValueError, RuntimeError) as e:
            self._json({"error": str(e)}, 400)
            return
        self._json({"ok": True, "job": job})
        return

    @rotta("POST", "/api/cron/update")
    def _r_post_cron_update(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import cron as cron_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        if not jid:
            self._json({"error": "id richiesto"}, 400)
            return
        campi = {}
        if isinstance(body, dict):
            if body.get("nome") is not None:
                campi["nome"] = body.get("nome")
            if body.get("schedule") is not None:
                campi["schedule"] = body.get("schedule")
            if body.get("action_type") is not None:
                campi["action_type"] = body.get("action_type")
            if body.get("enabled") is not None:
                campi["enabled"] = bool(body.get("enabled"))
            if body.get("objective") is not None or body.get("command") is not None:
                at = body.get("action_type") or "goal"
                if at == "shell":
                    campi["action"] = {"command": (body.get("command") or "").strip()}
                else:
                    campi["action"] = {"objective": (body.get("objective") or "").strip(),
                                       "profile": (body.get("profile") or "auto").strip()}
        try:
            job = cron_mod.aggiorna(jid, **campi)
        except (ValueError, RuntimeError) as e:
            self._json({"error": str(e)}, 400)
            return
        if job is None:
            self._json({"error": "job sconosciuto"}, 404)
            return
        self._json({"ok": True, "job": job})
        return

    @rotta("POST", "/api/cron/delete")
    def _r_post_cron_delete(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import cron as cron_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        ok = cron_mod.elimina(str(jid or ""))
        self._json({"ok": ok})
        return

    @rotta("POST", "/api/cron/run")
    def _r_post_cron_run(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        from . import cron as cron_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        r = cron_mod.esegui_job(str(jid or ""), env=self.app.env)
        self._json(r)
        return

    @rotta("POST", "/api/cron/scheduler/start")
    def _r_post_cron_scheduler_start(self, path: str, body: dict[str, Any],
                                     s: Any) -> None:
        from . import cron as cron_mod
        interval = 30.0
        if isinstance(body, dict) and body.get("interval") is not None:
            try:
                interval = float(body.get("interval"))
            except (TypeError, ValueError):
                interval = 30.0
        ok = cron_mod.scheduler_start(env=self.app.env, interval=interval)
        self._json({"ok": True} if ok else {"ok": False, "error": "gia' attivo"})
        return

    @rotta("POST", "/api/cron/scheduler/stop")
    def _r_post_cron_scheduler_stop(self, path: str, body: dict[str, Any],
                                    s: Any) -> None:
        from . import cron as cron_mod
        cron_mod.scheduler_stop()
        self._json({"ok": True})
        return

    @rotta("POST", "/api/mcp/servers")
    def _r_post_mcp_servers(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import mcp as mcp_mod
        self._json({"servers": mcp_mod.list_servers()})
        return

    @rotta("POST", "/api/mcp/tools")
    def _r_post_mcp_tools(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        from . import mcp as mcp_mod
        self._json({"tools": mcp_mod.list_tools()})
        return

    @rotta("POST", "/api/mcp/status")
    def _r_post_mcp_status(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        from . import mcp as mcp_mod
        self._json(mcp_mod.stato())
        return

    @rotta("POST", "/api/mcp/resources")
    def _r_post_mcp_resources(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        # Risorse e prompt sono parte del protocollo, non solo i tool:
        # la UI li mostra accanto ai tool dello stesso server.
        from . import mcp as mcp_mod
        self._json({"resources": mcp_mod.list_resources()})
        return

    @rotta("POST", "/api/mcp/prompts")
    def _r_post_mcp_prompts(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import mcp as mcp_mod
        self._json({"prompts": mcp_mod.list_prompts()})
        return

    @rotta("POST", "/api/mcp/add")
    def _r_post_mcp_add(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        from . import mcp as mcp_mod
        cfg = body if isinstance(body, dict) else {}
        c = mcp_mod.add_server(cfg)
        self._json({"ok": True, "server": c})
        return

    @rotta("POST", "/api/mcp/delete")
    def _r_post_mcp_delete(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        from . import mcp as mcp_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        ok = mcp_mod.remove_server(str(jid or ""))
        self._json({"ok": ok})
        return

    @rotta("POST", "/api/mcp/connect")
    def _r_post_mcp_connect(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import mcp as mcp_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        r = mcp_mod.connect(str(jid or ""))
        self._json(r)
        return

    @rotta("POST", "/api/mcp/disconnect")
    def _r_post_mcp_disconnect(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        from . import mcp as mcp_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        ok = mcp_mod.disconnect(str(jid or ""))
        self._json({"ok": ok})
        return

    @rotta("POST", "/api/mcp/connect_all")
    def _r_post_mcp_connect_all(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from . import mcp as mcp_mod
        r = mcp_mod.connect_all()
        self._json({"results": r})
        return

    @rotta("POST", "/api/autostart/enable")
    def _r_post_autostart_enable(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        from . import autostart as as_mod
        ok = as_mod.abilita()
        self._json({"ok": ok, "attivo": as_mod.stato()})
        return

    @rotta("POST", "/api/autostart/disable")
    def _r_post_autostart_disable(self, path: str, body: dict[str, Any],
                                  s: Any) -> None:
        from . import autostart as as_mod
        ok = as_mod.disabilita()
        self._json({"ok": ok, "attivo": as_mod.stato()})
        return

    @rotta("POST", "/api/goal/stop")
    def _r_post_goal_stop(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        gid = (body.get("id") if isinstance(body, dict) else None)
        from . import goal as goal_mod
        ok = goal_mod.cancel(str(gid or ""))
        self._json({"ok": ok})
        return

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
