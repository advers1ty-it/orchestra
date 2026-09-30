"""CLI di Orchestra.

Uso:
    python -m orchestra.cli run "il tuo compito"
    python -m orchestra.cli chat          (sessione interattiva)
    python -m orchestra.cli doctor        (verifica chiavi e provider)
    python -m orchestra.cli models        (modelli disponibili, filtro :free)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from . import __version__
from .agent import Agent, LoopConfig
from .providers import KNOWN_PROVIDERS, ProviderError, build_provider, load_env
from .tools import SYSTEM_PROMPT, default_registry

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _env() -> dict[str, str]:
    """Le chiavi del .env vincono sull'ambiente: è il file di config del
    progetto e deve poter sovrascrivere senza rompere la shell."""
    merged = dict(os.environ)
    merged.update(load_env(ENV_PATH))
    return merged


def _config(env: dict[str, str]) -> LoopConfig:
    def num(key: str, default: int) -> int:
        try:
            return int(env.get(key, default))
        except (TypeError, ValueError):
            return default

    def flt(key: str, default: float) -> float:
        try:
            return float(env.get(key, default))
        except (TypeError, ValueError):
            return default

    return LoopConfig(
        max_iterations=num("ORCHESTRA_MAX_ITERATIONS", 12),
        context_limit=num("ORCHESTRA_CONTEXT_LIMIT", 120_000),
        keep_recent=num("ORCHESTRA_KEEP_RECENT", 8),
        temperature=flt("ORCHESTRA_TEMPERATURE", 0.7),
        max_tokens=num("ORCHESTRA_MAX_TOKENS", 4096),
    )


# --------------------------------------------------------------------------
# rendering degli eventi
# --------------------------------------------------------------------------

C = {
    "dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
    "r": "\033[31m", "c": "\033[36m", "x": "\033[0m",
}


def _on_event(kind: str, data: dict[str, Any]) -> None:
    t0 = time.time()
    if kind == "assistant":
        if data.get("content"):
            print(f"\n{C['b']}{data['content']}{C['x']}")
        for tc in data.get("tool_calls") or []:
            args = ", ".join(f"{k}={str(v)[:40]!r}" for k, v in tc["args"].items())
            print(f"{C['c']}  -> {tc['name']}({args}){C['x']}")
    elif kind == "tool_end":
        mark = f"{C['g']}ok{C['x']}" if data.get("ok") else f"{C['r']}err{C['x']}"
        preview = " ".join((data.get("result") or "").split())[:110]
        print(f"{C['dim']}  [{mark}] {data['name']}: {preview}{C['x']}")
    elif kind == "tool_error":
        print(f"{C['r']}  [eccezione] {data['tool']}: {data['error']}{C['x']}")
    elif kind == "compaction":
        r = data
        print(
            f"{C['y']}  [contesto] {r['tokens_before']} -> {r['tokens_after']} token "
            f"(potati {r['tools_pruned']} tool, fusi {r['history_merged']} turni){C['x']}"
        )
    elif kind == "retry":
        print(f"{C['y']}  [retry {data['attempt']}] {data['error'][:90]}{C['x']}")


def _footer(agent: Agent) -> None:
    st = agent.state
    per_model = ", ".join(f"{k}:{v}" for k, v in st.usage_by_model.items())
    print(
        f"\n{C['dim']}── {st.iterations} iterazioni | {st.tool_calls_made} tool | "
        f"{st.tool_errors} errori | {st.total_tokens} token ({per_model}) | "
        f"stop: {st.stopped_because}{C['x']}"
    )


# --------------------------------------------------------------------------
# comandi
# --------------------------------------------------------------------------


def _build_agent(env: dict[str, str], extra_prompt: str = "") -> Agent:
    provider_name = env.get("ORCHESTRA_PROVIDER", "openrouter")
    model = env.get("ORCHESTRA_MODEL", "")
    if not model:
        raise SystemExit(
            "ORCHESTRA_MODEL non impostato. Copia orchestra/.env.example "
            "in orchestra/.env e scegli un modello."
        )
    provider = build_provider(provider_name, model=model, env=env)
    reg = default_registry()
    prompt = SYSTEM_PROMPT + (f"\n\n{extra_prompt}" if extra_prompt else "")
    return Agent(provider, reg, prompt, _config(env), on_event=_on_event)


def cmd_run(args: argparse.Namespace) -> int:
    env = _env()
    try:
        agent = _build_agent(env, args.system or "")
    except ProviderError as e:
        print(f"{C['r']}errore provider: {e}{C['x']}", file=sys.stderr)
        return 2
    t = time.time()
    agent.run(args.prompt)
    _footer(agent)
    print(f"{C['dim']}in {time.time() - t:.1f}s{C['x']}")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    env = _env()
    try:
        agent = _build_agent(env, args.system or "")
    except ProviderError as e:
        print(f"{C['r']}errore provider: {e}{C['x']}", file=sys.stderr)
        return 2

    print(f"{C['b']}Orchestra {__version__}{C['x']} — modello {env.get('ORCHESTRA_MODEL')}")
    print(f"{C['dim']}/esci per uscire{C['x']}\n")
    while True:
        try:
            line = input(f"{C['c']}tu >{C['x']} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/esci", "/exit", "/quit"):
            break
        agent.run(line)
        _footer(agent)
        print()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    env = _env()
    print(f"{C['b']}Orchestra {__version__} — doctor{C['x']}\n")
    ok = True

    print("Configurazione")
    print(f"  .env letto:       {'sì' if load_env(ENV_PATH) else 'NO'}")
    print(f"  provider:         {env.get('ORCHESTRA_PROVIDER', '(non impostato)')}")
    print(f"  modello:          {env.get('ORCHESTRA_MODEL', '(non impostato)')}")
    cfg = _config(env)
    print(f"  max_iterations:   {cfg.max_iterations}")
    print(f"  context_limit:    {cfg.context_limit}")
    print(f"  keep_recent:      {cfg.keep_recent}")
    print(f"  root:             {os.environ.get('ORCHESTRA_ROOT', os.getcwd())}")

    print("\nChiavi")
    dim, reset = C["dim"], C["x"]
    for name, (_, key_env, _) in KNOWN_PROVIDERS.items():
        present = bool(env.get(key_env))
        # stampiamo solo se presente, mai il valore
        stato = "presente" if present else f"{dim}assente{reset}"
        print(f"  {key_env:<24} {stato}")
        if name == env.get("ORCHESTRA_PROVIDER") and not present:
            ok = False

    print("\nProvider")
    name = env.get("ORCHESTRA_PROVIDER", "")
    if name not in KNOWN_PROVIDERS:
        print(f"  {C['r']}provider sconosciuto: {name}{C['x']}")
        ok = False
    else:
        _, key_env, _ = KNOWN_PROVIDERS[name]
        if not env.get(key_env):
            print(f"  {C['r']}manca {key_env}{C['x']}")
            ok = False
        else:
            try:
                p = build_provider(name, model=env.get("ORCHESTRA_MODEL", ""), env=env)
                models = p.list_models()
                free = [m for m in models if m.endswith(":free")]
                print(f"  connesso a {name}: {len(models)} modelli, {len(free)} gratuiti")
                for m in free[:8]:
                    print(f"    {C['g']}{m}{C['x']}")
                if len(free) > 8:
                    print(f"    ... altri {len(free) - 8}")
            except Exception as e:
                print(f"  {C['y']}non verificato: {e}{C['x']}")

    print(f"\n{C['g'] if ok else C['r']}{'pronto' if ok else 'configurazione incompleta'}{C['x']}")
    return 0 if ok else 1


def cmd_models(args: argparse.Namespace) -> int:
    env = _env()
    name = args.provider or env.get("ORCHESTRA_PROVIDER", "openrouter")
    try:
        p = build_provider(name, model=env.get("ORCHESTRA_MODEL", ""), env=env)
    except ProviderError as e:
        print(f"errore: {e}", file=sys.stderr)
        return 2
    models = p.list_models()
    if not models:
        print("nessun modello ottenuto (il provider potrebbe non esporre /models)")
        return 1
    if args.free:
        models = [m for m in models if m.endswith(":free")]
    print(f"{len(models)} modelli su {name}\n")
    for m in models:
        print(f"  {m}")
    return 0


def cmd_model(args: argparse.Namespace) -> int:
    """Elenca i modelli e quello in uso, e permette di cambiarlo."""
    env = _env()
    provider_name = args.provider or env.get("ORCHESTRA_PROVIDER", "openrouter")
    from .catalog import Catalog

    try:
        cat = Catalog.fetch(provider_name)
    except Exception as e:  # noqa: BLE001
        print(f"{C['r']}errore: {e}{C['x']}", file=sys.stderr)
        return 2

    if not cat.models:
        print("nessun modello con tool-calling trovato")
        return 1

    current = env.get("ORCHESTRA_MODEL", "")
    if args.set:
        if args.set not in cat.models:
            print(f"{C['r']}modello sconosciuto: {args.set}{C['x']}")
            print(f"disponibili: {len(cat.models)}")
            return 1
        _write_model(args.set)
        print(f"{C['g']}modello impostato su {args.set}{C['x']}")
        return 0

    if args.list:
        print(f"{len(cat.models)} modelli con tool-calling su {provider_name}\n")
        for p in sorted(cat.with_tools(), key=lambda x: x.info.id):
            mark = f"{C['g']}*{C['x']} " if p.info.id == current else "  "
            price = "free" if p.info.is_free else (
                f"${p.info.prompt_price:.2f}/1M in"
            )
            ctx = f"{p.info.context_length // 1000}k" if p.info.context_length else "?"
            print(f" {mark}{p.info.id:<48} {price:>12}  ctx {ctx:>5}")
        print(f"\n{'*' } = in uso. Cambia con: orchestra model --set <id>")
        return 0

    # default: riepilogo + misurazioni
    print(f"in uso: {current}\n")
    measured = cat.measured()
    if not measured:
        print(f"{C['y']}nessun modello misurato ancora.{C['x']}")
        print(f"Misura con: orchestra bench --sample 3")
        print(f"\n{C['dim']}{len(cat.models)} modelli disponibili, "
              f"{len(cat.free())} gratuiti con tool-calling{C['x']}")
        return 0

    print(f"{C['b']}misurati{C['x']} (fatto, non ipotesi)\n")
    for cat_name in sorted({c for p in measured for c in p.scores}):
        board = cat.leaderboard(cat_name)
        if not board:
            continue
        print(f"{C['b']}{cat_name}{C['x']}")
        for name, s in board:
            bar = "#" * int(s * 20)
            print(f"  {name:<28} {s:.2f}  {C['c']}{bar}{C['x']}")
        print()
    return 0


def _write_model(model_id: str) -> None:
    """Scrive ORCHESTRA_MODEL nel .env, sostituendo la riga se c'è."""
    import re

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return
    if re.search(r"^ORCHESTRA_MODEL=.*$", content, re.M):
        content = re.sub(r"^ORCHESTRA_MODEL=.*$", f"ORCHESTRA_MODEL={model_id}",
                         content, flags=re.M)
    else:
        content += f"\nORCHESTRA_MODEL={model_id}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def cmd_bench(args: argparse.Namespace) -> int:
    env = _env()
    provider_name = args.provider or env.get("ORCHESTRA_PROVIDER", "openrouter")

    from .benchmark import render_table, run_task, summarize, tasks_for
    from .catalog import Catalog

    try:
        cat = Catalog.fetch(provider_name)
    except Exception as e:  # noqa: BLE001
        print(f"{C['r']}errore catalogo: {e}{C['x']}", file=sys.stderr)
        return 2

    if args.show:
        tasks = tasks_for(args.category)
        if not tasks:
            print(f"nessun task nella categoria {args.category}", file=sys.stderr)
            return 1
        print(f"{len(tasks)} task\n")
        for t in tasks:
            print(f"  {C['b']}{t.id}{C['x']}  [{C['c']}{t.category}{C['x']}]")
            print(f"    {C['dim']}{t.prompt[:100]}...{C['x']}\n")
        return 0

    # Scelta dei modelli. Tre modi, in ordine di precisione:
    # lista esplicita, filtro per prezzo, campione.
    #   --models a b c      proprio quelli che scelgo
    #   --free / --paid     tutta la fascia, niente casuale'
    #   (default)           campione di free
    #   --all               tutto, free e a pagamento
    if args.models:
        ids = list(args.models)
    else:
        if args.free or args.paid:
            # fascia intera: niente campionamento, niente ordine arbitrario
            scelti = cat.select(free=args.free, paid=args.paid)
            if args.batch:
                scelti = scelti[:args.batch]
                print(f"{C['dim']}batch: {len(scelti)} modelli, ordine alfabetico."
                      f" Prosegui con --batch {len(scelti)} per il giro successivo.{C['x']}\n")
            ids = [p.info.id for p in scelti]
            if not ids:
                fascia = "gratuiti" if args.free else "a pagamento"
                print(f"{C['r']}nessun modello {fascia} con tool-calling{C['x']}", file=sys.stderr)
                return 1
        elif args.all:
            ids = sorted(cat.models)
        else:
            free = sorted(cat.free(), key=lambda p: p.info.id)
            if not free:
                print(f"{C['r']}nessun modello gratuito con tool-calling{C['x']}", file=sys.stderr)
                return 1
            # campione: primo, uno medio, uno con contesto grande. Non e'
            # casuale perche' il confronto deve essere leggibile.
            free.sort(key=lambda p: -(p.info.context_length or 0))
            step = max(1, len(free) // max(1, args.sample))
            ids = [m.info.id for m in free[::step]][:args.sample]

    if not ids:
        print("nessun modello da testare", file=sys.stderr)
        return 1

    tasks = tasks_for(args.category)
    if not tasks:
        print(f"categoria sconosciuta: {args.category}", file=sys.stderr)
        return 1

    total = len(ids) * len(tasks) * args.repeat
    print(f"{C['b']}Benchmark{C['x']}: {len(ids)} modelli × {len(tasks)} task"
          f"{f' × {args.repeat} ripetizioni' if args.repeat > 1 else ''}")
    print(f"{C['dim']}{total} run. Costo reale: consumo token del provider."
          f" I modelli :free non costano nulla.{C['x']}\n")
    print(f"{C['dim']}n=1 per task: indicazione, non statistica. "
          f"Usa --repeat per confronti che contano.{C['x']}\n")
    if args.throttle:
        print(f"{C['dim']}pausa {args.throttle}s fra i run: i free tier di OpenRouter "
              f"rispondono 429 se vai troppo veloce.{C['x']}\n")

    from .benchmark import RunResult

    results: list[RunResult] = []
    t0 = time.time()
    done = 0
    # un modello che il provider riserva ad altri client fallisce su OGNI
    # task: inutile insistere. Lo scopriamo al primo run.
    dead: set[str] = set()
    for mid in ids:
        if mid in dead:
            print(f"{C['b']}{cat.models[mid].info.short if mid in cat.models else mid}{C['x']}"
                  f"  {C['dim']}saltato: non raggiungibile{C['x']}\n")
            continue
        name = cat.models[mid].info.short if mid in cat.models else mid
        print(f"{C['b']}{name}{C['x']}")
        for rep in range(args.repeat):
            for task in tasks:
                # Pausa fra i run. I free tier di OpenRouter rispondono 429
                # se spari troppo veloce, e un benchmark interamente
                # "errore 429" non misura niente. Meglio aspettare che
                # misurare male.
                if done and args.throttle:
                    time.sleep(args.throttle)
                done += 1
                sys.stdout.write(f"  {task.id:<18} ")
                sys.stdout.flush()
                r = run_task(task, provider_name=provider_name, model=mid,
                             env=env, max_iterations=args.max_iterations)
                results.append(r)
                if r.unusable:
                    # il modello è riservato ad altri client: inutile
                    # continuare, e segnarlo 0.00 farebbe sembrare che sia
                    # scarso quando è solo irraggiungibile da qui
                    dead.add(mid)
                    print(f"{C['y']}non raggiungibile{C['x']}  {C['dim']}"
                          f"{r.error[:70]}{C['x']}")
                    break
                if r.error:
                    mark = f"{C['r']}errore{C['x']}"
                    note = r.error[:110]
                elif r.passed:
                    mark = f"{C['g']}ok{C['x']}"
                    note = f"{r.seconds:.0f}s {r.completion_tokens}tok"
                else:
                    mark = f"{C['y']}fail{C['x']}"
                    # 60 caratteri tagliavano via metà del messaggio di
                    # errore, e il dettaglio è l'unica cosa che serve per
                    # capire se il fallo è del modello o del benchmark
                    note = r.detail[:110]
                print(f"{mark}  {C['dim']}{note}{C['x']}")
            if mid in dead:
                break
        if mid in dead:
            continue
        passed = sum(1 for r in results if r.model == mid and r.passed)
        n = len([r for r in results if r.model == mid])
        print(f"  {C['dim']}-> {passed}/{n}{C['x']}\n")

    summary = summarize(results)
    print(f"\n{C['b']}risultati ({time.time() - t0:.0f}s){C['x']}\n")
    print(render_table(summary, cat))

    # persistenza: i punteggi alimentano il routing
    scored = {}
    for mid, data in summary["per_model"].items():
        prof = cat.models.get(mid)
        if prof:
            prof.scores = {c: v for c, v in data["by_category"].items() if v > 0}
            prof.last_measured = time.time()
            scored[mid] = prof
    if scored and not args.no_save:
        cat.save()
        print(f"\n{C['dim']}misurazioni salvate. "
              f"Routing: orchestra model{C['x']}")

    if args.json:
        from .benchmark import asdict as _ad
        out = os.path.join(os.getcwd(), "bench_result.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump([_ad(r) for r in results], f, indent=2, default=str)
        print(f"{C['dim']}JSON: {out}{C['x']}")

    return 0


def cmd_web(args: argparse.Namespace) -> int:
    env = _env()
    if not env.get("ORCHESTRA_MODEL"):
        print(f"{C['r']}ORCHESTRA_MODEL non impostato.{C['x']} Copia orchestra/.env.example in orchestra/.env")
        return 2
    from .webapp import serve

    serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orchestra", description="Orchestratore agentico")
    p.add_argument("--version", action="version", version=f"orchestra {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="esegui un compito e esci")
    r.add_argument("prompt")
    r.add_argument("--system", help="istruzioni extra di sistema")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("chat", help="sessione interattiva")
    c.add_argument("--system", help="istruzioni extra di sistema")
    c.set_defaults(func=cmd_chat)

    w = sub.add_parser("web", help="interfaccia web in locale")
    w.add_argument("--host", default="127.0.0.1",
                   help="default 127.0.0.1; non esporre su rete (nessuna autenticazione)")
    w.add_argument("--port", type=int, default=8737)
    w.add_argument("--no-browser", action="store_true", help="non aprire il browser")
    w.set_defaults(func=cmd_web)

    mo = sub.add_parser("model", help="modelli disponibili e cambio modello")
    mo.add_argument("--list", action="store_true", help="elenca i modelli")
    mo.add_argument("--set", metavar="ID", help="imposta il modello in uso")
    mo.add_argument("--provider")
    mo.set_defaults(func=cmd_model)

    b = sub.add_parser("bench", help="misura quale modello fa cosa")
    b.add_argument("--sample", type=int, default=3,
                   help="quanti modelli provare (default 3)")
    b.add_argument("--all", action="store_true", help="prova tutti i modelli")
    b.add_argument("--free", action="store_true",
                   help="solo i modelli gratuiti, tutti, in ordine alfabetico")
    b.add_argument("--paid", action="store_true",
                   help="solo i modelli a pagamento (costano token veri)")
    b.add_argument("--batch", type=int, metavar="N", default=0,
                   help="con --free/--paid, fermati dopo N modelli "
                        "(un batch alla volta invece di 17 in un colpo)")
    b.add_argument("--models", nargs="+", metavar="ID", help="modelli specifici")
    b.add_argument("--category", help="solo una categoria (code, reasoning, ...)")
    b.add_argument("--repeat", type=int, default=1,
                   help="ripetizioni per task; >1 per confronti che contano")
    b.add_argument("--max-iterations", type=int, default=10)
    b.add_argument("--throttle", type=float, default=3.0,
                   help="secondi di pausa fra i run (default 3, evita i 429)")
    b.add_argument("--provider")
    b.add_argument("--show", action="store_true", help="mostra i task senza eseguirli")
    b.add_argument("--json", action="store_true", help="salva i risultati in JSON")
    b.add_argument("--no-save", action="store_true", help="non salvare le misurazioni")
    b.set_defaults(func=cmd_bench)

    d = sub.add_parser("doctor", help="verifica configurazione e connessione")
    d.set_defaults(func=cmd_doctor)

    m = sub.add_parser("models", help="elenca i modelli del provider")
    m.add_argument("--provider")
    m.add_argument("--free", action="store_true", help="solo modelli gratuiti")
    m.set_defaults(func=cmd_models)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
