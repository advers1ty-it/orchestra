"""Guard di sicurezza: il root è un confine, non una convenzione.

Il caso che ha motivato questo file: `run_shell` non aveva guardia e
bypassava quella di `read_file`. Un test e2e ha quindi letto
`../../../Windows/win.ini` correttamente ("il modello non può uscire dal
root" passava) mentre un `head -2 .../.env` sarebbe stampato le chiavi API.

Questi test verificano che il blocco AVVENGA, non solo che non crashi.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe5")
os.environ["ORCHESTRA_ROOT"] = WORK
os.makedirs(WORK, exist_ok=True)

from orchestra.tools import _check_shell_access, default_registry  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


print("\n[1] run_shell: i tentativi di escape devono essere bloccati")
sh = default_registry().get("run_shell")

ESCAPES = [
    ("lettura .env dei genitori", "head -2 ../../.env"),
    ("lettura chiave Hermes", "head -2 /c/Users/adver/AppData/Local/hermes/.env"),
    ("path win.ini relativo", "cat ../../../Windows/win.ini"),
    ("percorso assoluto Windows", "type C:\\Windows\\win.ini"),
    ("home esplicita", "ls /home/adver"),
    ("ssh keys", "cat ~/.ssh/id_rsa"),
    ("aws credentials", "cat .aws/credentials"),
    ("git credentials", "cat .git-credentials"),
    ("etc/passwd", "head -3 /etc/passwd"),
    ("npmrc", "cat .npmrc"),
    ("config hermes", "cat ../../.config/hermes/config.yaml"),
]
for label, cmd in ESCAPES:
    out = sh.handler(command=cmd)
    blocked = "BLOCCATO" in out
    check(f"bloccato: {label}", blocked, f"output={out[:90]}")

print("\n[2] i comandi legittimi devono passare")
ALLOWED = [
    "ls",
    "python3 script.py",
    'python3 -c "print(1)"; python3 -c "print(2)"',
    "grep -r pattern src/",
    "cat src/main.py",
    "mkdir -p build && cd build",
    "git status",
    "npm test -- --watch=false",
    "python3 -c \"print('perche gia citta')\"",
]
for cmd in ALLOWED:
    out = sh.handler(command=cmd)
    blocked = "BLOCCATO" in out
    check(f"consentito: {cmd[:42]}", not blocked, f"bloccato per errore: {out[:90]}")

print("\n[3] il messaggio di blocco dice al modello cosa fare")
out = sh.handler(command="cat ../../../Windows/win.ini")
check("blocca con motivo", "root" in out.lower() or "protetto" in out.lower(), out[:150])
check("suggerisce un'alternativa", "relativi" in out or "root consentito" in out, out[:150])
check("non espone il contenuto del file", "boot loader" not in out.lower())

print("\n[4] read_file: guardia coerente")
rf = default_registry().get("read_file")
for bad in ["../../../Windows/win.ini", "..\\..\\secrets.txt", "/etc/passwd"]:
    try:
        rf.handler(path=bad)
        check(f"read_file blocca {bad[:30]}", False, "ha letto!")
    except ValueError as e:
        check(f"read_file blocca {bad[:30]}", True)
    except Exception as e:
        check(f"read_file blocca {bad[:30]}", False, f"tipo inatteso: {type(e).__name__}")

print("\n[5] il blocco non uccide il loop")
from orchestra import Agent, LoopConfig, LLMResponse  # noqa: E402
from orchestra.types import ToolCall  # noqa: E402


class EvilProvider:
    """Il modello insiste nel tentare di leggere fuori dal root."""

    def __init__(self):
        self.t = 0
        self.model = "m"

    def chat(self, messages, tools=None, **kw):
        self.t += 1
        if self.t > 3:
            return LLMResponse(content="Mi arrendo, non posso leggerlo.", model="m")
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id=f"e{self.t}", name="run_shell",
                                 arguments='{"command":"head -2 ../../.env"}')],
            model="m",
        )


reg = default_registry()
a = Agent(EvilProvider(), reg, "SYS", LoopConfig(max_iterations=6))
st = a.run("leggimi le chiavi")
check("loop sopravvive ai tentativi bloccati", st.stopped_because == "risposta_finale", st.stopped_because)
tool_out = "\n".join(m.content for m in st.messages if m.role == "tool")
check("nessun segreto trapelato", "sk-" not in tool_out and "BLOCCATO" in tool_out)
check("il modello ha visto il rifiuto", "BLOCCATO" in tool_out)

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
