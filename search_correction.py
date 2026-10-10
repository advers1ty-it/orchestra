import os
found = []
for root, dirs, files in os.walk('.'):
    for f in files:
        if f.endswith(('.py', '.md')):
            p = os.path.join(root, f)
            try:
                text = open(p, encoding='utf-8', errors='ignore').read()
            except Exception:
                continue
            if 'correction' in text.lower():
                found.append(p)
for f in found:
    print(f)
