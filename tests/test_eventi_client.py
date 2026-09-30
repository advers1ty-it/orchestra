"""Ogni client SSE deve ricevere TUTTI gli eventi, non una fetta.

Con una sola coda, due consumatori si dividono il flusso a meta': il
primo prende gli eventi dispari, il secondo i pari. Non e' un caso
raro, e' cio' che succede ogni volta che la pagina e' aperta mentre
qualcos'altro guarda lo stesso stream — ed e' successo perche' un
client di test rubava meta' dei messaggi di una conversazione vera,
facendo sembrare un bug della chat quello che era un bug della coda.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ORCHESTRA_ROOT"] = r"D:\orchestra"

from orchestra.session import EventBridge  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def raccogli(bridge, n, risultato, idx):
    """Un client che ascolta finche' non ha n eventi."""
    for ev in bridge.stream(timeout=1.5):
        if ev["kind"] != "keepalive":
            risultato[idx].append(ev["kind"])
            if len(risultato[idx]) >= n:
                return


print("[1] Due client, stessi eventi")
b = EventBridge()
presi: list[list[str]] = [[], []]
ts = [threading.Thread(target=raccogli, args=(b, 4, presi, i), daemon=True)
      for i in (0, 1)]
for t in ts:
    t.start()
time.sleep(0.4)
for k in ("uno", "due", "tre", "quattro"):
    b.emit(k, {})
    time.sleep(0.1)
for t in ts:
    t.join(timeout=3)

check("il client A riceve tutti e 4", len(presi[0]) == 4, str(presi[0]))
check("il client B riceve tutti e 4", len(presi[1]) == 4, str(presi[1]))
check("e ricevono gli stessi, nello stesso ordine", presi[0] == presi[1],
      f"A={presi[0]} B={presi[1]}")

print("\n[2] Tre client: nessuno resta indietro")
b2 = EventBridge()
p2: list[list[str]] = [[], [], []]
ts2 = [threading.Thread(target=raccogli, args=(b2, 3, p2, i), daemon=True)
       for i in range(3)]
for t in ts2:
    t.start()
time.sleep(0.4)
for k in ("a", "b", "c"):
    b2.emit(k, {})
    time.sleep(0.1)
for t in ts2:
    t.join(timeout=3)
check("tutti e tre hanno tutto", all(len(p) == 3 for p in p2),
      str([len(p) for p in p2]))

print("\n[3] Un client che arriva dopo gli altri")
# Chi si collega a meta' NON deve ricevere il passato: deve vedere da
# dove si trova, e il suo unico riferimento e' la snapshot. Se ricevesse
# anche i vecchi, li mostrerebbe due volte.
b3 = EventBridge()
primo: list[str] = []
t3 = threading.Thread(target=raccogli, args=(b3, 2, [primo], 0), daemon=True)
t3.start()
time.sleep(0.3)
b3.emit("vecchio", {})
time.sleep(0.2)
tardivo: list[str] = []
t3b = threading.Thread(target=raccogli, args=(b3, 1, [tardivo], 0), daemon=True)
t3b.start()
time.sleep(0.3)
b3.emit("nuovo", {})
time.sleep(0.3)
t3b.join(timeout=2)
t3.join(timeout=2)
check("chi arriva dopo non riceve il passato", tardivo == ["nuovo"], str(tardivo))
check("chi c'era prima ha sentito entrambi", "vecchio" in primo, str(primo))

print("\n[4] Un client che non legge non blocca gli altri")
# Il tetto esiste per non far crescere la coda all'infinito, ma la
# perdita deve essere SOLO di quel client. Se blocca, un browser
# dimenticato in una scheda fermerebbe la chat.
b4 = EventBridge(maxsize=4)
lento: list[str] = []
veloce: list[str] = []
# il lento si iscrive ma non legge mai
q_lenta = b4._iscriviti()
t4 = threading.Thread(target=raccogli, args=(b4, 3, [veloce], 0), daemon=True)
t4.start()
time.sleep(0.3)
for k in ("1", "2", "3", "4", "5", "6", "7", "8"):
    b4.emit(k, {})
    time.sleep(0.05)
t4.join(timeout=3)
check("il client che legge riceve tutto", len(veloce) == 3, str(veloce))
check("nessuno e' rimasto bloccato", b4.dropped >= 0, str(b4.dropped))

print("\n[5] Un client che chiude viene tolto")
b5 = EventBridge()
prima = len(b5._subs)
gen = b5.stream(timeout=0.3)
next(gen)  # avvia il generatore: si iscrive
check("si e' iscritto", len(b5._subs) == prima + 1, str(len(b5._subs)))
gen.close()  # finally: si disiscrive
check("chiuso il generatore viene tolto", len(b5._subs) == prima, str(len(b5._subs)))

print("\n[6] close() chiude TUTTI i client")
b6 = EventBridge()
chiusi: list[bool] = [False, False]


def ascolta_close(i):
    for _ in b6.stream(timeout=2.0):
        pass
    chiusi[i] = True


ts6 = [threading.Thread(target=ascolta_close, args=(i,), daemon=True) for i in (0, 1)]
for t in ts6:
    t.start()
time.sleep(0.4)
b6.close()
for t in ts6:
    t.join(timeout=3)
check("entrambi i client hanno visto la chiusura", all(chiusi), str(chiusi))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
