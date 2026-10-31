"""Sessione: il ponte fra il loop sincrono e un consumatore asincrono.

Il nucleo di Orchestra e' sincrono perche' un loop sincrono e' piu facile da
leggere e da debuggare. Ma una GUI ha bisogno del contrario: deve mostrare
l'attivita' mentre l'agente lavora, e poter cancellare il lavoro in corso.

Qui stanno i due pezzi che rendono possibile incrociare le due cose:

  - `EventBridge` mette gli eventi di `on_event` in una coda thread-safe.
  - `Session` possiede un `Agent` e lo esegue in un thread dedicato, con
    un lock perche' due richieste non possano parlare con lo stesso agent.

Il punto delicato e' la cancellazione: non possiamo uccidere il thread
Python, quindi chiediamo educatamente al loop di fermarsi al prossimo
check, tramite `should_continue`. Il task corrente finisce, ma i
successivi non partono. E' l'unico modo pulito senza processi separati.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any, Iterator

from .agent import Agent, AgentState, LoopConfig
from .context import count_tokens
from .storico import storico
from .types import Message, ToolRegistry


class EventBridge:
    """Diffusione di eventi thread-safe, con seq numerico per riprendere.

    Il seq serve a riconnettere: se il browser ricarica la pagina, chiede
    gli eventi da dove si era interrotto invece di rivedere tutto.

    UNA coda per client, non una coda sola. Con una sola, due schede del
    browser si dividono gli eventi a meta': una vede "uno, tre, cinque"
    e l'altra "due, quattro, sei". Non e' un caso raro — e' quello che
    succede ogni volta che apri la pagina mentre un altro strumento
    guarda lo stesso stream, ed e' successo perche' un client di test
    rubava meta' dei messaggi di una conversazione vera.

    Il buffer e' condiviso perche' la seq e' globale: ogni client vede
    gli stessi numeri, e un client che si ricollega riprende dal suo
    ultimo seq. Ogni client ha la sua coda, con un tetto: un client
    che non legge rallenta, non blocca.

    Nota: `dropped` conta gli eventi persi DA UN CLIENT. Se un browser
    e' aperto da troppo tempo senza leggere, perde i suoi eventi — ma
    gli altri client non ne risentono, che e' il punto.
    """

    def __init__(self, maxsize: int = 2000) -> None:
        self._subs: list[queue.Queue] = []
        self._maxsize = maxsize
        self._seq = 0
        self._lock = threading.Lock()
        self._closed = False
        self._dropped = 0

    def _iscriviti(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        self._subs.append(q)
        return q

    def _disiscriviti(self, q: queue.Queue) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    def stream(self, timeout: float = 15.0) -> Iterator[dict[str, Any]]:
        """Gli eventi per QUEL client, finche' il bridge non chiude.

        La sottoscrizione avviene QUI, non alla prima iterazione. Un
        generatore non esegue il suo corpo finche' non lo si chiama:
        subscribing dentro la funzione generatorica significava che un
        client che apriva lo stream e non lo leggeva subito — o che
        leggeva dopo un'attesa — poteva perdere eventi emessi nel
        frattempo. Ed e' esattamente il caso di un browser che si
        collega e deve aspettare il primo chunk.
        """
        q = self._iscriviti()

        def genera() -> Iterator[dict[str, Any]]:
            try:
                while True:
                    try:
                        item = q.get(timeout=timeout)
                    except queue.Empty:
                        yield {"kind": "keepalive", "data": {}, "seq": -1,
                               "ts": time.time()}
                        continue
                    if item is None:
                        return
                    yield item
            finally:
                # sempre: un client che chiude la connessione non deve
                # lasciarsi una coda in giro per il resto della sessione
                self._disiscriviti(q)

        return genera()

    def _esegui(self, agent: Any, richiesta: str,
               raccolti: list[Any]) -> None:
        """Esegue un turno e raccoglie gli eventi, in modo sincrono.

        Serve ai test: loro non hanno un ciclo di eventi, e senza questo
        dovrebbero andare a pescare nella coda interna — che e' un
        dettaglio, e un test appoggiato su un dettaglio finisce per
        verificare una cosa diversa da quella che l'utente vede.

        L'attesa e' AFTER RUN, non "smetti al primo evento": fermarsi
        sul primo e' una corsa. `user_message` arriva prima di
        `assistant`, e un test che si ferma li' conclude che
        l'assistant non e' stato emesso — che e' falso, e dipende solo
        da quanto e' veloce il thread che ascolta.

        Non serve in produzione: chi ascolta davvero usa stream().
        """
        def ascolta() -> None:
            for ev in self.stream(timeout=0.3):
                if ev["kind"] != "keepalive":
                    raccolti.append(ev)
            # niente return anticipato: si raccoglie tutto il turno

        t = threading.Thread(target=ascolta, daemon=True)
        t.start()
        time.sleep(0.15)
        try:
            agent.run(richiesta)
        finally:
            # il turno e' finito: un breve margine perche' il thread
            # svuoti la coda, poi si chiude il generatore
            time.sleep(0.3)
            t.join(timeout=3)

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            if self._closed:
                return
            self._seq += 1
            item = {"seq": self._seq, "kind": kind, "data": data,
                    "ts": time.time()}
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(item)
            except queue.Full:
                # Se questo client non legge, non vogliamo rallentare
                # gli altri ne' l'agent: perdiamo il suo vecchio evento
                # e lo segnaliamo. Solo per lui.
                try:
                    q.get_nowait()
                    self._dropped += 1
                    q.put_nowait(item)
                except queue.Empty:
                    pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
            subs = list(self._subs)
        # La sentinella si mette in un thread: se la coda di un client e'
        # piena (il flood del test precedente, o un browser che non
        # legge da un pezzo), put_nowait solleva Full e la chiusura
        # andava persa — il client restava appeso per sempre, con la
        # connessione SSE viva e nessuno che parla.
        def chiudi() -> None:
            for q in subs:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    # liberiamo il posto: un client che non legge non
                    # ha comunque i suoi eventi, e deve poter chiudersi
                    try:
                        q.get_nowait()
                        q.put_nowait(None)
                    except (queue.Empty, queue.Full):
                        pass

        t = threading.Thread(target=chiudi, daemon=True, name="orchestra-bridge-close")
        t.start()
        t.join(timeout=1.0)

    @property
    def dropped(self) -> int:
        return self._dropped

    def drain(self, timeout: float = 0.3,
              fino: str = "idle") -> list[dict[str, Any]]:
        """Raccoglie gli eventi emessi DA ORA, senza bloccare.

        Non e' una coda di eventi gia' passati: si iscrive, poi legge.
        Serve ai test e a chi deve ispezionare il flusso dopo un
        turno — ed e' l'unico modo onesto, perche' un client che
        ascolta DOPO che gli eventi sono passati non li vede, e non
        deve fingere di averli visti.

        `fino` e' il genere di evento che chiude la raccolta: senza, si
        ascolterebbe i keepalive per sempre.
        """
        raccolti: list[dict[str, Any]] = []
        for ev in self.stream(timeout=timeout):
            if ev["kind"] != "keepalive":
                raccolti.append(ev)
                if fino and ev["kind"] == fino:
                    return raccolti
        return raccolti


class Session:
    """Una conversazione con l'agente, eseguita in background.

    Un Agent = una conversazione. Ogni sessione ne possiede uno e lo
    mantiene fra i turni, cosi' il contesto (e la compattazione) sopravvivono
    da un messaggio all'altro.
    """

    def __init__(
        self,
        *,
        provider: Any,
        registry: ToolRegistry,
        system_prompt: str,
        config: LoopConfig | None = None,
        summarize: Any = None,
    ) -> None:
        self.bridge = EventBridge()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = False
        # Due pezzi che l'app fornisce e che dipendono dal provider:
        # scegliere un modello alternativo, e cambiare il modello a
        # meta' turno. Senza, un modello che non regge i tool uccide
        # il turno con un errore che sembra di rete.
        self._scegli_sostituto: Any = None
        self._cambia_modello: Any = None
        # Instrada il PRIMO modello sui punteggi del benchmark.
        # Diverso dal sostituto: quello serve quando un modello e'
        # morto, questo serve quando la sessione comincia, e la
        # domanda a cui risponde e' "quale modello e' migliore per
        # QUESTA domanda" invece di "quale ne rimane".
        self._scegli_primo: Any = None
        # Perche' e' una variabile e non un parametro di send(): la
        # scelta la fa chi ha il catalogo, non chi ha la chat. Chi
        # scrive in chat deve poter mandare senza sapere niente dei
        # punteggi.
        self._routing_attivo: bool = False
        # su quale modello si e' gia' ripiegati: senza il segno,
        # ogni turno sbagliato cambia modello e la sessione diventa
        # un carosello
        self._ripiegato_su: str | None = None

        # La delega. Il padre riceve il tool `delega`; il figlio NON
        # lo riceve, e questo e' il tetto — non un contatore che
        # qualcuno deve ricordare di rispettare. La fabbrica e' quella
        # che sa costruire un agente: senza di lei il Delegatore
        # esiste ma non ha niente da costruire, che e' la definizione
        # di un modulo che sembra fare un lavoro e non lo fa.
        self.registry = registry
        self._catalogo_per_costo: Any = None
        self._modello_delegato: str = ""
        self._fabbrica_figlio: Any = None
        self._delegatore: Any = None
        # Id della sessione nello storico su disco. None = non si salva
        # (le prove costruiscono Session senza storico, e salvarle
        # riempirebbe il DB di conversazioni finte).
        self._sessione_id: int | None = None

        # Il progetto su cui si sta lavorando. Ogni fatto che nasce da
        # un turno porta questa etichetta, ed e' quello che permette
        # di chiedere alla memoria "cosa serve per QUESTO progetto"
        # invece di "tutto quello che Orchestra sa".
        #
        # Stringa vuota = nessun progetto, e i fatti si salvano senza
        # etichetta. Non e' un caso speciale: e' il modo normale di
        # lavorare, e i fatti senza progetto restano raggiungibili
        # con ogni ricerca.
        self.progetto: str = ""

        # La root di un checkout isolato, quando questo turno non deve
        # scrivere nella cartella del progetto. Arriva dall'argomento
        # `root_isolata` di `send` e vale solo per quel turno: e' un
        # attributo della sessione e non del thread perche' il turno gira
        # in un thread suo, creato da `send` stesso.
        #
        # Vuoto = nessun isolamento, si usa la root del progetto.
        self._root_isolata: str = ""

        # Il callback che registra una proposta di merge per il lavoro
        # isolato in corso. Vuoto = nessun lavoro isolato: il tool
        # `proponi_merge` non e' attivo, e non c'e' niente da proporre.
        self._proponi_merge: Any = None

        # L'identita' del bot che possiede questa sessione. Vuoto =
        # l'agente principale, quello configurato in Opzioni: e' il caso
        # di chi non ha mai creato un bot, e deve continuare a funzionare
        # esattamente come prima.
        #
        # Il nome viaggia anche nello storico (`sessioni.bot`), perche'
        # senza non si puo' riaprire "la conversazione di Grok": si puo'
        # solo riaprire l'ultima di tutte.
        self.bot: str = ""
        # Quanti passaggi di bot ci sono sopra questo turno. 0 = turno
        # nato dall'utente; 1 = turno chiesto da un altro bot. Il tetto e'
        # 1: un bot puo' chiedere, il bot che riceve non puo' richiedere.
        self._bot_depth: int = 0
        self._bot_parla_con: list[str] = []
        self._bot_risolutore: Any = None
        # La policy del bot (tool e shell ammessi). Vuota = nessun
        # limite oltre al profilo: e' il caso dell'agente principale.
        self._policy: dict[str, list[str]] = {}

        self.agent = Agent(
            provider,
            registry,
            system_prompt,
            config or LoopConfig(),
            summarize=summarize,
            on_event=self.bridge.emit,
        )
        # L'agente deve conoscere il progetto fin dall'inizio: e' lui
        # che mette il blocco del progetto nel prompt e che sa quale
        # filtro passare al tool `memoria`. Senza questa riga, il
        # progetto lo sa solo la sessione — e quindi i fatti vengono
        # etichettati ma il modello non li cerca col filtro giusto.
        try:
            self.agent.progetto = self.progetto
        except Exception:
            pass

    # -- stato -------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._busy

    def snapshot(self) -> dict[str, Any]:
        """Stato corrente, serializzabile, per la UI.

        I messaggi assistant senza testo vengono omessi: sono i turni in cui
        il modello ha solo emesso tool call, e mostrarli come messaggi vuoti
        fa righe bianche nella cronologia. Il loro contenuto si vede dai tool.

        I tool CI sono, invece: chiamate e risultati viaggiano nello
        snapshot, o al refresh spariscono dallo schermo. Sono già nel
        contesto del modello — mostrarli non costa un token in più,
        perché i token li paga chi li MANDA al modello, non chi li
        mostra nel browser. Nasconderli risparmierebbe zero e toglierebbe
        la storia di cosa ha fatto.
        """
        with self._lock:
            st: AgentState = self.agent.state
            messaggi = []
            for m in st.messages:
                # Le coppie assistant/tool sintetiche (nudge, verifica,
                # steer, gira-a-vuoto) servono al modello, non all'utente:
                # sono role="tool" con un id inventato, e per poterle
                # mandare a gateway stretti (Beam) sono precedute da un
                # assistant con una tool_call fittizia. Se finissero nello
                # snapshot, l'UI disegnerebbe un tool card "__nudge__" con
                # dentro la nota di sistema — rumore che non e' quello che
                # e' successo. Il nome con "__" le riconosce.
                if m.name and m.name.startswith("__"):
                    continue
                if m.role == "user":
                    messaggi.append({"role": m.role, "content": m.content,
                                     "name": m.name})
                elif m.role == "assistant" and (
                        m.content.strip() or m.tool_calls):
                    item: dict[str, Any] = {"role": m.role,
                                            "content": m.content,
                                            "name": m.name}
                    # Il ragionamento viaggia con l'assistant: così la UI lo
                    # renderizza dallo snapshot e non ha bisogno di preservare
                    # nodi DOM lato client, che è il punto in cui si rompeva
                    # l'ordine (ragionamento spinto sotto la risposta).
                    if getattr(m, "reasoning", ""):
                        item["reasoning"] = m.reasoning
                    if m.tool_calls:
                        item["tool_calls"] = [
                            {"id": tc.id, "name": tc.name,
                             "arguments": tc.arguments}
                            for tc in m.tool_calls
                        ]
                    messaggi.append(item)
                elif m.role == "tool":
                    messaggi.append({"role": m.role, "content": m.content,
                                     "name": m.name,
                                     "tool_call_id": m.tool_call_id})
            return {
                "busy": self._busy,
                "iterations": st.iterations,
                "total_tokens": st.total_tokens,
                "context_limit": self.agent.config.context_limit,
                "tool_calls": st.tool_calls_made,
                "tool_errors": st.tool_errors,
                "compactions": st.compactions,
                "stopped_because": st.stopped_because,
                "usage_by_model": dict(st.usage_by_model),
                "messages": messaggi,
                "routing": bool(self._routing_attivo),
                "bot": self.bot,
                "context_limit": getattr(getattr(self.agent, "config", None),
                                         "context_limit", 0) or 0,
                # La barra misura la FINESTRA, non la storia: il cumulato
                # (total_tokens) cresce per sempre e la barra resterebbe
                # rossa e piena anche a contesto vuoto. Qui va la
                # dimensione attuale dei messaggi, la stessa che decide
                # se compattare.
                "context_tokens": count_tokens(self.agent.state.messages),
            }

    def imposta_progetto(self, progetto: str) -> str:
        """Cambia il progetto su cui si lavora. Ritorna quello nuovo.

        Va fatto in un posto solo, e non settando l'attributo a mano:
        il progetto vive su due oggetti — la sessione (che etichetta i
        fatti) e l'agente (che deve saperlo per cercarli). Se uno dei
        due resta indietro, la memoria etichetta col progetto vecchio
        mentre il modello cerca col nuovo: fatti che non si
        ritrovano, senza che nessuno dica perche'.

        Il prompt viene ricalcolato subito, non al turno dopo: se
        l'utente cambia progetto e scrive "ora il menu", il modello
        deve gia' sapere di essere nel progetto nuovo.

        Il progetto vuoto e' legittimo: si lavora senza progetto, e i
        fatti non vengono etichettati. Non e' un errore.

        QUI si sposta anche la root: il progetto non e' solo
        un'etichetta, e' la cartella in cui si scrive. La root sta nel
        thread, e il thread del turno e' un thread suo — quindi la
        root viene impostata dentro `_esegui_turno`, dove il thread
        esiste gia'. Qui si tiene il NOME, che e' quello che serve
        alla memoria e al prompt.
        """
        progetto = (progetto or "").strip()
        with self._lock:
            self.progetto = progetto
            # Cambiare progetto mentre un checkout e' impostato
            # lascerebbe una root che non appartiene al progetto nuovo.
            # Un turno isolato non puo' cambiare progetto (il
            # riconoscimento e' spento), quindi qui l'isolamento o e'
            # finito o non e' mai iniziato.
            self._root_isolata = ""
            try:
                self.agent.progetto = progetto
            except Exception:
                pass
            try:
                self.agent._aggiorna_prompt()
            except Exception:
                pass
        return progetto

    def _prepara_root(self) -> None:
        """Mette la root di questo thread sul progetto giusto.

        Va fatto nel thread del turno, non quando si cambia progetto:
        il thread che cambia il progetto e' quello della richiesta
        HTTP, non quello che eseguira' i tool. Impostare la root li'
        non cambierebbe nulla, perche' il tool la legge nel suo thread.

        Se il progetto non e' registrato, la root resta quella
        globale: e' il caso normale, e lavorare dentro la cartella
        di installazione e' sempre lecito.
        """
        try:
            from . import progetti as _pr
            nome = (getattr(self, "progetto", "") or "").strip()
            isolata = (getattr(self, "_root_isolata", "") or "").strip()
            if isolata:
                # Un checkout isolato che sparisce non deve diventare un
                # ritorno silenzioso alla cartella dell'utente: sarebbe
                # esattamente il danno che l'isolamento evita. Meglio far
                # fallire il turno.
                if not os.path.isdir(isolata):
                    raise RuntimeError(
                        "il checkout isolato non esiste piu': " + isolata)
                _pr._set_root_sessione(isolata, nome)
                return
            if not nome:
                _pr._set_root_sessione("", "")
                return
            percorso = _pr.percorso_di(nome)
            if not percorso:
                _pr._set_root_sessione("", "")
                return
            _pr._set_root_sessione(percorso, nome)
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            pass

    def set_system_prompt(self, prompt: str) -> None:
        """Cambia le istruzioni di sistema a sessione avviata.

        Se il primo messaggio e' ancora il system prompt lo sostituiamo;
        altrimenti lo aggiorniamo dove sta, senza ricostruire la sessione e
        perdere il contesto.
        """
        with self._lock:
            for m in self.agent.state.messages:
                if m.role == "system":
                    m.content = prompt
                    return
            self.agent.state.messages.insert(
                0, Message(role="system", content=prompt)
            )

    # -- esecuzione --------------------------------------------------------

    def attiva_delega(self) -> bool:
        """Registra il tool `delega` sul padre, se si puo'.

        Resta un NO esplicito e non un errore quando la fabbrica non
        c'e': la delega senza un modo di costruire un figlio e' un
        pulsante che non fa niente, e un pulsante che non fa niente
        e' peggio di un pulsante che non c'e' — l'utente lo preme e
        aspetta un risultato che non arriva.

        Il tool non viene MAI registrato sul registro del figlio: e'
        li' che sta il tetto di profondita'.
        """
        from .delega import Delegatore
        from .types import Tool

        if self._fabbrica_figlio is None:
            return False

        self._delegatore = Delegatore(
            self._fabbrica_figlio,
            scegli_modello=self._scegli_primo,
            tariffa=self._tariffa_delegato,
            on_modello_usato=self._ricorda_modello_delegato,
        )

        def _delega(obiettivo: str, contesto: str = "") -> str:
            if self._delegatore is None:
                return "[delega non attiva]"
            f = self._delegatore.delega(obiettivo, contesto)
            # l'evento va al padre, non al figlio: e' cosi' che nella
            # chat si vede che un figlio sta lavorando invece che il
            # padre sembrare fermo
            try:
                self.bridge.emit("delega", {
                    "obiettivo": obiettivo[:160],
                    "esito": f.esito,
                    "passi": f.passi,
                    "modello": f.modello,
                    "costo": f.costo,
                })
            except Exception:
                pass
            return f.per_il_padre()

        self.registry.register(Tool(
            name="delega",
            description=("Affida un compito preciso e circoscritto a un "
                         "sub-agente che parte con una finestra vuota. "
                         "Torni solo la risposta finale, non il "
                         "trascorso. Usarlo per cercare, contare, "
                         "leggere in blocco o verificare un risultato. "
                         "NON usarlo per chiedere un parere: quello lo "
                         "sai rispondere da solo."),
            schema={
                "type": "object",
                "properties": {
                    "obiettivo": {"type": "string",
                                  "description": ("Il compito, in una frase. "
                                                  "Deve essere finito: "
                                                  "'contare le righe di "
                                                  "a.txt' e' un compito, "
                                                  "'capire il progetto' no.")},
                    "contesto": {"type": "string",
                                 "description": ("Cosa deve sapere il figlio "
                                                 "per farlo: il percorso, il "
                                                 "formato atteso, la "
                                                 "soglia. NON la "
                                                 "conversazione: quello e' "
                                                 "il punto della delega.")},
                },
                "required": ["obiettivo"],
            },
            handler=_delega,
        ))
        return True

    # -- bot ----------------------------------------------------------------

    # Un bot puo' chiedere a un altro bot, ma il bot che riceve non puo'
    # richiedere: e' lo stesso tetto della delega, applicato a un contesto
    # che pero' sopravvive. Senza, due bot gentili si risponderebbero per
    # sempre e il conto lo scopriresti dopo.
    BOT_PROFONDITA_MAX = 1
    BOT_ATTESA_DEFAULT = 180.0
    BOT_ATTESA_MAX = 600.0
    BOT_MESSAGGIO_MAX = 6000

    def imposta_policy(self, policy: dict[str, Any] | None) -> dict[str, list[str]]:
        """Limita tool e shell di questa sessione. None o {} = nessun limite.

        La policy non si applica subito al registro: il registro viene
        rifatto a ogni turno, e applicarla qui verrebbe cancellato dal
        profilo. Si salva, e `_esegui_turno` la applica dopo il profilo.
        """
        from . import policy as policy_mod

        self._policy = policy_mod.normalizza(policy)
        return self._policy

    def attiva_bot(self, risolutore: Any, *, nome: str = "",
                   parla_con: list[str] | None = None) -> bool:
        """Da' a questa sessione un'identita' di bot e il tool `bot_chiedi`.

        `risolutore(nome)` deve tornare un dizionario con `nome` e
        `sessione` (la Session dell'altro bot), oppure None. La sessione
        non sa niente del registro dei bot: sa solo chiedere, e questa e'
        la parte che rende il modulo testabile senza un server.

        `parla_con` e' l'allowlist del CHIAMANTE. Vuota = nessuno. Il
        default non e' "tutti" perche' un permesso concesso per omissione
        e' un permesso che nessuno ha deciso.
        """
        from .types import Tool

        self.bot = (nome or "").strip()
        self._bot_parla_con = [str(n).strip() for n in (parla_con or [])
                               if str(n).strip()]
        self._bot_risolutore = risolutore
        if risolutore is None:
            return False

        def _chiedi(destinatario: str, messaggio: str,
                    attesa: float = 180) -> str:
            return self._chiama_bot(destinatario, messaggio, attesa)

        # La registrazione e' idempotente: aggiornare l'allowlist di un
        # bot gia' attivo richiama questo metodo, e `register` solleva se
        # il nome c'e' gia'.
        if "bot_chiedi" not in self.registry:
            self.registry.register(Tool(
                name="bot_chiedi",
                description=(
                    "Chiedi qualcosa a un altro bot, che ha una sua "
                    "conversazione, un suo modello e un suo progetto. La "
                    "risposta arriva quando il bot ha finito: costa un "
                    "turno sul suo provider. Usalo solo quando quel bot sa "
                    "o puo' fare qualcosa che tu non puoi, non per chiedere "
                    "un parere che sai darti da solo."
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "destinatario": {
                            "type": "string",
                            "description": "Il nome del bot a cui chiedere.",
                        },
                        "messaggio": {
                            "type": "string",
                            "description": (
                                "La richiesta, con il contesto che serve a "
                                "quel bot: cosa deve fare, dove, in che "
                                "formato. Non la tua conversazione."
                            ),
                        },
                        "attesa": {
                            "type": "number",
                            "description": ("Secondi massimi di attesa "
                                            "(default 180).")
                        },
                    },
                    "required": ["destinatario", "messaggio"],
                },
                handler=_chiedi,
            ))
        return True

    def _chiama_bot(self, destinatario: str, messaggio: str,
                    attesa: Any = None) -> str:
        """Manda un messaggio a un altro bot e ne aspetta la risposta.

        Il turno del destinatario gira nel SUO thread, con la sua
        profondita' a 1: se prova a chiamare a sua volta, il tool lo
        rifiuta. Il chiamante aspetta qui, senza bloccare il server, perche'
        questo handler gira gia' dentro il thread del turno.
        """
        import time as _time

        nome = (destinatario or "").strip()
        testo = (messaggio or "").strip()
        if not nome:
            return "ERRORE: serve il nome del bot a cui chiedere."
        if not testo:
            return "ERRORE: serve un messaggio da mandare."
        if len(testo) > self.BOT_MESSAGGIO_MAX:
            return (f"ERRORE: messaggio troppo lungo ({len(testo)} caratteri, "
                    f"il massimo e' {self.BOT_MESSAGGIO_MAX}).")
        if self._bot_depth >= self.BOT_PROFONDITA_MAX:
            return ("ERRORE: un bot non puo' chiamare un altro bot da dentro "
                    "una chiamata. Rispondi direttamente a chi ti ha "
                    "chiesto, con quello che sai o che hai fatto.")
        if nome.lower() == (self.bot or "").lower():
            return "ERRORE: un bot non puo' chiamare se stesso."
        if not self._bot_parla_con:
            return ("ERRORE: questo bot non puo' parlare con nessun altro. "
                    "L'utente deve aggiungere il destinatario alla sua "
                    "lista `parla_con` nelle impostazioni dei bot.")
        permessi = {n.lower(): n for n in self._bot_parla_con}
        if nome.lower() not in permessi:
            return (f"ERRORE: {self.bot!r} non ha il permesso di parlare "
                    f"con {nome!r}. Puo' chiedere a: "
                    f"{', '.join(self._bot_parla_con)}.")
        if self._bot_risolutore is None:
            return "ERRORE: nessun bot disponibile in questo momento."
        try:
            altro = self._bot_risolutore(nome)
        except Exception as e:  # noqa: BLE001
            return f"ERRORE: non riesco a trovare il bot {nome!r}: {e}"
        if not altro or altro.get("sessione") is None:
            return f"ERRORE: il bot {nome!r} non esiste (piu')."

        sessione = altro["sessione"]
        nome_vero = str(altro.get("nome") or nome)
        try:
            secondi = float(attesa) if attesa is not None else self.BOT_ATTESA_DEFAULT
        except (TypeError, ValueError):
            secondi = self.BOT_ATTESA_DEFAULT
        secondi = max(5.0, min(self.BOT_ATTESA_MAX, secondi))

        # Se il bot sta gia' lavorando per l'utente, non gli si mette in
        # coda un secondo turno: `Session.send` rifiuterebbe, e il rifiuto
        # arriverebbe come "occupato" senza spiegare che basta aspettare.
        if sessione.busy:
            scadenza = _time.monotonic() + secondi
            while sessione.busy and _time.monotonic() < scadenza:
                _time.sleep(0.25)
            if sessione.busy:
                return (f"[il bot {nome_vero} sta ancora lavorando per "
                        f"l'utente: nessuna risposta entro {int(secondi)}s]")

        try:
            self.bridge.emit("bot", {
                "fase": "chiedo", "da": self.bot, "a": nome_vero,
            })
        except Exception:  # noqa: BLE001
            pass
        involucro = (f"[messaggio dal bot {self.bot or 'principale'}]\n"
                     f"{testo}")
        if not sessione.send(involucro, bot_depth=self._bot_depth + 1):
            return (f"[il bot {nome_vero} ha appena iniziato un altro "
                    f"lavoro: riprova fra poco]")
        finito = sessione.wait(timeout=secondi)
        risposta = ""
        for m in reversed(getattr(sessione.agent.state, "messages", [])):
            if getattr(m, "role", "") == "assistant" \
                    and (getattr(m, "content", "") or "").strip():
                risposta = m.content.strip()
                break
        try:
            self.bridge.emit("bot", {
                "fase": "risposta", "da": self.bot, "a": nome_vero,
                "ok": bool(finito and risposta),
            })
        except Exception:  # noqa: BLE001
            pass
        if not finito:
            return (f"[il bot {nome_vero} sta ancora lavorando dopo "
                    f"{int(secondi)}s: la risposta non e' pronta — non e' "
                    f"un risultato]")
        if not risposta:
            return (f"[il bot {nome_vero} ha finito senza una risposta "
                    f"testuale — non e' un risultato]")
        return f"[risposta dal bot {nome_vero}]\n{risposta}"

    def _ricorda_modello_delegato(self, modello: str) -> None:
        """Il Delegatore dice quale modello ha usato davvero.

        Serve al tariffario, che al momento della scelta non lo sapeva
        ancora: il prezzo che conta e' quello del modello che ha fatto
        il lavoro. Senza questo il costo tornerebbe sempre "non noto",
        che e' la stessa cosa che non misurare niente.
        """
        self._modello_delegato = modello

    def _tariffa_delegato(self, token: int) -> float | None:
        """Costo di `token` token per il modello che il figlio usa.

        Non sa quale modello sarà — quello lo sceglie il Delegatore
        mentre lavora. E va bene così: il costo di una delega si
        registra a posteriori, e il prezzo che conta è quello del
        modello che l'ha fatta, non quello previsto.

        Se il catalogo non c'è, o il modello non ha prezzi, torna
        None e il resoconto dirà "costo non noto". Non torna zero: un
        free-tier dà prezzo zero, che è una cosa vera, e non sapere è
        un'altra.
        """
        cat = getattr(self, "_catalogo_per_costo", None)
        mod = getattr(self, "_modello_delegato", None)
        if cat is None or not mod:
            return None
        prof = cat.models.get(mod) if hasattr(cat, "models") else None
        if prof is None:
            return None
        try:
            return float(prof.info.estimate_cost(token, 0))
        except Exception:  # noqa: BLE001
            return None

    def resoconto_deleghe(self) -> str:
        """Quanto hanno costato i figli, o un avviso che non ce ne sono."""
        if self._delegatore is None:
            return "delega non attiva"
        return self._delegatore.resoconto()

    def instradamento_attivo(self, attivo: bool = True) -> None:
        """Accende o spegne l'instradamento automatico.

        Di' default True perche' e' quello che rende utile lo
        strumento, ma l'interruttore esiste perche' un
        instradamento che non si puo' disattivare non e' automatico:
        e' imposto. E quando e' spento si puo' scegliere a mano e
        vedere se la scelta automatica era migliore — che e' l'unico
        modo di sapere se il router serve.
        """
        self._routing_attivo = attivo
        # emit(kind, data) e non emit(kind, **kwargs): la firma e' quella,
        # e un errore qui impedisce al server di partire — il che
        # significa che un falso segno in una riga ferma tutto.
        self.bridge.emit("routing", {
            "modello": "", "categoria": "", "punteggio": None,
            "prove": None, "scartati": [], "spiegazione": "",
            "motivo": "instradamento acceso" if attivo
                      else "instradamento spento",
        })

    def _ripiego_se_ripetono(self, richiesta: str) -> None:
        """Se il modello ha sbagliato due volte, prova il successivo.

        Il ripiego e' l'unica parte dell'instradamento che vale la
        pena dopo che l'hai scritto: senza misurazioni non c'e' un
        "successivo", c'e' solo l'unico che hai. Con, c'e' una fila e si
        sa chi viene dopo — e quella fila era gia' scritta e testata
        mentre nessuno la chiamava.

        Perche' DOPO il turno e non dentro. Cambiare modello a meta'
        di un ragionamento cambia il modo in cui lo stesso compito
        viene affrontato, e l'errore che ha fatto fallire il tentativo
        non e' stato letto dal nuovo modello: si ripeterebbe. Dopo il
        turno, il prossimo parte pulito.

        Perche' UNA volta sola per errore. Senza un segno, ogni turno
        sbagliato cambia modello e la sessione diventa un carosello:
        quattro modelli in quattro turni, nessuno che finisce un
        lavoro. Il segno e' `_ripiegato_su`: quando il nuovo modello
        funziona, si cancella.

        E se non c'e' un successivo non si fa niente e si dice. Un
        "non ho alternative" detto adesso e' una riga; detto fra tre
        settimane e' un ciphertext.
        """
        from .routing import SOGLIA_DI_CAMBIO, il_successivo

        errori = int(getattr(self.agent.state, "consecutive_errors", 0) or 0)

        # Il segno si cancella QUI, e non dentro il ramo del cambio.
        #
        # Prima non lo cancellavo, e il docstring prometteva il
        # contrario: dopo il primo ripiego la sessione non ripiegava
        # piu' per tutta la vita. Non e' che ripiegasse troppo — e' che
        # smetteva di ripiegare, che e' il difetto peggiore: un
        # modello scelto male per due errori ti resta addosso anche
        # dopo che hai scritto tre messaggi buoni.
        #
        # La regola e' semplice e non ha bisogno di essere giusta in
        # ogni caso: se il modello corrente non sta sbagliando piu' di
        # fila, il ripiego di prima non e' piu' valido come divieto.
        if errori == 0 and self._ripiegato_su is not None:
            self._ripiegato_su = None

        if errori < SOGLIA_DI_CAMBIO:
            return
        if getattr(self, "_ripiegato_su", None) == self.modello_in_uso():
            return

        cat = getattr(self, "_catalogo_per_costo", None)
        if cat is None or not getattr(cat, "models", None):
            return

        try:
            from .routing import Scelta
            # Si esclude il modello ATTUALE, non quello da cui si e'
            # partiti. Sono due cose diverse dopo un ripiego, ed e'
            # stato un test a notarlo: escludendo solo il primo,
            # il secondo ripiego sceglieva di nuovo quello di
            # partenza e la sessione tornava indietro invece che
                    # avanti — cioe' non ripiegava.
            prima = Scelta(self.modello_in_uso(), "", None, None, "")
            dopo = il_successivo(prima, cat)
        except Exception as e:  # noqa: BLE001
            self.bridge.emit("routing", {
                "modello": "", "categoria": "", "punteggio": None,
                "prove": None, "scartati": [], "spiegazione": "",
                "motivo": f"ripiego non disponibile: {e}",
            })
            return

        if dopo.modello is None or dopo.modello == self.modello_in_uso():
            self.bridge.emit("routing", {
                "modello": "", "categoria": dopo.categoria,
                "punteggio": None, "prove": None, "scartati": [],
                "spiegazione": "",
                "motivo": (f"{errori} errori di fila e nessuna "
                           f"alternativa misurata"),
            })
            return

        if not self.cambia_modello(dopo.modello):
            return
        self._ripiegato_su = dopo.modello
        self.agent.state.consecutive_errors = 0
        self.bridge.emit("routing", {
            "modello": dopo.modello,
            "categoria": dopo.categoria,
            "punteggio": dopo.punteggio,
            "prove": dopo.prove,
            "scartati": dopo.scartati[:3],
            "spiegazione": dopo.spiega(),
            "motivo": (f"{errori} errori di fila: passo a "
                       f"{dopo.modello}"),
        })

    def instradamento_ora(self) -> bool:
        """Se l'instradamento automatico e' acceso adesso."""
        return bool(self._routing_attivo)

    def _registra_tool_proposta(self) -> None:
        """Registra `proponi_merge` sulla sessione, una volta sola.

        Il tool non unisce niente: registra una proposta che l'utente
        vede nel pannello. Tenerlo fuori dal registro finche' non c'e'
        un checkout evita di offrire al modello un'azione che, in chat
        normale, non avrebbe senso.
        """
        from .types import Tool

        if "proponi_merge" in self.registry:
            return

        def _proposta(riepilogo: str, verifica: str) -> str:
            fn = getattr(self, "_proponi_merge", None)
            if fn is None:
                return "[nessun checkout isolato attivo: non c'e' nulla da proporre]"
            return str(fn(riepilogo, verifica))

        self.registry.register(Tool(
            name="proponi_merge",
            description=(
                "Chiamalo solo quando lavori in un checkout isolato, hai "
                "finito le modifiche e hai eseguito le verifiche (test, "
                "build). Committa le modifiche sul ramo isolato e registra "
                "una proposta di merge per l'utente: NON unisce il ramo e "
                "non tocca il progetto. Se le verifiche non sono passate, "
                "non chiamarlo."),
            schema={
                "type": "object",
                "properties": {
                    "riepilogo": {
                        "type": "string",
                        "description": ("Cosa hai cambiato, in due o tre "
                                        "righe: file e comportamento."),
                    },
                    "verifica": {
                        "type": "string",
                        "description": ("Quali comandi hai eseguito e con "
                                        "quale risultato. Non inventare: "
                                        "l'utente lo legge prima di unire."),
                    },
                },
                "required": ["riepilogo", "verifica"],
            },
            handler=_proposta,
        ))

    def send(self, user_input: str, allegati: list | None = None,
             scope: str | None = None, bot_depth: int = 0,
             root_isolata: str = "", proponi_merge: Any = None) -> bool:
        """Invia un messaggio all'agente. Non blocca.

        Restituisce False se la sessione e' gia' occupata: rifiutiamo il
        secondo turno invece di accodarlo, perche' accodare richieste che
        l'utente non vede e' peggio che dirgli di aspettare.

        `allegati` sono Attachment gia' pronti (foto, pagine di PDF come
        data URL). Vanno sull'UTIMO messaggio utente, non su un nuovo
        messaggio: l'utente ha scritto "estrai i prezzi" e l'immagine
        insieme, e due messaggi separati fanno leggere all'agente
        l'istruzione senza l'allegato, o il contrario.

        Un PDF con testo non viaggia come immagine: finisce nel testo
         è la categoria di lavoro scelta nell'header (code, extraction,
        reasoning, ecc.). Se fornito, guida l'instradamento automatico
        invece di lasciarlo indovinare dalle parole chiave.
        del messaggio. Costa zero token ed e' esatto, mentre renderlo
        in immagini costerebbe 1100 token a pagina per un risultato
        peggiore.
        """
        # Instradamento automatico. Prima di occupare la sessione e
        # prima di accodare il messaggio: se lo si facesse dopo, il
        # turno partirebbe col modello sbagliato e la correzione
        # arriverebbe al turno successivo — cioe' mai, perche' nel
        # frattempo hai gia' letto la risposta.
        #
        # Non e' il posto giusto per farlo? Lo e': qui la richiesta
        # dell'utente esiste per intero, e prima non si sa cosa
        # rispondere. Dopo, si sa e si e' tardi.
        if self._routing_attivo and self._scegli_primo is not None \
                and not self._busy:
            scelto = None
            try:
                scelto = self._scegli_primo(user_input, scope=scope)
            except Exception:  # noqa: BLE001
                # Una scelta che fallisce non puo' far fallire il
                # turno: si continua col modello che si ha. Ma si dice
                # — un instradamento che non parte e non lo dice e'
                # un instradamento spento.
                self.bridge.emit("routing", {
                    "modello": "", "categoria": "", "punteggio": None,
                    "prove": None, "scartati": [], "spiegazione": "",
                    "motivo": "instradamento non disponibile",
                })
                scelto = None
            if scelto:
                _busy = self._busy
                self._busy = False
                try:
                    if self._cambia_modello is not None:
                        self._cambia_modello(scelto)
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    self._busy = _busy

        with self._lock:
            if self._busy:
                return False
            self._busy = True
            # La profondita' vale per il turno che sta per partire. Sta
            # qui e non nel thread: il tool la legge dal proprio oggetto
            # Session, e una sessione esegue un turno alla volta — quindi
            # non c'e' il caso in cui due turni si contendono il valore.
            self._bot_depth = max(0, int(bot_depth))
            # La root isolata si lega al turno QUI, sotto lo stesso lock
            # che lo fa partire. Impostarla prima di `send` aprirebbe
            # una corsa con un turno dell'utente: se quello vincesse,
            # girerebbe nel worktree destinato al lavoro in background.
            self._root_isolata = (os.path.abspath(os.path.expanduser(
                str(root_isolata or ""))) if root_isolata else "")
            if proponi_merge is not None:
                self._registra_tool_proposta()
            self._proponi_merge = proponi_merge
            self._cancel.clear()

        self._thread = threading.Thread(
            target=self._run_turn,
            args=(user_input, allegati or []),
            daemon=True,
            name="orchestra-turn",
        )
        self._thread.start()
        return True

    def _run_turn(self, user_input: str, allegati: list | None = None) -> None:
        allegati = allegati or []
        # Traccia del turno: registra OGNI evento su disco mentre gira, così
        # domani si può riaprire "perché quel task ha sbagliato" senza
        # ripeterlo. Avvolgo l'on_event dell'agent: registra e poi inoltra al
        # bridge (lo streaming live non si tocca). Nel finally si salva la
        # traccia — anche se il turno muore a metà, quello che è successo
        # fino a lì resta, ed è spesso la parte che conta.
        from .traccia import RegistratoreTurno
        reg = RegistratoreTurno(sessione_id=getattr(self, "_sessione_id", None))
        emit_originale = self.agent.on_event
        def emit_con_traccia(kind, data):
            reg.registra(kind, data)
            if emit_originale:
                emit_originale(kind, data)
        self.agent.on_event = emit_con_traccia
        try:
            self._esegui_turno(user_input, allegati, reg)
        finally:
            self.agent.on_event = emit_originale
            st = self.agent.state
            reg.imposta_riepilogo(
                esito=getattr(st, "stopped_because", "") or "",
                iterazioni=getattr(st, "iterations", 0) or 0,
                tool_chiamate=getattr(st, "tool_calls_made", 0) or 0,
                errori=getattr(st, "tool_errors", 0) or 0,
                token=getattr(st, "total_tokens", 0) or 0,
                modello=self.modello_in_uso(),
                evento_finale=getattr(st, "stopped_because", "") or "",
            )
            # Solo la traccia: `_salva_su_disco` lo fa già il `finally`
            # interno di `_esegui_turno`, in ogni caso (successo, annulla,
            # eccezione). Duplicarlo qui sarebbe lavoro speso due volte.
            reg.salva()

    def _esegui_turno(self, user_input: str, allegati: list,
                      reg: Any) -> None:
        allegati = allegati or []
        # Se il testo nomina un progetto, si cambia progetto. E' il
        # meccanismo che fa diventare "oggi lavoriamo al sito
        # ristorante" una frase che FA qualcosa.
        #
        # Poi la root: va rimessa DOPO il riconoscimento, perche' e'
        # il riconoscimento a poter cambiare il progetto, e quindi
        # la cartella in cui si scrive. La root preparata prima
        # rifletterebbe il progetto vecchio, e l'agente scriverebbe
        # nella cartella sbagliata per un turno intero.
        try:
            # In un checkout isolato il progetto e' gia' deciso dal
            # lavoro: riconoscerlo dal testo potrebbe spostare il turno
            # su un altro progetto (e quindi su un altro repository)
            # mentre la root resta il worktree. Il nome cambierebbe e i
            # tool scriverebbero nel posto sbagliato con l'etichetta
            # giusta, che e' peggio di non riconoscere niente.
            if not (getattr(self, "_root_isolata", "") or "").strip():
                self._riconosci_progetto(user_input)
        except Exception:  # noqa: BLE001
            pass
        self._prepara_root()
        if allegati:
            # Si dice subito quanto costeranno. Un allegato da 12 MB
            # diventa una richiesta da 40.000 token, e scoprirlo dalla
            # fattura e' peggio che vederlo prima.
            totale = sum(a.token_stimati for a in allegati)
            self.bridge.emit("allegati", {
                "nomi": [a.nome for a in allegati],
                "immagini": len(allegati[0].immagini) if allegati else 0,
                "token_stimati": totale,
            })
        if self.agent.config.tool_profile:
            try:
                from .tools import applica_profilo, profilo_per_testo
                nome = self.agent.config.tool_profile
                if nome == "auto":
                    # L'auto si specializza sul testo del turno: il registro
                    # viene rifatto a ogni turno, e quello che conta e' che
                    # gli strumenti disponibili corrispondano a quello che
                    # sta per succedere.
                    nome = profilo_per_testo(user_input)
                applica_profilo(self.agent.registry, nome)
            except Exception:
                pass
        # `bot_chiedi` e' registrato a runtime e non compare in nessun
        # profilo: `applica_profilo` lo spegnerebbe al primo turno con un
        # profilo scelto, e il bot smetterebbe di poter chiedere senza che
        # nulla lo dica. Si riaccende dopo il profilo, non prima.
        if self._bot_risolutore is not None:
            try:
                self.agent.registry.attiva("bot_chiedi")
            except Exception:  # noqa: BLE001
                pass
        # Come `bot_chiedi`: il profilo puo' averlo disattivato, ma il
        # lavoro isolato lo ha registrato apposta per questo turno.
        if getattr(self, "_proponi_merge", None) is not None:
            try:
                self.agent.registry.attiva("proponi_merge")
            except Exception:  # noqa: BLE001
                pass
        # La policy viene DOPO il profilo e DOPO i tool runtime: e'
        # l'ultima parola, e vale anche per `bot_chiedi` e
        # `proponi_merge`. Se una allowlist non li nomina, il bot non li
        # ha — che e' quello che "tool consentiti" significa. Chi vuole
        # un bot che delega deve metterli nella lista, insieme a
        # `parla_con` per `bot_chiedi`.
        try:
            from . import policy as policy_mod
            policy_mod.attiva(self._policy)
            policy_mod.applica_al_registro(self.agent.registry, self._policy)
        except Exception:  # noqa: BLE001
            # Una policy che non si applica non deve diventare "nessun
            # limite": si toglie tutto, che e' il lato sicuro. I due
            # registri (tools e types) hanno nomi diversi per la stessa
            # cosa, e qui non si assume quale sia.
            try:
                from . import policy as policy_mod
                for tool in policy_mod.attivi(self.agent.registry):
                    policy_mod.spegni(self.agent.registry, tool.name)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.bridge.emit("turn_start", {"input": user_input})
            try:
                self.agent.run(user_input, allegati=allegati,
                               should_continue=self._should_continue)
            except Exception as e:  # noqa: BLE001
                # Alcuni provider listano modelli che non si possono usare
                # come agenti: senza tool-calling, o che non fanno chat
                # (whisper, per esempio). Il catalogo non lo dichiara, e
                # l'errore e' un HTTP 400 che sembra un problema di rete.
                #
                # Non si indovina quale sono: si prova, si segna il
                # fallimento, si passa al successivo. Ogni tentativo
                # insegna qualcosa, e la lezione resta scritta. Un
                # limite di 3 tiene il conto: oltre, il servizio non ha
                # niente di utilizzabile e insistere e' solo costo.
                for tentativo in range(3):
                    if not self._modello_rifiutato(e):
                        raise
                    if tentativo == 2:
                        raise
                    sostituto = self._prossimo_modello_utile()
                    if not sostituto:
                        raise
                    vecchio = self.modello_in_uso()
                    self.bridge.emit("log", {
                        "text": f"{vecchio}: {self._motivo_rifiuto(e)} — "
                                f"provo {sostituto}"
                    })
                    if not self.cambia_modello(sostituto):
                        raise
                    try:
                        self.agent.run(user_input, allegati=allegati,
                                       should_continue=self._should_continue)
                        break
                    except Exception as e2:  # noqa: BLE001
                        e = e2
            # Un turno che finisce senza una riga di risposta e' un
            # turno muto. Puo' capitare con un modello che risponde ma
            # non e' un modello conversazionale: senza dirlo, la chat
            # resta ferma e sembra un blocco della pagina.
            #
            # Non e' un errore da nascondere: e' la verita' sul servizio
            # scelto, e serve per scegliere un altro modello.
            if not any(m.role == "assistant" and (m.content or "").strip()
                       for m in self.agent.state.messages if hasattr(m, "role")):
                self.bridge.emit("log", {
                    "text": f"{self.modello_in_uso()} ha risposto con un "
                            f"testo vuoto: probabilmente non e' un modello "
                            f"conversazionale. Cambialo dal menu in alto."
                })
            self._ripiego_se_ripetono(user_input)

            self.bridge.emit(
                "turn_end",
                {
                    "stopped_because": self.agent.state.stopped_because,
                    "iterations": self.agent.state.iterations,
                    "total_tokens": self.agent.state.total_tokens,
                    "tool_calls": self.agent.state.tool_calls_made,
                    "tool_errors": self.agent.state.tool_errors,
                },
            )
        except Exception as e:  # noqa: BLE001 - l'ultima rete di sicurezza
            # Un'eccezione qui ucciderebbe il thread in silenzio e la UI
            # resterebbe appesa su uno stato "occupato" per sempre.
            self.bridge.emit(
                "error",
                {"message": f"{type(e).__name__}: {e}"},
            )
        finally:
            # La policy valeva per questo thread/turno, non per il
            # processo: il thread finisce qui, ma azzerarla esplicitamente
            # evita che un riuso del thread (o un test) porti in giro i
            # limiti di un bot che non sta piu' lavorando.
            try:
                from . import policy as policy_mod
                policy_mod.disattiva()
            except Exception:  # noqa: BLE001
                pass
            # Persistenza a fine turno, nel `finally`: un turno annullato
            # o caduto per errore ha già prodotto domanda e risposta
            # parziale, e buttarle via vuol dire ripetere la domanda per
            # riavere la risposta che il modello aveva già scritto.
            #
            # Si salva qui e non a ogni messaggio: un turno interrotto a
            # metà risposta non deve lasciare su disco una risposta
            # completa che non lo era. `stopped_because` dice com'è
            # andata, e resta nel DB accanto ai messaggi.
            self._salva_su_disco()
            self._ricorda_turno()
            # `busy` va azzerato PRIMA di emettere `idle`, non dopo: la UI
            # usa `idle` come segnale per riabilitare l'input, e se arrivasse
            # prima dello stato reale accetterebbe un messaggio che il server
            # rifiuterebbe con 409. Ordine: stato, poi segnale.
            with self._lock:
                self._busy = False
                # Il checkout valeva per questo turno, non per la
                # sessione: il prossimo messaggio dell'utente torna
                # nella cartella del progetto.
                self._root_isolata = ""
                self._proponi_merge = None
                try:
                    self.registry.disattiva("proponi_merge")
                except Exception:  # noqa: BLE001
                    pass
                now_free = True
            if now_free:
                st = self.agent.state
                self.bridge.emit("idle", {"busy": False,
                    "iterations": st.iterations,
                    "total_tokens": st.total_tokens,
                    "tool_calls": st.tool_calls_made,
                    "tool_errors": st.tool_errors,
                    "compactions": st.compactions,
                    "context_limit": getattr(
                        getattr(self.agent, "config", None),
                        "context_limit", 0) or 0,
                    "context_tokens": count_tokens(self.agent.state.messages)})

    def _nuova_sessione_db(self) -> int:
        """Crea una riga nello storico e ne torna l'id."""
        try:
            return storico().nuova_sessione(modello=self.modello_in_uso(),
                                            bot=self.bot)
        except Exception:
            return -1

    def carica_sessione(self, sessione_id: int) -> bool:
        """Ripristina una conversazione dal disco.

        Sostituisce lo stato in memoria, non lo accoda: i messaggi di
        adesso appartengono a un'altra chat, e mischiare le due darebbe
        una conversazione che non è mai esistita.
        """
        if self._busy:
            raise RuntimeError("sessione occupata: attendi o annulla prima")
        try:
            messaggi = storico().messaggi(sessione_id)
        except Exception:
            return False
        with self._lock:
            self._sessione_id = sessione_id
            ricostruiti = [Message(role="system",
                                   content=self.agent.system_prompt)]
            for m in messaggi:
                if m["ruolo"] in ("user", "assistant") and m["contenuto"].strip():
                    ricostruiti.append(Message(role=m["ruolo"],
                                               content=m["contenuto"],
                                               name=m.get("nome"),
                                               reasoning=m.get("ragionamento", "") or ""))
            self.agent.state.messages = ricostruiti
        self.bridge.emit("sessione_caricata", {"id": sessione_id})
        return True

    def _salva_su_disco(self) -> None:
        """Scrive i messaggi del turno nello storico.

        Silenziosa per scelta: un errore del DB non deve uccidere un
        turno che è già riuscito. La conversazione è in memoria, l'utente
        l'ha vista — perdere il salvataggio è un difetto da segnalare, non
        da far diventare un errore in chat.
        """
        st = self.agent.state
        messaggi = [
            {"ruolo": m.role, "contenuto": m.content, "nome": m.name,
             "ragionamento": getattr(m, "reasoning", "") if m.role == "assistant" else ""}
            for m in st.messages
            if m.role in ("user", "assistant") and m.content.strip()
        ]
        # Niente da salvare = niente riga. Creare una conversazione vuota
        # per ogni turno vuoto riempie la cronologia di righe senza
        # contenuto — ed è il loop: elimini la riga, ricompare al giro
        # dopo, la elimini di nuovo. Una riga nasce solo quando c'è qualcosa
        # da metterci dentro.
        if not messaggi:
            return
        # Se non c'è una riga attiva (es. hai eliminato l'ultima
        # conversazione), la si crea ORA, al primo messaggio vero. Così
        # eliminare l'ultima lascia la lista vuota, e la conversazione
        # riparte da sola al prossimo scambio — senza ricreare righe
        # fantasma nel frattempo.
        if self._sessione_id is None:
            self._sessione_id = self._nuova_sessione_db()
            if self._sessione_id == -1:
                return
        try:
            storico().salva_turno(self._sessione_id, messaggi,
                                  modello=self.modello_in_uso())
            # Il titolo si prende dal primo messaggio dell'utente: una
            # sessione si apre prima che si scriva, quindi all'inizio non
            # c'è niente da metterci.
            primo = next((m["contenuto"] for m in messaggi
                          if m["ruolo"] == "user"), "")
            if primo:
                storico().titolo_se_vuoto(self._sessione_id, primo)
        except Exception:
            pass

    def _should_continue(self, state: AgentState) -> bool:
        return not self._cancel.is_set()

    def _ricorda_turno(self) -> int:
        """Alla fine del turno, la conversazione diventa memoria.

        Questo e' il pezzo che mancava. `estrai_fatti` e `applica_fatti`
        esistevano in `memoria.py` da tempo, ma nessuno le chiamava: la
        memoria non ricordava niente da sola. L'unico modo perché un
        fatto arrivasse era che l'agente si ricordasse di chiamare il
        tool `memoria` con `azione=aggiungi` — e un agente non si
        ricorda le cose da solo.

        Si chiama qui, nel `finally` di `_esegui_turno`, perche' e' il
        punto in cui il turno e' finito: anche un turno annullato a
        meta' ha prodotto una domanda e una risposta parziale, e
        quello che c'e' da imparare c'e'.

        Non blocca il turno: l'estrazione chiama il provider, e un
        provider lento aggiungerebbe secondi a ogni risposta. Va in un
        thread secco, e il suo fallimento non tocca niente: una memoria
        che non ha imparato niente e' un turno che ha funzionato lo
        stesso.

        Ritorna 0 SEMPRE, e non per un difetto: il lavoro avviene nel
        thread, e il chiamante non puo' saperlo al momento della
        chiamata. Un numero qui sarebbe un numero inventato — e un
        numero inventato in un resoconto e' peggio di nessun numero.

        Il progetto e' quello attivo. Ogni fatto che nasce porta
        quell'etichetta, e cosi un archivio condiviso resta
        interrogabile per progetto.
        """
        try:
            testo = self._testo_per_estrazione()
            if not testo:
                return 0
            from .memoria import estrai_e_ricorda
            progetto = getattr(self, "progetto", "") or ""
            provider = self.agent.provider
        except Exception:
            # La memoria non deve mai far cadere un turno riuscito.
            return 0

        # In un thread, perche' l'estrazione chiama il provider e un
        # provider lento aggiungerebbe secondi a ogni risposta. Il
        # thread e' "secco": non blocca nessuno e il suo fallimento
        # non tocca niente — una memoria che non ha imparato niente
        # e' un turno che ha funzionato lo stesso.
        #
        # Il risultato non viene aspettato: il turno e' gia' finito e
        # l'utente non aspetta che la memoria si riempia. Il fatto
        # sara' li' per il turno successivo, che e' quando serve.
        def _lavora() -> None:
            try:
                estrai_e_ricorda(testo, provider, progetto=progetto)
            except Exception:
                pass

        try:
            t = threading.Thread(target=_lavora, daemon=True,
                                name="orchestra-memoria")
            t.start()
        except Exception:
            pass

        # Ogni tanto la memoria si pota da sola. Non a ogni turno: la
        # potatura tocca il file e l'indice, e farlo sempre sarebbe costo
        # fisso su un'operazione che serve solo dopo settimane. Ogni
        # venti turni è un compromesso: abbastanza spesso da non far
        # crescere la roba morta, abbastanza raro da non disturbare.
        try:
            self._turni_memoria = getattr(self, "_turni_memoria", 0) + 1
            if self._turni_memoria % 20 == 0:
                def _potatura() -> None:
                    try:
                        from .memoria_indice import ottimizza_memoria
                        ottimizza_memoria(dry_run=False, giorni_grazia=30)
                    except Exception:
                        pass
                threading.Thread(target=_potatura, daemon=True,
                                 name="orchestra-ottimizzatore").start()
        except Exception:
            pass
        return 0

    def _riconosci_progetto(self, testo: str) -> str:
        """Se il testo nomina un progetto, cambia progetto. Ritorna il nome.

        Il meccanismo che rende "oggi lavoriamo al sito ristorante"
        una frase che fa qualcosa, e non una frase che il modello
        interpreta da solo.

        Il perche' non e' "il modello capisce": un modello che vede
        "sito ristorante" in un prompt e in un progetto registrato
        PUO' capirlo, e PUO' sbagliare — e quando sbaglia scrive
        nel progetto sbagliato. Il costo di quell'errore e' alto
        (file sovrascritti, fatti etichettati sul progetto sbagliato)
        e non e' visibile subito.

        Quindi: il riconoscimento e' fatto QUI, deterministicamente,
        e il modello viene avvisato. Se il testo nomina piu'
        progetti non si sceglie: si chiede. Una domanda all'utente
        costa un secondo; un file scritto nella cartella sbagliata
        costa di piu'.

        Un progetto gia' attivo non viene cambiato per un testo che
        lo nomina: e' gia' quello su cui si sta lavorando.
        """
        try:
            from . import progetti as _pr
        except Exception:  # noqa: BLE001
            return ""
        try:
            nome, motivo = _pr.riconosci(testo)
        except Exception:  # noqa: BLE001
            return ""
        if not nome:
            return ""
        attuale = (getattr(self, "progetto", "") or "").strip()
        if attuale and attuale.lower() == nome.lower():
            return attuale
        # Il progetto deve esistere: `riconosci` lavora solo sui
        # progetti registrati, quindi questo e' solo una difesa.
        if not _pr.percorso_di(nome):
            return attuale
        try:
            self.imposta_progetto(nome)
            _pr.tocca(nome)
            self.bridge.emit("progetto_cambiato", {
                "progetto": nome,
                "percorso": _pr.percorso_di(nome),
                "motivo": motivo,
            })
        except Exception:  # noqa: BLE001
            return attuale
        return nome

    def _testo_per_estrazione(self) -> str:
        """La conversazione da rileggere per tirare fuori i fatti.

        Solo i messaggi dell'utente e dell'assistente: i risultati dei
        tool sono rumore per l'estrattore (sonooutput di programmi, non
        frasi dell'utente), e mandargli tuttoCosta token e diluisce la
        conversazione.

        Solo l'ULTIMO scambio, pero'. Una sessione lunga ha cento
        messaggi, e rileggerli tutti a ogni turno fa due cose sbagliate:
        costa token, e fa rileggere all'estrattore fatti che il
        modello aveva gia' imparato — con il rischio che ne tragga
        duplicati o che perda il filo di quello che e' successo ADESSO.

        Il limite di 8000 caratteri c'e' comunque, come rete di
        sicurezza: un singolo messaggio enorme non deve portare il
        prompt dell'estrattore a 500 KB.
        """
        scambio: list[str] = []
        for m in reversed(self.agent.state.messages):
            if m.role not in ("user", "assistant"):
                continue
            t = (m.content or "").strip()
            if not t:
                continue
            scambio.append(f"{m.role}: {t}")
            # l'ultimo scambio e' la domanda piu' la risposta: due
            # messaggi. Oltre, si sta rileggendo la sessione intera.
            if len(scambio) >= 2:
                break
        return "\n".join(reversed(scambio))[-8000:]

    # -- recupero da un modello che non regge il tool-calling ---------------
    #
    # Tre pezzi, ognuno con un nome suo cosi' si sa chi fa cosa:
    # riconoscere l'errore, scegliere il sostituto, cambiare il modello.
    # Sta nella Session e non nell'app perche' e' il posto dove si vede
    # l'errore; l'app fornisce solo i pezzi che dipendono dal provider.

    def _modello_rifiutato(self, err: Exception) -> bool:
        """L'errore dice che questo modello non va bene come agente?

        Si guarda il testo, non il tipo di eccezione: i provider
        rispondono in modi diversi e non c'e' un codice comune.

        Le parole chiave sono strette di proposito. Un 400 qualsiasi non
        e' la stessa cosa, e mascherarlo dietro un retry nasconderebbe il
        guasto vero — e costerebbe tre richieste a vuoto per capire che
        il problema era un altro.

        Copre i due casi reali incontrati: mancato tool-calling, e
        modello che non fa chat (whisper e affini, che un provider puo'
        elencare senza avvertire che sono modelli audio).
        """
        testo = str(err).lower()
        if "tool calling" not in testo and "tool_calling" not in testo \
                and "chat completion" not in testo and "chat/completions" not in testo:
            return False
        return any(w in testo for w in (
            "not supported", "non supportato", "unsupported", "does not support",
            "not available", "non e' supportato", "invalid_request",
        ))

    def _motivo_rifiuto(self, err: Exception) -> str:
        """Il motivo in parole brevi, per il log. Non l'errore intero."""
        testo = str(err)
        for segno in ("tool calling", "tool_calling"):
            if segno in testo.lower():
                return "niente tool-calling"
        return "non regge le chat"

    def _prossimo_modello_utile(self) -> str | None:
        """Un altro modello che regge i tool, se il provider ne sa qualcosa."""
        if self._scegli_sostituto is None:
            return None
        return self._scegli_sostituto(self.modello_in_uso())

    def modello_in_uso(self) -> str:
        return getattr(self.agent.provider, "model", "") or "?"

    def cambia_modello(self, model_id: str) -> bool:
        """Cambia il modello a meta' turno, perche' quello vecchio e' morto."""
        if self._cambia_modello is None:
            return False
        if not self._cambia_modello(model_id):
            return False
        self.bridge.emit("model_changed", {"model": model_id})
        return True

    def cancel(self) -> bool:
        """Chiede l'arresto gentile. Il turno in corso finisce."""
        if not self._busy:
            return False
        self._cancel.set()
        self.agent.request_cancel()
        self.bridge.emit("cancel_requested", {})
        return True

    def reset(self) -> None:
        """Nuova conversazione, stesso agent.

        Ricostruiamo lo stato ma teniamo provider, tool e configurazione:
        e' un reset logico, non un riavvio.
        """
        with self._lock:
            if self._busy:
                raise RuntimeError("sessione occupata: attendi o annulla prima")
            self._cancel.set()
            self.agent.state.messages = [
                Message(role="system", content=self.agent.system_prompt)
            ]
            self.agent.state.iterations = 0
            self.agent.state.total_tokens = 0
            self.agent.state.tool_calls_made = 0
            self.agent.state.tool_errors = 0
            self.agent.state.consecutive_errors = 0
            self.agent.state.compactions = 0
            self.agent.state.stopped_because = ""
            self.agent.state.usage_by_model = {}
            self.agent.state.steer_queue = []
            self.agent.state.steer_count = 0
            # Nuova conversazione = nuova riga nello storico, ma la si crea
            # QUANDO c'è qualcosa da salvarci, non adesso. Prima la creava
            # subito (`_nuova_sessione_db`), e ogni "nuova chat" o reset
            # lasciava una riga vuota nella cronologia: elimini l'ultima,
            # ricompare vuota al giro dopo, la elimini di nuovo — loop. La
            # riga nasce in `_salva_su_disco`, al primo turno con contenuto.
            # Così la cronologia mostra solo conversazioni vere.
            self._sessione_id = None
        self.bridge.emit("reset", {})

    def steer(self, testo: str) -> bool:
        """Inietta un messaggio durante il turno in corso.

        Fuori da un turno non si accoda niente: la coda verrebbe letta
        all'inizio del turno successivo e la guida finirebbe sulla
        domanda sbagliata. Meglio dire di no adesso.
        """
        if not self._busy:
            return False
        return self.agent.steer(testo)

    def wait(self, timeout: float | None = None) -> bool:
        """Attende la fine del turno in corso. Per i test e lo shutdown."""
        t = self._thread
        if t is None:
            return True
        t.join(timeout=timeout)
        return not t.is_alive()
