"""Tipi fondamentali dell'orchestratore.

Nessuna dipendenza esterna: solo dataclass e typing della stdlib.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Callable, Awaitable


# --------------------------------------------------------------------------
# Ruoli dei messaggi
# --------------------------------------------------------------------------

Role = Literal["system", "user", "assistant", "tool"]


def _args_validi(arguments: str) -> str:
    """Gli argomenti di un tool call, gia' come stringa JSON valida.

    Un provider OpenAI-compatibile rifiuta l'intera richiesta se un
    `tool_calls[].function.arguments` non e' un oggetto JSON valido: il
    sintomo e' un 400 al giro successivo, con l'errore che parla di
    "must be a valid JSON object string". Un modello che taglia a meta'
    una chiamata lascia una stringa rotta, e se la rispedissimo com'e'
    la conversazione non ripartirebbe mai piu'. Qui si mette `{}` al
    posto della stringa rotta: la chiamata fallisce in modo pulito, il
    tool riceve un errore e il modello puo' riprovare.
    """
    if not arguments:
        return "{}"
    try:
        data = json.loads(arguments)
    except json.JSONDecodeError:
        return "{}"
    return arguments if isinstance(data, dict) else "{}"


@dataclass
class ToolCall:
    """Una richiesta di esecuzione tool emessa dal modello."""

    id: str
    name: str
    arguments: str  # stringa JSON grezza, come la restituisce il provider

    def args_non_validi(self) -> bool:
        """True se gli argomenti non sono un oggetto JSON valido.

        Un modello a volte taglia a meta' o produce un JSON rotto. Se
        questi argomenti venissero passati al tool, il tool riceverebbe
        una chiave inesistente e risponderebbe con un TypeError inutile;
        e se venissero rispediti al provider, esso risponderebbe 400.
        """
        if not self.arguments:
            return False
        try:
            return not isinstance(json.loads(self.arguments), dict)
        except json.JSONDecodeError:
            return True

    def parsed_args(self) -> dict[str, Any]:
        """Tollerante: se il provider ha restituito JSON malformato non crashiamo.

        Ritorna un dizionario VUOTO in quel caso, mai una chiave inventata:
        una chiave `_raw` finirebbe come keyword argument del tool e il
        tool risponderebbe `unexpected keyword argument '_raw'`, che non
        dice nulla al modello. La segnalazione degli argomenti rotti sta
        in `args_non_validi` e viene fatta prima di eseguire.
        """
        if not self.arguments:
            return {}
        try:
            data = json.loads(self.arguments)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}


@dataclass
class Message:
    """Un singolo messaggio nella conversazione.

    Allegati: un messaggio puo' portare immagini. `images` e' una lista
    di data URL gia' encodate, non percorsi — il percorso esiste solo
    sul disco di chi ha caricato il file, e chi chiama l'API non ce
    l'ha. Per lo stesso motivo non si tiene traccia del nome originale:
    finisce nella cronologia del browser e occupa spazio per sempre.
    """

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # solo per role="tool"
    name: str | None = None  # nome del tool, per role="tool"
    # data: URL delle immagini allegate (foto, pagine di PDF)
    images: list[str] = field(default_factory=list)
    # metadati di conteggio per la compaction
    tokens: int = 0
    created_at: float = field(default_factory=time.time)
    # Il ragionamento del modello, se arriva. I modelli che ragionano
    # SEMPRE (Beam 1.0 in testa) lo richiedono indietro ai turni
    # successivi: senza `reasoning_content` rispondono 400
    # missing_required_parameter e i tool call si fermano al secondo
    # giro. Si conserva qui per poterlo rimandare.
    reasoning: str = ""

    def to_api(self) -> dict[str, Any]:
        """Converte nel formato OpenAI chat-completions.

        Con immagini, `content` non e' piu' una stringa: e' una lista di
        parti, e l'ordine conta. Il testo va PRIMA delle immagini, e non
        per abitudine: e' l'istruzione, e se viene dopo un modello puo'
        leggerla come descrizione di quello che ha appena visto invece
        che come richiesta.

        Senza immagini resta una stringa: alcuni gateway rifiutano la
        forma a lista, e non costa nulla mandare la forma semplice
        quando la semplice basta.
        """
        if not self.images:
            msg: dict[str, Any] = {"role": self.role, "content": self.content}
        else:
            parti: list[dict[str, Any]] = []
            if self.content:
                parti.append({"type": "text", "text": self.content})
            for url in self.images:
                parti.append({"type": "image_url", "image_url": {"url": url}})
            msg = {"role": self.role, "content": parti}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name,
                                 "arguments": _args_validi(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        # Il ragionamento va rimandato SOLO nei messaggi assistant e solo
        # se non e' vuoto. Beam 1.0 lo richiede ai turni successivi; i
        # gateway che non lo conoscono si aspettano il campo assente, e
        # un `reasoning_content: ""` li manda in 400.
        if self.reasoning and self.role == "assistant":
            msg["reasoning_content"] = self.reasoning
        return msg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Message":
        tcs = [ToolCall(**tc) for tc in d.get("tool_calls") or []]
        return cls(
            role=d["role"],
            content=d.get("content", "") or "",
            tool_calls=tcs,
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
            tokens=d.get("tokens", 0),
            created_at=d.get("created_at", time.time()),
            reasoning=d.get("reasoning", "") or "",
        )


# --------------------------------------------------------------------------
# Tool
# --------------------------------------------------------------------------

ToolHandler = (
    Callable[..., "str | ToolResult"]
    | Callable[..., Awaitable["str | ToolResult"]]
)


@dataclass
class ToolResult:
    """Il risultato di un tool che porta anche un'immagine.

    La maggior parte dei tool restituisce una stringa e basta. Alcuni —
    un tool che legge uno screenshot, per esempio — devono dare al
    modello QUALCOSA DA VEDERE, non una descrizione: il testo da solo
    non basta, e il modello non ha modo di sapere com'e' lo schermo.

    `immagini` sono data URL (`data:image/png;base64,...`), lo stesso
    formato che gli allegati della chat usano: il provider li accetta
    cosi', e non c'e' motivo di averne due formati.
    """

    text: str
    immagini: list[str] = field(default_factory=list)


@dataclass
class Tool:
    """Un tool eseguibile, con schema dichiarato per il provider.

    `schema` è un JSON Schema passato invariato al provider: stiamo
    assumendo conformità OpenAI function-calling, che è lo standard de facto.
    """

    name: str
    description: str
    schema: dict[str, Any]
    handler: ToolHandler
    # il tool system-prompt è l'unico posto dove la policy dei prompt
    # policy tool prompt ("usa le skill, non improvvisare") viene codificata
    is_async: bool = False

    def to_api(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


class ToolRegistry:
    """Registro dei tool disponibili.

    Nota di progetto: non passiamo MAI l'intero catalogo al provider.
    Vediamo `active` e `activate` — il carico selettivo dei tool è uno dei
    problemi che questo orchestratore deve risolvere bene.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._active: set[str] = set()

    def register(self, tool: Tool, *, active: bool = True) -> "ToolRegistry":
        if tool.name in self._tools:
            raise ValueError(f"tool già registrato: {tool.name}")
        self._tools[tool.name] = tool
        if active:
            self._active.add(tool.name)
        return self

    def activate(self, *names: str) -> None:
        for n in names:
            if n not in self._tools:
                raise KeyError(f"tool sconosciuto: {n}")
            self._active.add(n)

    def deactivate(self, *names: str) -> None:
        self._active.difference_update(names)

    @property
    def active(self) -> list[Tool]:
        return [self._tools[n] for n in sorted(self._active) if n in self._tools]

    def all_names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def api_payload(self) -> list[dict[str, Any]]:
        return [t.to_api() for t in self.active]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# --------------------------------------------------------------------------
# Risposta provider
# --------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """Risposta grezza dal provider, normalizzata sul nostro formato."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    # Il ragionamento, se il modello lo manda. OpenRouter lo mette in
    # `delta.reasoning` durante lo streaming e in `message.reasoning` alla
    # fine: 328 chunk e 2044 caratteri su una domanda di fisica, TUTTI
    # prima del primo carattere di contenuto.
    #
    # Questo campo è il vuoto che l'utente vedeva: 18 secondi di niente,
    # mentre il modello stava lavorando e non lo potevamo dire.
    reasoning: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


def new_id(prefix: str = "call") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"
