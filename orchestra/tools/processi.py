"""I processi che sopravvivono alla chiamata: avviarli, leggerli, fermarli.

Il problema che risolve. `run_shell` ASPETTA: ha un timeout, e quando
scade uccide il processo. Va bene per `pytest`, non per un `npm run dev`,
un `python -m http.server`, un watcher — comandi che per definizione non
finiscono. Con `run_shell` l'agente non poteva avviare un server e poi
guardarlo, e per un lavoro web quello e' meta' del ciclo: il modo di
sapere se una pagina si apre e' aprirla.

Qui il processo si avvia, si stacca, e resta vivo. L'output va su un
FILE e non in una pipe: una pipe la deve leggere qualcuno, e se nessuno
la legge il processo si blocca appena il buffer e' pieno — cioe' un
server che smette di rispondere proprio quando lo si guarda. Un file lo
legge il tool, quando serve.

Le regole, e il perche' di ognuna:

- il log sta DENTRO la root (`tmp/processi/`), non in una temp di
  sistema: cosi' `read_file` lo puo' aprire, e il percorso che il modello
  vede e' uno che puo' rileggere.
- l'output si legge in coda (le ultime N righe) e NON si consuma: due
  letture di fila danno lo stesso stato, e una `leggi` non fa sparire la
  riga che il modello non aveva ancora guardato.
- l'attesa all'avvio e' breve ma obbligatoria. Il caso peggiore di un
  comando in background e' quello che muore subito: porta gia' occupata,
  comando sbagliato, modulo mancante. Senza guardare, l'agente crede di
  aver avviato un server e non capisce perche' la pagina non risponde.
  Quindi si aspetta un secondo o due e, se e' gia' morto, si riporta
  l'exit code e la coda del log invece di un id apparentemente sano.
- quando Orchestra esce, i processi si fermano. Un server orfano tiene
  occupata la porta, e il turno dopo non riesce piu' ad avviarlo senza
  che nessuno dica perche'.
- al massimo `MASSIMO_VIVI` insieme: senza un tetto, un modello che
  riprova in loop riempie la macchina di server e la diagnosi diventa
  "perche' va tutto lento".

Cosa NON fa: non registra i processi per l'annullamento del turno. Un
`ferma` esplicito, o l'uscita di Orchestra. Annullare un turno non deve
portarsi via il server che l'utente sta guardando nel browser — e se lo
porta via, la pagina che sta guardando smette di funzionare senza che
nessuno abbia chiesto niente.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import testo as testo_mod
from ._guard import _detect_posix_shell, _kill_tree, _root, _sandbox_env

# Quanti processi possono essere vivi insieme. Otto copre il caso vero
# (frontend, backend, database, tunnel) con margine, e lascia un numero
# finito di porte occupabili per sbaglio.
MASSIMO_VIVI = 8

# L'attesa massima all'avvio: oltre, non e' piu' una diagnosi, e' una
# chiamata che sembra appesa.
ATTESA_MASSIMA = 30.0

# Quanti processi usciti restano nell'elenco (il modello puo' ancora
# voler leggere il loro output: e' quello che spiega perche' sono usciti).
MASSIMO_MORTI = 20

# Quanti byte di log si leggono dal fondo. Un log di 200 MB non si legge
# per intero per mostrarne le ultime 80 righe, e il modello non ha modo
# di sapere quanto e' grosso finche' non glielo si dice.
BYTE_IN_CODA = 400_000

# Le ultime righe del log che accompagnano un processo morto subito: e'
# il messaggio d'errore del comando, cioe' la diagnosi.
RIGHE_DIAGNOSI = 40

_LOCK = threading.Lock()
_PROCESSI: dict[str, "Processo"] = {}
_CONTATORE = 0


@dataclass
class Processo:
    """Un comando avviato e ancora (o non piu') vivo."""

    id: str
    comando: str
    cwd: str
    log: Path
    avviato: float
    popen: subprocess.Popen
    fermato: bool = False
    pid: int = field(default=0)
    # Quando e' finito. Si registra al primo controllo che lo trova
    # morto, perche' altrimenti la durata continua a crescere e un
    # processo morto in 0,3s risulta "uscito dopo 40s": il numero che
    # serve a capire se il comando ha fallito subito direbbe il falso.
    fine: float | None = None

    def __post_init__(self) -> None:
        self.pid = self.popen.pid

    def _aggiorna_fine(self) -> None:
        if self.fine is None and not self.vivo:
            self.fine = time.time()

    @property
    def vivo(self) -> bool:
        try:
            return self.popen.poll() is None
        except Exception:  # noqa: BLE001
            return False

    @property
    def codice(self) -> int | None:
        try:
            return self.popen.poll()
        except Exception:  # noqa: BLE001
            return -1

    @property
    def durata(self) -> float:
        self._aggiorna_fine()
        return (self.fine or time.time()) - self.avviato

    def stato(self) -> str:
        """Lo stato in una riga, come lo legge il modello."""
        if self.vivo:
            return f"in esecuzione da {self.durata:.0f}s (pid {self.pid})"
        if self.fermato:
            return f"fermato da me dopo {self.durata:.1f}s"
        return f"uscito con codice {self.codice} dopo {self.durata:.1f}s"


def _cartella_log() -> Path:
    """`tmp/processi` dentro la root, creata se manca.

    Dentro la root e non in una temp di sistema: il log deve essere un
    file che `read_file` puo' aprire, altrimenti "guarda il log" e' un
    consiglio che il modello non puo' seguire.
    """
    cartella = Path(_root()) / "tmp" / "processi"
    cartella.mkdir(parents=True, exist_ok=True)
    return cartella


def _decodifica(dati: bytes) -> str:
    """Testo da byte di un log, senza mai sollevare.

    Un comando puo' scrivere cp1252 su Windows e UTF-8 altrove: usare la
    stessa funzione di `read_file` evita due risposte diverse allo stesso
    file — e un UnicodeDecodeError dentro un tool lo ucciderebbe proprio
    mentre sta riportando l'errore che conta.
    """
    try:
        testo, _ = testo_mod.decodifica(dati)
        return testo
    except Exception:  # noqa: BLE001
        return dati.decode("utf-8", errors="replace")


def _coda_log(log: Path, righe: int) -> tuple[str, str]:
    """Le ultime `righe` righe del log, e un avviso se ne mancano.

    Il taglio si dice, con la stessa regola di `run_shell`: un output che
    finisce senza dirlo sembra completo, e un traceback tagliato a meta'
    si diagnostica male.
    """
    note = []
    try:
        dimensione = log.stat().st_size
        with open(log, "rb") as fh:
            if dimensione > BYTE_IN_CODA:
                fh.seek(dimensione - BYTE_IN_CODA)
                note.append(
                    f"log di {dimensione} byte: qui gli ultimi {BYTE_IN_CODA}")
            dati = fh.read()
    except FileNotFoundError:
        return "", "il log non esiste (il processo non ha ancora scritto niente)"
    except OSError as exc:
        return "", f"log non leggibile: {exc}"

    testo = _decodifica(dati)
    tutte = testo.splitlines()
    scelte = tutte[-righe:] if righe > 0 else tutte
    if len(tutte) > len(scelte):
        note.append(f"{len(tutte) - len(scelte)} righe in piu' non mostrate "
                    f"(alza 'righe' per vederle)")
    elif dimensione > BYTE_IN_CODA:
        note.append("la prima riga potrebbe essere tagliata a meta'")
    return "\n".join(scelte), "; ".join(note)


def _pota() -> None:
    """Tiene l'elenco leggibile: i morti piu' vecchi escono.

    Il processo non si tocca (e' gia' finito), si toglie solo la voce: un
    elenco di quaranta processi di cui trentanove morti non aiuta a
    trovare quello che serve.
    """
    morti = [p for p in _PROCESSI.values() if not p.vivo]
    if len(morti) <= MASSIMO_MORTI:
        return
    morti.sort(key=lambda p: p.avviato)
    for p in morti[:len(morti) - MASSIMO_MORTI]:
        _PROCESSI.pop(p.id, None)


def avvia(comando: str, cwd: str = ".", attesa: float = 2.0) -> dict:
    """Avvia `comando` staccato, e dice subito se e' gia' morto."""
    global _CONTATORE
    comando = (comando or "").strip()
    if not comando:
        return {"errore": "comando vuoto: niente da avviare"}
    try:
        attesa = max(0.0, min(float(attesa), ATTESA_MASSIMA))
    except (TypeError, ValueError):
        attesa = 2.0

    cartella = Path(cwd or ".")
    if not cartella.is_absolute():
        cartella = Path(_root()) / cartella
    if not cartella.is_dir():
        return {"errore": f"NON È UNA DIRECTORY: {cwd}"}

    with _LOCK:
        _pota()
        vivi = [p for p in _PROCESSI.values() if p.vivo]
        if len(vivi) >= MASSIMO_VIVI:
            elenco = ", ".join(f"{p.id} ({p.comando[:40]})" for p in vivi)
            return {"errore": (
                f"ci sono gia' {len(vivi)} processi vivi ({elenco}): "
                f"fermane uno con azione='ferma' prima di avviarne altri. "
                f"Un server orfano tiene occupata la porta, e il prossimo "
                f"avvio fallirebbe senza dirti perche'")}
        _CONTATORE += 1
        pid_tool = f"p{_CONTATORE}"

    # La cartella dei log puo' non essere creabile: in un'installazione
    # dentro `site-packages` la root e' di sola lettura. Meglio dirlo che
    # sollevare un'eccezione dal tool mentre il modello aspetta un id.
    try:
        cartella_log = _cartella_log()
    except OSError as exc:
        return {"errore": (
            f"non posso creare la cartella dei log in {_root()}/tmp "
            f"({exc}). Avvia Orchestra da una cartella scrivibile.")}
    log = cartella_log / f"{pid_tool}.log"
    posix = _detect_posix_shell()
    if posix:
        # Stessa scelta di `run_shell`: niente shell=True con cmd.exe, che
        # tratta i backslash e le virgolette a modo suo e restituisce
        # exit 0 su comandi mai eseguiti.
        argv: object = [posix, "-lc", comando]
        extra: dict = {}
    else:
        argv = comando
        extra = {"shell": True}
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        with open(log, "ab", buffering=0) as fh:
            proc = subprocess.Popen(
                argv,  # type: ignore[arg-type]
                cwd=str(cartella),
                env=_sandbox_env(),
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                start_new_session=(os.name != "nt"),
                **extra,
            )
    except OSError as exc:
        return {"errore": f"avvio fallito: {exc}"}

    p = Processo(id=pid_tool, comando=comando, cwd=str(cartella), log=log,
                 avviato=time.time(), popen=proc)
    with _LOCK:
        _PROCESSI[pid_tool] = p

    if attesa:
        try:
            proc.wait(timeout=attesa)
        except subprocess.TimeoutExpired:
            pass

    testo, nota = _coda_log(log, RIGHE_DIAGNOSI)
    esito = {
        "id": pid_tool,
        "comando": comando,
        "pid": p.pid,
        "vivo": p.vivo,
        "codice": p.codice,
        "stato": p.stato(),
        "cwd": str(cartella),
        "log": str(log),
        "uscita": testo,
        "nota": nota,
        "durata": round(p.durata, 2),
    }
    return esito


def _prendi(pid_tool: str) -> Processo | None:
    return _PROCESSI.get((pid_tool or "").strip())


def leggi(pid_tool: str, righe: int = 80) -> dict:
    """Lo stato di un processo e le ultime righe del suo output."""
    p = _prendi(pid_tool)
    if p is None:
        return {"errore": _non_trovato(pid_tool)}
    try:
        righe = max(1, min(int(righe or 80), 5000))
    except (TypeError, ValueError):
        righe = 80
    testo, nota = _coda_log(p.log, righe)
    return {
        "id": p.id,
        "stato": p.stato(),
        "vivo": p.vivo,
        "codice": p.codice,
        "durata": round(p.durata, 1),
        "cmd": p.comando,
        "cwd": p.cwd,
        "log": str(p.log),
        "uscita": testo,
        "nota": nota,
    }


def ferma(pid_tool: str, timeout: float = 5.0) -> dict:
    """Ferma il processo e tutto quello che ha generato.

    `_kill_tree` e non `kill`: un `npm run dev` e' un albero di tre
    processi, e uccidere il padre lascia il figlio che tiene la porta.
    """
    p = _prendi(pid_tool)
    if p is None:
        return {"errore": _non_trovato(pid_tool)}
    if not p.vivo:
        return {"id": p.id, "stato": p.stato(), "vivo": False,
                "giafinito": True,
                "nota": "era gia' finito: niente da fermare"}
    _kill_tree(p.pid)
    p.fermato = True
    try:
        p.popen.wait(timeout=max(1.0, min(float(timeout), 30.0)))
    except (subprocess.TimeoutExpired, ValueError):
        try:
            p.popen.kill()
        except Exception:  # noqa: BLE001
            pass
    testo, nota = _coda_log(p.log, 20)
    return {
        "id": p.id,
        "stato": p.stato(),
        "vivo": p.vivo,
        "codice": p.codice,
        "uscita": testo,
        "nota": nota,
    }


def elenca() -> dict:
    """Tutti i processi di questa sessione, vivi e morti."""
    with _LOCK:
        _pota()
        processi = sorted(_PROCESSI.values(), key=lambda p: p.avviato)
    vivi = [p for p in processi if p.vivo]
    return {
        "vivi": len(vivi),
        "totale": len(processi),
        "processi": [
            {"id": p.id, "stato": p.stato(), "vivo": p.vivo,
             "cmd": p.comando[:120], "cwd": p.cwd,
             "durata": round(p.durata, 1)}
            for p in processi
        ],
    }


def _non_trovato(pid_tool: str) -> str:
    """Un id sbagliato deve dire quali id esistono, non solo "non c'e'"."""
    noti = ", ".join(p.id for p in _PROCESSI.values()) or "nessuno"
    return (f"nessun processo con id '{pid_tool}'. Id di questa sessione: "
            f"{noti}. Gli id non sopravvivono a un riavvio di Orchestra.")


def ferma_tutti() -> int:
    """Ferma tutto, all'uscita di Orchestra.

    Senza questo, un server avviato in un turno resta acceso dopo che
    l'applicazione e' chiusa: la porta e' occupata, e al riavvio l'avvio
    fallisce con un messaggio che parla di porte invece che di un
    processo rimasto indietro.
    """
    with _LOCK:
        processi = list(_PROCESSI.values())
    fermati = 0
    for p in processi:
        if not p.vivo:
            continue
        try:
            _kill_tree(p.pid)
            p.fermato = True
            fermati += 1
        except Exception:  # noqa: BLE001
            continue
        # Attendere il decesso, non solo chiederlo. `taskkill` (e `killpg`
        # su POSIX) ritorna quando ha INVIATO il segnale: il processo puo'
        # essere ancora nel processo di uscire, e un `poll()` immediato
        # risponde "vivo" a un processo che sta morendo. Chi legge il
        # risultato — l'atexit, o un test — vedrebbe un orfano che c'e'
        # gia' stato ucciso. Due secondi sono un tetto, non un'attesa.
        try:
            p.popen.wait(timeout=2.0)
        except Exception:  # noqa: BLE001
            try:
                p.popen.kill()
                p.popen.wait(timeout=1.0)
            except Exception:  # noqa: BLE001
                pass
    return fermati


def azzera() -> None:
    """Svuota l'elenco (per i test: i processi non sono fermati)."""
    with _LOCK:
        _PROCESSI.clear()


atexit.register(ferma_tutti)
