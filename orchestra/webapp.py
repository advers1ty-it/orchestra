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

import hmac
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import shutil

from . import __version__
from .agent import LoopConfig
from .percorsi import ENV_PATH, HERE
from .prompt_figlio import PROMPT_FIGLIO
from .providers import (ProviderError, ambiente, build_provider,
                         load_env)
from .rotte import ROTTE
from .session import Session
from .tools import SYSTEM_PROMPT, default_registry
from .webapp_rotte import Rotte

REMOTE_STATE_PATH = os.path.join(HERE, ".remote_state.json")

# Quanti minuti un catalogo puo' invecchiare prima di essere
# ricaricato. Non e' un dettaglio: senza, un modello che esce
# dal provider resta nel menu fino al riavvio.
CATALOGO_TTL_SECONDS = 15 * 60

UI_PATH = os.path.join(HERE, "web", "index.html")


def _prompt_base_con_memoria() -> str:
    """Il prompt di sistema senza identita', con le cose sempre vere.

    Sta fuori dalla classe perche' serve sia a costruire una sessione sia
    ad aggiornare l'identita' di una sessione viva: nel secondo caso non
    si puo' ricostruire tutto (si perderebbe la conversazione), quindi il
    punto di partenza va ricomposto allo stesso modo.
    """
    from .istruzioni_progetto import blocco_prompt as blocco_progetto
    from .tools.memoria import blocco_prompt

    prompt = SYSTEM_PROMPT
    # Le istruzioni del repository (AGENTS.md, CLAUDE.md, ...) stanno tra
    # le regole e i fatti personali: sono piu' specifiche delle regole
    # generali, ma non possono sovrascriverle.
    istruzioni = blocco_progetto()
    if istruzioni:
        prompt = f"{prompt}\n\n{istruzioni}"
    importanti = blocco_prompt()
    if importanti:
        prompt = (
            f"{prompt}\n\n"
            f"---\n"
            f"Cose che valgono in ogni conversazione. Non ripeterle "
            f"se non servono. Per tutto il resto hai il tool "
            f"`memoria`: cerca quello che ti serve invece di "
            f"assumere di non saperlo.\n\n"
            f"{importanti}")
    return prompt


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


def _log_telegram(messaggio: str) -> None:
    """Un ponte Telegram che si lamenta, senza far cadere niente.

    Su stderr come il resto del server: se Telegram non risponde, chi
    guarda il log deve poterlo capire senza aprire il pannello.
    """
    print(f"[telegram] {messaggio}", file=sys.stderr, flush=True)


def _coda(testo: str, quanti: int) -> str:
    """La fine di un testo, senza tagliare una parola a meta'.

    Il messaggio di stato mostra quello che l'agente sta scrivendo
    adesso: la testa di un discorso lungo e' proprio la parte vecchia,
    quella che non serve piu'.
    """
    testo = (testo or "").strip()
    if len(testo) <= quanti:
        return testo
    tagliato = testo[-quanti:]
    spazio = tagliato.find(" ")
    if 0 <= spazio < 40:
        tagliato = tagliato[spazio + 1:]
    return "..." + tagliato.lstrip()


# Quanti modelli in una pagina del modulo a bottoni. Otto stanno in
# uno schermo di telefono senza scorrere, e ogni pagina in piu' e' un
# tocco: con cinquanta modelli per pagina il "cerca" non si userebbe
# mai e la lista sarebbe illeggibile.
MODELLI_PER_PAGINA = 8

# Quanti modelli entrano nel menu. Un catalogo come quello di Nous ne ha
# 354: a otto per pagina sono quarantacinque pagine, cioe' un menu che
# nessuno scorre fino in fondo. Il menu mostra i piu' utili e per il
# resto c'e' la ricerca per nome, che e' l'unica cosa che scala.
MENU_MASSIMO = 40


def _scegli_modello(scelta: str, modelli: list[str]) -> tuple[str, str]:
    """Trova il modello che l'utente ha nominato, o spiega perche' no.

    Torna (id, errore): uno dei due e' vuoto. Chi scrive da un telefono
    non ha una lista da toccare, quindi si accetta anche un pezzo del
    nome — ma solo se ne resta uno, perche' indovinare fra due modelli
    che si somigliano e' peggio che chiedere di essere piu' precisi.
    """
    scelta = (scelta or "").strip()
    if not scelta:
        return "", "Uso: /modello <nome>."
    if not modelli:
        # Senza catalogo non c'e' niente contro cui controllare: si
        # accetta, e chi chiama dice che non e' stato verificato.
        return scelta, ""
    if scelta in modelli:
        return scelta, ""
    basso = scelta.lower()
    esatti = [m for m in modelli if m.lower() == basso]
    if len(esatti) == 1:
        return esatti[0], ""
    parziali = [m for m in modelli if basso in m.lower()]
    if len(parziali) == 1:
        return parziali[0], ""
    if len(parziali) > 1:
        return "", (f"Piu' di un modello contiene «{scelta}»: "
                     + ", ".join(parziali[:10])
                     + ". Scrivi il nome per intero.")
    return "", (f"Nessun modello di questo provider si chiama «{scelta}». "
                 "Qualcuno: " + ", ".join(modelli[:10]) + ".")


class OrchestraApp:
    """Lo stato del server, condiviso fra i thread.

    ThreadingHTTPServer crea un thread per richiesta, quindi tutto quello
    che tocciamo qui deve essere o immutabile o protetto. La Session ha gia'
    i propri lock; questo oggetto contiene solo la sessione.
    """

    def __init__(self, env: dict[str, str], session: Session | None = None,
                 remoto_attivo: bool = False) -> None:
        self.env = env
        self.remoto_attivo = bool(remoto_attivo)
        self.tunnel_url = ""
        # token per accesso remoto (generato al primo avvio remoto e
        # salvato in .env come ORCHESTRA_REMOTE_TOKEN)
        self.token_remoto = self._token_remoto()
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
        self.session = None
        sess_err = ""
        try:
            self.session = session if session is not None else self._make_session(
                env.get("ORCHESTRA_PROVIDER", "openrouter"),
                env.get("ORCHESTRA_MODEL", ""),
            )
        except (ProviderError, KeyError, Exception) as _e:
            self.session = None
            sess_err = str(_e)
        # I bot: identita' persistenti con una sessione ciascuna. Il
        # dizionario si riempie a richiesta, non all'avvio: un bot che non
        # usi non deve costare una sessione in memoria, un provider e un
        # prompt. `_sessione_principale` e' l'agente configurato in
        # Opzioni, quello che c'era prima dei bot: si conserva perche'
        # attivare un bot non deve distruggerlo, e disattivarlo deve
        # riportare la conversazione di prima esattamente com'era.
        self._bots_runtime: dict[int, dict[str, Any]] = {}
        self._bot_attivo_id: int = 0
        self._sessione_principale: Session | None = None
        # I lavori in background dei bot. Non sono il turno attivo: sono
        # code separate, una per bot, con un filo che le consuma. E' il
        # pezzo che permette a due bot di avanzare insieme — la sessione
        # attiva resta una sola, e la UI non deve seguire due stream.
        #
        # La coda vive in SQLite (`lavori.py`), non in questo dizionario:
        # qui restano solo i fili, che sono un dettaglio del processo e
        # devono sparire con lui. La verita' e' su disco.
        self._bots_fili: dict[int, threading.Thread] = {}
        self._bots_fili_lock = threading.RLock()
        # Lo storico. La sessione appena creata non ha ancora un id: o è
        # nuova, o deve caricare l'ultima conversazione da disco.
        #
        # Senza questo il salvataggio è morto — `_salva_su_disco` esce
        # subito se `_sessione_id` è None, ed è lì che si vede se il
        # pezzo è agganciato o è solo un modulo che funziona da solo.
        self._storico: Any = None
        self._aggancia_storico()
        self.delega_attiva = False
        self.ready = self.session is not None
        self.error = sess_err if self.session is None else ""
        # Gate dei permessi: l'unico posto dove l'utente puo' autorizzare
        # un accesso fuori dalla cartella di lavoro. Vive sull'app perche'
        # deve sopravvivere fra una richiesta e l'altra: il tool che
        # chiede gira in un thread, la risposta arriva su un altro.
        self.gate = self._make_gate()
        # La delega. `_collega_delega` costruisce la fabbrica del
        # figlio e registra il tool: senza, l'agente non ha modo di
        # chiedere un lavoro circoscritto. Va fatto qui, e non in un
        # secondo momento, perche' il figlio eredita anche il
        # PROGETTO del padre: e' il padre che sa in quale cartella
        # si sta lavorando.
        # il catalogo viene caricato pigramente: `/models` lo chiede, la
        # chat no. Caricarlo all'avvio aggiungerebbe una chiamata di rete a
        # ogni start, anche quando l'utente vuole solo chattare.
        self._catalog: Any = None
        self._catalog_tried = False
        self._catalog_at = None
        self._catalog_error: str = ""
        # stato del benchmark lanciato dalla UI
        self._bench: dict[str, Any] = {"running": False, "log": [],
                                       "result": None, "last_progress": 0.0,
                                       # quanti run sono FINITI. Lo conta
                                       # il server, perche' il log che
                                       # manda al frontend e' troncato:
                                       # contarlo li' dava un numero che
                                       # non poteva superare 60 e sembrava
                                       # un benchmark fermo.
                                       "finiti": 0, "modelli": []}
        # stato del consiglio (Roast Room) lanciato dalla UI
        self._council: dict[str, Any] = {"running": False, "log": [],
                                          "verdict": "", "session_dir": "",
                                          "started": 0.0, "error": "",
                                          "current_round": 0, "current_seat": ""}

    def _token_remoto(self, forza: bool = False) -> str:
        # Token per accesso remoto. Letto da .env; se manca e il modo
        # remoto e' attivo (o forza=True, es. avvio da UI), ne genero uno
        # e lo salvo, poi lo stampo a console.
        tok = (self.env.get("ORCHESTRA_REMOTE_TOKEN")
               or load_env(ENV_PATH).get("ORCHESTRA_REMOTE_TOKEN")
               or "").strip()
        if tok:
            self.env["ORCHESTRA_REMOTE_TOKEN"] = tok
            return tok
        if not (self.remoto_attivo or forza):
            return ""
        import secrets
        tok = secrets.token_urlsafe(24)
        # persisti in .env
        try:
            righe = []
            if os.path.isfile(ENV_PATH):
                with open(ENV_PATH, "r", encoding="utf-8") as f:
                    righe = f.read().splitlines()
            # rimuovi eventuale riga vuota/esistente
            righe = [r for r in righe if not r.strip().startswith("ORCHESTRA_REMOTE_TOKEN=")]
            righe.append(f"ORCHESTRA_REMOTE_TOKEN={tok}")
            with open(ENV_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(righe) + "\n")
        except Exception:
            pass
        self.env["ORCHESTRA_REMOTE_TOKEN"] = tok
        return tok

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
        # Le domande libere (`ask_user`) usano lo stesso bridge ma un
        # registro separato: la risposta e' testo, non una delle quattro
        # scelte di permesso, e mescolarle renderebbe "si'" un permesso.
        from . import domande

        domande.imposta_canale(
            lambda d: self.session.bridge.emit("domanda_utente", d))
        return gate

    def gate_root(self) -> Any:
        from .tools import _root
        return _root()

    def _rotta_progetti(self, percorso: str, corpo: dict[str, Any]) -> dict[str, Any] | None:
        """Le rotte dei progetti. None = non e' una rotta di questo gruppo.

        La sessione e' un pezzo solo: cambiando progetto si cambia
        anche la cartella in cui si scrive, e quindi quello che segue
        l'agente. Per questo l'impostazione del progetto e' su
        `/api/progetto` (la sessione) e non qui: due porte per la
        stessa cosa sarebbero due regole diverse.
        """
        if percorso == "/api/progetti/registra":
            return self._api_progetti_registra(corpo)
        if percorso == "/api/progetti/alias":
            return self._api_progetti_alias(corpo)
        if percorso == "/api/progetti/elimina":
            return self._api_progetti_elimina(corpo)
        if percorso == "/api/progetti/file":
            return self._api_progetti_file(corpo)
        if percorso == "/api/progetti":
            return {"ok": True, "progetti": self._elenco_progetti(),
                    "attivo": self._progetto_attivo()}
        return None

    def _api_progetti_registra(self, corpo: dict[str, Any]) -> dict[str, Any]:
        """Registra (o aggiorna) un progetto."""
        from . import progetti as _pr
        nome = str(corpo.get("nome") or "").strip()
        percorso = str(corpo.get("percorso") or "").strip()
        if not nome or not percorso:
            return {"ok": False, "errore": "nome e percorso sono obbligatori"}
        try:
            _pr.registra(nome, percorso,
                        alias=str(corpo.get("alias") or ""),
                        note=str(corpo.get("note") or ""))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "errore": str(e)}
        return {"ok": True, "progetti": self._elenco_progetti()}

    def _api_progetti_alias(self, corpo: dict[str, Any]) -> dict[str, Any]:
        """Cambia gli alias di un progetto.

        Gli alias sono gli altri nomi dello stesso progetto, in un'altra
        lingua o in un'altra forma. Servono perche' i nomi non si possono
        tradurre da soli: un progetto chiamato "Sito Ristorante" non
        contiene la parola "restaurant", e nessun algoritmo puo' tirare
        a indovinare che sono la stessa cosa.
        """
        from . import progetti as _pr
        nome = str(corpo.get("progetto") or "").strip()
        if not nome:
            return {"ok": False, "errore": "manca il progetto"}
        riga = _pr.per_nome(nome)
        if not riga:
            return {"ok": False, "errore": f"progetto sconosciuto: {nome}"}
        try:
            _pr.registra(riga["nome"], riga["percorso"],
                         note=riga.get("note") or "",
                         alias=str(corpo.get("alias") or ""))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "errore": str(e)}
        return {"ok": True, "alias": _pr.alias_di(riga)}

    def _api_progetti_elimina(self, corpo: dict[str, Any]) -> dict[str, Any]:
        from . import progetti as _pr
        nome = str(corpo.get("nome") or "").strip()
        if not nome:
            return {"ok": False, "errore": "manca il nome"}
        _pr.elimina(nome)
        return {"ok": True, "progetti": self._elenco_progetti()}

    def _api_progetti_file(self, corpo: dict[str, Any]) -> dict[str, Any]:
        """I file toccati, per progetto o tutti."""
        from . import progetti as _pr
        nome = str(corpo.get("progetto") or "").strip()
        try:
            file = _pr.file_toccati(nome)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "errore": str(e)}
        return {"ok": True, "file": file, "progetto": nome}

    def _progetto_attivo(self) -> str:
        """Il nome del progetto attivo, o "" se non c'e'."""
        if self.session is None:
            return ""
        return getattr(self.session, "progetto", "") or ""

    def _elenco_progetti(self) -> list[dict[str, Any]]:
        """I progetti registrati, con il file toccati."""
        from . import progetti as _pr
        out = []
        for p in _pr.tutti():
            item = dict(p)
            item["attivo"] = (str(p.get("nome") or "").lower()
                              == self._progetto_attivo().lower()
                              and bool(self._progetto_attivo()))
            # Gli alias come lista, non come stringa: la colonna e' una
            # stringa separata da virgole, e chi la riceve non deve
            # re-interpretare il formato. Due forme per lo stesso dato
            # sono due cose che possono divergere.
            item["alias"] = _pr.alias_di(p)
            out.append(item)
        return out

    def _carica_catalogo(self, forza: bool) -> Any:
        """Il lavoro vero. La property `catalog` e' il-wrapper.

        Due metodi invece di uno con un parametro, perche' una property
        non accetta argomenti: `catalog(forza=True)` su una property
        solleva TypeError, e l'errore dice solo "non e' un oggetto
        chiamabile" — che non dice nulla su cosa sia andato storto.
        """

        """Catalogo dei modelli, ricaricato quando invecchia.

        PRIMA c'era un flag, `_catalog_tried`, che a true non tornava
        piu' indietro: la prima richiesta scaricava e tutte le altre
        leggevano la stessa copia per sempre. Un modello che esce da
        OpenRouter restava nel menu fino al riavvio del server, e uno
        nuovo non compariva mai senza riavviare.

        Ora la copia invecchia. Quindici minuti sono un compromesso:
        abbastanza corta da non mostrare un catalogo di ieri, abbastanza
        lunga da non scaricare a ogni passaggio fra i pannelli.

        Il ricaricamento NON perde i punteggi: quelli stanno su disco, in
        `load_measurements`, e vengono riapplicati a ogni fetch. Percio'
        un catalogo fresco non e' un catalogo con i numeri azzerati —
        quello sarebbe un difetto che si vede solo al secondo giorno.

        `forza=True` serve al cambio provider e allo switch del
        modello: li' la risposta deve essere quella di adesso.
        """
        import time as _t

        scaduta = ((self._catalog_at is None)
                   or (_t.time() - self._catalog_at > CATALOGO_TTL_SECONDS))
        if forza or scaduta:
            try:
                from .catalog import Catalog

                self._catalog = Catalog.fetch(
                    self.env.get("ORCHESTRA_PROVIDER", "openrouter"))
                self._catalog_at = _t.time()
                self._catalog_tried = True
                self._catalog_error = ""
            except Exception as e:  # noqa: BLE001 - l'UI mostra l'errore
                # Un errore NON cancella il catalogo che c'era gia'.
                # Togliendolo, un provider che per un momento non
                # risponde lascia il menu vuoto e sembra che non ci
                # siano piu' modelli: il peggiore dei due errori, perche'
                # fa sparire informazione vera.
                if not self._catalog_tried:
                    self._catalog = None
                self._catalog_error = str(e)
        return self._catalog

    @property
    def catalog(self) -> Any:
        """Catalogo dei modelli, ricaricato quando invecchia."""
        return self._carica_catalogo(forza=False)

    def catalogo_ora(self) -> Any:
        """Il catalogo ricaricato adesso, scartando la copia invecchiata.

        Lo usa il cambio provider e il cambio modello: li' la risposta
        deve essere quella di adesso, non quella di quindici minuti fa.
        """
        return self._carica_catalogo(forza=True)

    def switch_provider(self, provider_name: str) -> None:
        """Cambia il provider predefinito e ricarica il catalogo.

        Stesso vincolo di switch_model: durante un turno non si cambia,
        o la conversazione si troverebbe a metà fra due provider diversi.
        La chiave deve gia' esistere: cambiare provider non e' un modo
        per aggirare la configurazione, quindi se manca la chiave si
        dice subito e in chiaro.
        """
        if self.session is not None and self.session.busy:
            raise RuntimeError("l'agente sta lavorando: attendi o annulla prima")
        if self.bot_attivo() is not None:
            # Il servizio dell'applicazione e quello del bot sono due
            # cose diverse: cambiare il primo lascerebbe il bot sul
            # provider vecchio e il menu convinto del contrario.
            raise RuntimeError(
                "stai usando un bot: il suo servizio si cambia dal "
                "pannello Opzioni → Bot")

        from .providers import KNOWN_PROVIDERS, NO_KEY_PROVIDERS, base_url_for

        if provider_name not in KNOWN_PROVIDERS:
            raise ValueError(f"provider sconosciuto: {provider_name}")
        key_env = KNOWN_PROVIDERS[provider_name][1]
        chiave_presente = bool(self.env.get(key_env) or load_env(ENV_PATH).get(key_env)) if key_env else True
        if provider_name == "nous" and not chiave_presente:
            # Il collegamento OAuth scrive il JWT in un file separato, non
            # una riga NOUS_API_KEY: se il token esiste, la chiave e' ok.
            try:
                from . import nous_auth as _nous_auth
                token, _base = _nous_auth.get_nous_credentials(self.env)
                chiave_presente = bool(token)
            except Exception:
                chiave_presente = False
        if key_env and not chiave_presente:
            raise ValueError(f"manca la chiave {key_env} per {provider_name}")

        self.env["ORCHESTRA_PROVIDER"] = provider_name
        # il catalogo appartiene al provider: tenere quello vecchio
        # mostrerebbe i modelli sbagliati nella select
        self._catalog = None
        self._catalog_tried = False
        # Anche l'orario: senza azzerarlo, il catalogo del provider
        # nuovo sembrerebbe fresco e la TTL aspetterebbe quindici
        # minuti prima di ricaricarlo — con un menu che mostra i
        # modelli del provider sbagliato per tutto quel tempo.
        self._catalog_at = None
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
        # Se l'app era senza sessione, prima la si costruisce: la scelta
        # del modello valido dopo presuppone una sessione esistente.
        if self.session is None:
            try:
                self.session = self._make_session(provider_name, self.env.get("ORCHESTRA_MODEL", ""))
                self.ready = self.session is not None
                if self.ready:
                    self._collega_recupero_tool(); self._collega_delega()
                    self._ripara_modello_iniziale()
                    try: self.allinea_finestra()
                    except Exception: pass
                    self.error = ""
            except Exception as e:
                self.ready = False; self.error = str(e)
        modello_vecchio = self.env.get("ORCHESTRA_MODEL", "")
        scelto = self._modello_per_servizio(provider_name, modello_vecchio)
        if scelto:
            self.switch_model(scelto)
        return {
            "provider": provider_name,
            "modello": scelto or modello_vecchio,
            "modello_cambiato": bool(scelto and scelto != modello_vecchio),
            "ready": self.ready,
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

        def instrada(prima_richiesta: str, scope: str | None = None) -> str | None:
            """Il PRIMO modello, scelto sui punteggi. None se non si puo'.

            Chiama routing.instrada, che non conosce la Sessione: il
              motore di scelta e'uno solo e testato da solo, e la
              Sessione gli passa solo la richiesta. Se la scelta fosse
              dentro questa funzione, il classifier non si potrebbe
              verificare senza una sessione viva — che e'esattamente
              come i punteggi hanno finito per non essere usati da
              nessuno. Se scope e' fornito, lo usa come categoria
              invece di dedurla dal testo.
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
            scelta = _instrada(cat, prima_richiesta, scope=scope)
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
        if self.session is None:
            # Senza sessione non c'e' nulla da aggiornare live: si valida
            # contro il catalogo (se c'e') e si registra la scelta, che
            # la sessione usera' quando nascera'.
            cat = self.catalog
            if cat is not None and cat.models and model_id not in cat.models:
                raise ValueError(
                    f"modello sconosciuto: {model_id}. "
                    f"Disponibili: {', '.join(sorted(cat.models)[:5])}…"
                )
            self.env["ORCHESTRA_MODEL"] = model_id
            from . import keys as keys_mod
            keys_mod.scrivi(ENV_PATH, "ORCHESTRA_MODEL", model_id)
            return
        if self.session.busy:
            raise RuntimeError("l'agente sta lavorando: attendi o annulla prima")

        bot = self.bot_attivo()
        # Il catalogo e' quello del provider dell'APPLICAZIONE. Se il bot
        # usa un provider diverso, il suo modello non c'e' dentro: rifiutarlo
        # sarebbe un errore inventato dal catalogo sbagliato.
        provider_name = ((bot or {}).get("provider")
                         or self.env.get("ORCHESTRA_PROVIDER", "openrouter"))
        cat = self.catalog
        if (not bot or provider_name == self.env.get("ORCHESTRA_PROVIDER")) \
                and cat is not None and cat.models \
                and model_id not in cat.models:
            raise ValueError(
                f"modello sconosciuto: {model_id}. "
                f"Disponibili: {', '.join(sorted(cat.models)[:5])}…"
            )

        from .providers import build_provider
        from .fallback import get_chain_for_provider, ChainEntry

        env = ambiente(ENV_PATH)
        prov = build_provider(provider_name, model=model_id, env=env)
        self.session.agent.provider = prov
        if bot is not None:
            # Il modello scelto qui e' QUELLO DEL BOT: scriverlo in .env
            # cambierebbe il default di ogni altra identita', e il bot
            # successivo nascerebbe col modello sbagliato.
            from . import bots as bots_mod
            try:
                bots_mod.aggiorna(bot["id"], modello=model_id)
            except Exception:  # noqa: BLE001
                pass
            rt = self._bots_runtime.get(int(bot["id"]))
            if rt is not None:
                rt["config"] = bots_mod.per_id(bot["id"]) or rt["config"]
        else:
            self.env["ORCHESTRA_MODEL"] = model_id
            from . import keys as keys_mod
            keys_mod.scrivi(ENV_PATH, "ORCHESTRA_MODEL", model_id)
        # La catena di fallback va RICOSTRUITA sul nuovo modello. Senza,
        # la prima entry continua a puntare al modello di prima: quello
        # morto o inesistente viene chiamato per primo, risponde 404/410,
        # e la catena consuma i passi sui provider sbagliati fino a
        # finire con "Nessun provider disponibile" — mentre il modello
        # nuovo non è mai stato provato per primo.
        ag = self.session.agent
        chain = get_chain_for_provider(provider_name, model_id)
        if chain:
            chain[0] = ChainEntry(
                provider=provider_name,
                model=model_id,
                name=f"{provider_name}/{model_id}",
            )
            ag.fallback_chain = chain
            ag._fallback_state = None  # si ricrea al primo uso, pulita
        # La finestra segue il modello: se cambia il modello e resta il
        # limite vecchio, un modello da 1M di token viene compattato a
        # 120k — e uno da 32k non viene compattato finché non è troppo
        # tardi. Entrambi i versi sbagliano, e nessuno dei due avvisa.
        self.allinea_finestra(model_id)

    def allinea_finestra(self, model_id: str | None = None) -> int:
        """Mette `context_limit` al 75% della finestra del modello.

        Torna il limite applicato. Se il modello non è nel catalogo o il
        catalogo non si apre, resta 120_000: un default prudente batte un
        crash all'avvio, e un modello sconosciuto con un limite piccolo
        spreca contesto invece di perdere messaggi.

        75% e non 100%: sopra resta spazio per la risposta che sta
        arrivando, i tool e il system prompt. Compattare al 100% della
        finestra è come riempire una valigia fino all'orlo e poi sedercisi
        sopra per chiuderla.
        """
        # 120_000 è lo stesso default di LoopConfig: se il catalogo non
        # sa rispondere, il comportamento è quello di prima. Nessun nuovo
        # numero magico, solo lo stesso in due posti.
        limite = 120_000
        try:
            modello = model_id or self.env.get("ORCHESTRA_MODEL", "")
            cat = self.catalog
            prof = cat.models.get(modello) if cat is not None else None
            finestra = prof.info.context_length if prof is not None else 0
            if finestra and finestra > 0:
                limite = int(finestra * 0.75)
        except Exception:
            pass
        try:
            self.session.agent.config.context_limit = limite
        except Exception:
            pass
        return limite

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
            # salva_punteggi DEVE stare qui dentro. Prima finiva nel
            # commento noqa, che sembrava una lista di codici da
            # ignorare: non veniva importata, e la chiamata alla fine
            # del benchmark sollevava NameError — dopo due ore di
            # chiamate. Il benchmark finiva, e i risultati non
            # venivano salvati.
            from .benchmark import (  # noqa: PLC0415
                render_table, run_task, summarize, tasks_for, perché,
                salva_punteggi,
            )

            tasks = tasks_for(category)
            if not tasks:
                self._bench["log"].append(f"categoria sconosciuta: {category}")
                self._bench["running"] = False
                return
            results = []
            stop = False
            try:
                # riparte da zero: il conteggio e' di QUESTO
                # benchmark. Senza, un secondo giro ripartirebbe
                # dal numero del primo e si annuncerebbe a
                # meta' prima di aver fatto una riga.
                self._bench["finiti"] = 0
                self._bench["modelli"] = []
                for mid in ids:
                    if stop:
                        break
                    name = cat.models[mid].info.short if mid in cat.models else mid
                    self._bench["log"].append(f"== {name} ==")
                    if name not in self._bench["modelli"]:
                        self._bench["modelli"].append(name)
                    self._bench["last_progress"] = time.monotonic()
                    for t in tasks:
                        def _avanza(b=self._bench):
                            # Ogni evento dell'agent e' un passo: il
                            # watchdog misura vita vera, non task finiti.
                            b["last_progress"] = time.monotonic()
                        r = run_task(t, provider_name=self.env.get("ORCHESTRA_PROVIDER", "openrouter"),
                                     model=mid, env=dict(os.environ, **self.env),
                                     max_iterations=10, on_progress=_avanza)
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
                        self._bench["finiti"] += 1
                        self._bench["last_progress"] = time.monotonic()
                        if throttle:
                            time.sleep(throttle)
                # L'ultimo progresso, in secondi dall'avvio. Il pannello
                # lo usa per dire "bloccato" invece di "in corso": non
                # possiamo sapere se un run sara' lento o fermo, ma
                # sappiamo che se il log non cresce da due minuti, il
                # worker non sta lavorando.
                self._bench["last_progress"] = time.monotonic()
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

    def start_council(self, decision: str, seats: list[str] | None = None,
                      rounds: int = 3) -> dict[str, Any]:
        if self._council.get("running"):
            raise RuntimeError("un consiglio e' gia' in corso")
        decision = (decision or "").strip()
        if not decision:
            raise RuntimeError("decisione vuota")
        self._council = {"running": True, "log": [], "verdict": "",
                         "session_dir": "", "started": __import__("time").time(),
                         "error": "", "rounds": rounds, "seats": seats or [],
                         "current_round": 0, "current_seat": ""}

        def _log(kind, data):
            try:
                # traccia chi sta parlando per la UI del tavolo
                if kind == "round_start":
                    self._council["current_round"] = int(data.get("round") or 0)
                    self._council["current_seat"] = ""
                elif kind == "seat_start":
                    self._council["current_round"] = int(data.get("round") or self._council.get("current_round", 0))
                    self._council["current_seat"] = str(data.get("seat") or "")
                elif kind == "round_done":
                    self._council["current_seat"] = ""
                elif kind == "chair_start":
                    self._council["current_seat"] = "chair"
                elif kind == "council_done":
                    self._council["current_seat"] = ""
                    self._council["current_round"] = 0
                msg = ""
                if kind == "seat_done":
                    msg = f"[round {data.get('round')}] {data.get('name')}:\n{str(data.get('text','')).strip()}"
                elif kind == "round_done":
                    msg = f"--- round {data.get('round')} finito ---"
                elif kind == "chair_done":
                    msg = "Chair: verdict pronto"
                elif kind == "council_done":
                    msg = "Consiglio concluso"
                elif kind == "council_start":
                    msg = "Consiglio avviato"
                if msg:
                    self._council["log"].append(msg)
                    # tieni il log corto
                    if len(self._council["log"]) > 200:
                        self._council["log"] = self._council["log"][-200:]
            except Exception:
                pass

        def worker():
            try:
                from .council import run_council
                r = run_council(
                    decision,
                    seats=seats,
                    rounds=rounds,
                    provider=None,  # _ensure_provider sceglie un provider funzionante
                    base_dir=os.getcwd(),
                    on_event=_log,
                )
                self._council["verdict"] = r.get("verdict", "")
                self._council["session_dir"] = r.get("session_dir", "")
                self._council["log"].append("Verdict salvato in " + r.get("verdict_path", ""))
            except Exception as e:  # noqa: BLE001
                self._council["error"] = f"{type(e).__name__}: {e}"
                self._council["log"].append("ERRORE: " + self._council["error"])
            finally:
                self._council["running"] = False

        import threading
        threading.Thread(target=worker, daemon=True, name="orchestra-council").start()
        return {"ok": True, "running": True}

    def council_status(self) -> dict[str, Any]:
        return {
            "running": self._council.get("running", False),
            "log": list(self._council.get("log", [])),
            "verdict": self._council.get("verdict", ""),
            "session_dir": self._council.get("session_dir", ""),
            "error": self._council.get("error", ""),
            "current_round": self._council.get("current_round", 0),
            "current_seat": self._council.get("current_seat", ""),
            "rounds": self._council.get("rounds", 0),
            "seats": list(self._council.get("seats", [])),
        }

    @staticmethod
    def council_roster() -> list[dict[str, Any]]:
        try:
            from .council import load_roster
            return load_roster()
        except Exception:
            return []

    @staticmethod
    def _make_session(provider_name: str, model: str, *,
                      persona: str = "", nome_bot: str = "") -> Session:
        # Il fallback e' su ENV_PATH (.env), non su os.environ: quando si
        # salva un'impostazione via API (es. /api/iterazioni) scrive in .env
        # e in self.app.env, ma os.environ non viene aggiornato. Riavviando
        # il server, questo codice leggeva os.environ (che non ha il valore)
        # e perdeva il salvataggio. Ora legge la stessa fonte che usa il
        # resto del server, cosi' il riavvio non cancella niente.
        _env = load_env(ENV_PATH)
        def num(key: str, default: int) -> int:
            try:
                return int(_env.get(key, default))
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
        # Nel system prompt entra SOLO il poco che deve essere vero
        # sempre — la sezione `## Importanti`. Il resto lo cerca l'agente
        # col tool `memoria`.
        #
        # Il motivo è il costo: iniettare la memoria intera la paga a ogni
        # turno, e il prezzo cresce con quanto ricordi. Dopo qualche mese
        # di uso avvelena il contesto di ogni richiesta, comprese quelle
        # che non c'entrano niente con quello che c'è salvato. Il tool
        # costa solo quando si usa.
        from . import identita as identita_mod

        prompt_con_memoria = _prompt_base_con_memoria()
        # La persona di un bot viene DOPO le regole, non al posto loro:
        # il bot ha un carattere e un compito, ma resta un agente di
        # Orchestra, con i suoi confini e i suoi divieti. Lo stesso vale
        # per l'agente principale: il suo nome e le sue istruzioni sono
        # un blocco in fondo, non un prompt alternativo.
        #
        # Un `_make_session` senza nome di bot e' l'agente principale:
        # se l'utente non ha passato una persona esplicita, si legge
        # quella salvata. Cosi' ogni ricostruzione della sessione — cambio
        # provider, cambio modello, riavvio — non perde l'identita'.
        e_bot = bool((nome_bot or "").strip())
        if not e_bot:
            ident = identita_mod.carica()
            nome_bot = nome_bot or ident["nome"]
            persona = (persona or "").strip() or ident["persona"]
        prompt_con_memoria = identita_mod.componi_prompt(
            prompt_con_memoria, nome_bot, persona, bot=e_bot)
        _provider = build_provider(provider_name, model=model,
                                   env=load_env(ENV_PATH) | os.environ)
        # Il riassunto del contesto usa un modello vero. Prima `summarize`
        # restava None e la compaction ripiegava sul troncamento
        # testa/coda: in una conversazione lunga spariva il centro, cioe'
        # le decisioni e gli errori gia' risolti. Il costo e' di una
        # chiamata corta, e solo quando il contesto si riempie davvero.
        from .context import summarizer_llm

        return Session(
                    provider=_provider,
                    registry=default_registry(),
                    system_prompt=prompt_con_memoria,
                    config=LoopConfig(max_iterations=num("ORCHESTRA_MAX_ITERS", 20),
                                                          context_limit=num("ORCHESTRA_CONTEXT_LIMIT", 120_000),
                                                          keep_recent=8,
                                                          # Senza questo, un turno web poteva
                                                          # restare appeso finche' il browser
                                                          # era aperto: il tetto vale anche
                                                          # qui, e non e' un dettaglio della CLI.
                                                          max_secondi_turno=num(
                                                              "ORCHESTRA_MAX_SECONDI_TURNO",
                                                              900),
                                                          reasoning_level=_env.get("ORCHESTRA_REASONING") or None,
                                                          tool_profile=_env.get("ORCHESTRA_TOOL_PROFILE") or None),
                    summarize=summarizer_llm(_provider),
                )

    # -- bot ----------------------------------------------------------------

    def elenco_bot(self) -> list[dict[str, Any]]:
        """I bot salvati, con lo stato che serve al pannello.

        `busy` e `modello_effettivo` vengono dalla sessione viva, non
        dalla configurazione: un bot che sta lavorando e uno fermo hanno
        la stessa riga nel DB, e la differenza e' quella che l'utente
        guarda per decidere se mandargli qualcosa.
        """
        from . import bots as bots_mod

        fuori = []
        # getattr e non self._x: il server puo' essere costruito con
        # __new__ (lo fanno i test e una vecchia create()), e allora gli
        # attributi aggiunti dopo non ci sono. Un pannello che legge
        # l'elenco dei bot non deve far cadere /api/state per questo.
        attivo_id = int(getattr(self, "_bot_attivo_id", 0) or 0)
        runtime = getattr(self, "_bots_runtime", {}) or {}
        for b in bots_mod.tutti():
            voce = dict(b)
            voce["attivo"] = int(b["id"]) == attivo_id
            rt = runtime.get(int(b["id"]))
            voce["busy"] = bool(rt and rt["sessione"].busy)
            voce["modello_effettivo"] = (
                rt["sessione"].modello_in_uso() if rt else b["modello"])
            # Lo stato dei lavori in background. `busy` da solo non basta:
            # un compito in coda non ha ancora reso la sessione occupata,
            # e la UI deve poter dire "in coda: 2" prima che parta.
            #
            # Qui si legge il database, non la memoria del processo: un
            # lavoro rimasto in coda prima di un riavvio deve comparire
            # nello stesso modo di uno appena messo.
            try:
                from . import lavori as lavori_mod

                riass = lavori_mod.riassunto("bot", str(b["id"]))
            except Exception:  # noqa: BLE001
                riass = {}
            voce["coda"] = int(riass.get("in_attesa") or 0)
            voce["in_corso"] = str(riass.get("in_corso_testo") or "")
            voce["in_corso_id"] = int(riass.get("in_corso_id") or 0)
            voce["in_corso_worktree"] = riass.get("in_corso_worktree")
            voce["ultimo"] = riass.get("ultimo")
            voce["riprovabile"] = riass.get("riprovabile")
            voce["interrotti"] = int(riass.get("interrotti") or 0)
            voce["falliti"] = int(riass.get("falliti") or 0)
            fuori.append(voce)
        return fuori

    def bot_attivo(self) -> dict[str, Any] | None:
        ident = int(getattr(self, "_bot_attivo_id", 0) or 0)
        if not ident:
            return None
        from . import bots as bots_mod

        return bots_mod.per_id(ident)

    # -- lavori in background dei bot -------------------------------------

    # Quanti compiti si possono accodare su un bot. Un tetto basso non e'
    # una limitazione tecnica: e' il punto in cui un errore di battitura
    # (premere due volte "Avvia") smette di produrre una fila di turni a
    # pagamento che nessuno ha chiesto.
    MAX_LAVORI_BOT = 20

    def _fili_bot(self) -> dict[int, threading.Thread]:
        fili = getattr(self, "_bots_fili", None)
        if fili is None:
            fili = self._bots_fili = {}
        return fili

    def _lock_fili_bot(self) -> threading.RLock:
        lock = getattr(self, "_bots_fili_lock", None)
        if lock is None:
            lock = self._bots_fili_lock = threading.RLock()
        return lock

    def _avvia_filo_bot(self, ident: int) -> None:
        """Avvia il consumatore di una coda, se non c'e' gia'.

        Il lock e' RLock perche' il chiamante puo' gia' tenerlo mentre
        accoda: l'operazione e' "registra il filo", non "esegui il
        turno", e non deve aspettare il lavoro per finire.
        """
        with self._lock_fili_bot():
            filo = self._fili_bot().get(ident)
            if filo is not None and filo.is_alive():
                return
            filo = threading.Thread(
                target=self._gira_lavori_bot, args=(ident,),
                daemon=True, name=f"orchestra-bot-{ident}")
            self._fili_bot()[ident] = filo
            filo.start()

    def avvia_lavoro_bot(self, bot_id: int | str | None,
                         testo: str) -> dict[str, Any]:
        """Accoda un compito per un bot, senza cambiare l'identita' attiva.

        Il turno parte in un filo suo: chi chiama torna subito, e il bot
        lavora mentre l'utente (o un altro bot) continua altrove. Una
        coda per bot, non una globale: due compiti sullo stesso bot non
        possono girare insieme — la Session ha un turno solo — ma due
        bot diversi hanno sessioni e fili diversi, quindi avanzano
        davvero in parallelo.

        La coda e' su disco: se il server muore subito dopo questa
        chiamata, il lavoro e' ancora li' al riavvio.
        """
        from . import bots as bots_mod
        from . import lavori as lavori_mod

        b = bots_mod.per_id(bot_id) if bot_id not in (None, "", 0, "0") \
            else None
        if b is None:
            raise ValueError(f"bot inesistente: {bot_id}")
        testo = (testo or "").strip()
        if not testo:
            raise ValueError("serve un compito da svolgere")
        if len(testo) > Session.BOT_MESSAGGIO_MAX:
            raise ValueError("compito troppo lungo")
        ident = int(b["id"])
        # Costruire la sessione qui, e non nel filo, fa fallire subito un
        # provider mal configurato: l'utente vede l'errore sul pulsante
        # invece di un lavoro che non parte e non dice perche'.
        self._sessione_bot(b)
        # Inserimento e avvio del filo sotto lo stesso lock con cui il
        # consumatore decide di uscire: senza, un lavoro accodato
        # nell'istante fra "coda vuota" e "filo terminato" resterebbe
        # orfano fino al prossimo riavvio.
        with self._lock_fili_bot():
            lavoro = lavori_mod.accoda(
                "bot", str(ident), {"testo": testo}, titolo=testo,
                max_tentativi=1, limite=self.MAX_LAVORI_BOT)
            self._avvia_filo_bot(ident)
            riass = lavori_mod.riassunto("bot", str(ident))
        return {"ok": True, "bot": b["nome"],
                "in_coda": int(riass.get("in_attesa") or 0)
                           + int(riass.get("in_corso") or 0),
                "lavoro": int(lavoro["id"])}

    def _gira_lavori_bot(self, ident: int) -> None:
        """Consuma la coda di un bot, un compito alla volta.

        La coda e' su disco; questo filo e' solo il consumatore. Il lock
        dei fili non si tiene durante un turno: servirebbe a bloccare
        `elenco_bot` e la UI per minuti. Lo si prende solo per decidere
        se uscire e per non lasciare un lavoro orfano mentre si esce.
        """
        from . import lavori as lavori_mod

        errori_db = 0
        while True:
            try:
                lavoro = lavori_mod.prossimo("bot", str(ident))
                errori_db = 0
            except Exception:  # noqa: BLE001
                # Un lock conteso o un disco momentaneamente occupato non
                # deve uccidere il consumatore: si riprova. Dopo qualche
                # errore di fila, pero', si esce e lascia il lavoro in
                # coda: meglio fermarsi che girare a vuoto per sempre.
                errori_db += 1
                if errori_db >= 5:
                    with self._lock_fili_bot():
                        if self._fili_bot().get(ident) is threading.current_thread():
                            self._fili_bot().pop(ident, None)
                    return
                time.sleep(0.5)
                continue
            if lavoro is None:
                with self._lock_fili_bot():
                    # La ricontrollata sotto lock chiude la corsa con
                    # `avvia_lavoro_bot`: se un lavoro e' stato appena
                    # inserito, il filo non muore e lo prende.
                    try:
                        if lavori_mod.ha_in_attesa("bot", str(ident)):
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                    if self._fili_bot().get(ident) is threading.current_thread():
                        self._fili_bot().pop(ident, None)
                return
            self._esegui_lavoro_bot(ident, lavoro)

    def _esegui_lavoro_bot(self, ident: int,
                           lavoro: dict[str, Any]) -> None:
        """Esegue un lavoro gia' rivendicato e ne chiude lo stato.

        `prima` e' il confine della conversazione: si prende prima di
        mandare il messaggio, cosi' la risposta del lavoro non si confonde
        con un turno dell'utente che stava gia' sulla stessa sessione.
        """
        from . import bots as bots_mod
        from . import lavori as lavori_mod

        job_id = int(lavoro["id"])
        testo = str((lavoro.get("payload") or {}).get("testo") or "")
        try:
            b = bots_mod.per_id(ident)
            if b is None:
                lavori_mod.fallisci(job_id, "il bot non esiste piu'")
                return
            sess = self._sessione_bot(b)
            # Il checkout isolato e' per QUESTO lavoro. Si crea prima del
            # turno e resta dopo, cosi' l'utente puo' rivedere i file: un
            # worktree che sparisce a fine turno sarebbe solo un posto
            # dove il bot ha buttato il lavoro.
            #
            # Progetto non git (o ORCHESTRA_WORKTREE=0): None, si lavora
            # nella cartella normale come prima. Un progetto git che non
            # riesce a creare il checkout invece fa fallire il lavoro:
            # scrivere nel repository dell'utente "per ripiego" sarebbe
            # esattamente il danno che l'isolamento evita.
            info = None
            percorso_progetto = ""
            if b.get("progetto"):
                from . import progetti as progetti_mod
                percorso_progetto = (progetti_mod.percorso_di(
                    b["progetto"]) or "")
            if percorso_progetto:
                from . import worktree as worktree_mod
                info = worktree_mod.prepara(percorso_progetto, job_id)
                if info:
                    lavori_mod.salva_checkpoint(job_id, {"worktree": info})
            radice_isolata = str((info or {}).get("radice") or "")
            proposta = None
            if info:
                def proposta(riepilogo, verifica, _job=job_id,
                             _info=info):
                    riepilogo = str(riepilogo or "").strip()
                    verifica = str(verifica or "").strip()
                    if not riepilogo or not verifica:
                        return ("[proposta non registrata: servono il "
                                "riepilogo e la verifica]")
                    # Un merge unisce commit, non file: si committa il
                    # lavoro DENTRO il checkout prima di proporlo.
                    try:
                        primo = riepilogo.splitlines()[0][:120]
                        commit = worktree_mod.commit_modifiche(
                            _info, "orchestra: " + primo)
                    except Exception as e:  # noqa: BLE001
                        return ("[proposta non registrata: "
                                f"{type(e).__name__}: {e}]")
                    dati = {
                        "pronto": True,
                        "riepilogo": riepilogo[:2000],
                        "verifica": verifica[:4000],
                        "branch": str(_info.get("branch") or ""),
                        "commit": str(commit.get("commit") or ""),
                        "ts": time.time(),
                    }
                    lavori_mod.aggiorna_checkpoint(_job, {"merge": dati})
                    return ("proposta registrata: l'utente decidera' se "
                            "unire. Non unire tu e non modificare il "
                            "progetto principale.")
            prima = 0
            while True:
                if lavori_mod.stato(job_id) == "annullato":
                    return
                if sess.busy:
                    lavori_mod.batti(job_id)
                    time.sleep(0.2)
                    continue
                try:
                    prima = len(sess.snapshot().get("messages", []))
                except Exception:  # noqa: BLE001
                    prima = 0
                if radice_isolata:
                    avviato = sess.send(
                        testo, root_isolata=radice_isolata,
                        proponi_merge=proposta)
                else:
                    avviato = sess.send(testo)
                if avviato:
                    break
                # Un turno dell'utente o `bot_chiedi` ha vinto la corsa:
                # si aspetta, non si accoda un secondo turno.
                time.sleep(0.2)
            ultimo_battito = 0.0
            while sess.busy:
                if lavori_mod.stato(job_id) == "annullato":
                    sess.cancel()
                    break
                ora = time.monotonic()
                if ora - ultimo_battito >= 2.0:
                    lavori_mod.batti(job_id)
                    ultimo_battito = ora
                time.sleep(0.2)
            if lavori_mod.stato(job_id) == "annullato":
                while sess.busy:
                    time.sleep(0.2)
                return
            risposta = ""
            try:
                messaggi = sess.snapshot().get("messages", [])
                for m in reversed(messaggi[prima:]):
                    if (m.get("role") == "assistant"
                            and (m.get("content") or "").strip()):
                        risposta = (m.get("content") or "").strip()
                        break
            except Exception:  # noqa: BLE001
                pass
            if risposta:
                lavori_mod.completa(job_id, risposta)
            else:
                lavori_mod.fallisci(job_id, "nessuna risposta")
        except Exception as e:  # noqa: BLE001
            try:
                lavori_mod.fallisci(job_id, f"{type(e).__name__}: {e}")
            except Exception:  # noqa: BLE001
                pass

    def _riprendi_lavori_bot(self) -> int:
        """Recupera le code dopo un avvio.

        I lavori in corso appartenevano a un processo morto e vengono
        marcati `interrotti`, non rieseguiti: un turno a meta' puo' avere
        gia' scritto file o speso token. Quelli in attesa non hanno ancora
        toccato niente e ripartono subito.
        """
        from . import lavori as lavori_mod

        try:
            interrotti = lavori_mod.interrompi_in_corso(
                "bot", "interrotto dal riavvio del server: riprova il lavoro")
        except Exception:  # noqa: BLE001
            interrotti = 0
        try:
            chiavi = lavori_mod.chiavi_con_attesa("bot")
        except Exception:  # noqa: BLE001
            chiavi = []
        for chiave in chiavi:
            try:
                ident = int(chiave)
            except (TypeError, ValueError):
                continue
            if ident > 0:
                self._avvia_filo_bot(ident)
        return interrotti

    def riprova_lavoro(self, lavoro_id: int | str) -> dict[str, Any]:
        """Rimette in coda un lavoro fallito o interrotto e lo riavvia."""
        from . import lavori as lavori_mod

        lavoro = lavori_mod.ottieni(lavoro_id)
        if lavoro is None:
            raise ValueError("lavoro inesistente")
        if lavoro.get("tipo") != "bot":
            raise ValueError("tipo di lavoro non gestito da questo pannello")
        nuovo = lavori_mod.riprova(int(lavoro["id"]))
        if nuovo is None:
            raise RuntimeError("questo lavoro non si puo' riprovare")
        try:
            ident = int(nuovo["chiave"])
        except (TypeError, ValueError):
            raise ValueError("lavoro senza un bot valido")
        self._avvia_filo_bot(ident)
        return nuovo

    def unisci_lavoro(self, lavoro_id: int | str) -> dict[str, Any]:
        """Unisce il ramo del bot nel progetto, su richiesta dell'utente.

        Il bot puo' solo proporre, con il tool `proponi_merge`; qui
        l'utente accetta. Si rifiuta se il working tree del progetto non
        e' pulito: il merge non deve mescolare il lavoro del bot con
        modifiche non committate dell'utente, ne' lasciare conflitti
        aperti in una cartella che magari non sta guardando.
        """
        from . import lavori as lavori_mod
        from . import worktree as worktree_mod

        lavoro = lavori_mod.ottieni(lavoro_id)
        if lavoro is None:
            raise ValueError("lavoro inesistente")
        if lavoro.get("tipo") != "bot":
            raise ValueError("tipo di lavoro non gestito da questo pannello")
        if lavoro.get("stato") != "completato":
            raise ValueError("si unisce solo un lavoro completato")
        checkpoint = lavoro.get("checkpoint") or {}
        if not isinstance(checkpoint, dict):
            checkpoint = {}
        merge = checkpoint.get("merge")
        if not isinstance(merge, dict) or not merge.get("pronto"):
            raise ValueError("il bot non ha proposto un merge per questo lavoro")
        if merge.get("unito"):
            return {"ok": True, "gia_unito": True, "lavoro": lavoro,
                    "commit": str(merge.get("commit") or "")}
        info = checkpoint.get("worktree")
        if not isinstance(info, dict) or info.get("scartato"):
            raise RuntimeError(
                "il checkout isolato non c'e' piu': non c'e' niente da unire")
        esito = worktree_mod.unisci(
            info, commit_atteso=str(merge.get("commit") or ""))
        nuovo_merge = {**merge, "unito": True,
                       "gia_unito": bool(esito.get("gia_unito")),
                       "commit": str(esito.get("commit") or ""),
                       "unito_il": time.time()}
        aggiornato = lavori_mod.aggiorna_checkpoint(
            int(lavoro["id"]), {"merge": nuovo_merge})
        return {"ok": True, "commit": nuovo_merge["commit"],
                "gia_unito": nuovo_merge["gia_unito"],
                "lavoro": aggiornato or lavoro}

    def scarta_checkout_lavoro(self, lavoro_id: int | str) -> dict[str, Any]:
        """Butta via il worktree di un lavoro chiuso.

        Non unisce niente: il ramo del bot e' una proposta, e un merge
        automatico nel repository dell'utente sarebbe una decisione presa
        al posto suo. Se la proposta va bene si usa `unisci_lavoro`.
        """
        from . import lavori as lavori_mod
        from . import worktree as worktree_mod

        lavoro = lavori_mod.ottieni(lavoro_id)
        if lavoro is None:
            raise ValueError("lavoro inesistente")
        if lavoro.get("stato") in lavori_mod.ATTIVI:
            raise RuntimeError(
                "il lavoro e' ancora attivo: annullalo prima di scartare "
                "il checkout")
        # `annullato` e' gia' terminale, ma il turno puo' essere ancora
        # in corso mentre si ferma: cancellare il checkout sotto i piedi
        # del consumatore farebbe scrivere il bot in una cartella che non
        # esiste piu'. Si aspetta che la sessione sia libera.
        if lavoro.get("stato") == "annullato":
            try:
                ident = int(lavoro.get("chiave") or 0)
            except (TypeError, ValueError):
                ident = 0
            rt = (getattr(self, "_bots_runtime", {}) or {}).get(ident)
            if rt is not None and getattr(rt.get("sessione"), "busy", False):
                raise RuntimeError(
                    "il turno annullato si sta ancora fermando: riprova "
                    "tra un istante")
        checkpoint = lavoro.get("checkpoint") or {}
        info = checkpoint.get("worktree") if isinstance(checkpoint, dict) else None
        if not isinstance(info, dict) or not info.get("percorso"):
            raise ValueError("questo lavoro non ha un checkout isolato")
        if info.get("scartato"):
            return {"ok": True, "gia_scartato": True, "lavoro": lavoro}
        worktree_mod.rimuovi(info)
        aggiornato = lavori_mod.aggiorna_checkpoint(
            int(lavoro["id"]), {"worktree": {**info, "scartato": True}})
        return {"ok": True, "lavoro": aggiornato or lavoro}

    def annulla_lavoro(self, lavoro_id: int | str) -> dict[str, Any]:
        """Annulla un lavoro in attesa o in corso."""
        from . import lavori as lavori_mod

        lavoro = lavori_mod.ottieni(lavoro_id)
        if lavoro is None:
            raise ValueError("lavoro inesistente")
        if lavoro.get("tipo") != "bot":
            raise ValueError("tipo di lavoro non gestito da questo pannello")
        annullato = lavori_mod.annulla(int(lavoro["id"]))
        if annullato is None:
            raise RuntimeError("questo lavoro non e' piu' annullabile")
        # NON si chiama `Session.cancel()` da qui. Se il lavoro sta
        # aspettando che la sessione si liberi, quella sessione potrebbe
        # essere occupata da un turno dell'utente: annullare il lavoro
        # non deve fermare la chat. Il consumatore vede lo stato
        # `annullato` al giro successivo e chiama `cancel()` solo se e'
        # davvero lui a stare eseguendo il turno.
        return annullato

    def annulla_modifica(self) -> dict[str, Any]:
        """Rimette l'ultimo file toccato dall'agente com'era prima.

        Solleva ValueError quando non c'e' niente da annullare: la UI
        deve poter distinguere "non ho fatto niente" da "ho fallito".
        """
        from . import checkpoint

        voce = checkpoint.annulla_ultima()
        if voce is None:
            raise ValueError(
                "nessuna modifica da annullare: il registro degli "
                "ultimi file toccati e' vuoto")
        return voce

    def identita(self) -> dict[str, str]:
        """Nome e persona dell'agente principale (vuoti = Orchestra)."""
        from . import identita as identita_mod

        return identita_mod.carica()

    def salva_identita(self, nome: str, persona: str) -> dict[str, str]:
        """Salva l'identita' e la applica subito alla sessione principale.

        Non si ricostruisce la sessione: perderebbe la conversazione in
        corso. Si ricompone il prompt di base (regole + memoria) e ci si
        aggiunge la nuova identita', poi si lascia che l'Agent rimetta
        skills e progetto come fa a ogni turno.

        Se in questo momento e' attivo un bot, la sessione da aggiornare
        e' quella principale conservata da parte: l'utente la ritrovera'
        gia' aggiornata quando torna.
        """
        from . import identita as identita_mod

        dati = identita_mod.salva(nome, persona)
        if self.bot_attivo() is None:
            target = self.session
        else:
            target = getattr(self, "_sessione_principale", None)
        if target is not None:
            nuovo = identita_mod.componi_prompt(
                _prompt_base_con_memoria(), dati["nome"], dati["persona"])
            try:
                target.agent.system_prompt = nuovo
                target.agent._aggiorna_prompt()
            except Exception:  # noqa: BLE001
                # Se l'Agent non e' ancora pronto, il prompt del primo
                # messaggio e' comunque meglio di un'identita' salvata
                # solo su disco: la si applica dove si puo'.
                try:
                    target.set_system_prompt(nuovo)
                except Exception:  # noqa: BLE001
                    pass
        return dati

    def provider_attivo(self) -> str:
        """Il nome del provider che la sessione attiva sta usando."""
        sess = self.session
        agente = getattr(sess, "agent", None) if sess is not None else None
        prov = getattr(agente, "provider", None) if agente is not None else None
        nome = str(getattr(prov, "name", "") or "")
        return nome or self.env.get("ORCHESTRA_PROVIDER", "")

    def _bot_provider_modello(self, bot: dict[str, Any]) -> tuple[str, str]:
        """Con quale provider e modello parla questo bot.

        Vuoto significa "come l'applicazione": e' il default di chi crea
        un bot e non vuole scegliere, e deve continuare a funzionare
        quando l'utente cambia modello in Opzioni. Se invece il bot ha un
        provider suo e nessun modello, si prova a sceglierne uno valido
        dal catalogo: un provider senza modello non parte, e il primo
        turno morirebbe con un 400 che sembra un problema di rete.
        """
        provider = (bot.get("provider") or self.env.get("ORCHESTRA_PROVIDER")
                    or "openrouter").strip()
        modello = (bot.get("modello") or "").strip()
        if not modello:
            if provider == (self.env.get("ORCHESTRA_PROVIDER") or ""):
                modello = self.env.get("ORCHESTRA_MODEL", "")
            else:
                try:
                    modello = self._modello_per_servizio(provider, "") or ""
                except Exception:  # noqa: BLE001
                    modello = ""
        return provider, modello

    def _risolutore_bot(self, nome: str) -> dict[str, Any] | None:
        """Il ponte che `bot_chiedi` usa per raggiungere un altro bot.

        Costruisce la sessione del destinatario se non c'e': un bot che
        riceve un messaggio deve poter rispondere anche se non l'hai mai
        aperto in questa esecuzione. E' l'unica differenza fra un bot e
        un'etichetta.
        """
        from . import bots as bots_mod

        b = bots_mod.per_nome(nome)
        if b is None:
            return None
        return {"nome": b["nome"], "sessione": self._sessione_bot(b)}

    def _sessione_bot(self, bot: dict[str, Any]) -> Session:
        """La sessione di un bot, costruita una volta e poi riusata.

        Il riuso e' voluto: la conversazione vive in memoria fra un turno
        e l'altro, e ricostruirla a ogni messaggio vorrebbe dire rileggere
        lo storico e perdere le tool call non ancora salvate. Quando la
        configurazione cambia, il chiamante la butta esplicitamente.
        """
        ident = int(bot["id"])
        runtime = getattr(self, "_bots_runtime", None)
        if runtime is None:
            runtime = self._bots_runtime = {}
        rt = runtime.get(ident)
        if rt is not None:
            return rt["sessione"]
        provider, modello = self._bot_provider_modello(bot)
        sess = self._make_session(provider, modello,
                                  persona=bot.get("persona", ""),
                                  nome_bot=bot.get("nome", ""))
        sess.bot = bot["nome"]
        sess.attiva_bot(self._risolutore_bot, nome=bot["nome"],
                        parla_con=list(bot.get("parla_con") or []))
        if bot.get("profilo"):
            sess.agent.config.tool_profile = bot["profilo"]
        if bot.get("progetto"):
            sess.imposta_progetto(bot["progetto"])
        # La policy si salva nella sessione e si applica a ogni turno,
        # dopo il profilo: applicarla qui la farebbe cancellare dal
        # profilo che `_esegui_turno` rifa' da capo.
        sess.imposta_policy(bot.get("policy"))
        self._bots_runtime[ident] = {"config": bot, "sessione": sess}
        self._collega_delega(sess)
        # Riapri l'ultima conversazione DI QUESTO bot, non l'ultima di
        # tutte: senza il filtro, attivare un bot appena creato mostrerebbe
        # la chat dell'agente principale, che non c'entra niente.
        try:
            if self._storico is not None:
                ultima = self._storico.elenco(limite=1, bot=bot["nome"])
                if ultima:
                    sess.carica_sessione(int(ultima[0]["id"]))
        except Exception:  # noqa: BLE001
            pass
        return sess

    # --- Telegram -----------------------------------------------------
    def telegram_turno(self, bot_id: int, testo: str,
                       allegati: list | None = None,
                       avanzamento: Any = None) -> str:
        """Un messaggio arrivato su Telegram, e la risposta da rimandare.

        E' lo stesso turno della finestra: stessa sessione, stessi tool,
        stessa policy. Telegram e' il filo da cui arriva il messaggio,
        non un agente diverso ne' uno con meno permessi — e questo e'
        anche il motivo per cui il ponte risponde solo alla chat
        collegata con il codice.

        Il turno si guarda mentre gira, con gli stessi eventi che
        arrivano al browser, e se ne ricava una riga di stato: e' la
        cosa piu' vicina al ragionamento che si vede nella finestra, e
        senza quella una richiesta lunga resta un puntino che scrive per
        dieci minuti. Solo la coda, pero': un muro di testo su un
        telefono non lo legge nessuno.
        """
        from . import bots as bots_mod

        b = bots_mod.per_id(bot_id)
        if b is None:
            return ("Questo bot non esiste piu' in Orchestra: manda "
                    "/scollega qui e ricollega quello giusto dal pannello.")
        sess = self._sessione_bot(b)
        if sess.busy:
            return "Sto ancora lavorando al messaggio precedente."
        # La sottoscrizione avviene prima di `send`: iscriversi dopo
        # vorrebbe dire perdere il primo pezzo di ragionamento, che e'
        # proprio quello che si vuole mostrare.
        eventi = sess.stream(timeout=0.4)
        try:
            if not sess.send(testo, allegati=allegati or None):
                return ("C'e' gia' un turno in corso su questo bot: rimanda "
                        "il messaggio quando ha finito.")
            stato = self._telegram_segui(sess, eventi, avanzamento, b)
        finally:
            eventi.close()
        if stato.get("annullato"):
            return "Turno interrotto."
        if not stato.get("finito"):
            # Non e' un errore: e' un turno lungo. Dirlo e' meglio che
            # inventare una risposta o lasciare l'utente senza niente.
            return ("Sto ancora lavorando: il turno e' lungo e non e' "
                    "finito. La risposta completa la trovi nella finestra "
                    "di Orchestra.")
        return self._telegram_ultima_risposta(sess)

    def _telegram_ultima_risposta(self, sess: Any) -> str:
        for m in reversed(getattr(sess.agent.state, "messages", [])):
            if getattr(m, "role", "") == "assistant":
                risposta = (getattr(m, "content", "") or "").strip()
                if risposta:
                    return risposta
        return ""

    def _telegram_segui(self, sess: Any, eventi: Any, avanzamento: Any,
                        bot: dict[str, Any]) -> dict[str, Any]:
        """Legge gli eventi del turno e alimenta il messaggio di stato.

        Torna cosa e' successo: se il turno e' finito e se qualcuno l'ha
        fermato. Chi chiama lo usa per decidere cosa scrivere in chat —
        e per non scrivere niente quando ha gia' risposto /stop.
        """
        stato: dict[str, Any] = {
            "testo": "", "ragiona": "", "tool": [], "giro": 0,
            "inizio": time.monotonic(), "annullato": False, "finito": False,
            "ultimo_evento": time.monotonic(),
        }
        scadenza = stato["inizio"] + self._telegram_attesa()
        for ev in eventi:
            tipo = ev.get("kind")
            dati = ev.get("data") or {}
            if tipo == "keepalive":
                # Un turno che muore senza emettere `idle` non deve
                # lasciare il ponte a girare per quindici minuti: se la
                # sessione non e' piu' occupata e non arriva niente da
                # un secondo, il turno e' finito, in un modo o
                # nell'altro.
                if (not sess.busy
                        and time.monotonic() - stato["ultimo_evento"] > 1.0):
                    stato["finito"] = True
                    break
            else:
                stato["ultimo_evento"] = time.monotonic()
            if tipo == "ragionamento":
                stato["ragiona"] = (stato["ragiona"]
                                    + (dati.get("testo") or ""))[-600:]
            elif tipo == "contenuto":
                stato["testo"] = (stato["testo"]
                                  + (dati.get("testo") or ""))[-600:]
            elif tipo == "tool_start":
                stato["tool"].append(str(dati.get("name") or "?"))
            elif tipo == "thinking":
                try:
                    stato["giro"] = int(dati.get("iteration") or 0)
                except (TypeError, ValueError):
                    pass
            elif tipo == "cancel_requested":
                stato["annullato"] = True
            elif tipo == "idle" and not dati.get("busy", True):
                stato["finito"] = True
                break
            if avanzamento is not None:
                try:
                    avanzamento(self._telegram_stato(bot, stato))
                except Exception:  # noqa: BLE001
                    # Un ponte che non riesce a dire come va non deve
                    # fermare il turno: la risposta conta piu' della
                    # cronaca.
                    pass
            if time.monotonic() > scadenza:
                break
        return stato

    def _telegram_stato(self, bot: dict[str, Any], stato: dict[str, Any]) -> str:
        """Tre righe per dire che sta succedendo, non un log."""
        secondi = int(time.monotonic() - stato["inizio"])
        prima = f"{bot.get('nome') or 'bot'} · {secondi}s"
        if stato["giro"]:
            prima += f" · giro {stato['giro']}"
        righe = [prima]
        if stato["tool"]:
            righe.append("tool: " + ", ".join(stato["tool"][-4:]))
        testo = (stato["testo"] or "").strip()
        if testo:
            righe.append(_coda(testo, 400))
        elif stato["ragiona"].strip():
            righe.append("pensa: " + _coda(stato["ragiona"].strip(), 400))
        return "\n".join(righe)

    def _telegram_attesa(self) -> float:
        try:
            return max(30.0, float(
                os.environ.get("ORCHESTRA_TELEGRAM_ATTESA", "900")))
        except (TypeError, ValueError):
            return 900.0

    def telegram_comando(self, bot_id: int, nome: str,
                         argomento: str = "") -> str | dict[str, Any]:
        """I comandi che si possono dare al bot dal telefono.

        Un comando non e' un turno: non costa token e non entra nella
        conversazione. `/stop` ferma un turno che dal telefono non si
        potrebbe fermare in nessun altro modo, ed e' la ragione per cui
        questa funzione esiste.
        """
        from . import bots as bots_mod

        b = bots_mod.per_id(bot_id)
        if b is None:
            return "Questo bot non esiste piu' in Orchestra."
        nome = (nome or "").strip().lower()
        sess = self._sessione_bot(b)
        if nome == "stato":
            return self._telegram_stato_bot(b, sess)
        if nome == "steer":
            if not argomento.strip():
                return ("Uso: /steer <testo>. Mentre lavora, un messaggio "
                        "normale fa la stessa cosa.")
            if not sess.busy:
                return ("Nessun turno in corso da guidare: scrivi la "
                        "richiesta e parte.")
            if not sess.steer(argomento.strip()):
                return ("La coda delle guide e' piena (max 5): aspetta che "
                        "il turno ne legga una.")
            return "Guida inviata al turno in corso."
        if nome == "stop":
            if not sess.busy:
                return ("Nessun turno in corso. (Per staccare questa chat "
                        "dal bot: /scollega.)")
            sess.cancel()
            return "Ho chiesto di fermare il turno."
        if nome == "nuova":
            if sess.busy:
                return "C'e' un turno in corso: /stop, poi /nuova."
            sess.reset()
            return ("Nuova conversazione. La precedente resta nella "
                    "cronologia di Orchestra.")
        if nome == "modello":
            return self._telegram_modello(b, argomento)
        return f"Comando /{nome} non riconosciuto. /aiuto per la lista."

    def _telegram_stato_bot(self, b: dict[str, Any], sess: Any) -> str:
        provider, _configurato = self._bot_provider_modello(b)
        righe = [f"{b.get('nome')} · {provider}",
                 f"Modello: {sess.modello_in_uso()}",
                 "Stato: al lavoro adesso" if sess.busy else "Stato: libero"]
        try:
            from . import telegram as tg

            if tg.codice_in_corso(b["id"]):
                righe.append("C'e' un codice di collegamento attivo "
                             "(vale dieci minuti).")
            if tg.chat_di(b["id"])[0]:
                righe.append("Chat Telegram collegata.")
        except Exception:  # noqa: BLE001
            pass
        if getattr(sess.agent, "modalita_piano", False):
            righe.append("Modalita' piano: attiva.")
        return "\n".join(righe)

    def _telegram_modello(self, b: dict[str, Any],
                          argomento: str) -> str | dict[str, Any]:
        argomento = (argomento or "").strip()
        # Un tocco su un pulsante non e' un nome scritto: la scelta e'
        # gia' stata fatta, va solo applicata o mostrata.
        if argomento.startswith("cb:"):
            return self._telegram_modulo(b, argomento[3:])
        provider, configurato = self._bot_provider_modello(b)
        attuale = (b.get("modello") or "").strip() or configurato
        if not argomento:
            # Senza nome si apre il modulo: prima il servizio, poi i
            # modelli, un tocco per attivare. Chiedere di scrivere
            # `provider/modello` funziona per chi li sa a memoria; gli
            # altri non hanno modo di indovinare un nome che esiste.
            modulo = self._telegram_modulo(b, "")
            return modulo
        modelli = self.telegram_modelli(provider)
        scelto, errore = _scegli_modello(argomento, modelli)
        if errore:
            return errore
        return self._telegram_salva_modello(b, scelto, bool(modelli))

    def _telegram_salva_modello(self, b: dict[str, Any], scelto: str,
                                verificato: bool) -> str:
        sess = self._sessione_bot(b)
        if sess.busy:
            return "C'e' un turno in corso: /stop, poi /modello."
        from . import bots as bots_mod

        if not bots_mod.aggiorna(b["id"], modello=scelto):
            return "Non sono riuscito a salvare il modello."
        # La sessione in memoria e' nata col modello vecchio: si butta, e
        # il prossimo messaggio ne crea una nuova. La conversazione non
        # si perde, si ricarica dallo storico.
        runtime = getattr(self, "_bots_runtime", None) or {}
        runtime.pop(int(b["id"]), None)
        avviso = "" if verificato else " (non ho potuto verificare il nome)"
        return (f"Modello cambiato in {scelto}{avviso}. Da adesso questo "
                "bot usa un modello suo, e vale dal prossimo messaggio.")

    def _telegram_servizi(self, attuale: str) -> list[tuple[str, str]]:
        """(id, nome) dei servizi con una credenziale, il corrente per primo.

        Un servizio senza chiave non compare: proporre un modello che non
        si puo' chiamare e' peggio che non proporlo, perche' lo si scopre
        solo dopo averlo scelto. Il servizio gia' in uso c'e' sempre,
        anche se la sua credenziale vive in un posto che questo menu non
        guarda (Nous la tiene in un token suo).
        """
        from . import keys as keys_mod
        from .providers import KNOWN_PROVIDERS

        try:
            presenti = {c["chiave"] for c in keys_mod.stato(ENV_PATH, self.env)
                        if c.get("presente")}
        except Exception:  # noqa: BLE001
            presenti = set()
        etichette = {s.get("id"): s.get("nome") for s in keys_mod.FREE_SERVICES}
        fuori: list[tuple[str, str]] = []
        for pid, (_url, chiave_env, _modello) in KNOWN_PROVIDERS.items():
            if chiave_env:
                if chiave_env not in presenti:
                    continue
            elif pid != attuale:
                # i motori locali non chiedono chiave: compaiono solo se
                # sono gia' quelli in uso, altrimenti sarebbero due
                # bottoni che rispondono "non raggiungibile".
                continue
            fuori.append((pid, str(etichette.get(pid) or pid)))
        if attuale and all(pid != attuale for pid, _n in fuori):
            fuori.append((attuale, str(etichette.get(attuale) or attuale)))
        fuori.sort(key=lambda v: (v[0] != attuale, v[1].lower()))
        return fuori

    def _telegram_nome_servizio(self, provider: str) -> str:
        from . import keys as keys_mod

        for s in keys_mod.FREE_SERVICES:
            if s.get("id") == provider:
                return str(s.get("nome") or provider)
        return provider

    def _telegram_ordina_modelli(self, provider: str, elenco: list[str],
                                 attuale: str) -> list[str]:
        """I modelli nell'ordine in cui qualcuno li sceglierebbe col pollice.

        In ordine alfabetico la prima pagina di OpenRouter e' "ai21/...":
        il modello buono sta a pagina nove e nessuno ci arriva. Prima
        quello in uso, poi i gratuiti che sanno usare i tool, poi gli
        altri con i tool, poi il resto — lo stesso criterio con cui l'app
        sceglie da sola quando deve.
        """
        cat = (getattr(self, "_catalog_per_provider", None) or {}).get(provider)
        profili = getattr(cat, "models", None) or {}

        def rango(mid: str) -> tuple:
            info = getattr(profili.get(mid), "info", None)
            gratis = bool(getattr(info, "is_free", False))
            tool = getattr(info, "supports_tools", None) is True
            return (mid != attuale, not gratis, not tool, mid.lower())

        return sorted(elenco, key=rango)

    def _telegram_modulo(self, b: dict[str, Any],
                         dati: str) -> dict[str, Any] | str:
        """Il modulo a bottoni di `/modello`, con lo stato dentro i pulsanti.

        Nessuna memoria lato server: `callback_data` dice da solo cosa
        fare (servizio, pagina, indice del modello), quindi anche un
        modulo rimasto nella chat per un giorno funziona se il catalogo
        non e' cambiato — e se e' cambiato lo dice invece di applicare il
        modello sbagliato.
        """
        provider, configurato = self._bot_provider_modello(b)
        attuale = (b.get("modello") or "").strip() or configurato
        dati = (dati or "").strip()

        if dati == "x":
            return {"testo": "Va bene: non ho cambiato niente."}
        if dati.startswith("s:") and len(dati) > 2:
            return self._telegram_modulo_modelli(dati[2:].strip(), attuale, 0)
        if dati.startswith("p:"):
            parti = dati[2:].split(":")
            if len(parti) != 2 or not parti[0]:
                return "Modulo scaduto: riscrivi /modello."
            try:
                pagina = int(parti[1])
            except ValueError:
                pagina = 0
            return self._telegram_modulo_modelli(parti[0], attuale, pagina)
        if dati.startswith("m:"):
            parti = dati[2:].split(":")
            if len(parti) != 2 or not parti[0]:
                return "Modulo scaduto: riscrivi /modello."
            elenco = self.telegram_modelli(parti[0])
            try:
                scelto = elenco[int(parti[1])]
            except (ValueError, IndexError):
                return ("Quel modello non e' piu' nell'elenco: riscrivi "
                        "/modello.")
            return self._telegram_salva_modello(b, scelto, True)

        servizi = self._telegram_servizi(provider)
        if len(servizi) == 1:
            # Un solo servizio collegato: chiedere "quale servizio?" per
            # poi aprire una lista con dentro solo quello e' un tocco in
            # piu' per niente.
            return self._telegram_modulo_modelli(servizi[0][0], attuale, 0)
        righe = [[{"testo": ("✓ " if pid == provider else "") + nome,
                   "dati": f"s:{pid}"}] for pid, nome in servizi]
        return {"testo": (f"Modello: {attuale or '?'} ({provider})\n"
                           "Scegli il servizio:"),
                "tastiera": righe}

    def _telegram_modulo_modelli(self, provider: str, attuale: str,
                                 pagina: int) -> dict[str, Any] | str:
        elenco = self.telegram_modelli(provider)
        nome = self._telegram_nome_servizio(provider)
        if not elenco:
            return (f"Non riesco a leggere l'elenco dei modelli di {nome}: "
                    "la rete non ha risposto. Puoi cambiarlo lo stesso con "
                    "/modello <nome>, senza che il nome venga controllato.")
        ordinati = self._telegram_ordina_modelli(provider, elenco, attuale)
        visibili = ordinati[:MENU_MASSIMO]
        per_pagina = MODELLI_PER_PAGINA
        pagine = max(1, (len(visibili) + per_pagina - 1) // per_pagina)
        pagina = max(0, min(int(pagina or 0), pagine - 1))
        fetta = visibili[pagina * per_pagina:(pagina + 1) * per_pagina]
        righe: list[list[dict[str, str]]] = []
        for mid in fetta:
            try:
                # L'indice e' quello alfabetico, non quello mostrato:
                # cambiando il modello in uso l'ordine si sposta, e un
                # pulsante vecchio applicherebbe il modello sbagliato.
                posizione = elenco.index(mid)
            except ValueError:
                continue
            righe.append([{"testo": ("✓ " if mid == attuale else "") + mid,
                           "dati": f"m:{provider}:{posizione}"}])
        if pagine > 1:
            naviga: list[dict[str, str]] = []
            if pagina > 0:
                naviga.append({"testo": "«",
                               "dati": f"p:{provider}:{pagina - 1}"})
            if pagina < pagine - 1:
                naviga.append({"testo": "»",
                               "dati": f"p:{provider}:{pagina + 1}"})
            righe.append(naviga)
        if len(self._telegram_servizi(provider)) > 1:
            righe.append([{"testo": "Cambia servizio", "dati": "S"}])
        testo = [f"{nome} · {len(ordinati)} modelli · pagina "
                 f"{pagina + 1}/{pagine}",
                 f"Modello attuale: {attuale or 'nessuno'}",
                 "Tocca un modello per attivarlo."]
        altri = len(ordinati) - len(visibili)
        if altri:
            testo.append(f"Qui i {len(visibili)} piu' utili; gli altri "
                         f"{altri} si trovano con /modello <parte del nome>.")
        elif pagine > 1:
            testo.append("Sono tanti: /modello <parte del nome> li cerca.")
        return {"testo": "\n".join(testo), "tastiera": righe}

    def telegram_modelli(self, provider: str) -> list[str]:
        """I modelli di un provider, dal catalogo.

        Costa una richiesta di rete una volta per provider, e la fa un
        comando, non un turno. Se la rete non risponde la lista resta
        vuota e chi chiama lo dice: meglio di una lista vuota che fa
        credere che quel provider non abbia modelli.
        """
        provider = (provider or "").strip()
        if not provider:
            return []
        cache = getattr(self, "_catalog_per_provider", None)
        if cache is None:
            cache = self._catalog_per_provider = {}
        cat = cache.get(provider)
        if cat is None:
            from .catalog import Catalog

            try:
                cat = Catalog.fetch(provider)
            except Exception:  # noqa: BLE001
                return []
            if cat is None or not getattr(cat, "models", None):
                return []
            cache[provider] = cat
        return sorted(cat.models)

    def telegram_attivi(self) -> set[int]:
        """Quali bot hanno un ponte che sta davvero girando."""
        return {int(k) for k, p in
                (getattr(self, "_telegram_ponti", {}) or {}).items()
                if p.attivo}

    def telegram_sync(self) -> int:
        """Allinea i ponti ai token salvati. Torna quanti sono attivi.

        Una funzione sola per tutti i casi — token nuovo, token tolto,
        bot eliminato — perche' tre punti che avviano e fermano thread
        sono tre occasioni di lasciarne uno acceso.
        """
        if not getattr(self, "_telegram_on", False):
            return 0
        from . import bots as bots_mod
        from . import telegram as tg

        ponti = getattr(self, "_telegram_ponti", None)
        if ponti is None:
            ponti = self._telegram_ponti = {}
        voluti: dict[int, tuple[str, str]] = {}
        for riga in tg.tutti():
            if not riga["token"]:
                continue
            b = bots_mod.per_id(riga["bot_id"])
            if b is None:
                continue
            voluti[int(riga["bot_id"])] = (riga["token"], b["nome"])
        for bid, ponte in list(ponti.items()):
            if bid not in voluti or voluti[bid][0] != ponte.api.token:
                ponte.ferma()
                ponti.pop(bid, None)
        for bid, (token, nome) in voluti.items():
            esistente = ponti.get(bid)
            if esistente is not None and esistente.attivo:
                continue
            ponte = esistente or tg.Ponte(
                bid, nome, tg.Api(token),
                (lambda testo, allegati=None, avanzamento=None, b=bid:
                 self.telegram_turno(b, testo, allegati, avanzamento)),
                comandi=(lambda cmd, arg="", b=bid:
                         self.telegram_comando(b, cmd, arg)),
                log=_log_telegram)
            ponti[bid] = ponte
            ponte.avvia()
        return len(ponti)

    def telegram_avvia(self) -> int:
        """Da chiamare una volta, quando il server parte.

        Non parte da `create`: chi costruisce l'app per provarla non
        deve ritrovarsi un thread che parla con Telegram.
        """
        self._telegram_on = True
        try:
            from . import telegram as tg

            tg.pulisci()
        except Exception:  # noqa: BLE001
            pass
        return self.telegram_sync()

    def _salva_bot_attivo(self, nome: str) -> None:
        try:
            from . import keys as keys_mod

            keys_mod.scrivi(ENV_PATH, "ORCHESTRA_BOT", nome)
        except Exception:  # noqa: BLE001
            pass

    def attiva_bot(self, bot_id: int | str | None) -> dict[str, Any]:
        """Passa da un'identita' all'altra. None = agente principale.

        Cambiare identita' NON ferma il turno di quella che lasci. Le
        Session sono indipendenti, ognuna col suo filo: il lavoro
        continua nella sua sessione e lo ritrovi quando ci torni. E'
        esattamente il caso d'uso di due bot su due progetti — e
        bloccare il cambio costringerebbe ad aspettare il primo per
        poter avviare il secondo, che e' il problema da cui nascono i
        lavori in background.

        Il turno lasciato non trasmette piu' eventi alla UI (lo stream
        segue la sessione attiva), ma la conversazione e il risultato
        restano: al ritorno lo snapshot li ricostruisce. L'unica cosa
        che resta vietata e' mandare un secondo messaggio alla stessa
        sessione mentre e' occupata: quello la Session lo rifiuta.
        """
        from . import bots as bots_mod

        if bot_id in (None, "", 0, "0"):
            if getattr(self, "_sessione_principale", None) is not None:
                self.session = self._sessione_principale
                self._sessione_principale = None
            self._bot_attivo_id = 0
            self.env["ORCHESTRA_BOT"] = ""
            self._salva_bot_attivo("")
            return {"ok": True, "bot": None}
        b = bots_mod.per_id(bot_id)
        if b is None:
            raise ValueError(f"bot inesistente: {bot_id}")
        if int(getattr(self, "_bot_attivo_id", 0) or 0) == int(b["id"]):
            return {"ok": True, "bot": b}
        sess = self._sessione_bot(b)
        if getattr(self, "_sessione_principale", None) is None:
            self._sessione_principale = self.session
        self.session = sess
        self._bot_attivo_id = int(b["id"])
        self.env["ORCHESTRA_BOT"] = b["nome"]
        self._salva_bot_attivo(b["nome"])
        self.ready = self.session is not None
        self.error = ""
        return {"ok": True, "bot": b}

    def crea_bot(self, **campi: Any) -> dict[str, Any]:
        """Crea un bot, scegliendo un modello se il provider lo richiede."""
        from . import bots as bots_mod

        provider = str(campi.get("provider") or "").strip().lower()
        modello = str(campi.get("modello") or "").strip()
        if provider and not modello \
                and provider != (self.env.get("ORCHESTRA_PROVIDER") or ""):
            try:
                modello = self._modello_per_servizio(provider, "") or ""
            except Exception:  # noqa: BLE001
                modello = ""
            if modello:
                campi["modello"] = modello
        return bots_mod.crea(**campi)

    def aggiorna_bot(self, bot_id: int | str, **campi: Any) -> dict | None:
        from . import bots as bots_mod

        runtime = getattr(self, "_bots_runtime", {}) or {}
        rt = runtime.get(int(bot_id)) if str(bot_id).isdigit() else None
        if rt is not None and rt["sessione"].busy:
            raise RuntimeError(
                "il bot sta lavorando: attendi o annulla prima di "
                "modificarlo")
        if str(bot_id).isdigit():
            try:
                from . import lavori as lavori_mod

                riass = lavori_mod.riassunto("bot", str(int(bot_id)))
                if riass.get("in_attesa") or riass.get("in_corso"):
                    raise RuntimeError(
                        "il bot ha lavori in coda: attendi che finiscano "
                        "prima di modificarlo")
            except RuntimeError:
                raise
            except Exception:  # noqa: BLE001
                pass
        b = bots_mod.aggiorna(bot_id, **campi)
        if b is None:
            return None
        # La configurazione e' cambiata: la sessione viva non la riflette
        # piu'. Si butta e si ricostruisce al prossimo uso — tenere una
        # sessione col vecchio prompt sarebbe peggio che perdere il
        # contesto, perche' l'utente crede di aver cambiato l'identita'.
        runtime.pop(int(b["id"]), None)
        attivo_id = int(getattr(self, "_bot_attivo_id", 0) or 0)
        if int(b["id"]) == attivo_id and self.session is not None:
            self.session = self._sessione_bot(b)
        return b

    def elimina_bot(self, bot_id: int | str) -> bool:
        from . import bots as bots_mod

        b = bots_mod.per_id(bot_id)
        if b is None:
            return False
        try:
            from . import lavori as lavori_mod

            riass = lavori_mod.riassunto("bot", str(b["id"]))
            if riass.get("in_attesa") or riass.get("in_corso"):
                raise RuntimeError(
                    "il bot ha lavori in coda: attendi o annulla")
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            pass
        # Il controllo va PRIMA di cambiare identita': altrimenti si
        # tornerebbe al principale e solo dopo si scoprirebbe che il bot
        # non si puo' eliminare, lasciando l'utente su un'identita'
        # diversa da quella che credeva.
        rt = (getattr(self, "_bots_runtime", {}) or {}).get(int(b["id"]))
        if rt is not None and rt["sessione"].busy:
            raise RuntimeError("il bot sta lavorando: attendi o annulla")
        if int(b["id"]) == int(getattr(self, "_bot_attivo_id", 0) or 0):
            self.attiva_bot(None)
        (getattr(self, "_bots_runtime", {}) or {}).pop(int(b["id"]), None)
        (getattr(self, "_bots_fili", {}) or {}).pop(int(b["id"]), None)
        fatto = bots_mod.elimina(b["id"])
        if fatto:
            # Un token dimenticato e' un bot ancora vivo su Telegram che
            # risponde a una chat che nessuno guarda.
            try:
                from . import telegram as tg

                tg.salva_token(b["id"], "")
                self.telegram_sync()
            except Exception:  # noqa: BLE001
                pass
            try:
                from . import lavori as lavori_mod

                # I checkout del bot non devono restare orfani: senza la
                # riga del lavoro nessuno saprebbe piu' che esiste, e
                # nessuno potrebbe scartarli dal pannello. Best effort:
                # un checkout gia' spostato a mano non deve impedire
                # l'eliminazione del bot.
                from . import worktree as worktree_mod
                for info in lavori_mod.worktree_di("bot", str(b["id"])):
                    if not info.get("scartato"):
                        try:
                            worktree_mod.rimuovi(info)
                        except Exception:  # noqa: BLE001
                            pass
                lavori_mod.elimina_chiave("bot", str(b["id"]))
            except Exception:  # noqa: BLE001
                pass
        return fatto

    def _ripristina_bot(self) -> None:
        """Riapri l'ultimo bot attivo, se c'era.

        Un riavvio non deve riportare l'utente nella chat dell'agente
        principale mentre il bot con cui stava lavorando e' ancora la'. La
        scelta si salva in `.env` come ORCHESTRA_BOT, nello stesso posto e
        nello stesso modo del modello.
        """
        nome = (self.env.get("ORCHESTRA_BOT") or "").strip()
        if not nome:
            return
        from . import bots as bots_mod

        b = bots_mod.per_nome(nome)
        if b is None:
            self.env["ORCHESTRA_BOT"] = ""
            self._salva_bot_attivo("")
            return
        try:
            self.attiva_bot(b["id"])
        except Exception:  # noqa: BLE001
            pass

    def _collega_delega(self, sessione: Session | None = None) -> None:
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
        # La delega si collega alla sessione che la riceve, non sempre a
        # quella attiva: un bot ha la sua, e il figlio deve nascere col
        # provider e col progetto del bot che delega, non con quelli
        # dell'agente principale.
        sess = sessione or self.session
        if sess is None:
            return
        nome_provider = (getattr(getattr(sess, "agent", None), "provider", None)
                        and getattr(sess.agent.provider, "name", ""))
        nome_provider = nome_provider or self.env.get("ORCHESTRA_PROVIDER",
                                                       "openrouter")
        env_chiavi = ambiente(ENV_PATH)

        def fabbrica(obiettivo: str):
            # Il figlio nasce nel progetto in cui sta lavorando il
            # padre. Due cose devono viaggiare: il NOME (e' quello
            # che etichetta i fatti di memoria) e la CARTELLA (e' li'
            # che il figlio scrive).
            #
            # Senza, un figlio che produce un file lo mette nella
            # cartella di installazione: il padre riceve un "fatto"
            # che riguarda un posto che non gli e' stato chiesto, e
            # il progetto giusto resta vuoto. E' il tipo di difetto
            # che non si vede finche' il progetto giusto e' pieno di
            # file dell'altro.
            progetto = ""
            percorso = ""
            try:
                progetto = getattr(sess, "progetto", "") or ""
            except Exception:  # noqa: BLE001
                progetto = ""
            if progetto:
                try:
                    from . import progetti as _pr
                    percorso = _pr.percorso_di(progetto)
                except Exception:  # noqa: BLE001
                    percorso = ""
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
            # Il tetto dei passi è quello del PADRE, non un numero fisso.
            # Prima era 16 hard-coded, e cambiavo le Opzioni del padre che
            # il figlio non se ne accorgeva: due numeri diversi per la
            # stessa scelta, e quello del figlio non si poteva toccare da
            # nessuna parte. Adesso leggono la stessa impostazione.
            # Limite di sicurezza: se il padre ne ha pochi (o zero), il
            # figlio non può averne di più — un figlio non allarga il
            # lavoro che gli hanno dato.
            try:
                passi_padre = int(
                    self.env.get("ORCHESTRA_MAX_ITERS", "")
                    or sess.agent.config.max_iterations)
            except (TypeError, ValueError):
                passi_padre = 20
            passi_figlio = max(1, min(passi_padre, 50))
            # La root del padre va impostata PRIMA di creare il
            # figlio: il thread del padre e' un thread diverso da
            # quello in cui il figlio girera', e la root sta nel
            # thread. Impostarla qui, e' l'unico modo che funzioni.
            try:
                from . import progetti as _pr
                _pr._set_root_sessione(percorso, progetto)
            except Exception:  # noqa: BLE001
                pass
            figlio = Agent(
                build_provider(nome_provider, model=modello, env=env_chiavi),
                default_registry(),          # NUOVO: senza 'delega'
                PROMPT_FIGLIO,
                LoopConfig(max_iterations=passi_figlio, context_limit=60_000,
                           keep_recent=6),
                # Il figlio NON e' piu' muto: i suoi eventi passano al
                # bridge del padre con un tag `figlio`. Prima era
                # `lambda: None`, e quando il figlio si incagliava sui
                # tool (gira a vuoto su run_shell, per esempio) non si
                # vedeva niente — ne' nell'UI ne' nel log — e l'unico
                # indizio era "ha finito i passi senza risposta", che
                # non dice DOVE. Adesso si vede cosa ha tentato.
                on_event=lambda kind, data: sess.bridge.emit(
                    "figlio", {"tipo": kind, **(data or {})}),
            )
            # Il figlio sa su quale progetto lavora: e' lui che mette
            # il blocco del progetto nel prompt e che etichetta i
            # suoi fatti. Senza, il padre lavora sul sito del
            # ristorante e il figlio scrive nella cartella di
            # installazione.
            try:
                figlio.progetto = progetto
                figlio._aggiorna_prompt()
            except Exception:  # noqa: BLE001
                pass
            # Il figlio non allarga i permessi del padre: nasce con
            # `default_registry()` (tutti i tool), e senza questa riga la
            # delega sarebbe la porta per aggirare la policy del bot.
            # Il thread e' lo stesso del padre, quindi la policy della
            # shell e' gia' attiva; qui si restringe il registro.
            try:
                from . import policy as policy_mod
                policy_mod.applica_al_registro(
                    figlio.registry, getattr(sess, "_policy", {}) or {})
            except Exception:  # noqa: BLE001
                pass
            return figlio

        sess._fabbrica_figlio = fabbrica
        # il catalogo serve al tariffario del figlio: senza i prezzi del
        # modello che ha lavorato, il costo di una delega resta sconosciuto
        # Solo se il catalogo e' GIA' caricato: `app.catalog` lo scarica al
        # primo accesso, e attivare un bot non deve fare una chiamata di
        # rete solo per conoscere dei prezzi che servono a una delega che
        # forse non ci sara'.
        sess._catalogo_per_costo = getattr(app, "_catalog", None)
        attiva = sess.attiva_delega()
        if sess is self.session:
            self.delega_attiva = attiva

    def _aggancia_storico(self) -> None:
        """Collega la sessione allo storico su disco.

        All'avvio si riapre l'ULTIMA conversazione, non se ne crea una
        nuova: l'utente chiude il browser e lo riapre aspettandosi di
        ritrovare quello che stava facendo, non una pagina bianca con la
        chat di ieri sparita da qualche parte.

        Se il DB non si può aprire, si continua senza storico invece di
        fermare l'avvio: una chat che funziona e non salva è un difetto,
        una chat che non parte è un blocco.
        """
        if self.session is None:
            self._storico = None
            return
        try:
            from .storico import storico
            self._storico = storico()
            ultima = self._storico.elenco(limite=1)
            if ultima:
                sid = int(ultima[0]["id"])
                if self.session.carica_sessione(sid):
                    return
            # Niente da riaprire: NON si crea una riga adesso. La riga
            # nasce al primo messaggio vero (`_salva_su_disco`), non
            # all'avvio: crearne una vuota qui la faceva comparire in
            # cronologia senza contenuto, e toccava eliminarla a mano.
            # La sessione resta senza id: `_salva_su_disco` lo mette al
            # primo turno.
        except Exception:
            self._storico = None

    @classmethod
    def _pulizia_tools_obsoleti(cls) -> None:
        """Rimuove il vecchio orchestra/tools.py se la cartella orchestra/tools/
        esiste gia'. Senza questo, Python sceglie il file e ignora il package,
        rompendo l'import di orchestra.tools.memoria e degli altri tool."""
        here = os.path.dirname(os.path.abspath(__file__))
        vecchio_file = os.path.join(here, "tools.py")
        nuova_cartella = os.path.join(here, "tools")
        if os.path.isfile(vecchio_file) and os.path.isdir(nuova_cartella):
            try:
                os.remove(vecchio_file)
            except OSError:
                pass  # se non si puo' rimuovere, l'errore emergera' dopo

    @classmethod
    def create(cls, remoto_attivo: bool = False) -> "OrchestraApp":
        """Costruisce l'app, o la mette in stato di errore se il provider
        non e' configurato. La UI deve poter mostrare l'errore invece di
        fallire all'avvio."""
        cls._pulizia_tools_obsoleti()
        env = ambiente(ENV_PATH)
        try:
            app = cls(
                env,
                session=cls._make_session(
                    env.get("ORCHESTRA_PROVIDER", "openrouter"),
                    env.get("ORCHESTRA_MODEL", ""),
                ),
                remoto_attivo=remoto_attivo,
            )
            app._collega_recupero_tool()
            app._collega_delega()
            app._ripara_modello_iniziale()
            # Dopo il modello: il bot attivo puo' averne uno suo, e la
            # riparazione del modello riguarda l'agente principale.
            app._ripristina_bot()
            # Le code dei bot sono su disco: un lavoro messo prima del
            # riavvio deve ripartire adesso. I lavori a meta' vengono
            # marcati interrotti, non rieseguiti alla cieca.
            try:
                app._riprendi_lavori_bot()
            except Exception:  # noqa: BLE001
                pass
            # La finestra del modello attivo, se il catalogo lo conosce.
            # In try separato: se il catalogo non si apre, l'app parte
            # comunque col default di 120k. Un limite prudente batte un
            # avvio che muore per un'impostazione.
            try:
                app.allinea_finestra()
            except Exception:
                pass
            return app
        except (ProviderError, KeyError) as e:
            # l'app esiste anche senza sessione: /api/state deve poter
            # rispondere con l'errore, e la UI lo mostra
            app = cls(env, session=None, remoto_attivo=remoto_attivo)
            app.ready = False
            app.error = str(e)
            return app


class Handler(Rotte, BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app: OrchestraApp  # impostato dal server

    # silenzio: il log di ogni richiesta SSE èrumore
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def send_error(self, code: int, message: str | None = None,
                   explain: str | None = None) -> None:
        # Per le API mai HTML: la UI fa resp.json() su tutto, e una pagina
        # di errore standard diventerebbe un SyntaxError illeggibile.
        try:
            path = (self.path or "").split("?")[0]
        except Exception:
            path = ""
        if path.startswith("/api/"):
            try:
                testo = f"errore {code}" + (f": {message}" if message else "")
                stato = code if isinstance(code, int) and 100 <= code < 600 else 500
                self._json({"error": testo}, stato)
            except Exception:
                pass
            return
        super().send_error(code, message, explain)

    # handle_error e' sulla sottoclasse OrchestraServer: socketserver chiama
    # server.handle_error (non handler.handle_error), quindi una definizione
    # qui non avrebbe alcun effetto. La gestione delle chiusure improvvise
    # del client vive li'.

    # -- helper ------------------------------------------------------------

    def _send_bytes(self, code: int, body: bytes, content_type: str,
                    headers: dict[str, str] | None = None) -> None:
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
        # Header aggiuntivi della singola risposta: oggi solo `Allow`,
        # che un 405 deve avere per dire quali metodi esistono.
        for nome, valore in (headers or {}).items():
            self.send_header(nome, valore)
        self.end_headers()
        self.wfile.write(body)

    def _council_pdf(self) -> None:
        try:
            from .pdf_mini import text_to_pdf
            st = self.app.council_status()
            text = st.get("verdict") or "Nessun verdict disponibile."
            # appendi la trascrizione completa (round 1/2/3) dopo il verdict,
            # cosi' il PDF contiene anche cio' che hanno detto i mentor.
            sdir = (st.get("session_dir") or "").strip()
            if sdir and os.path.isdir(sdir):
                parts = [text]
                for rn in (1, 2, 3):
                    rp = os.path.join(sdir, f"round-{rn}.md")
                    if os.path.isfile(rp):
                        try:
                            with open(rp, encoding="utf-8") as f:
                                parts.append(f.read())
                        except OSError:
                            pass
                text = "\n\n".join(parts)
            data = text_to_pdf(text, "Consiglio")
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", "attachment; filename=consiglio.pdf")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)

    def _json(self, obj: Any, code: int = 200, *,
              headers: dict[str, str] | None = None) -> None:
        self._send_bytes(code, json.dumps(obj).encode("utf-8"),
                         "application/json; charset=utf-8", headers)

    # I file restano separati su disco: ognuno ha una responsabilita' e
    # resta testabile da solo. Al browser arrivano in uno, perche' piu'
    # richieste significa piu' modi in cui la pagina resta a meta' — e con
    # un solo script inline (la versione monolitica) funzionava.
    # `panels.js` era un file da 5.320 righe: ora ogni area della UI ha il
    # suo. L'ordine conta (le funzioni si chiamano fra loro a livello di
    # file), e per questo sta qui e non in un test: e' il server a
    # concatenarli, e `tests/_ordine.py` legge questa lista.
    BUNDLE_ORDER = (
        "core.js",
        "panels-bench.js", "panels-opzioni.js", "panels-lavoro.js",
        "panels-skill.js", "panels-storia.js", "panels-shell.js",
        "panels-progetto.js", "panels-automazioni.js", "panels-bot.js",
        "modelpick.js", "main.js",
    )

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

    def _guida(self) -> None:
        """La guida utente, con la versione del pacchetto al posto del segnaposto.

        Il file dice `{{versione}}` e non un numero scritto a mano: la guida
        era rimasta a 0.5.45 per venticinque versioni, e un utente che la
        leggeva per capire quale versione aveva veniva informato male. Qui la
        versione e' una sola, quella di `__version__`, e nessuno deve
        ricordarsene a ogni release.
        """
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "web", "docs.html")
        try:
            with open(path, "rb") as f:
                html = f.read().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            self._json({"error": "guida non trovata"}, 404)
            return
        corpo = html.replace("{{versione}}", __version__).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(corpo)

    def _portrait(self, name: str) -> None:
        if not name or not all(c.isalnum() or c in "._-" for c in name):
            self._json({"error": "nome file non valido"}, 400)
            return
        portraits_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "web", "portraits")
        path = os.path.join(portraits_dir, name)
        if not os.path.abspath(path).startswith(portraits_dir + os.sep):
            self._json({"error": "non trovato"}, 404)
            return
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._json({"error": "non trovato"}, 404)
            return
        ct = "image/webp"
        if name.endswith(".png"):
            ct = "image/png"
        elif name.endswith(".jpg") or name.endswith(".jpeg"):
            ct = "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
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

    def _login_page(self) -> None:
        html = """<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra — Accesso</title>
<style>body{font-family:system-ui,sans-serif;background:#0f1115;color:#e6e6e6;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#1a1d24;padding:24px;border-radius:12px;width:320px;box-shadow:0 8px 30px rgba(0,0,0,.4)}
h1{font-size:18px;margin:0 0 12px}p{font-size:13px;color:#9aa0a6;margin:0 0 16px}
input{width:100%;padding:10px;border-radius:8px;border:1px solid #2a2e36;background:#0f1115;color:#e6e6e6;box-sizing:border-box}
button{width:100%;padding:10px;margin-top:12px;border:none;border-radius:8px;background:#4f8cff;color:#fff;font-weight:600;cursor:pointer}
.err{color:#ff6b6b;font-size:12px;margin-top:8px;display:none}</style></head>
<body><div class="card"><h1>Accesso remoto</h1><p>Incolla il token mostrato sul PC (oppure nelle impostazioni di Orchestra).</p>
<input id="tok" type="password" placeholder="token" autocomplete="off">
<button id="btn">Entra</button><div class="err" id="err">Token non valido</div></div>
<script>
document.getElementById('btn').onclick=async()=>{const t=document.getElementById('tok').value.trim();
const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:t})});
if(r.ok){location.href='/'}else{document.getElementById('err').style.display='block'}};
document.getElementById('tok').addEventListener('keydown',e=>{if(e.key==='Enter')document.getElementById('btn').click()});
</script></body></html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _info_remoto(self) -> dict[str, Any]:
        app = self.app
        ip = ""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            ip = "127.0.0.1"
        port = getattr(app, "porta", 8737) or 8737
        lan_url = f"http://{ip}:{port}" if ip else ""
        return {
            "attivo": bool(getattr(app, "remoto_attivo", False)),
            "token": getattr(app, "token_remoto", "") or "",
            "tunnel_url": getattr(app, "tunnel_url", "") or "",
            "lan_url": lan_url,
        }

    def _porta_libera(self) -> int:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _leggi_stato_remoto(self) -> dict[str, Any]:
        try:
            with open(REMOTE_STATE_PATH, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (OSError, ValueError):
            return {}

    def _scrivi_stato_remoto(self, stato: dict[str, Any]) -> None:
        try:
            with open(REMOTE_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(stato, f)
        except OSError:
            pass

    def _pid_vivo(self, pid: int) -> bool:
        if not pid:
            return False
        try:
            import os as _os
            _os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _api_remote_status(self, corpo: dict[str, Any]) -> dict[str, Any]:
        stato = self._leggi_stato_remoto()
        pid = int(stato.get("pid") or 0)
        vivo = self._pid_vivo(pid)
        if stato and not vivo:
            try:
                os.remove(REMOTE_STATE_PATH)
            except OSError:
                pass
            stato = {}
        # anche il server corrente se e' remoto
        app = self.app
        if getattr(app, "remoto_attivo", False) and not stato:
            info = self._info_remoto()
            stato = {
                "pid": os.getpid(),
                "port": getattr(app, "porta", 8737) or 8737,
                "url": info.get("lan_url") or "",
                "tunnel_url": info.get("tunnel_url") or "",
                "token": info.get("token") or "",
                "mode": "remote",
                "self": True,
            }
        return {"ok": True, "stato": stato, "vivo": bool(stato)}

    def _api_remote_start(self, corpo: dict[str, Any]) -> dict[str, Any]:
        mode = str(corpo.get("mode") or "remote").strip().lower()
        if mode not in ("remote", "tunnel"):
            mode = "remote"
        # genera token se manca
        app = self.app
        if not (app.token_remoto or ""):
            app.token_remoto = app._token_remoto(forza=True)
        token = app.token_remoto or ""
        if not token:
            return {"ok": False, "errore": "impossibile generare il token"}
        # se gia' attivo, ritorna stato
        stato = self._leggi_stato_remoto()
        pid = int(stato.get("pid") or 0)
        if pid and self._pid_vivo(pid):
            return {"ok": True, "gia_attivo": True, "stato": stato}
        porta = self._porta_libera()
        # comando
        import sys as _sys
        cmd = [_sys.executable, "-m", "orchestra.cli", "web",
               "--host", "0.0.0.0", "--port", str(porta),
               "--no-browser"]
        if mode == "tunnel":
            cmd.append("--tunnel")
        else:
            cmd.append("--remote")
        # persisti token in env del subprocess tramite .env (gia' scritto)
        try:
            import subprocess
            log_path = os.path.join(HERE, ".remote.log")
            lf = open(log_path, "a", encoding="utf-8")
            flags = 0
            if os.name == "nt":
                flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf,
                                    creationflags=flags, close_fds=True)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "errore": str(e)}
        # attendi che il server sia pronto (poll stato file o porta)
        import time as _t
        import urllib.request
        url = f"http://127.0.0.1:{porta}"
        pronto = False
        for _ in range(40):
            _t.sleep(0.5)
            try:
                with urllib.request.urlopen(url + "/api/remote/info" if False else url + "/", timeout=1) as r:
                    if r.status < 500:
                        pronto = True
                        break
            except Exception:
                pass
        # leggi tunnel_url dallo stato file (scritto dal subprocess se tunnel)
        tunnel_url = ""
        for _ in range(10):
            st = self._leggi_stato_remoto()
            if st.get("pid") == proc.pid or st.get("port") == porta:
                tunnel_url = st.get("tunnel_url") or ""
                if tunnel_url or mode != "tunnel":
                    break
            _t.sleep(0.5)
        stato = {
            "pid": proc.pid,
            "port": porta,
            "url": f"http://{self._ip_lan()}:{porta}",
            "tunnel_url": tunnel_url,
            "token": token,
            "mode": mode,
        }
        self._scrivi_stato_remoto(stato)
        return {"ok": True, "stato": stato}

    def _api_remote_stop(self, corpo: dict[str, Any]) -> dict[str, Any]:
        stato = self._leggi_stato_remoto()
        pid = int(stato.get("pid") or 0)
        if pid and pid != os.getpid():
            try:
                if os.name == "nt":
                    import subprocess
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   capture_output=True)
                else:
                    import signal
                    os.kill(pid, 9)
            except Exception:
                pass
        try:
            os.remove(REMOTE_STATE_PATH)
        except OSError:
            pass
        return {"ok": True}

    def _ip_lan(self) -> str:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

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

    def _imposta_verifica(self, specifiche: list) -> None:
        """Traduce i controlli scelti dall'utente in verificatori oggettivi.

        `specifiche` è una lista di dict dichiarativi dal frontend, es.:
          {"tipo": "json_campi", "file": "out.json", "campi": ["totale"]}
          {"tipo": "testo_presente", "file": "appunti.md"}
          {"tipo": "json_somma", "file": "v.json", "campo": "totale", "somma": 42}

        Li traduco nei verificatori veri (verificatori.py) e li attacco al
        config del giro. Se qualcosa non torna — tipo ignoto, file mancante
        — quel controllo si SALTA invece di far cadere il turno: una
        verifica rotta non deve bloccare l'invio. Se non resta nessun
        verificatore valido, la self-correzione non si attiva e il turno
        gira come al solito.
        """
        from . import verificatori as V
        cat = {
            "testo_presente": lambda s: V.v_testo_presente(s["file"]),
            "testo_lungo": lambda s: V.v_testo_lungo(
                s["file"], minimo=int(s.get("minimo", 1)),
                massimo=int(s.get("massimo", 10_000_000))),
            "testo_contiene": lambda s: V.v_testo_contiene(s["file"], s.get("frammenti", [])),
            "json_campi": lambda s: V.v_json_campi(s["file"], s.get("campi", [])),
            "json_valori": lambda s: V.v_json_valori(s["file"], s.get("attesi", {})),
            "json_somma": lambda s: V.v_json_somma(s["file"], s["campo"], float(s.get("somma", 0))),
        }
        verificatori = []
        for s in specifiche:
            if not isinstance(s, dict):
                continue
            tipo = s.get("tipo")
            if not s.get("file") or tipo not in cat:
                continue
            try:
                verificatori.append(cat[tipo](s))
            except Exception:
                continue
        cfg = self.app.session.agent.config
        if verificatori:
            cfg.verifica_compito = {
                "verificatori": verificatori,
                "work": "",
                "max_tentativi": 3,
            }
        else:
            cfg.verifica_compito = None

    # -- difese contro il browser di un altro sito ------------------------
    #
    # Il token remoto protegge chi arriva da fuori, ma non protegge dal
    # CSRF: una pagina qualsiasi aperta nel browser puo' fare una POST
    # verso 127.0.0.1:8737, e se il server e' in locale non c'e' token da
    # indovinare. Il browser manda `Origin`, quindi si confronta con
    # l'Host: se non coincidono, la richiesta viene da un'altra origine e
    # non e' un'azione dell'utente su questa app.
    _RATE_LOCK = threading.Lock()
    _RATE: dict[str, list[float]] = {}

    def _origine_ammessa(self) -> bool:
        """True se la POST arriva da questa stessa origine."""
        if (self.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
            return False
        orig = (self.headers.get("Origin") or "").strip()
        if not orig:
            # Client non-browser (curl, script, CLI): niente Origin. Il
            # token remoto resta l'autorizzazione per quelli.
            return True
        if orig.lower() == "null":
            return False
        try:
            o = urllib.parse.urlsplit(orig)
        except ValueError:
            return False
        if o.scheme not in ("http", "https"):
            return False
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False

        def _norm(valore: str) -> str:
            # http://host:80 e http://host sono la stessa origine.
            for prefisso, porta in (("http://", ":80"), ("https://", ":443")):
                if valore.startswith(prefisso) and valore.endswith(porta):
                    return valore[: -len(porta)]
            return valore

        return _norm(o.netloc.lower()) == _norm(host)

    def _limite(self, chiave: str, massimo: int, finestra: float) -> float:
        """Finestra scorrevole. Torna 0 se si puo' passare, o i secondi."""
        ora = time.monotonic()
        with self._RATE_LOCK:
            voci = self._RATE.setdefault(chiave, [])
            voci[:] = [t for t in voci if ora - t < finestra]
            if len(voci) >= massimo:
                return max(0.1, finestra - (ora - voci[0]))
            voci.append(ora)
            # Pulizia opportunistica: senza, un IP che cambia chiave a
            # ogni richiesta fa crescere il dizionario per sempre.
            if len(self._RATE) > 512:
                for k in [k for k, v in self._RATE.items()
                          if not v or ora - v[-1] > 3600]:
                    self._RATE.pop(k, None)
            return 0.0

    def _troppe_richieste(self, chiave: str, massimo: int,
                          finestra: float) -> bool:
        attesa = self._limite(chiave, massimo, finestra)
        if not attesa:
            return False
        self._json({"error": "troppe richieste",
                    "riprova": int(attesa) + 1}, 429)
        return True

    def _gate_remoto(self, path: str) -> bool:
        # Accesso remoto: se attivo e il client non e' localhost, serve
        # un token valido. Restituisce True se la richiesta puo' proseguire.
        if not getattr(self.app, "remoto_attivo", False):
            return True
        ip = (self.client_address[0] or "") if self.client_address else ""
        if ip in ("127.0.0.1", "::1", "localhost"):
            return True
        tok = getattr(self.app, "token_remoto", "") or ""

        def _uguale(a: str, b: str) -> bool:
            # Confronto a tempo costante: `==` si ferma al primo byte
            # diverso, e su una rete reale la differenza si misura.
            return bool(a) and bool(b) and hmac.compare_digest(a, b)

        # cookie
        for part in (self.headers.get("Cookie") or "").split(";"):
            part = part.strip()
            if part.startswith("orchestra_tok="):
                val = urllib.parse.unquote(part[len("orchestra_tok="):])
                if _uguale(val, tok):
                    return True
        # bearer
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer ") and _uguale(auth[7:].strip(), tok):
            return True
        # non autorizzato: risposta
        if path.startswith("/api/"):
            self._json({"error": "accesso non autorizzato"}, 401)
        else:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
        return False

    # I parametri dell'ultima rotta (`/api/tracce/{id}` -> {"id": ...}).
    # Stanno qui e non nella firma del gestore perche' il gestore e' un
    # metodo come gli altri e il corpo deve poter restare quello che era:
    # quando serve, si legge `self._rotta_parametri`.
    _rotta_parametri: dict[str, str] = {}

    def _instrada(self, metodo: str, path: str,
                  body: dict[str, Any] | None = None,
                  s: Any = None) -> None:
        """Serve una richiesta dalla tabella `orchestra/rotte.py`.

        Una risposta sola per ogni esito: il gestore scrive la sua, qui si
        scrive solo quando il gestore non c'e'. None vuol dire due cose
        diverse e vanno dette diverse — 404 se il percorso non esiste, 405
        se esiste ma non con questo metodo. Prima erano entrambe 404, e un
        client che sbagliava metodo leggeva "non trovato" per una rotta
        che c'era.
        """
        trovata = ROTTE.cerca(metodo, path)
        if trovata is None:
            ammessi = ROTTE.metodi(path)
            if ammessi:
                elenco = ", ".join(sorted(ammessi))
                self._json({"error": f"metodo {metodo} non ammesso su {path}",
                            "ammessi": sorted(ammessi)}, 405,
                           headers={"Allow": elenco})
                return
            self._json({"error": "non trovato"}, 404)
            return
        scelta, parametri = trovata
        self._rotta_parametri = parametri
        # Un GET non ha corpo: il gestore riceve un dizionario vuoto e non
        # None, cosi' la firma e' la stessa per tutti e un `body.get`
        # scritto per sbaglio in una rotta GET non diventa un crash.
        scelta.gestore(self, path, body if body is not None else {}, s)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        # risorse necessarie alla pagina di login: sempre accessibili
        if path not in ("/login",) and not path.endswith((".css", ".js", ".ico", ".png", ".svg", ".webmanifest", ".webp", ".jpg", ".jpeg")):
            if not self._gate_remoto(path):
                return
        if path == "/":
            if not self._gate_remoto(path):
                return
            self._html(UI_PATH)
        elif path == "/login":
            self._login_page()
        elif path == "/docs":
            self._guida()
            return
        elif path == "/manifest.webmanifest":
            self._static("manifest.webmanifest", "application/manifest+json")
            return
        elif path == "/sw.js":
            self._static("sw.js", "text/javascript; charset=utf-8")
            return
        elif path == "/icon.svg":
            self._static("icon.svg", "image/svg+xml")
            return
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
        elif path.startswith("/portraits/"):
            name = path[len("/portraits/"):]
            self._portrait(name)
        elif path.endswith(".webp"):
            self._static(path[1:], "image/webp")
        elif path.endswith(".png"):
            self._static(path[1:], "image/png")
        elif path.endswith(".jpg") or path.endswith(".jpeg"):
            self._static(path[1:], "image/jpeg")
        elif path.endswith(".svg"):
            self._static(path[1:], "image/svg+xml")
        elif path.endswith(".ico"):
            self._static(path[1:], "image/x-icon")
        # Le rotte /api vivono nella tabella (orchestra/rotte.py):
        # percorso, metodo e gestore dichiarati una volta accanto al
        # codice che li serve. La catena di elif che stava qui aveva un
        # ramo per percorso, e un ramo scritto solo sotto GET faceva
        # rispondere 404 a un POST che esisteva.
        if path.startswith("/api/"):
            self._instrada("GET", path)
            return
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
        # CSRF: una pagina di un altro sito non deve poter comandare
        # l'agente con una POST verso 127.0.0.1. Sta PRIMA di tutto,
        # perche' anche il login e' una POST.
        if not self._origine_ammessa():
            self._json({"error": "origine non ammessa"}, 403)
            return
        ip = (self.client_address[0] or "") if self.client_address else ""
        # Tetto generale: nessuna applicazione vera manda 600 POST in
        # dieci secondi, e un flood locale blocca il server per tutti
        # (un thread per connessione).
        if self._troppe_richieste(f"post:{ip}", 600, 10.0):
            return
        # /api/login e /api/logout sono sempre raggiungibili (il primo
        # serve proprio a ottenere il cookie).
        if path not in ("/api/login", "/api/logout"):
            if not self._gate_remoto(path):
                return
        # Login remoto: non richiede sessione ne' token (e' il modo per
        # ottenerlo).
        if path == "/api/login":
            # Il token remoto e' l'unica credenziale: senza un limite, un
            # client puo' provarne milioni. Sei tentativi al minuto per
            # IP lasciano passare un errore di battitura e fermano il resto.
            if self._troppe_richieste(f"login:{ip}", 6, 60.0):
                return
            try:
                body = self._body()
            except ValueError as e:
                self._json({"error": str(e)}, 400); return
            tok = (body.get("token") or "").strip()
            atteso = self.app.token_remoto or ""
            if tok and atteso and hmac.compare_digest(tok, atteso):
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie",
                    f"orchestra_tok={urllib.parse.quote(tok)}; Path=/; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
            else:
                self._json({"error": "token non valido"}, 401)
            return
        if path == "/api/logout":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie",
                "orchestra_tok=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return

        # Rotte di configurazione e memoria: devono funzionare anche
        # senza sessione, altrimenti senza chiave non si puo' salvare
        # nessuna chiave e l'app resta bloccata per sempre.
        if path in ("/api/nous/auth/start", "/api/chiavi",
                    "/api/provider", "/api/memoria/cerca",
                    "/api/memoria/aggiungi", "/api/memoria/elimina",
                    "/api/memoria/modifica", "/api/memoria/ottimizza",
                    "/api/progetto", "/api/identita", "/api/bots/crea",
                    "/api/bots/attiva", "/api/bots/aggiorna",
                    "/api/bots/elimina", "/api/bots/avvia",
                    "/api/lavori/riprova", "/api/lavori/annulla",
                    "/api/lavori/scarta", "/api/lavori/unisci",
                    "/api/remote/start",
                    "/api/remote/stop", "/api/remote/status",
                    "/api/remote/info"):
            s = self.app.session  # puo' essere None: non la usano
        else:
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

        # Un corpo solo, letto una volta (il tetto dipende dalla rotta),
        # poi la tabella decide chi lo riceve.
        self._instrada("POST", path, body, s)


def _trova_cloudflared() -> str:
    import shutil
    cf = shutil.which("cloudflared")
    if cf:
        return cf
    # posizioni comuni dopo installazione via winget/brew/apt
    candidati = []
    if sys.platform.startswith("win"):
        bases = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")]
        # percorsi fissi: la shell di servizio (es. MSYS) non espone le
        # variabili d'ambiente di Windows, ma il binario e' li'.
        bases += [r"C:\Program Files", r"C:\Program Files (x86)",
                  os.path.join(os.path.expanduser("~"), "AppData", "Local")]
        for base in bases:
            if not base:
                continue
            candidati.append(os.path.join(base, "cloudflared", "cloudflared.exe"))
            candidati.append(os.path.join(base, "cloudflared.exe"))
            candidati.append(os.path.join(base, "Microsoft", "WindowsApps", "cloudflared.exe"))
    else:
        for base in ("/usr/local/bin", "/usr/bin", "/opt/homebrew/bin"):
            candidati.append(os.path.join(base, "cloudflared"))
    for c in candidati:
        if c and os.path.isfile(c):
            return c
    return ""


def _stdin_attivo() -> bool:
    """True se si puo' chiedere una risposta all'utente da tastiera.

    Lanciato da una .bat/shortcut senza console, sys.stdin puo' essere un
    handle invalido: isatty() risponde True ma input() poi muore con
    OSError [Errno 9] Bad file descriptor, e l'app va in crash proprio
    quando il tunnel non trova cloudflared. Qui il controllo e' piu'
    prudente e non lascia l'app a terra.
    """
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


def _domanda(testo: str) -> str:
    """input() che non puo' rompere: senza console o con handle chiuso
    risponde con la stringa vuota, e il chiamante decide il default."""
    try:
        return input(testo).strip().lower()
    except (EOFError, OSError):
        return ""


def _installa_cloudflared_winget() -> str:
    """Prova a installare cloudflared con winget (silenzioso) e ritorna il
    binario trovato, oppure "" se non ci e' riuscito."""
    import subprocess
    print("  Installazione in corso (puo' richiedere un minuto)...",
          file=sys.stderr, flush=True)
    try:
        subprocess.run(
            ["winget", "install", "--id", "Cloudflare.cloudflared", "-e",
             "--accept-package-agreements", "--accept-source-agreements",
             "--silent", "--disable-interactivity"],
            check=False, capture_output=True, timeout=300,
        )
    except Exception as e:
        print("  installazione fallita: %s" % e, file=sys.stderr)
    return _trova_cloudflared()


def _avvia_tunnel(port: int, app: Any) -> None:
    import re
    import shutil
    import subprocess
    import threading

    cf = _trova_cloudflared()
    if not cf:
        # cloudflared assente: provo a installarlo. Chi ha chiesto il tunnel
        # vuole il tunnel, quindi l'installazione automatica e' lo scopo; se
        # non e' possibile (winget mancante, permessi, installazione fallita)
        # si prosegue con le istruzioni e il server resta comunque attivo in
        # LAN con il token, senza lasciare l'app a terra.
        if sys.platform.startswith("win") and shutil.which("winget"):
            if _stdin_attivo():
                print("  cloudflared non trovato. Posso installarlo ora con winget "
                      "(Cloudflare.cloudflared).", file=sys.stderr)
                if _domanda("  Installo? [s/N] ") == "s":
                    cf = _installa_cloudflared_winget()
            else:
                # Niente console: non si puo' chiedere. Installo comunque, e'
                # lo scopo del tunnel; se fallisce si dice come farlo a mano.
                cf = _installa_cloudflared_winget()
            if not cf:
                # riprova dopo un attimo (winget aggiorna il PATH nel registro)
                import time as _t
                _t.sleep(2)
                cf = _trova_cloudflared()
        if not cf:
            print("  cloudflared non trovato. Per il tunnel automatico installa:",
                  file=sys.stderr)
            print("    Windows: winget install Cloudflare.cloudflared", file=sys.stderr)
            print("    macOS:   brew install cloudflared", file=sys.stderr)
            print("    Linux:   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/",
                  file=sys.stderr)
            print("  In alternativa usa una VPN (es. Tailscale) e l'URL LAN qui sopra.",
                  file=sys.stderr)
            return

    def _run() -> None:
        try:
            # Su Windows la finestra nera di cloudflared resta aperta in
            # secondo piano: la nascondo con CREATE_NO_WINDOW. Il processo
            # gira comunque, e i log vengono letti da stdout (PIPE).
            _flags = 0
            if sys.platform.startswith("win"):
                _flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                [cf, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=_flags,
            )
            app._tunnel_proc = proc
            for line in proc.stdout:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m:
                    url = m.group(0)
                    app.tunnel_url = url
                    print(f"\n  Tunnel pubblico: {url}\n", flush=True)
                    # aggiorna il file stato condiviso col processo padre
                    try:
                        import json as _json
                        st = {}
                        if os.path.isfile(REMOTE_STATE_PATH):
                            with open(REMOTE_STATE_PATH, encoding="utf-8") as _f:
                                st = _json.loads(_f.read())
                        st["tunnel_url"] = url
                        with open(REMOTE_STATE_PATH, "w", encoding="utf-8") as _f:
                            _json.dump(st, _f)
                    except Exception:
                        pass
                    # QR code via servizio esterno (stampa URL)
                    print(f"  Apri sul telefono: {url}\n", flush=True)
            proc.wait()
        except Exception as e:
            print(f"  tunnel fallito: {e}", file=sys.stderr)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


class OrchestraServer(ThreadingHTTPServer):
    """Server che gestisce davvero le chiusure improvvise del client.

    `socketserver` chiama `self.handle_error` dove `self` e' il server, non
    il request handler: una definizione di `handle_error` su `Handler` non
    avrebbe alcun effetto. Qui e' sul server, come deve essere.

    Un browser (o il telefono) che chiude la scheda, la ricarica, o cambia
    rete mentre il server sta ancora leggendo la richiesta, lascia la
    connessione a meta'. `http.server` di base stampa uno stack trace di
    dieci righe per un fatto normale. Lo distinguiamo da un errore vero
    (che in `do_GET` arriva come 500 e va visto) e lo riduciamo a una riga.
    """
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        import sys as _sys
        import errno as _errno
        exc = _sys.exc_info()[1]
        # Connessioni interrotte dal lato client: ConnectionAbortedError /
        # ConnectionResetError / BrokenPipeError, piu' gli OSError Windows
        # (10053 interrotta, 10054 reset, 10058 shutdown) che arrivano come
        # `OSError` generici. Tutto normale, niente stack trace.
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError)):
            pass
        elif isinstance(exc, OSError) and getattr(exc, "errno", None) in (
                _errno.ECONNABORTED, _errno.ECONNRESET, _errno.EPIPE,
                10053, 10054, 10058):
            pass
        elif isinstance(exc, (TimeoutError, _sys.modules["socket"].timeout)):
            pass
        elif isinstance(exc, SystemError):
            # Windows: "returned a result with an exception set" durante la
            # lettura della richiesta (rfile.readline) con il socket rotto.
            # Artefatto socket/protocollo, non un bug dell'app. Niente stack.
            pass
        else:
            # errore vero: si vede.
            _sys.stderr.write(
                f"  errore serving {client_address[0]}: {exc!r}\n")
            _sys.stderr.flush()
            return
        try:
            addr = client_address[0]
        except Exception:
            addr = "?"
        print(f"  connessione chiusa dal client ({addr}) — normale, non un errore",
              flush=True)


def serve(host: str = "127.0.0.1", port: int = 8737, *, open_browser: bool = True,
          remoto: bool = False, tunnel: bool = False) -> None:
    if remoto or tunnel:
        host = "0.0.0.0"
    remoto_attivo = bool(remoto or tunnel or host not in ("127.0.0.1", "localhost", "::1"))

    if remoto_attivo and not (remoto or tunnel):
        # bind manuale fuori localhost: conferma come prima
        print(f"ATTENZIONE: ascolto su {host}, non su localhost.", file=sys.stderr)
        print("Abilito l'accesso remoto con autenticazione a token.", file=sys.stderr)
        if not _stdin_attivo():
            raise SystemExit("rifiuto di esporre fuori da localhost in modo non interattivo")
        if _domanda("Continuo? [s/N] ") != "s":
            raise SystemExit("annullato")

    app = OrchestraApp.create(remoto_attivo=remoto_attivo)
    Handler.app = app
    app.porta = port

    # I bot Telegram salvati ripartono con il server: chi ha collegato
    # una chat si aspetta di trovarla viva dopo un riavvio, senza
    # riaprire il pannello. Se la rete non c'e', il ponte riprova da
    # solo e il pannello lo dice.
    try:
        quanti = app.telegram_avvia()
        if quanti:
            print(f"  Telegram: {quanti} bot in ascolto", flush=True)
    except Exception as e:  # noqa: BLE001
        _log_telegram(f"non sono riuscito ad avviare i ponti: {e}")

    if remoto_attivo and app.token_remoto:
        print(f"\n  Token di accesso remoto: {app.token_remoto}\n", flush=True)

    # stato remoto condiviso con il processo padre
    if remoto_attivo:
        try:
            import json as _json
            _stato = {"pid": os.getpid(), "port": port,
                      "url": f"http://{host}:{port}", "tunnel_url": "",
                      "token": app.token_remoto or "",
                      "mode": "tunnel" if tunnel else "remote"}
            with open(REMOTE_STATE_PATH, "w", encoding="utf-8") as _f:
                _json.dump(_stato, _f)
        except Exception:
            pass

    httpd = OrchestraServer((host, port), Handler)

    # tunnel opzionale
    if tunnel:
        _avvia_tunnel(port, app)
        if remoto_attivo:
            try:
                import json as _json
                _stato["tunnel_url"] = getattr(app, "tunnel_url", "") or ""
                with open(REMOTE_STATE_PATH, "w", encoding="utf-8") as _f:
                    _json.dump(_stato, _f)
            except Exception:
                pass

    # cron scheduler: parte in automatico, cosi' i job programmati girano
    # anche se nessuno tocca la UI. Si puo' fermare dal pannello.
    try:
        from . import cron as _cron_mod
        _cron_mod.scheduler_start(env=app.env, interval=30.0)
    except Exception:
        pass

    # MCP: connette i server abilitati all'avvio.
    try:
        from . import mcp as _mcp_mod
        _mcp_mod.connect_all()
    except Exception:
        pass

    url = f"http://{host}:{port}"
    print(f"\n  Orchestra {__version__}  ->  {url}\n")
    if not app.ready:
        print(f"  ATTENZIONE: {app.error}")
        print(f"  Configura orchestra/.env, poi riavvia.\n")
    else:
        print(f"  modello: {app.env.get('ORCHESTRA_MODEL')} "
              f"({app.env.get('ORCHESTRA_PROVIDER')})")
        print(f"  Ctrl+C per fermare\n")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  fermo.")
    finally:
        httpd.shutdown()
        httpd.server_close()
        if remoto_attivo:
            try:
                st = json.loads(open(REMOTE_STATE_PATH, encoding="utf-8").read())
                if st.get("pid") == os.getpid():
                    os.remove(REMOTE_STATE_PATH)
            except Exception:
                pass


if __name__ == "__main__":
    serve()
