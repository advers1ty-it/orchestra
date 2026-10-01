import os
est = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff'}
res = []
for d, dn, fn in os.walk('.'):
    dn[:] = [x for x in dn if x != '.git']
    for f in fn:
        if os.path.splitext(f)[1].lower() in est:
            p = os.path.join(d, f)
            res.append((os.path.getmtime(p), os.path.getsize(p), p))
res.sort(reverse=True)
for m, s, p in res[:30]:
    print(f"{s:>9}B  {p}")
print("TOTALE:", len(res))
