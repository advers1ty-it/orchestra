import os, time
now = time.time()
rec = []
for d, dn, fn in os.walk('.'):
    dn[:] = [x for x in dn if x not in ('.git', '__pycache__')]
    for f in fn:
        p = os.path.join(d, f)
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if now - m < 7200:
            rec.append((now - m, os.path.getsize(p), p))
rec.sort()
for eta, s, p in rec[:40]:
    print(f"{int(eta):>6}s fa  {s:>9}B  {p}")
print("TOTALE recenti:", len(rec))
