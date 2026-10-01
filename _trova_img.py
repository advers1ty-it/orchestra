"""Trova immagini recenti in una cartella (argomento = cartella da esaminare)."""
import os, sys, time

est = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")
radice = sys.argv[1]
profondita_max = int(sys.argv[2]) if len(sys.argv) > 2 else 2
now = time.time()
risultati = []
for dp, dn, fn in os.walk(radice):
    if dp[len(radice):].count(os.sep) >= profondita_max:
        dn[:] = []
    for f in fn:
        if f.lower().endswith(est):
            p = os.path.join(dp, f)
            try:
                risultati.append((now - os.path.getmtime(p), os.path.getsize(p), p))
            except OSError:
                pass
risultati.sort()
for eta, dim, p in risultati[:30]:
    print(f"{int(eta):>7}s fa  {dim:>9}B  {p}")
