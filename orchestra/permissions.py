"""Permessi per uscire dalla root, con conferma dell'utente.

Il default e' chiuso: un tool puo' toccare solo la root, e per andare
fuori chiede. Questo e' il senso di un agente che scrive codice: se puo'
arrivare ovunque senza chiedere, non e' un aiuto, e' una porta aperta con
una sbarra.

Le quattro scelte, e sono quattro perche' tre non bastano:

  una volta    vale per questa chiamata e basta
  per sessione vale finche' Orchestra resta aperto, non oltre
  sempre       resta concesso finche' non viene revocato a mano
  mai          resta negato, e lo ricorda

"sempre" esiste perche' alcuni percorsi sono di lavoro, non di passaggio:
un progetto in un'altra cartella, una toolchain. Chiedere ogni volta e'
fastidioso, e "per sessione" scade mentre il lavoro e' ancora aperto.
Revocabile da /api/permessi, cosi' non e' un permesso che resta per caso.

C'e' anche un quinto caso, non negoziabile: i percorsi sensibili. Non
sono autorizzabili con nessuna delle quattro scelte, perche' sbagliarli
non costa un file, costa il sistema. Su quelli si nega e basta — e si dice
perche', altrimenti sembra un bug.

Il vincolo e' sul TOOL, non sul prompt. Se autorizzi la lettura di una
cartella, vale anche quando l'agente usa run_shell per arrivarci: al
trimenti basta chiedere la permesso giusta e usare quella sbagliata.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Percorsi dove non si autorizza niente, in nessun modo. Non sono un
# elenco esaustivo di tutto quello che non va toccato: sono quelli che
# sbagliando rompono il computer, e un errore li' non e' recuperabile.
SENSIBILI: list[str] = [
    "C:/Windows",
    "C:/Program Files",
    "C:/Program Files (x86)",
    "C:/ProgramData",
    "C:/$Recycle.Bin",
    "C:/System Volume Information",
]

# Su Unix gli equivalenti, perche' Orchestra gira anche li' e un utente
# che la usa su macOS o Linux deve avere le stesse garanzie.
SENSIBILI_POSIX: list[str] = [
    "/etc", "/boot", "/sys", "/proc", "/dev", "/bin", "/sbin",
    "/usr/bin", "/usr/sbin", "/System", "/Library", "/private/etc",
]

# Percorsi di configurazione che l'utente NON vuole persi ma che non
# sono il sistema: chiedere e' giusto, negare sempre e' sbagliato.
CHIAVI_SENSIBILI = (".env", ".ssh", ".aws", ".gnupg", "id_rsa", "credentials")

# Come scade "per sessione": se l'utente conferma e poi lascia Orchestra
# aperto per un giorno, il permesso non deve durare per sempre. Un
# permesso che non scade e' un permesso che hai dimenticato di dare.
SESSIONE_SECONDI = 60 * 60 * 2

# Le scelte riconosciute. Unica fonte di verita': la UI, il prompt e il
# gate le leggono da qui, cosi' non possono divergere.
SCELTE = ("una_volta", "sessione", "sempre", "mai")


class Negato(Exception):
    """L'operazione non e' consentita. Non e' un errore da riprovare."""


def _log_permesso(msg: str) -> None:
    """Lo dice a stderr.

    Serve perche' il caso peggiore di questo modulo non e' negare per
    errore: e' negare per errore SENZA DIRE NIENTE. L'utente vede un
    rifiuto e pensa che l'agente abbia deciso cosi', mentre in realta' il
    canale delle domande e' rotto.
    """
    import sys
    try:
        print("[permessi] " + msg, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 - stderr puo' essere chiuso
        pass


@dataclass
class Richiesta:
    """Una domanda all'utente, in attesa di risposta."""

    id: str
    percorso: str
    azione: str          # "leggere" | "scrivere" | "eseguire"
    dettaglio: str = ""
    motivo: str = ""
    creata: float = field(default_factory=time.time)


@dataclass
class Risposta:
    scelta: str          # "una_volta" | "sessione" | "sempre" | "mai"
    testo: str = ""


class Gate:
    """Decide se un'operazione passa, e ferma chiedendo se non passa."""

    def __init__(self, root: str | os.PathLike[str] | None = None,
                 chiedi: Callable[[Richiesta], Risposta] | None = None) -> None:
        self.root = Path(root or os.environ.get("ORCHESTRA_ROOT", ".")).resolve()
        self.chiedi = chiedi
        # id di richiesta -> risposta. Il tool aspetta su questo.
        self._risposte: dict[str, Risposta] = {}
        self._attesa: dict[str, threading.Event] = {}
        # permessi concessi per la sessione: percorso -> scade
        self._sessione: dict[str, float] = {}
        # permessi concessi per sempre: percorso -> True
        self._sempre: set[str] = set()
        # permessi negati per sempre: percorso -> True
        self._negati: set[str] = set()
        self._lock = threading.Lock()
        self._contatore = 0

    # -- helpers ------------------------------------------------------------

    def _chiave(self, p: Path) -> str:
        return str(p).lower() if os.name == "nt" else str(p)

    def dentro_root(self, p: Path) -> bool:
        try:
            p.relative_to(self.root)
            return True
        except ValueError:
            return False

    def percorso_sensibile(self, p: Path) -> str:
        """Ritorna il motivo per cui il percorso e' vietato, o ''.

        La normalizzazione dei separatori non e' un dettaglio: su
        Windows `Path.resolve()` restituisce `C:\\Windows\\...` con i
        backslash, mentre le liste sono scritte con la forward slash. Il
        confronto falliva in silenzio — `C:/Windows` diventava
        autorizzabile con un semplice clic. Un controllo di sicurezza che
        non scatta e' peggio di non averlo, perche' sembra che ci sia.
        """
        sl = self._norm(str(p))
        for prefisso in SENSIBILI + SENSIBILI_POSIX:
            if sl.startswith(self._norm(prefisso)):
                return prefisso
        # chiavi e credenziali: vietate ovunque stiano
        for parte in CHIAVI_SENSIBILI:
            if parte in p.parts:
                return parte
        return ""

    @staticmethod
    def _norm(s: str) -> str:
        """Minuscolo e separatori uniformi, per confronti che reggano."""
        s = s.replace("\\", "/").rstrip("/")
        return s.lower() if os.name == "nt" else s

    # -- decisione ----------------------------------------------------------

    def _concesso_anche_figli(self, p: Path, chiave: str) -> bool:
        """Il permesso su una cartella vale anche per quello che c'e' dentro.

        Senza, concedere "Documenti" non serve a niente: il primo
        `ls Documenti/2024` chiede di nuovo, e poi `2024/marzo`, e
        l'utente preme "questa volta" ogni volta che scende di un
        livello. Il permesso che hai dato e' su una cartella, non su un
        indirizzo esatto.
        """
        try:
            padre = p.parent
        except Exception:  # noqa: BLE001
            return False
        while True:
            kp = self._chiave(padre)
            if kp == chiave:
                return True
            if padre == padre.parent:  # arrivati alla radice
                return False
            padre = padre.parent

    def valuta(self, percorso: str, azione: str,
               dettaglio: str = "") -> str:
        """Tre esiti: "concesso", "chiedi", "negato".

        "chiedi" vuol dire che il chiamante deve fare una domanda
        all'utente. "negato" non e' rimandabile: si nega e basta.
        """
        p = Path(percorso)
        if not p.is_absolute():
            p = (self.root / percorso).resolve()
        else:
            p = p.resolve() if p.exists() else Path(os.path.normpath(str(p)))

        # 1. dentro la root: nessuna domanda, e' il posto di lavoro
        if self.dentro_root(p):
            return "concesso"

        # 2. percorsi vietati: nessuna delle quattro scelte li sblocca
        motivo = self.percorso_sensibile(p)
        if motivo:
            return "negato"

        k = self._chiave(p)
        with self._lock:
            # 3. negato in precedenza: non si torna indietro
            if k in self._negati:
                return "negato"
            # 4. concesso per sempre
            if k in self._sempre:
                return "concesso"
            # 5. concesso per la sessione, se non e' scaduto
            scade = self._sessione.get(k)
            ora = time.time()
            if scade is not None:
                if scade > ora:
                    return "concesso"
                del self._sessione[k]
            # 5b. concesso perché sta dentro una cartella già concessa
            for kc, sc in self._sessione.items():
                if sc > ora and self._concesso_anche_figli(p, kc):
                    return "concesso"
            for kc in self._sempre:
                if self._concesso_anche_figli(p, kc):
                    return "concesso"
        return "chiedi"

    # -- la domanda ---------------------------------------------------------

    def chiedi_all_utente(self, percorso: str, azione: str,
                          dettaglio: str = "",
                          richiesta_id: str | None = None) -> bool:
        """Ferma l'esecuzione finche' l'utente non risponde.

        True = concesso. False = negato. Se non c'e' nessuno a cui
        chiedere (CLI, benchmark) si nega: il default sicuro e' negare,
        non tirare a indovinare.

        `richiesta_id` serve a chi genera la domanda per conto proprio e
        deve conoscere l'id per rispondere: senza, il chiamante lo
        scoprirebbe solo dentro l'evento, e nel frattempo la domanda
        sarebbe gia' partita con un id diverso.
        """
        esito = self.valuta(percorso, azione, dettaglio)
        if esito == "concesso":
            return True
        if esito == "negato":
            return False
        if self.chiedi is None:
            return False

        with self._lock:
            rid = richiesta_id or f"p{self._contatore + 1}"
            self._contatore += 1
        richiesta = Richiesta(id=rid, percorso=str(percorso), azione=azione,
                              dettaglio=dettaglio,
                              motivo="fuori dalla cartella di lavoro")
        evento = threading.Event()
        with self._lock:
            self._attesa[rid] = evento

        try:
            risp = self.chiedi(richiesta)
        except Exception as e:  # noqa: BLE001
            # Un canale rotto NON e' un "no". La differenza e' tutta qui:
            # se il canale muore e noi rispondiamo "no", l'utente vede un
            # rifiuto e non sa che il sistema e' guasto. Negare resta il
            # default sicuro, ma adesso lo si dice, almeno nei log.
            _log_permesso("canale dei permessi rotto: %s: %s"
                          % (type(e).__name__, e))
            risp = Risposta("mai")
        finally:
            with self._lock:
                self._attesa.pop(rid, None)
            evento.set()

        scelta = (risp.scelta or "mai").strip()
        if scelta == "una_volta":
            return True
        k = self._chiave(Path(str(percorso)))
        with self._lock:
            if scelta == "sessione":
                self._sessione[k] = time.time() + SESSIONE_SECONDI
                return True
            if scelta == "sempre":
                self._sempre.add(k)
                return True
            # "mai", o qualsiasi risposta non riconosciuta
            self._negati.add(k)
        return False

    def rispondi(self, richiesta_id: str, scelta: str) -> bool:
        """Risponde a una domanda in attesa. True se qualcuno aspettava."""
        with self._lock:
            evento = self._attesa.get(richiesta_id)
        if evento is None:
            return False
        self._risposte[richiesta_id] = Risposta(scelta)
        return True

    # -- stato per la UI ----------------------------------------------------

    def stato(self) -> dict[str, Any]:
        with self._lock:
            ora = time.time()
            attive = {k: v for k, v in self._sessione.items() if v > ora}
            return {
                "root": str(self.root),
                "in_attesa": list(self._attesa.keys()),
                "sessione": [
                    {"percorso": k,
                     "scade_tra": int(v - ora)}
                    for k, v in attive.items()
                ],
                "sempre": sorted(self._sempre),
                "negati": sorted(self._negati),
            }

    def revoca(self, percorso: str) -> bool:
        """Toglie un permesso concesso (sessione/sempre) o dimentica un "mai"."""
        k = self._chiave(Path(str(percorso)))
        with self._lock:
            tolto = self._sessione.pop(k, None) is not None
            tolto = k in self._sempre or tolto
            self._sempre.discard(k)
            tolto = k in self._negati or tolto
            self._negati.discard(k)
        return tolto
