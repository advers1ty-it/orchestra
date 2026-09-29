"""Chiude i processi Orchestra rimasti in ascolto.

Su Windows `taskkill //F` non viene tradotto da MSYS e `cmd //c` apre una
shell invece di eseguire il comando. Python lo fa senza ambiguità.

Uso: python3 kill_ports.py 8737 [8750 ...]
"""

import os
import signal
import subprocess
import sys
import time


def listening_pids(ports):
    """PID in ascolto sulle porte date, via netstat."""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=30).stdout
    except Exception as e:
        print(f"netstat fallito: {e}")
        return {}
    found = {}
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local, pid = parts[1], parts[4]
        if ":" not in local:
            continue
        try:
            port = int(local.rsplit(":", 1)[1])
        except ValueError:
            continue
        if port in ports and pid.isdigit():
            found.setdefault(port, set()).add(int(pid))
    return found


def kill(pid):
    """Termina un processo. Windows non ha SIGKILL: per un processo che
    ignora SIGTERM c'e' `terminate()` via taskkill, che e' equivalente."""
    def alive():
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, OSError):
            return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        print(f"  {pid}: permesso negato")
        return False

    for _ in range(10):
        time.sleep(0.2)
        if not alive():
            return True

    # non ha collaborato: taskkill /F
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                   capture_output=True, text=True, timeout=20)
    for _ in range(10):
        time.sleep(0.2)
        if not alive():
            return True
    return not alive()


def main():
    ports = {int(a) for a in sys.argv[1:]} or {8737}
    found = listening_pids(ports)
    if not found:
        print("nessun processo su quelle porte")
        return 0
    for port, pids in found.items():
        print(f"porta {port}: {len(pids)} processo/i")
        for pid in sorted(pids):
            ok = kill(pid)
            print(f"  {'chiuso' if ok else 'ANCORA VIVO'} PID {pid}")
    time.sleep(0.5)
    left = listening_pids(ports)
    if left:
        print(f"ancora in ascolto: {left}")
        return 1
    print("tutte le porte libere")
    return 0


if __name__ == "__main__":
    sys.exit(main())
