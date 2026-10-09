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

import queue
import threading
import time
from typing import Any, Iterator

from .agent import Agent, AgentState, LoopConfig
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

        self.agent = Agent(
            provider,
            registry,
            system_prompt,
            config or LoopConfig(),
            summarize=summarize,
            on_event=self.bridge.emit,
        )

    # -- stato -------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._busy

    def snapshot(self) -> dict[str, Any]:
        """Stato corrente, serializzabile, per la UI.

        I messaggi assistant senza testo vengono omessi: sono i turni in cui
        il modello ha solo emesso tool call, e mostrarli come messaggi vuoti
        fa righe bianche nella cronologia. Il loro contenuto si vede dai tool.
        """
        with self._lock:
            st: AgentState = self.agent.state
            return {
                "busy": self._busy,
                "iterations": st.iterations,
                "total_tokens": st.total_tokens,
                "tool_calls": st.tool_calls_made,
                "tool_errors": st.tool_errors,
                "compactions": st.compactions,
                "stopped_because": st.stopped_because,
                "usage_by_model": dict(st.usage_by_model),
                "messages": [
                    {"role": m.role, "content": m.content, "name": m.name}
                    for m in st.messages
                    if m.role == "user"
                    or (m.role == "assistant" and m.content.strip())
                ],
            }

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

    def send(self, user_input: str, allegati: list | None = None, scope: str | None = None) -> bool:
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
            # `busy` va azzerato PRIMA di emettere `idle`, non dopo: la UI
            # usa `idle` come segnale per riabilitare l'input, e se arrivasse
            # prima dello stato reale accetterebbe un messaggio che il server
            # rifiuterebbe con 409. Ordine: stato, poi segnale.
            with self._lock:
                self._busy = False
                now_free = True
            if now_free:
                self.bridge.emit("idle", {"busy": False})

    def _nuova_sessione_db(self) -> int:
        """Crea una riga nello storico e ne torna l'id."""
        try:
            return storico().nuova_sessione(modello=self.modello_in_uso())
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
                                               name=m.get("nome")))
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
        if self._sessione_id is None:
            return
        try:
            st = self.agent.state
            messaggi = [
                {"ruolo": m.role, "contenuto": m.content, "nome": m.name}
                for m in st.messages
                if m.role in ("user", "assistant") and m.content.strip()
            ]
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
            # Nuova conversazione = nuova riga nello storico, non la
            # vecchia svuotata. Senza questo, "nuova chat" cancella la
            # conversazione di ieri e ci scrive sopra: l'utente crede di
            # averne aperta una e ha perso l'altra.
            if self._sessione_id is not None:
                self._sessione_id = self._nuova_sessione_db()
        self.bridge.emit("reset", {})

    def wait(self, timeout: float | None = None) -> bool:
        """Attende la fine del turno in corso. Per i test e lo shutdown."""
        t = self._thread
        if t is None:
            return True
        t.join(timeout=timeout)
        return not t.is_alive()
