"""Permessi per uscire dalla root, con conferma dell'utente.

Il default e' chiuso: un tool puo' toccare solo la root, e per andare
fuori chiede. Questo e' il senso di un agente che scrive codice: se puo'
arrivare ovunque senza chiedere, non e' un aiuto, e' una porta aperta con
una sbarra.

Le tre scelte, e sono tre perche' due non bastano:

  una volta    vale per questa chiamata e basta
  per sessione vale finche' Orchestra resta aperto, non oltre
  mai         resta negato, e lo ricorda

La terza esiste perche' "questa volta" e "per questa sessione" si
assomigliano troppo: chiedere ogni volta e' fastidioso, e con un
permesso "per sempre" accordato a caso sul primo prompt si ottiene un
agente che scrive dove gli pare per il resto della giornata.

C'e' anche un quarto caso, non negoziabile: i percorsi sensibili. Non
sono autorizzabili con nessuna delle tre scelte, perche' sbagliarli non
costa un file, costa il sistema. Su quelli si nega e basta — e si dice
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


class Negato(Exception):
    """L'operazione non e' consentita. Non e' un errore da riprovare."""


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
    scelta: str          # "una_volta" | "sessione" | "mai"
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

        # 2. percorsi vietati: nessuna delle tre scelte li sblocca
        motivo = self.percorso_sensibile(p)
        if motivo:
            return "negato"

        k = self._chiave(p)
        with self._lock:
            # 3. negato in precedenza, e il tempo non e' scaduto
            if k in self._negati:
                return "negato"
            # 4. concesso per la sessione, se non e' scaduto
            scade = self._sessione.get(k)
            if scade is not None:
                if scade > time.time():
                    return "concesso"
                del self._sessione[k]
        return "chiedi"

    # -- la domanda ---------------------------------------------------------

    def chiedi_all_utente(self, percorso: str, azione: str,
                          dettaglio: str = "") -> bool:
        """Ferma l'esecuzione finche' l'utente non risponde.

        True = concesso. False = negato. Se non c'e' nessuno a cui
        chiedere (CLI, benchmark) si nega: il default sicuro e' negare,
        non tirare a indovinare.
        """
        esito = self.valuta(percorso, azione, dettaglio)
        if esito == "concesso":
            return True
        if esito == "negato":
            return False
        if self.chiedi is None:
            return False

        with self._lock:
            self._contatore += 1
            rid = f"p{self._contatore}"
        richiesta = Richiesta(id=rid, percorso=str(percorso), azione=azione,
                              dettaglio=dettaglio,
                              motivo="fuori dalla cartella di lavoro")
        evento = threading.Event()
        with self._lock:
            self._attesa[rid] = evento

        try:
            risp = self.chiedi(richiesta)
        except Exception:  # noqa: BLE001
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
                "negati": sorted(self._negati),
            }

    def revoca(self, percorso: str) -> bool:
        """Toglie un permesso concesso per la sessione."""
        k = self._chiave(Path(str(percorso)))
        with self._lock:
            return self._sessione.pop(k, None) is not None
