"""Runner della suite. `python3 tests/run_all.py`

Ordine: offline -> resilienza -> shell -> e2e. I primi tre non chiamano
l'API e devono passare sempre; l'e2e salta da solo se manca la chiave.
"""

import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))

SUITES = [
    ("offline", "test_offline.py", True),
    ("resilienza", "test_resilience.py", True),
    ("shell", "test_shell.py", True),
    ("sicurezza", "test_security.py", True),
    ("sessione", "test_session.py", True),
    ("webapp", "test_webapp.py", True),
    ("ui", "test_ui.py", True),
    ("benchmark", "test_benchmark.py", True),
    ("e2e", "test_e2e.py", False),
]

results = []
for name, script, required in SUITES:
    print(f"\n{'='*66}\n>>> {name.upper()}\n{'='*66}")
    r = subprocess.run([sys.executable, os.path.join(HERE, script)],
                       cwd=os.path.dirname(HERE))
    results.append((name, r.returncode, required))

print(f"\n{'='*66}\nRIEPILOGO\n{'='*66}")
failed = []
for name, code, required in results:
    if code == 0:
        print(f"  PASS  {name}")
    elif not required:
        print(f"  SKIP  {name} (non richiesto)")
    else:
        print(f"  FAIL  {name} (exit {code})")
        failed.append(name)

if failed:
    print(f"\n{len(failed)} suite fallite: {', '.join(failed)}")
    sys.exit(1)
print("\nTutto verde.")