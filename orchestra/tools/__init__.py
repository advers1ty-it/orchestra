"""Loader e registro degli strumenti Orchestra.

Questo pacchetto raccoglie tutti i tool in moduli singoli:
- read_file, write_file, edit_file, list_dir, run_shell, calculate
- memoria, web, storico, skill, browser, computer

default_registry() restituisce il registro completo con tutti i tool attivi.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Root del progetto e guardie di percorso
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent


def _root() -> Path:
    """Restituisce la root del progetto Orchestra."""
    return _ROOT


# Il gate vero sta in ._guard: qui si riesporta solo, perche' webapp lo
# importa da qui (`from .tools import set_permission_gate`). La versione
# booleana che stava qui prima intercettava la chiamata e il gate vero
# restava None: tutti i tool negavano all'istante senza mai chiedere.
from ._guard import set_permission_gate  # noqa: E402,F401

# Le guardie della shell, riesportate perche' i test e il resto del
# codice le cercano da qui: sono il cuore del "la shell non esce
# dalla cartella di lavoro", e una funzione che sta in un posto e
# viene cercata in un altro e' una funzione che non si trova.
from ._guard import (  # noqa: E402,F401
    _check_shell_access,
    _detect_posix_shell,
)


# ---------------------------------------------------------------------------
# Import dei tool dai moduli singoli
# ---------------------------------------------------------------------------

from .read_file import tool_read_file  # noqa: E402
from .write_file import tool_write_file  # noqa: E402
from .edit_file import tool_edit_file  # noqa: E402
from .list_dir import tool_list_dir  # noqa: E402
from .run_shell import tool_run_shell  # noqa: E402
from .calculate import tool_calculate  # noqa: E402
from .memoria import tool_memoria  # noqa: E402
from .web import tool_web_cerca, tool_web_leggi  # noqa: E402
from .storico import tool_storico_cerca  # noqa: E402
from .cron import tool_cron  # noqa: E402
from .skill import (
    tool_skill_cerca,
    tool_skill_leggi,
    tool_skill_genera,
    tool_skill_importa,  # noqa: E402
)
from .browser import (
    tool_browser_apri,
    tool_browser_render,
    tool_browser_screenshot,  # noqa: E402
)
from .computer import (
    tool_computer_screenshot,
    tool_computer_click,
    tool_computer_open,
    tool_computer_type,  # noqa: E402
)

# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class Tool:
    """Rappresenta uno strumento disponibile per il modello."""

    def __init__(self, name: str, description: str, schema: dict, handler) -> None:
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler


class ToolRegistry:
    """Registro degli strumenti attivi."""

    def __init__(self) -> None:
        self._tool: dict[str, Tool] = {}
        self._attivi: set[str] = set()

    def registra(self, tool: Tool) -> None:
        self._tool[tool.name] = tool

    def attiva(self, nome: str) -> None:
        self._attivi.add(nome)

    def disattiva(self, nome: str) -> None:
        self._attivi.discard(nome)

    def attivo(self, nome: str) -> bool:
        return nome in self._attivi

    def tool(self, nome: str) -> Tool | None:
        return self._tool.get(nome)

    def elenco_attivi(self) -> list[Tool]:
        return [self._tool[n] for n in self._attivi if n in self._tool]

    def nomi_attivi(self) -> list[str]:
        return sorted(self._attivi)

    # ---- alias inglesi: Session e Agent parlano questa API ----
    def register(self, tool: Tool, *, active: bool = True) -> "ToolRegistry":
        self.registra(tool)
        if active:
            self.attiva(tool.name)
        return self

    def get(self, nome: str) -> Tool | None:
        return self.tool(nome)

    def all_names(self) -> list[str]:
        return sorted(self._tool)

    def activate(self, *names: str) -> None:
        for n in names:
            self.attiva(n)

    def deactivate(self, *names: str) -> None:
        for n in names:
            self.disattiva(n)

    @property
    def active(self) -> list[Tool]:
        return [self._tool[n] for n in sorted(self._attivi) if n in self._tool]

    def __contains__(self, name: str) -> bool:
        # "n in registro" e' il modo naturale di chiedere se un tool
        # esiste, e la classe gemella in types.py lo supporta gia'.
        #
        # Senza questo, due classi con lo stesso nome hanno un'API
        # diversa: `from orchestra import ToolRegistry` (che e' quella di
        # types.py) accetta "n in r", ma il registro che
        # default_registry() restituisce — quello che il codice usa
        # davvero — solleva TypeError. E il TypeError dice "not a
        # container", che non somiglia a un difetto ma a un errore
        # di battitura.
        return name in self._tool

    def __len__(self) -> int:
        return len(self._tool)

    def api_payload(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema,
                },
            }
            for t in self.active
        ]


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = r"""Sei Orchestra, un agente tecnico.

Come lavori:
- Usa gli strumenti per fare, non per confermare che hai fatto. Se ti serve un dato, leggilo.
- Se uno strumento restituisce un errore, leggi l'errore e correggi. Non ripetere la stessa chiamata identica.
- Preferisci `list_dir` e `read_file` a indovinare il contenuto di un file.
- Rispondi in modo conciso. Niente preamboli, niente ripetizioni di quello che hai già detto.
- Quando hai finito, dì in una riga cosa hai fatto e dove sta il risultato.

Modificare un file:
- Per cambiare una parte di un file, usa `edit_file` con la stringa esatta (copiala da `read_file`): non riscrivere il file intero con `write_file`. Riscrivere 2000 righe per una costa il file in token e ogni riga e' una riga che puoi corrompere.
- `edit_file` cambia la prima occorrenza; `all=true` le cambia tutte.
- Se dice che la stringa non c'e', non riprovare alla cieca: rileggi la riga e passa quella esatta.

Quando cercare sul web:
- La tua conoscenza ha una data di taglio. Se la domanda dipende da un fatto che può essere cambiato dopo — prezzi, versioni, notizie, documentazione, chi è in carica oggi — cerca con `web_cerca` invece di rispondere a memoria.
- Se rispondi a memoria su una cosa che puoi verificare, dillo: "questo lo so fino a <data>, se vuoi te lo verifico". Non presentare un ricordo come un fatto attuale.
- `web_cerca` dà titoli e riassunti; `web_leggi` apre la pagina. Se il riassunto non basta, apri il risultato invece di indovinare dal titolo.
- Cerca solo quando serve: per cose che sai già, cercare è rumore e costa tempo.

Fuori dalla cartella di lavoro:
- Gli strumenti accettano percorsi ASSOLUTI, non solo relativi. Puoi quindi leggere C:\Users\adver\pippo senza portare nulla dentro il progetto.
- Se il percorso è fuori, all'utente compare una domanda con quattro scelte: una volta, per questa sessione, sempre, mai. Non devi fare nulla: la domanda la fa lo strumento e aspetta. Tu non hai strumenti per chiedere e non devi spiegare come fare.
- Se l'utente nega, il messaggio lo dice. Non riprovare lo stesso percorso con un altro strumento e non presentarlo come un errore: è una risposta, non un guasto. Rispettala e prova un'altra strada, o spiega in una riga che ti serve quel permesso.
- Alcuni percorsi non sono negabili da nessuna scelta (file di credenziali, cartelle di sistema). Se è così, lo strumento lo dice: è una decisione del sistema, non un errore da riprovare.
- Non dire mai "non posso accedere a <cartella>" senza averci provato. Se hai la conferma che è irraggiungibile, allora sì, e in una riga spiega perché e cosa hai tentato.

La shell:
- Hai `run_shell`: puoi eseguire comandi. È il modo giusto per VERIFICARE il tuo lavoro — lanciare i test, un build, uno script. Un agente che scrive codice e non lo esegue sta indovinando.
- Su Windows il separatore è ` && `, non `;`. Con cmd.exe il `;` non è un separatore: esegue solo il primo comando e restituisce successo, e il secondo sparisce senza errore.
- La shell è soggetta allo stesso confine degli altri strumenti: un comando che tocca un percorso fuori dalla cartella di lavoro chiede il permesso all'utente, e i percorsi sensibili sono negati.
- Usa path relativi dentro il progetto: è più semplice e non fa scattare la domanda di permesso.

---
Cose che valgono in ogni conversazione. Non ripeterle se non servono. Per tutto il resto hai il tool `memoria`: cerca quello che ti serve invece di assumere di non saperlo.

- Lavora su Windows
"""

# ---------------------------------------------------------------------------
# Profili
# ---------------------------------------------------------------------------

# I profili, e la ragione per cui `run_shell` e' in TUTTI.
#
# Prima era solo in `pieno`, e la conseguenza era che Orchestra non
# poteva eseguire il codice che scriveva: poteva correggere un file e
# non poteva girare il test che diceva se la correzione era giusta.
# Un agente che non puo' verificare il proprio lavoro e' un agente che
# indovina — e il ciclo "scrivi, gira, correggi" e' metà del valore di
# un agente tecnico.
#
# Il confine non e' il profilo: e' il GUATE. `run_shell` chiede il
# permesso all'utente quando il comando tocca un percorso fuori dalla
# cartella di lavoro, con le stesse quattro scelte degli altri tool, e
# i percorsi sensibili (C:/Windows, .ssh, .env) sono negati senza
# domanda. Il vincolo e' sul TOOL, non sul PROFILO: se l'utente
# autorizza la lettura di una cartella, vale anche quando l'agente ci
# arriva con la shell, altrimenti basta chiedere la permesso giusta e
# usare quella sbagliata.
#
# Perche' allora il profilo esiste ancora? Perche' i profili alti
# AGGIUNGONO (skill, browser, computer), non tolgono: un profilo e' un
# livello di capacita', non un livello di fiducia.
_PROFILI: dict[str, set[str]] = {
    "base": {
        "read_file", "write_file", "edit_file", "list_dir", "calculate",
        "memoria", "web_cerca", "web_leggi", "storico_cerca", "run_shell",
    },
    "ricerca": {
        "read_file", "write_file", "edit_file", "list_dir", "calculate",
        "memoria", "web_cerca", "web_leggi", "storico_cerca", "run_shell",
        "skill_cerca", "skill_leggi",
    },
    "skill": {
        "read_file", "write_file", "edit_file", "list_dir",
        "memoria", "web_cerca", "web_leggi", "storico_cerca", "run_shell",
        "skill_cerca", "skill_leggi", "skill_genera", "skill_importa",
    },
    "pieno": {
        "read_file", "write_file", "edit_file", "list_dir", "run_shell", "calculate",
        "memoria", "web_cerca", "web_leggi", "storico_cerca",
        "skill_cerca", "skill_leggi", "skill_genera", "skill_importa",
        "browser_apri", "browser_render", "browser_screenshot",
        "computer_screenshot", "computer_click", "computer_open", "computer_type",
    },
}


def applica_profilo(registry: ToolRegistry, profilo: str) -> None:
    """Attiva i tool del profilo specificato sul registro.

    Prima attivava e basta: un tool attivo restava attivo anche se il
    profilo successivo non lo includeva. Passando da `pieno` a `base`,
    browser e computer restavano in mano all'agente — e il profilo che
    l'utente aveva scelto non era quello che valeva.

    Ora il profilo e' LO STATO, non un'aggiunta: si disattiva tutto
    quello che non c'e' nel profilo e si attiva quello che c'e'. Il
    registro e' rifatto a ogni turno (`_esegui_turno` in `session.py`),
    quindi il profilo torna quello scelto.

    Un profilo che NON ESISTE non tocca niente. E' la differenza fra
    "l'utente ha scelto un profilo che non c'e'" (un errore da
    segnalare, e il registro resta com'era) e "l'utente ha scelto
    nessun profilo" (tutti i tool disattivati, l'agente che non puo'
    fare niente). La seconda e' un vicolo cieco: il modello chiama un
    tool, riceve "tool inesistente" e non capisce perche'.

    `run_shell` e' in tutti i profili, quindi nessun profilo lo
    toglie: la shell si puo' spegnere solo togliendola dal
    registro, e li' la decisione e' esplicita.
    """
    nomi = _PROFILI.get(profilo)
    if nomi is None:
        # profilo sconosciuto: non si tocca il registro. Scegliere
        # "nessuno" e' un'altra cosa, e si dice altrove.
        return
    for tool in registry.elenco_attivi():
        if tool.name not in nomi:
            registry.disattiva(tool.name)
    for nome in nomi:
        registry.attiva(nome)


def profilo_per_testo(testo: str) -> str:
    """Sceglie il profilo in base al testo dell'utente."""
    t = testo.lower()
    if any(k in t for k in ("skill", "procedura", "genera", "importa")):
        return "skill"
    if any(k in t for k in ("cerca", "web", "storico", "passato")):
        return "ricerca"
    return "base"


# ---------------------------------------------------------------------------
# default_registry
# ---------------------------------------------------------------------------

def default_registry() -> ToolRegistry:
    """Restituisce il registro con tutti i tool registrati, e ATTIVI.

    Nessun profilo viene applicato: un profilo e' una scelta, e chi la
    fa' la dichiara. "base" applicato qui disattivava i tool skill, i
    browser e i computer, e restava in vigore per sempre anche quando il
    chiamante ne chiedeva un altro (o nessuno). Vedere il commento poco
    sotto, che spiega perche' la riga c'era e perche' non c'e' piu'.
    """
    registry = ToolRegistry()

    # Ogni tool viene registrato E attivato.
    #
    # `registra` da sola basta a metterlo nel registro, ma non lo attiva:
    # l'attivazione e' un atto separato, e prima la faceva "base" (il
    # profilo applicato qui sotto). Se togli il profilo e lasci la sola
    # registrazione, il registro ha tutti i tool e nessuno attivo — che
    # e' peggio del difetto che stai correggendo: il modello non trova
    # niente, e il sintomo e' lo stesso.
    #
    # Attivare qui NON significa "per sempre": un profilo scelto a mano
    # (applica_profilo) continua a poter disattivare quello che non
    # contiene, e session.py riapplica il profilo scelto a ogni turno.
    # "Attivo qui" vuol dire "attivo finche' nessuno dice il contrario".
    for tool in (tool_read_file(), tool_write_file(), tool_edit_file(),
                 tool_list_dir(), tool_run_shell(), tool_calculate(),
                 tool_memoria(), tool_web_cerca(), tool_web_leggi(),
                 tool_storico_cerca(), tool_cron(),
                 tool_skill_cerca(), tool_skill_leggi(),
                 tool_skill_genera(), tool_skill_importa(),
                 tool_browser_apri(), tool_browser_render(),
                 tool_browser_screenshot(),
                 tool_computer_screenshot(), tool_computer_click(),
                 tool_computer_open(), tool_computer_type()):
        registry.registra(tool)
        registry.attiva(tool.name)

    # NESSUN profilo applicato qui. Prima si applicava "base", e
    # aveva due difetti:
    #
    # 1. "base" DISATTIVA i tool che non contiene (i 4 tool skill, i
    #    browser, i computer). Applica_profilo non e' un'aggiunta: e' lo
    #    STATO del registro. Quindi i tool skill finivano registrati ma
    #    disattivati, e il prompt di sistema li prometteva lo stesso
    #    (agent.py chiama skills.Indice().prompt() a ogni turno: li
    #    elenca con le righe "skill_leggi <nome>" e "skill_cerca"). Il
    #    modello leggeva l'istruzione, la eseguiva, e riceveva "tool
    #    inesistente": un'istruzione che il sistema stesso ha scritto e
    #    che il sistema rende impossibile da seguire.
    #
    # 2. Il profilo "base" restava lì per sempre, anche quando il
    #    chiamante diceva il contrario. LoopConfig.tool_profile=None
    #    significa "registro intatto" (agent.py lo documenta) e
    #    webapp.py passa None per default: allora session.py non
    #    applica NESSUN profilo e si aspetta il registro intatto. Ma
    #    "base" era gia' stato applicato qui, una volta sola, al momento
    #    della costruzione. Il profilo che valeva era un altro da quello
    #    che il resto del codice credeva.
    #
    # Il registro completo e' quello che i tool registrati fanno: sono
    # attivi. Chi vuole un profilo, lo chiede esplicitamente con
    # applica_profilo() — e lo fa' nel posto giusto, che e' a ogni
    # turno (session.py) e non una volta sola alla costruzione.
    return registry


# ---------------------------------------------------------------------------
# Pulizia automatica all'avvio
# ---------------------------------------------------------------------------

def _pulizia_tools_obsoleti() -> None:
    """Rimuove il vecchio orchestra/tools.py se coesiste con la nuova cartella orchestra/tools/."""
    tools_py = _ROOT / "tools.py"
    tools_dir = _ROOT / "tools"
    if tools_py.exists() and tools_dir.is_dir():
        try:
            tools_py.unlink()
        except OSError:
            pass


_pulizia_tools_obsoleti()
