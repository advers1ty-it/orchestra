"""Gestione del contesto: conteggio token e compaction.

La compaction è il punto in cui la maggior parte degli harness è mediocre.
Il riassunto cieco perde informazione che il modello serviva: se scarti i
risultati dei tool, il modello ripete le chiamate; se scarti le richieste
dell'utente, perde il bersaglio.

La strategia qui è deliberatamente conservativa e a due fasi:

  1. `compact_tools` — i risultati dei tool più vecchi vengono potati
     (diventano un segnaposto) PRIMA di toccare la conversazione. Sono la
     maggior parte del volume e quasi sempre recuperabili.
  2. `compact_history` — solo se non basta, i turni più vecchi dell'utente
     vengono fusi in un riepilogo. Tiene sempre: system prompt, primo
     messaggio utente, e ultimi N messaggi.

Regola che non negoziamo: gli ultimi `keep_recent` messaggi non si toccano
mai. Il modello deve poter vedere dove si trova.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from .types import Message


# Stima media: ~4 caratteri per token sui testi in inglese/italiano.
# Solo per il budgeting: il conteggio esatto lo diamo al provider quando
# risponde, e aggiorniamo da lì. Serve per decidere PRIMA di chiamare.
CHARS_PER_TOKEN = 3.6

# Quanto contesto serve DAVVERO all'agente.
#
# Il 75% della finestra del modello e' il punto oltre il quale la
# RICHIESTA non passa piu' (400 dal provider). Non e' il punto oltre il
# quale il modello lavora bene, e confondere i due e' il motivo per cui
# la compattazione non si vedeva mai: con una finestra da 1M il 75% sono
# 786.432 token, e una chat intera non ci arriva.
#
# Misurato in uso: 317 messaggi, ~145.000 token, `context_limit`
# 786.432, `compactions: 0`. Il sintomo non era un errore: era il
# modello che, dopo qualche ora sulla stessa conversazione, rispondeva
# fuori bersaglio o chiudeva il turno senza usare un tool. Centinaia di
# messaggi sotto il naso fanno quello; la finestra non c'entra.
#
# 60k bastano per un turno di lavoro (otto messaggi recenti con i loro
# risultati tool) e sono abbastanza pochi perche' la compattazione
# scatti in una sessione vera. Si cambia con ORCHESTRA_CONTEXT_LIMIT.
TETTO_PRATICO = 60_000

# Sotto questa soglia compattare mangerebbe il turno stesso: i messaggi
# recenti, da soli, non ci starebbero piu'.
MINIMO_UTILE = 4_000

# L'etichetta del messaggio fuso. Serve a riconoscere un riepilogo
# quando si ricompatta: vedi `compact_history`.
RIEPILOGO_TAG = "[RIEPILOGO sessione]"


def limite_compattazione(finestra: int, *, tetto: int = 0) -> int:
    """Quanti token tenere prima di compattare.

    `finestra` e' la finestra dichiarata dal modello (0 = sconosciuta).
    `tetto` e' una scelta esplicita dell'utente: se c'e' vale lei, ma
    sempre dentro la finestra — chiedere piu' della finestra non da' piu'
    contesto, da' un 400.

    Regola: il minore fra il tetto (pratico o scelto) e il 75% della
    finestra. Con una finestra da 1M si compatta a 60k, non a 786k.
    """
    scelto = int(tetto) if tetto and tetto > 0 else TETTO_PRATICO
    limite = scelto
    if finestra and finestra > 0:
        limite = min(scelto, int(finestra * 0.75))
    # Il minimo non puo' superare la finestra: su un modello da 2k token
    # un limite di 4k non e' prudente, e' una richiesta che non passa.
    minimo = min(MINIMO_UTILE, int(finestra)) if finestra and finestra > 0 \
        else MINIMO_UTILE
    return max(int(limite), int(minimo))


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def message_tokens(msg: Message) -> int:
    """Stima del costo di un messaggio, immagini e ragionamento inclusi.

    Prima contava solo `content`. Le immagini e il `reasoning` viaggiano
    al provider lo stesso, ma non entravano nella stima: con uno
    screenshot (~1.100 token) o un modello che ragiona, il conteggio
    era molto sotto il reale, la compaction non scattava, e la richiesta
    tornava 400 per contesto pieno. Un conteggio che ignora cio' che
    spedisci non e' una stima prudente, e' una stima sbagliata.
    """
    total = estimate_tokens(msg.content)
    total += 4  # overhead di ruolo e delimitatori
    for tc in msg.tool_calls:
        total += estimate_tokens(tc.name) + estimate_tokens(tc.arguments) + 4
    # Le immagini non si tokenizzano come testo: si paga la risoluzione,
    # non i byte. ~1.100 e' il valore misurato per uno screenshot 1280x800
    # su un modello con vision: abbastanza alto da far scattare la
    # compaction un giro prima, che e' il lato giusto su cui sbagliare.
    for _ in (getattr(msg, "images", None) or []):
        total += 1100
    ragionamento = getattr(msg, "reasoning", "") or ""
    if ragionamento:
        total += estimate_tokens(ragionamento)
    return total


def count_tokens(messages: list[Message]) -> int:
    return sum(message_tokens(m) for m in messages)


class Summarizer(Protocol):
    """Strategia di riassunto. Iniettabile perche' la qualita' del
    riassunto dipende dal modello usato — con un modello piccolo si perde
    piu' informazione, e va misurato."""

    def __call__(self, text: str, *, keep_hint: str) -> str: ...


# --------------------------------------------------------------------------
# Fase 1: potatura dei risultati tool
# --------------------------------------------------------------------------


def compact_tools(
    messages: list[Message],
    *,
    keep_recent: int = 8,
    placeholder: str = "[potato: risultato tool fuori dalla finestra di contesto]",
) -> int:
    """Sostituisce i risultati tool vecchi con un segnaposto.

    Restituisce quanti messaggi sono stati potati. Non tocca mai gli ultimi
    `keep_recent`, perche' il modello deve vedere il risultato della sua
    ultima azione.
    """
    cutoff = len(messages) - keep_recent
    if cutoff <= 0:
        return 0

    pruned = 0
    for msg in messages[:cutoff]:
        if msg.role == "tool" and msg.content and msg.content != placeholder:
            # conserviamo un frammento: spesso l'inizio del risultato
            # (es. le prime righe di un file) basta a orientare il modello
            head = msg.content[:200].strip()
            msg.content = f"{placeholder}\n{head}" if head else placeholder
            # L'immagine si toglie sempre: e' la parte che costa (un
            # screenshot sono ~1100 token) e l'unica che il segnaposto
            # non sostituisce. Lasciarla accanto a "[potato: ...]"
            # manderebbe al modello uno schermo che il testo dice di
            # non avere — e il modello ci ragionerebbe sopra, non sopra
            # quello che vede.
            if getattr(msg, "images", None):
                msg.images = []
            pruned += 1
    return pruned


# --------------------------------------------------------------------------
# Fase 2: fusione dei turni utente più vecchi
# --------------------------------------------------------------------------


def compact_history(
    messages: list[Message],
    *,
    keep_recent: int = 8,
    summarize: Summarizer | None = None,
) -> int:
    """Fonde in un riepilogo i messaggi utente/assistant più vecchi.

    Invarianti:
      - il system prompt resta in testa, intatto
      - il PRIMO messaggio utente resta (il bersaglio originale)
      - gli ultimi `keep_recent` messaggi restano intatti
    """
    system = [m for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]

    if len(rest) <= keep_recent + 1:
        return 0

    # primo messaggio utente = obiettivo della sessione, lo preserviamo
    first_user_idx = next(
        (i for i, m in enumerate(rest) if m.role == "user"), None
    )
    protected: set[int] = set()
    if first_user_idx is not None:
        primo = rest[first_user_idx]
        # ...ma un riepilogo di una compattazione precedente non e' un
        # obiettivo: e' il risultato del lavoro gia' fatto. Proteggendolo,
        # ogni compattazione ne aggiungeva uno nuovo davanti a quello
        # vecchio, e dopo dieci giri il contesto era fatto di dieci
        # riassunti sovrapposti — tutti "protetti", nessuno dei quali
        # diceva dove si era arrivati. Si lascia fondere in quello nuovo,
        # che lo riceve dentro la trascrizione.
        if not (primo.content or "").startswith(RIEPILOGO_TAG):
            protected.add(first_user_idx)

    cutoff = len(rest) - keep_recent
    to_merge = [
        i
        for i in range(cutoff)
        if i not in protected and rest[i].role in ("user", "assistant")
    ]
    if not to_merge:
        return 0

    def render(i: int) -> str:
        m = rest[i]
        who = "Utente" if m.role == "user" else "Assistente"
        body = m.content.strip()
        if m.tool_calls:
            names = ", ".join(sorted({tc.name for tc in m.tool_calls}))
            body = f"{body}\n[chiamate tool: {names}]".strip()
        return f"{who}: {body}"

    transcript = "\n".join(render(i) for i in to_merge)
    hint = "obiettivo della sessione e richieste già soddisfatte"

    if summarize is not None:
        summary = summarize(transcript, keep_hint=hint)
    else:
        # fallback: nessun modello disponibile. Comprimiamo in modo rozzo ma
        # non distruttivo, accorciando invece di cancellare.
        summary = _naive_summarize(transcript)

    merged = Message(role="user", content=f"{RIEPILOGO_TAG}\n{summary}")

    kept_indices = sorted(protected | set(range(cutoff, len(rest))))
    rebuilt = [merged] + [rest[i] for i in kept_indices]
    rebuilt = _senza_tool_orfani(rebuilt)
    messages[:] = system + rebuilt
    return len(to_merge)


def _senza_tool_orfani(messaggi: list[Message]) -> list[Message]:
    """Toglie i tool result che non seguono un tool_call.

    La compaction fonde gli assistant prima del taglio e butta i tool
    result che li seguono: se un tool result sopravvive al taglio ma il
    suo assistant e' finito nel riepilogo, resta un tool result orfano.
    I gateway permissivi lo ingoiano, ma quelli stretti rifiutano la
    richiesta intera con 400 ("is a tool result, but it does not follow
    an assistant message with 'tool_calls'") e il turno si interrompe.

    Si tiene un tool result solo se il suo id e' stato chiamato da un
    assistant visto poco prima. Il resto si butta: l'assistant e' gia'
    nel riepilogo, che ne conserva le chiamate.
    """
    attesi: set[str] = set()
    tenuti: list[Message] = []
    for m in messaggi:
        if m.role == "assistant":
            attesi |= {tc.id for tc in m.tool_calls}
            tenuti.append(m)
        elif m.role == "tool":
            if m.tool_call_id in attesi:
                attesi.discard(m.tool_call_id)
                tenuti.append(m)
            # altrimenti: orfano, si butta
        else:
            tenuti.append(m)
    return tenuti


def summarizer_llm(provider: Any, *, max_tokens: int = 700) -> Summarizer:
    """Un `Summarizer` che usa un modello vero, con ripiego onesto.

    Il riassunto a testa/coda esisteva perche' nessuno passava un
    `summarize` alla `Session`: il codice del riassunto con modello c'era
    ed era morto. In una conversazione lunga il troncamento butta via
    proprio il centro (le decisioni, gli errori gia' risolti), e il
    modello ricomincia a chiedere cose gia' fatte.

    Il prompt e' piccolo e vincolato: si chiede di conservare cio' che
    serve a CONTINUARE, non di raccontare. Se il modello non risponde (o
    risponde vuoto) si torna al troncamento: un riassunto peggiore e'
    meglio di un turno che muore perche' il riassunto e' fallito.
    """

    def _riassumi(testo: str, *, keep_hint: str = "") -> str:
        if not testo.strip():
            return ""
        sistema = (
            "Riassumi la conversazione tecnica che ricevi. Conserva: "
            "l'obiettivo dell'utente, le decisioni prese, i file e i "
            "comandi che contano, gli errori gia' risolti e quelli "
            "ancora aperti, i vincoli e le preferenze dette. Togli i "
            "pettegolezzi, i tentativi falliti che non hanno insegnato "
            "niente, e le ripetizioni. Scrivi in italiano, massimo 15 "
            "righe, in forma di elenco. Non inventare nulla che non sia "
            "nel testo."
        )
        if keep_hint:
            sistema += f" Cosa non perdere: {keep_hint}."
        try:
            resp = provider.chat(
                [Message(role="system", content=sistema),
                 Message(role="user", content=testo)],
                temperature=0.2,
                max_tokens=max_tokens,
            )
            fuori = (getattr(resp, "content", "") or "").strip()
        except Exception:  # noqa: BLE001 - un riassunto non deve uccidere il turno
            fuori = ""
        return fuori or _naive_summarize(testo)

    return _riassumi


def _naive_summarize(transcript: str, limit: int = 1200) -> str:
    """Fallback senza modello: tiene testa e coda.

    Sappiamo che perde il mezzo. E' preferibile a cancellare, e sappiamo
    che va misurato: se il fallback entra spesso in gioco, il riassunto con
    modello non e' piu' opzionale.
    """
    if len(transcript) <= limit:
        return transcript
    head = transcript[: limit // 2]
    tail = transcript[-limit // 2 :]
    return f"{head}\n\n[... {len(transcript) - limit} caratteri omessi ...]\n\n{tail}"


# --------------------------------------------------------------------------
# Orchestrazione delle fasi
# --------------------------------------------------------------------------


def fit_context(
    messages: list[Message],
    *,
    limit: int,
    keep_recent: int = 8,
    summarize: Summarizer | None = None,
) -> dict[str, int]:
    """Porta il contesto sotto `limit` eseguendo le fasi in ordine di costo.

    Restituisce un report di cosa è stato fatto — ci serve per misurare,
    non per indovinare: se `tools_pruned` e' sempre 0 la finestra e' semplicemente
    larga; se `history_merged` scatta a ogni turno il riassunto sta lavorando
    troppo e forse il problema e' a monte.
    """
    report = {"tokens_before": 0, "tokens_after": 0, "tools_pruned": 0, "history_merged": 0}
    report["tokens_before"] = count_tokens(messages)

    # le fasi sono additive: la seconda deve poter salvare quello che la
    # prima non ha toccato
    if count_tokens(messages) > limit:
        report["tools_pruned"] = compact_tools(
            messages, keep_recent=keep_recent
        )
    if count_tokens(messages) > limit:
        report["history_merged"] = compact_history(
            messages, keep_recent=keep_recent, summarize=summarize
        )

    report["tokens_after"] = count_tokens(messages)
    return report
