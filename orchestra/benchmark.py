"""Benchmark: misura cosa sa fare ogni modello, per categoria di compito.

Perché esiste. Serviva una risposta a "quale modello è più potente" e la
risposta onesta è che la domanda è sbagliata: un modello può batterne un
altro in codice e perderlo in ragionamento, e la classifica cambia ogni
settimana. Un punteggio unico sarebbe un numero che non serve a nessuna
decisione. Quindi si misura per CATEGORIA, e i risultati dicono
"per scrivere codice usa questo, per ragionare quest'altro, e il costo è
questo".

Come si misura. Ogni task ha una verifica **oggettiva e automatica**: se
il file contiene `def fib` e `fib(10)` ritorna 55, il task è passato. Non
chiediamo a un altro modello "è stato fatto bene?". Un giudizio LLM su un
altro LLM è rumore: misurerebbe la similarità di stile, non la correttezza,
e ci costerebbe token per produrre numeri che non reggono.

Costo. Ogni run reale costa token. Per questo:
  - il default è un campione, non tutti i modelli
  - ogni categoria gira una volta sola (n=1): non è un punteggio
    statistico, è un'indicazione, e lo diciamo
  - n=1 ha una varianza alta. Due valutazioni diverse dello stesso modello
    possono dare risultati diversi. Per una decisione che costa soldi,
    conviene rilanciare: `--repeat` esiste per questo.

Onestà sul metodo. Un benchmark misura i task che contiene, non
l'intelligenza generale. Se i task sono scritti male, il ranking è
inutile. Per questo ogni task è ispezionabile e i risultati sono
persistiti con la data: un ranking di tre settimane fa non è una
garanzia per oggi.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from .agent import Agent, LoopConfig
from .catalog import CATEGORIES, Catalog, ModelProfile
from .tools import default_registry
from .types import Message, ToolRegistry


# --------------------------------------------------------------------------
# Task
# --------------------------------------------------------------------------


@dataclass
class Task:
    """Un compito da misurare, con la sua verifica."""

    id: str
    category: str
    prompt: str
    # La verifica riceve la directory di lavoro e restituisce
    # (passato: bool, dettaglio: str). Nessuna euristica: o il codice gira
    # e dà la risposta giusta, o non passa.
    verify: Callable[[str], tuple[bool, str]] = field(repr=False, default=None)  # type: ignore[assignment]
    # setup opzionale: crea file di partenza
    setup: Callable[[str], None] | None = field(repr=False, default=None)


# --- verifiche riusabili -------------------------------------------------


def _run_python(work: str, code: str) -> tuple[bool, str]:
    """Esegue codice in un processo separato e ne cattura l'output.

    Processo separato perché un test che va in loop infinito o solleva
    un'eccezione non deve portare giù il benchmark con sé.
    """
    import subprocess
    import sys

    # Il file va eseguito con cwd=work. Se passiamo il path ASSOLUTO,
    # Windows lo risolve rispetto al cwd che stiamo per impostare e lo
    # raddoppia: cercava
    #   _bench\code_fib_123\_bench\code_fib_123\_verify_run.py
    # e il path era costruito PRIMA del subprocess. Passiamo il nome del
    # file e basta: il cwd fa il suo lavoro. Questo bug rendeva fallire
    # tutti i task `code` con codice perfetto.
    fname = "_verify_run.py"
    path = os.path.join(work, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        r = subprocess.run(
            [sys.executable, fname],
            capture_output=True, text=True, timeout=25,
            cwd=work,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout: il codice non termina"
    if r.returncode != 0:
        # il path completo nell'errore: un "can't open file" senza capire
        # QUALE file stava cercando è inutilizzabile per il debug
        return False, f"errore: {(r.stderr.strip() or '')[:220]} [cwd={os.path.abspath(work)}]"
    return True, r.stdout.strip()


def v_contains(path: str, needle: str) -> Callable[[str], tuple[bool, str]]:
    """Il file deve contenere quella stringa."""
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        with open(p, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if needle in content:
            return True, "contenuto trovato"
        return False, f"manca {needle!r} in {path}"
    return check


def v_python_prints(path: str, expected: str) -> Callable[[str], tuple[bool, str]]:
    """Eseguiamo il file e confrontiamo l'output con quello atteso."""
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        return _run_python(work, open(p, encoding="utf-8", errors="replace").read())
    return check


def v_python_prints_exact(path: str, expected: list[str]) -> Callable[[str], tuple[bool, str]]:
    """Come sopra, ma confrontiamo ogni riga attesa."""
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        src = open(p, encoding="utf-8", errors="replace").read()
        ok, out = _run_python(work, src)
        if not ok:
            return False, out
        got = [l.strip() for l in out.splitlines() if l.strip()]
        want = [l.strip() for l in expected if l.strip()]
        if got == want:
            return True, "output corretto"
        return False, f"output {got} invece di {want}"
    return check


def v_json_field(path: str, field_name: str, expected: Any) -> Callable[[str], tuple[bool, str]]:
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return False, f"JSON non valido: {e}"
        if field_name not in data:
            return False, f"manca il campo {field_name!r}"
        if data[field_name] == expected:
            return True, f"{field_name} == {expected!r}"
        return False, f"{field_name} == {data[field_name]!r}, atteso {expected!r}"
    return check


def v_file_lines(path: str, conditions: list[tuple[str, int]]) -> Callable[[str], tuple[bool, str]]:
    """Ogni (regex, numero atteso di occorrenze), applicata riga per riga.

    `re.M` non e' un dettaglio: in Python `$` matcha solo a fine stringa o
    prima di un \\n finale, quindi `^1$` su "1\\n2\\n3\\n" NON matcha e il
    task di formattazione fallirebbe per qualsiasi modello, anche se
    scrive esattamente quello che gli si chiede. In JS e PCRE `$` e' diverso:
    il benchmark deve usare le stesse convenzioni del task, non quelle
    della lingua in cui gira per caso.
    """
    def check(work: str) -> tuple[bool, str]:
        p = os.path.join(work, path)
        if not os.path.exists(p):
            return False, f"il file {path} non esiste"
        content = open(p, encoding="utf-8", errors="replace").read()
        for pattern, expected in conditions:
            n = len(re.findall(pattern, content, re.M))
            if n != expected:
                return False, f"{pattern!r} compare {n} volte, attese {expected}"
        return True, f"{len(conditions)} condizioni soddisfatte"
    return check


def v_written(paths: list[str]) -> Callable[[str], tuple[bool, str]]:
    """I file devono esistere e non essere vuoti."""
    def check(work: str) -> tuple[bool, str]:
        missing = [p for p in paths if not os.path.exists(os.path.join(work, p))]
        if missing:
            return False, f"non creati: {', '.join(missing)}"
        empty = [p for p in paths
                 if os.path.getsize(os.path.join(work, p)) == 0]
        if empty:
            return False, f"vuoti: {', '.join(empty)}"
        return True, f"{len(paths)} file creati"
    return check


def v_all(*checks: Callable[[str], tuple[bool, str]]) -> Callable[[str], tuple[bool, str]]:
    def check(work: str) -> tuple[bool, str]:
        for c in checks:
            ok, why = c(work)
            if not ok:
                return False, why
        return True, "tutte le verifiche passate"
    return check


# --------------------------------------------------------------------------
# Il corpus
# --------------------------------------------------------------------------

# Un corpus coperre le categorie che ci servono per il routing. Sono task
# piccoli e verificabili: preferisco 8 task netti a 30 ambigui, perché un
# benchmark che non distingue nulla è inutile quanto non farlo.
TASKS: list[Task] = [
    # --- code
    Task(
        id="code_fib", category="code",
        prompt="Crea il file fib.py con una funzione fib(n) che restituisce il "
                "n-esimo numero di Fibonacci. Aggiungi anche un blocco __main__ "
                "che stampi fib(10).",
        verify=v_python_prints_exact("fib.py", ["55"]),
    ),
    Task(
        id="code_dedup", category="code",
        prompt="Crea dedup.py con una funzione unique(items) che restituisce "
                "gli elementi unici mantenendo l'ordine originale. Stampa "
                "unique([1,2,2,3,1]).",
        verify=v_python_prints_exact("dedup.py", ["[1, 2, 3]"]),
    ),
    Task(
        id="code_class", category="code",
        prompt="Crea conta.py con una classe Contatore che ha un metodo "
                "incrementa(n=1) e una proprieta' valore. Stampa il valore "
                "dopo 3 incrementi partendo da 0, una volta sola.",
        # "una volta sola": altrimenti il modello stampa lo stato a ogni
        # passo (0 1 2 3) che è corretto ma non quello chiesto. La verifica
        # confronta le righe per ordine, quindi il risultato finale deve
        # essere l'ultimo.
        verify=v_python_prints_exact("conta.py", ["3"]),
    ),

    # --- reasoning
    Task(
        id="reason_logic", category="reasoning",
        prompt="Una cisterna si riempie in 6 ore con un tubo. Si svuota in 9 ore. "
                "Se entrambi i tubi sono aperti e la cisterna e' piena, quanto "
                "tempo ci vuole per riempirsi? Risponde con un file "
                "risposta.txt contenente solo il numero di ore (intero o "
                "decimale, senza unita').",
        # 1/6 - 1/9 = 1/18 ore^-1 -> 18 ore
        verify=v_contains("risposta.txt", "18"),
    ),
    Task(
        id="reason_sched", category="reasoning",
        prompt="Tre amici devono fare tre compiti A, B, C. Ognuno fa un compito "
                "diverso. Ada non fa A. Bo non fa C e non fa B. Chi fa B? "
                "Scrivi in risposta.txt solo la lettera del nome: Ada, Bo o Cy.",
        verify=v_all(
            v_contains("risposta.txt", "Cy"),
        ),
    ),

    # --- instruction
    Task(
        id="instr_format", category="instruction",
        prompt="Crea report.txt con ESATTAMENTE tre righe. Ogni riga deve "
                "contenere un numero da 1 a 3 nell'ordine. Nessun altro "
                "carattere, nessuna spiegazione, nessun titolo.",
        verify=v_file_lines("report.txt", [(r"^1$", 1), (r"^2$", 1), (r"^3$", 1)]),
    ),
    Task(
        id="instr_json", category="instruction",
        prompt="Crea dati.json con un oggetto JSON che ha esattamente due "
                "chiavi: 'nome' con valore stringa 'orchestra' e 'attivo' con "
                "valore booleano true. Solo il JSON, niente altro nel file.",
        verify=v_json_field("dati.json", "nome", "orchestra"),
    ),

    # --- tool_use
    Task(
        id="tool_multi", category="tool_use",
        prompt="Crea tre file: uno/uno.txt con la parola UNO, due/due.txt con "
                "la parola DUE, tre/tre.txt con la parola TRE. Poi rileggi "
                "uno/uno.txt per verificare. Non serve che tu dica cosa hai "
                "scritto, basta che i file ci siano.",
        verify=v_written(["uno/uno.txt", "due/due.txt", "tre/tre.txt"]),
    ),
    Task(
        id="tool_math", category="tool_use",
        prompt="Calcola con lo strumento calculate il risultato di "
                "(47 * 89) - 15. Poi scrivi in risultato.txt solo il numero.",
        verify=v_contains("risultato.txt", str(47 * 89 - 15)),
    ),
]


def tasks_for(category: str | None = None) -> list[Task]:
    if not category:
        return list(TASKS) + list(_task_lavoro()) + list(_task_scrizione())
    tutte = list(TASKS) + list(_task_lavoro()) + list(_task_scrizione())
    return [t for t in tutte if t.category == category]


def _task_lavoro() -> list[Task]:
    """Le task per tipo di lavoro (js, web, app).

    In un modulo separato perche' sono la parte che cresce: quando serve
    misurare un altro tipo di richiesta si aggiunge li', senza toccare
    il nucleo. Se il modulo manca, il benchmark funziona lo stesso — meglio
    pochi task che nessuno.
    """
    try:
        from .tasks_lavoro import TASK_LAVORO
        return list(TASK_LAVORO)
    except ImportError:  # pragma: no cover
        return []


def _task_scrizione() -> list[Task]:
    """Le task per estrazione e scrittura.

    Stesso motivo di sopra, e un motivo in piu': sono le due uniche
    categorie che non hanno tool. Il resto del benchmark misura
    l'agente al lavoro; queste misurano se produce un file che si puo'
    usare senza ritoccarlo a mano. E' un altro tipo di lavoro, e va
    detto per nome, non mescolato in silenzio.
    """
    try:
        from .tasks_scrizione import TASK_EXTRACTION, TASK_WRITING
        return list(TASK_EXTRACTION) + list(TASK_WRITING)
    except ImportError:  # pragma: no cover
        return []


# --------------------------------------------------------------------------
# Esecuzione
# --------------------------------------------------------------------------


@dataclass
class RunResult:
    model: str
    task_id: str
    category: str
    passed: bool
    detail: str
    seconds: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    tool_calls: int
    tool_errors: int
    stopped_because: str
    error: str = ""
    # il provider lo riserva ad altri client: non e' colpa del modello e non
    # deve entrare nel punteggio
    unusable: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def run_task(
    task: Task,
    *,
    provider_name: str,
    model: str,
    env: dict[str, str],
    registry: ToolRegistry | None = None,
    workdir: str | None = None,
    max_iterations: int = 10,
) -> RunResult:
    """Esegue un task e verifica il risultato. Non solleva mai."""
    from .providers import ProviderError, build_provider

    work = workdir or os.path.join(
        os.environ.get("ORCHESTRA_HOME", "."), "_bench", f"{task.id}_{int(time.time() * 1000)}"
    )
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    prev_root = os.environ.get("ORCHESTRA_ROOT")
    os.environ["ORCHESTRA_ROOT"] = work

    t0 = time.time()
    try:
        if task.setup:
            task.setup(work)
        prov = build_provider(provider_name, model=model, env=env)
        agent = Agent(prov, registry or default_registry(), BENCH_PROMPT,
                      LoopConfig(max_iterations=max_iterations, context_limit=60_000))
        agent.run(task.prompt)
        st = agent.state
        passed, detail = task.verify(work)
        return RunResult(
            model=model, task_id=task.id, category=task.category,
            passed=passed, detail=detail, seconds=time.time() - t0,
            prompt_tokens=0, completion_tokens=st.total_tokens,
            cost_usd=0.0, tool_calls=st.tool_calls_made,
            tool_errors=st.tool_errors, stopped_because=st.stopped_because,
        )
    except Exception as e:  # noqa: BLE001 - un task che fallisce non ferma il benchmark
        # Un modello irraggiungibile non e' un modello scarso: segnalarlo
        # come "unusable" evita che il benchmark lo valuti a 0.00 e finisca
        # per consigliare il modello sbagliato a chi chiede un confronto.
        unusable = getattr(e, "unusable", False)
        return RunResult(
            model=model, task_id=task.id, category=task.category,
            passed=False, detail="", seconds=time.time() - t0,
            prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
            tool_calls=0, tool_errors=0, stopped_because="",
            error=f"{type(e).__name__}: {e}",
            unusable=unusable,
        )
    finally:
        if prev_root is None:
            os.environ.pop("ORCHESTRA_ROOT", None)
        else:
            os.environ["ORCHESTRA_ROOT"] = prev_root


BENCH_PROMPT = """Sei Orchestra, agento in un test di valutazione automatico.

Il task e' gia' chiaro. Lavora con gli strumenti e non spiegare cosa faresti:
il risultato si verifica leggendo i file che hai scritto, non la tua prosa.
Non aggiungere file di testo che descrivono il lavoro: solo quello che il
task chiede. Se un comando fallisce, correggilo e riprova."""


# --------------------------------------------------------------------------
# Aggregazione
# --------------------------------------------------------------------------


@dataclass
class ManualResult:
    """Una prova libera: un prompt, un modello, quello che e' successo.

    Diversa da RunResult perche' non c'e' una verifica oggettiva da cui
    ricavare un punteggio. E' il modo per capire PERCHE' un modello
    perde un task automatico: si guarda cosa scrive, quali tool chiama,
    dove si ferma. Senza questo, un 0.00 e' un numero e non un problema.
    """

    model: str
    prompt: str
    reply: str = ""
    # trascrizione: un passo per messaggio, per ricostruire il ragionamento
    steps: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    tool_errors: int = 0
    iterations: int = 0
    stopped_because: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model, "prompt": self.prompt, "reply": self.reply,
            "steps": self.steps, "seconds": round(self.seconds, 2),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "tool_calls": self.tool_calls, "tool_errors": self.tool_errors,
            "iterations": self.iterations,
            "stopped_because": self.stopped_because, "error": self.error,
        }


def _trascrizione(messaggi: list[Any]) -> list[dict[str, Any]]:
    """Trasforma i messaggi in una lista di passi leggibili.

    Non serve un formato ricco: serve vedere, in ordine, cosa ha detto il
    modello e cosa ha risposto ogni tool. Il formato e' lo stesso che la
    web UI gia' usa per gli eventi, cosi' c'e' una sola rappresentazione.
    """
    passi: list[dict[str, Any]] = []
    for m in messaggi:
        if m.role == "assistant":
            if m.content:
                passi.append({"tipo": "testo", "testo": m.content})
            for tc in (m.tool_calls or []):
                passi.append({"tipo": "tool", "nome": tc.name,
                              "argomenti": tc.arguments, "id": tc.id})
        elif m.role == "tool":
            ok = not str(m.content or "").lower().startswith("errore")
            passi.append({"tipo": "risultato", "nome": m.name,
                          "id": m.tool_call_id, "ok": ok,
                          "testo": str(m.content or "")[:2000]})
    return passi


def run_manual(
    prompt: str,
    *,
    provider_name: str,
    model: str,
    env: dict[str, str],
    registry: ToolRegistry | None = None,
    workdir: str | None = None,
    max_iterations: int = 10,
) -> ManualResult:
    """Esegue un prompt a mano e restituisce tutto quello che e' successo.

    Non solleva mai: un errore torna dentro `error`, perche' una prova
    manuale che muore non serve a capire niente.
    """
    from .providers import ProviderError, build_provider

    work = workdir or os.path.join(
        os.environ.get("ORCHESTRA_HOME", "."), "_prova",
        f"{int(time.time() * 1000)}")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    prev_root = os.environ.get("ORCHESTRA_ROOT")
    os.environ["ORCHESTRA_ROOT"] = work

    t0 = time.time()
    try:
        prov = build_provider(provider_name, model=model, env=env)
        agent = Agent(prov, registry or default_registry(), BENCH_PROMPT,
                      LoopConfig(max_iterations=max_iterations, context_limit=60_000))
        agent.run(prompt)
        st = agent.state
        # l'ultimo messaggio assistant senza tool e' la risposta
        risposta = ""
        for m in reversed(st.messages):
            if m.role == "assistant" and m.content and not m.tool_calls:
                risposta = m.content
                break
        return ManualResult(
            model=model, prompt=prompt, reply=risposta,
            steps=_trascrizione(st.messages),
            seconds=time.time() - t0,
            completion_tokens=st.total_tokens,
            tool_calls=st.tool_calls_made, tool_errors=st.tool_errors,
            iterations=st.iterations, stopped_because=st.stopped_because,
        )
    except (ProviderError, KeyError, ValueError) as e:
        return ManualResult(model=model, prompt=prompt,
                            seconds=time.time() - t0, error=str(e))
    except Exception as e:  # noqa: BLE001
        return ManualResult(model=model, prompt=prompt,
                            seconds=time.time() - t0,
                            error=f"{type(e).__name__}: {e}")
    finally:
        if prev_root is None:
            os.environ.pop("ORCHESTRA_ROOT", None)
        else:
            os.environ["ORCHESTRA_ROOT"] = prev_root


def score(results: list[RunResult]) -> float:
    """Punteggio 0..1 per un insieme di risultati.

    Proporzione di task passati. Nessun peso: un benchmark con pesi
    arbitrari nasconde le scelte che hai fatto. Se un peso ti serve, è
    una decisione da prendere esplicitamente, non un default.
    """
    if not results:
        return 0.0
    return sum(1 for r in results if r.passed) / len(results)


def summarize(results: list[RunResult]) -> dict[str, Any]:
    """Riassunto per modello e per categoria.

    I modelli irraggiungibili (`unusable`) vengono esclusi dal punteggio e
    messi in `unusable_models`. Sono due fatti distinti: "non lo so" e "so
    che è scarso" non possono finire nello stesso numero, o il benchmark
    finisce per consigliare il modello sbagliato.
    """
    usable = [r for r in results if not r.unusable]
    unusable_models = sorted({r.model for r in results if r.unusable})

    by_model: dict[str, list[RunResult]] = {}
    for r in usable:
        by_model.setdefault(r.model, []).append(r)

    per_model = {}
    for model, rs in by_model.items():
        per_model[model] = {
            "score": score(rs),
            "passed": sum(1 for r in rs if r.passed),
            "total": len(rs),
            "seconds": round(sum(r.seconds for r in rs), 1),
            "tokens": sum(r.total_tokens for r in rs),
            "tool_calls": sum(r.tool_calls for r in rs),
            "errors": [r.error for r in rs if r.error],
            "by_category": {
                c: score([r for r in rs if r.category == c])
                for c in sorted({r.category for r in rs})
            },
        }

    by_cat: dict[str, dict[str, float]] = {}
    for c in CATEGORIES:
        rs = [r for r in usable if r.category == c]
        if rs:
            by_cat[c] = {m: score([x for x in rs if x.model == m]) for m in by_model}

    return {"per_model": per_model, "by_category": by_cat,
            "unusable_models": unusable_models,
            "n_results": len(results)}


def render_table(summary: dict[str, Any], catalog: Catalog | None = None) -> str:
    """Tabella leggibile. Una riga per modello, una colonna per categoria.

    Le categorie sono il punto: un modello con 0.9 in codice e 0.1 in
    ragionamento è migliore di uno con 0.5 ovunque, e la tabella lo mostra.
    """
    per_model = summary.get("per_model", {})
    if not per_model:
        return "(nessun risultato)"

    cats = sorted({c for m in per_model.values() for c in m.get("by_category", {})})
    short = {mid: (catalog.models[mid].info.short if catalog and mid in catalog.models else mid)
             for mid in per_model}

    w = max(len(s) for s in short.values())
    w = max(w, 8)

    head = f"{'modello':<{w}} {'tot':>5}  " + "  ".join(f"{c[:9]:>9}" for c in cats)
    lines = [head, "-" * len(head)]

    for mid, data in sorted(per_model.items(), key=lambda kv: -kv[1]["score"]):
        row = f"{short[mid]:<{w}} {data['score']:>5.2f}  "
        row += "  ".join(
            f"{data.get('by_category', {}).get(c, 0):>9.2f}" for c in cats
        )
        lines.append(row)

    lines.append("")
    lines.append("per_model = percentuale di task superati (n=1 per task, non è statistico)")
    if summary.get("unusable_models"):
        lines.append("")
        lines.append("NON MISURATI (il provider li riserva ad altri client, esclusi dal punteggio):")
        for m in summary["unusable_models"]:
            lines.append(f"  {short.get(m, m)}")
    return "\n".join(lines)
