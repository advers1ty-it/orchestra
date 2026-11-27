#!/usr/bin/env bash
# ============================================================
#  Avvia-Orchestra.sh — il file da lanciare dal Desktop su Linux
#
#  Si copia nella cache e si riavvia da li': un aggiornamento puo'
#  sostituire questo file mentre e' in esecuzione, e una shell che
#  legge un file che cambia sotto i piedi sbaglia. Poi aggiorna (se
#  serve) e passa la mano a Orchestra.sh.
# ============================================================
set -u

ROOT="${ORCHESTRA_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd -P)}"

if [ -z "${ORCHESTRA_STABILE:-}" ]; then
    export ORCHESTRA_STABILE=1
    export ORCHESTRA_DIR="$ROOT"
    CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/orchestra"
    mkdir -p "$CACHE" 2>/dev/null || true
    if cp -f "$ROOT/Avvia-Orchestra.sh" "$CACHE/Avvia-Orchestra.sh" 2>/dev/null; then
        exec bash "$CACHE/Avvia-Orchestra.sh" "$@"
    fi
    # Se la cache non e' scrivibile si continua da qui: meglio un
    # launcher che parte senza copia stabile che uno che non parte.
fi

cd "$ROOT" 2>/dev/null || {
    echo "Cartella di Orchestra non trovata: $ROOT" >&2
    exit 1
}

PY=""
for candidato in "$ROOT/venv/bin/python" "$ROOT/.venv/bin/python" python3 python; do
    if ! command -v "$candidato" >/dev/null 2>&1; then
        continue
    fi
    if "$candidato" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        PY="$candidato"
        break
    fi
done

# L'aggiornamento si fa solo per le azioni che avviano qualcosa: fermare
# un server non deve aspettare la rete, come su Windows.
AZIONE="${1:-avvia}"
case "$AZIONE" in
    ''|avvia|start|riavvia|restart)
        if [ -n "$PY" ]; then
            export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
            if command -v timeout >/dev/null 2>&1; then
                timeout 90 "$PY" -m orchestra.cli update --auto >/dev/null 2>&1 || true
            else
                "$PY" -m orchestra.cli update --auto >/dev/null 2>&1 || true
            fi
        fi
        ;;
esac

exec bash "$ROOT/Orchestra.sh" "$@"
