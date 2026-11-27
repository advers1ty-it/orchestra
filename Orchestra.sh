#!/usr/bin/env bash
# ============================================================
#  Orchestra.sh — avvia / ferma / riavvia il server su Linux
#
#  E' il corrispettivo di Orchestra.cmd. Il numero di porta, il PID
#  e i log stanno in un posto solo; il collegamento sul Desktop e
#  l'avvio automatico passano da qui.
#
#    ./Orchestra.sh avvia
#    ./Orchestra.sh ferma
#    ./Orchestra.sh riavvia
#    ./Orchestra.sh log
#    ./Orchestra.sh stato
#
#  Senza argomento: se il server e' gia' acceso apre l'interfaccia,
#  altrimenti lo avvia. Un doppio avvio non crea due server.
# ============================================================
set -u

PORTA="${ORCHESTRA_PORT:-8737}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd -P)"
PIDFILE="$ROOT/orchestra.pid"
LOGFILE="$ROOT/orchestra.log"
LOGERR="$ROOT/orchestra.err.log"
URL="http://127.0.0.1:$PORTA"
NO_BROWSER="${ORCHESTRA_NO_BROWSER:-0}"
PY=""

case "$PORTA" in
    ''|*[!0-9]*) echo "Porta non valida: $PORTA" >&2; exit 2 ;;
esac

_trova_python() {
    local candidato
    for candidato in \
        "$ROOT/venv/bin/python" \
        "$ROOT/.venv/bin/python" \
        python3.14 python3.13 python3.12 python3.11 python3 python
    do
        if ! command -v "$candidato" >/dev/null 2>&1; then
            continue
        fi
        if "$candidato" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            PY="$candidato"
            return 0
        fi
    done
    return 1
}

if ! _trova_python; then
    echo "Python 3.11 o superiore non trovato." >&2
    echo "Installa python3 e il modulo venv, poi rilancia l'installer." >&2
    exit 1
fi

_porta_in_ascolto() {
    "$PY" - "$PORTA" <<'PY' >/dev/null 2>&1
import socket
import sys

porta = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.35)
try:
    s.connect(("127.0.0.1", porta))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
raise SystemExit(0)
PY
}

_leggi_pid() {
    local pid=""
    [ -f "$PIDFILE" ] || return 0
    IFS= read -r pid < "$PIDFILE" || true
    case "$pid" in
        ''|*[!0-9]*) return 0 ;;
    esac
    printf '%s\n' "$pid"
}

_pid_vivo() {
    [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

_pid_e_orchestra() {
    local pid="$1" riga="" cwd=""
    if [ -r "/proc/$pid/cmdline" ]; then
        riga="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    else
        riga="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    fi
    # Su Linux il PID puo' essere stato riusato da un'altra installazione:
    # la cartella di lavoro dice se e' davvero questa. Se readlink non
    # riesce a risolverla non si rifiuta il processo: meglio fidarsi del
    # PID registrato che non riconoscere il proprio server.
    if [ -r "/proc/$pid/cwd" ]; then
        cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
        if [ -n "$cwd" ] && [ "$cwd" != "$ROOT" ]; then
            return 1
        fi
    fi
    case "$riga" in
        *"orchestra.cli"*"web"*"--port $PORTA "*) return 0 ;;
        *"orchestra.cli"*"web"*"--port=$PORTA "*) return 0 ;;
        *) return 1 ;;
    esac
}

_attendi_porta() {
    local tentativi=0 pid="${1:-}"
    while [ "$tentativi" -lt 80 ]; do
        if _porta_in_ascolto; then
            return 0
        fi
        if [ -n "$pid" ] && ! _pid_vivo "$pid"; then
            return 1
        fi
        sleep 0.5
        tentativi=$((tentativi + 1))
    done
    return 1
}

_apri_browser() {
    if [ "$NO_BROWSER" = "1" ]; then
        return 0
    fi
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 &
    else
        "$PY" - "$URL" <<'PY' >/dev/null 2>&1 &
import sys
import webbrowser

webbrowser.open(sys.argv[1])
PY
    fi
}

_ruota_log() {
    if [ -f "$LOGFILE" ]; then
        mv -f "$LOGFILE" "$LOGFILE.1" 2>/dev/null || true
    fi
    if [ -f "$LOGERR" ]; then
        mv -f "$LOGERR" "$LOGERR.1" 2>/dev/null || true
    fi
    : > "$LOGFILE"
    : > "$LOGERR"
}

_avvia_server() {
    local pid="" vecchio=""
    vecchio="$(_leggi_pid)"
    if _pid_vivo "$vecchio" && _pid_e_orchestra "$vecchio"; then
        if _porta_in_ascolto; then
            echo "Orchestra e' gia' acceso (PID $vecchio)."
            _apri_browser
            echo "Interfaccia: $URL"
            return 0
        fi
        echo "Il processo di Orchestra (PID $vecchio) e' vivo ma la porta" >&2
        echo "$PORTA non risponde. Usa \"$0 riavvia\" oppure \"$0 ferma\"." >&2
        return 1
    fi
    if [ -f "$PIDFILE" ]; then
        rm -f "$PIDFILE"
    fi
    if _porta_in_ascolto; then
        echo "La porta $PORTA e' gia' occupata da un altro processo." >&2
        echo "Non lo fermo: non so chi sia. Chiudi quel programma o cambia" >&2
        echo "porta con ORCHESTRA_PORT=... prima di riavviare." >&2
        return 1
    fi

    _ruota_log
    cd "$ROOT" || return 1
    export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
    if command -v setsid >/dev/null 2>&1; then
        nohup setsid "$PY" -m orchestra.cli web --port "$PORTA" --no-browser \
            >>"$LOGFILE" 2>>"$LOGERR" </dev/null &
    else
        nohup "$PY" -m orchestra.cli web --port "$PORTA" --no-browser \
            >>"$LOGFILE" 2>>"$LOGERR" </dev/null &
    fi
    pid=$!
    printf '%s\n' "$pid" > "$PIDFILE"

    if ! _attendi_porta "$pid"; then
        echo "Il server non ha risposto entro 40 secondi." >&2
        echo "Ultime righe di $LOGFILE:" >&2
        tail -n 30 "$LOGFILE" 2>/dev/null >&2 || true
        if [ -s "$LOGERR" ]; then
            echo "Ultime righe di $LOGERR:" >&2
            tail -n 30 "$LOGERR" 2>/dev/null >&2 || true
        fi
        if _pid_vivo "$pid"; then
            kill "$pid" 2>/dev/null || true
        fi
        rm -f "$PIDFILE"
        return 1
    fi

    echo "Orchestra e' acceso: $URL (PID $pid)"
    echo "Log: $LOGFILE"
    _apri_browser
    return 0
}

_ferma_server() {
    local pid="" tentativi=0
    pid="$(_leggi_pid)"
    if ! _pid_vivo "$pid"; then
        rm -f "$PIDFILE"
        if _porta_in_ascolto; then
            echo "La porta $PORTA e' occupata, ma non dal PID registrato." >&2
            echo "Non fermo un processo che non ho avviato io." >&2
            return 1
        fi
        echo "Orchestra non e' in esecuzione."
        return 0
    fi
    if ! _pid_e_orchestra "$pid"; then
        echo "Il PID $pid non e' piu' il server di Orchestra: non lo fermo." >&2
        rm -f "$PIDFILE"
        return 1
    fi

    echo "Fermo Orchestra (PID $pid)..."
    kill "$pid" 2>/dev/null || true
    while [ "$tentativi" -lt 40 ]; do
        if ! _pid_vivo "$pid"; then
            break
        fi
        sleep 0.25
        tentativi=$((tentativi + 1))
    done
    if _pid_vivo "$pid"; then
        echo "Non si e' fermato: lo interrompo." >&2
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
    if _porta_in_ascolto; then
        echo "La porta $PORTA risulta ancora occupata." >&2
        return 1
    fi
    echo "Fermato."
    return 0
}

_stato() {
    local pid=""
    pid="$(_leggi_pid)"
    if _pid_vivo "$pid" && _pid_e_orchestra "$pid"; then
        if _porta_in_ascolto; then
            echo "Orchestra: acceso"
            echo "PID: $pid"
            echo "Interfaccia: $URL"
        else
            echo "Orchestra: processo avviato, ma la porta $PORTA non risponde."
            echo "PID: $pid"
            echo "Usa \"$0 riavvia\" oppure \"$0 ferma\"."
        fi
    elif _porta_in_ascolto; then
        echo "Orchestra: la porta $PORTA e' occupata, ma il PID non e' quello noto."
    else
        echo "Orchestra: spento"
    fi
    echo "Cartella: $ROOT"
    echo "Log: $LOGFILE"
}

_mostra_log() {
    if [ ! -f "$LOGFILE" ] && [ ! -f "$LOGERR" ]; then
        echo "Nessun log: Orchestra non e' ancora stato avviato da qui."
        return 0
    fi
    if [ -f "$LOGFILE.1" ]; then
        echo "=== orchestra.log.1 (sessione precedente) ==="
        tail -n 40 "$LOGFILE.1" 2>/dev/null || true
        echo
    fi
    echo "=== orchestra.log ==="
    tail -n 100 "$LOGFILE" 2>/dev/null || true
    if [ -s "$LOGERR" ]; then
        echo
        echo "=== orchestra.err.log ==="
        tail -n 80 "$LOGERR" 2>/dev/null || true
    fi
}

_aiuto() {
    cat <<EOF
Uso: $(basename "$0") [comando] [--no-browser]

  avvia, start      avvia il server (e apre il browser)
  ferma, stop       ferma il server
  riavvia, restart  ferma e riavvia
  log               mostra gli ultimi log
  stato, status     dice se e' acceso e su quale porta
  aiuto, help       questo testo

Senza comando: avvia se spento, apre l'interfaccia se gia' acceso.
Porta: $PORTA (cambiala con ORCHESTRA_PORT).
EOF
}

AZIONE=""
for arg in "$@"; do
    case "$arg" in
        --no-browser) NO_BROWSER=1 ;;
        -h|--help|aiuto|help) AZIONE="aiuto" ;;
        avvia|start|ferma|stop|riavvia|restart|log|stato|status)
            AZIONE="$arg" ;;
        *)
            echo "Comando sconosciuto: $arg" >&2
            _aiuto >&2
            exit 2
            ;;
    esac
done

case "$AZIONE" in
    avvia|start) _avvia_server ;;
    ferma|stop) _ferma_server ;;
    riavvia|restart) _ferma_server && _avvia_server ;;
    log) _mostra_log ;;
    stato|status) _stato ;;
    aiuto) _aiuto ;;
    '') if _porta_in_ascolto; then _apri_browser; _stato; else _avvia_server; fi ;;
esac
