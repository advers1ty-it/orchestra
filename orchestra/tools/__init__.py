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

---
Cose che valgono in ogni conversazione. Non ripeterle se non servono. Per tutto il resto hai il tool `memoria`: cerca quello che ti serve invece di assumere di non saperlo.

- Lavora su Windows
"""

# ---------------------------------------------------------------------------
# Profili
# ---------------------------------------------------------------------------

_PROFILI: dict[str, set[str]] = {
    "base": {
        "read_file", "write_file", "edit_file", "list_dir", "calculate",
        "memoria", "web_cerca", "web_leggi", "storico_cerca",
    },
    "ricerca": {
        "read_file", "write_file", "edit_file", "list_dir", "calculate",
        "memoria", "web_cerca", "web_leggi", "storico_cerca",
        "skill_cerca", "skill_leggi",
    },
    "skill": {
        "read_file", "write_file", "edit_file", "list_dir",
        "memoria", "web_cerca", "web_leggi", "storico_cerca",
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
    """Attiva i tool del profilo specificato sul registro."""
    nomi = _PROFILI.get(profilo, set())
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
    """Restituisce il registro con tutti i tool registrati e il profilo base attivo."""
    registry = ToolRegistry()

    # Tool base
    registry.registra(tool_read_file())
    registry.registra(tool_write_file())
    registry.registra(tool_edit_file())
    registry.registra(tool_list_dir())
    registry.registra(tool_run_shell())
    registry.registra(tool_calculate())

    # Tool estesi
    registry.registra(tool_memoria())
    registry.registra(tool_web_cerca())
    registry.registra(tool_web_leggi())
    registry.registra(tool_storico_cerca())
    registry.registra(tool_skill_cerca())
    registry.registra(tool_skill_leggi())
    registry.registra(tool_skill_genera())
    registry.registra(tool_skill_importa())
    registry.registra(tool_browser_apri())
    registry.registra(tool_browser_render())
    registry.registra(tool_browser_screenshot())
    registry.registra(tool_computer_screenshot())
    registry.registra(tool_computer_click())
    registry.registra(tool_computer_open())
    registry.registra(tool_computer_type())

    # Profilo base attivo di default
    applica_profilo(registry, "base")

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
