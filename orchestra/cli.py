"""CLI di Orchestra.

Uso:
    python -m orchestra.cli run "il tuo compito"
    python -m orchestra.cli chat          (sessione interattiva)
    python -m orchestra.cli doctor        (verifica chiavi e provider)
    python -m orchestra.cli models        (modelli disponibili, filtro :free)
"""

from __future__ import annotations

import argparse
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
