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
from .types import Message, ToolRegistry


class EventBridge:
    """Coda di eventi thread-safe, con seq numerico per riprendere il flusso.

    Il seq serve a riconnettere: se il browser ricarica la pagina, chiede
    gli eventi da dove si era interrotto invece di rivedere tutto.
    """

    def __init__(self, maxsize: int = 2000) -> None:
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._seq = 0
        self._lock = threading.Lock()
        self._closed = False
        self._dropped = 0

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            if self._closed:
                return
            self._seq += 1
            item = {"seq": self._seq, "kind": kind, "data": data,
                    "ts": time.time()}
        try:
            self._q.put_nowait(item)
        except queue.Full:
            # Se il client non legge, non vogliamo bloccare il loop
            # dell'agente: perdiamo il vecchio evento e lo segnaliamo.
            try:
                self._q.get_nowait()
                self._dropped += 1
                self._q.put_nowait(item)
            except queue.Empty:
                pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
        # segnale di fine-stream: None come sentinella
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def stream(self, timeout: float = 15.0) -> Iterator[dict[str, Any]]:
        """Itera gli eventi finche' non arriva la sentinella.

        Emette un keep-alive ogni `timeout` secondi di silenzio: senza,
        proxy e browser chiudono la connessione SSE dopo poco.
        """
        while True:
            try:
                item = self._q.get(timeout=timeout)
            except queue.Empty:
                yield {"kind": "keepalive", "data": {}, "seq": -1, "ts": time.time()}
                continue
            if item is None:
                return
            yield item

    @property
    def dropped(self) -> int:
        return self._dropped


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

    def send(self, user_input: str) -> bool:
        """Invia un messaggio all'agente. Non blocca.

        Restituisce False se la sessione e' gia' occupata: rifiutiamo il
        secondo turno invece di accodarlo, perche' accodare richieste che
        l'utente non vede e' peggio che dirgli di aspettare.
        """
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self._cancel.clear()

        self._thread = threading.Thread(
            target=self._run_turn,
            args=(user_input,),
            daemon=True,
            name="orchestra-turn",
        )
        self._thread.start()
        return True

    def _run_turn(self, user_input: str) -> None:
        try:
            self.bridge.emit("turn_start", {"input": user_input})
            self.agent.run(user_input, should_continue=self._should_continue)
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
            # `busy` va azzerato PRIMA di emettere `idle`, non dopo: la UI
            # usa `idle` come segnale per riabilitare l'input, e se arrivasse
            # prima dello stato reale accetterebbe un messaggio che il server
            # rifiuterebbe con 409. Ordine: stato, poi segnale.
            with self._lock:
                self._busy = False
                now_free = True
            if now_free:
                self.bridge.emit("idle", {"busy": False})

    def _should_continue(self, state: AgentState) -> bool:
        return not self._cancel.is_set()

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
        self.bridge.emit("reset", {})

    def wait(self, timeout: float | None = None) -> bool:
        """Attende la fine del turno in corso. Per i test e lo shutdown."""
        t = self._thread
        if t is None:
            return True
        t.join(timeout=timeout)
        return not t.is_alive()
