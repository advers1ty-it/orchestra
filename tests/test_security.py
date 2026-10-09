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
    # Il blocco e' ancora garantito, ma il messaggio e' cambiato: ora
    # quando non c'e' nessuno a cui chiedere dice "NON ESEGUITO" e
    # spiega il percorso che ha toccato. Ci che conta e' che il comando
    # NON venga eseguito e che il messaggio dica perche' — non che usi
    # la stessa parola di prima.
    eseguito = "exit=" in out
    blocked = ("BLOCCATO" in out or "NON ESEGUITO" in out) and not eseguito
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
# 1) il blocco e' garantito
check("nessun comando di escape e' passato", not any(
    "exit=" in sh.handler(command=c) for _, c in ESCAPES))

# 2) il segreto non e' trapelato dal blocco stesso.
# Percorso ASSOLUTO, non relativo: con ../../ il risultato dipende da
# dove si trovi il processo, e il test passava o falliva a seconda
# della macchina. Un test che a volte passa non e' un test.
segreto = os.path.abspath(os.path.join(WORK, "..", "..", "segreto.env"))
out = sh.handler(command="head -2 " + segreto)
check("nessun segreto trapelato", "sk-" not in out, out[:70])

# 3) il modello ha visto il rifiuto, non un errore vuoto
check("il modello ha visto il rifiuto",
      "NON ESEGUITO" in out or "BLOCCATO" in out, out[:70])

# 4) e sa cosa fare: un blocco senza alternativa costringe a indovinare
check("suggerisce un'alternativa",
      any(s in out for s in ("relativi", "ORCHESTRA_ROOT", "root consentito")),
      out[:150])
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
        self.name = "evil"
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
# Il rifiuto e' garantito dal fatto che il segreto non c'e'. La PAROLA
# con cui viene detto e' cambiata: senza gate a cui chiedere ora e'
# "NON ESEGUITO: il comando tocca <percorso>", non "BLOCCATO". Un
# test che controlla la punteggiatura invece che la proprieta' fallisce
# e fa perdere tempo a chi crede che il controllo si sia indebolito.
rifiutato = "NON ESEGUITO" in tool_out or "BLOCCATO" in tool_out
check("nessun segreto trapelato", "sk-" not in tool_out and rifiutato, tool_out[:80])
check("il modello ha visto il rifiuto", rifiutato, tool_out[:80])
check("e ha visto il percorso che ha toccato",
      "D:\\" in tool_out or "C:\\" in tool_out, tool_out[:90])

print(f"\n{'='*60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
