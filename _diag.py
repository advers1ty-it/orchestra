import io
import os
import subprocess
import sys
import tempfile

s = io.open("tests/test_frontend_split.py", encoding="utf-8").read()
marcatore = '"""\n\n# scope condiviso'
i = s.index("probe = ")
j = s.index(marcatore)
harness = s[:i]
# il probe parte da " = '...'" fino alla chiusura
probe_start = s.index("'", i + 9)
probe_end = s.index("\n\"\"\"", probe_start)
probe = s[probe_start + 1:probe_end]

joined = "\n".join(
    io.open(os.path.join("orchestra", "web", n), encoding="utf-8").read()
    for n in ("core.js", "panels.js", "main.js"))

f = tempfile.mktemp(suffix=".js")
open(f, "w", encoding="utf-8").write(
    harness + joined + "\nconsole.log('LOADED');\n")
r = subprocess.run(["node", f], capture_output=True, text=True, timeout=60)
print("  rc:", r.returncode)
print("  stdout:", (r.stdout or "").strip()[-120:])
err = (r.stderr or "").strip()
print("  stderr:", err[-400:] if err else "(vuoto)")
os.unlink(f)