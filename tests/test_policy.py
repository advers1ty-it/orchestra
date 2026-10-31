"""La policy dei bot: tool ammessi e shell ammessa.

Nessuna rete e nessun comando eseguito: qui si verifica il CONFINE,
non quello che c'e' dentro. Le asserzioni sono sui tre punti che, se
sbagliati, rendono la policy una decorazione:

1. la normalizzazione (una lista vuota significa "nessun limite", e una
   lista scritta a mano non deve diventare una voce sola);
2. il registro (la policy restringe dopo il profilo, e non riallarga);
3. la shell (allowlist per programma, deny per sottostringa, e le
   sostituzioni `$(...)` rifiutate anche dentro le virgolette doppie).

Piu' la persistenza: un bot salvato con la policy la rilegge, e una
sessione a cui la policy viene impostata la applica al turno.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="orchestra_policy_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.environ["ORCHESTRA_ROOT"] = os.path.join(_TMP, "root")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)
os.makedirs(os.environ["ORCHESTRA_ROOT"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import LoopConfig, LLMResponse  # noqa: E402
from orchestra import bots as bt  # noqa: E402
from orchestra import policy as pol  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def nome_tool(t):
    if isinstance(t, dict):
        return str((t.get("function") or {}).get("name") or t.get("name") or "")
    return str(getattr(t, "name", ""))


print("\n[1] Normalizzazione: quattro liste, niente sorprese")
p = pol.normalizza({
    "tools": "read_file, RUN_SHELL, read_file",
    "nega_tools": ["image_gen"],
    "shell": "git, npm",
    "nega_shell": "rm -rf",
    "chiave_ignorata": ["x"],
})
check("i tool si normalizzano in minuscolo",
      p["tools"] == ["read_file", "run_shell"], str(p["tools"]))
check("i duplicati spariscono", len(p["tools"]) == 2, str(p["tools"]))
check("i tool vietati restano distinti",
      p["nega_tools"] == ["image_gen"], str(p["nega_tools"]))
check("la shell si legge dalla stringa",
      p["shell"] == ["git", "npm"], str(p["shell"]))
check("nega_shell e' una lista", p["nega_shell"] == ["rm -rf"],
      str(p["nega_shell"]))
check("le chiavi sconosciute non entrano",
      set(p) == {"tools", "nega_tools", "shell", "nega_shell"}, str(set(p)))
check("una policy None e' vuota", pol.vuota(None))
check("quattro liste vuote sono vuote", pol.vuota({"tools": []}))
check("una lista con dentro qualcosa non e' vuota",
      not pol.vuota({"shell": ["git"]}))
check("una stringa JSON si accetta",
      pol.normalizza('{"shell": "git"}')["shell"] == ["git"])
check("un JSON rotto non esplode",
      pol.normalizza("{non-json") == pol.normalizza(None))

print("\n[2] Il registro: la policy restringe, non allarga")
r = default_registry()
prima = set(r.nomi_attivi())
pol.applica_al_registro(r, {})
check("una policy vuota non tocca niente", set(r.nomi_attivi()) == prima)

r = default_registry()
pol.applica_al_registro(r, {"tools": ["read_file", "run_shell"],
                            "nega_tools": ["run_shell"]})
check("l'allowlist spegne il resto", set(r.nomi_attivi()) == {"read_file"},
      str(r.nomi_attivi()))
check("il deny vince sull'allowlist", "run_shell" not in r.nomi_attivi())
check("un tool spento dal profilo non torna acceso",
      "browser_apri" not in r.nomi_attivi())

# Il profilo ha gia' spento un tool; la policy non lo riaccende solo
# perche' compare nella sua lista.
r = default_registry()
r.disattiva("image_gen")
pol.applica_al_registro(r, {"tools": ["image_gen", "read_file"]})
check("la policy non riaccende un tool spento dal profilo",
      "image_gen" not in r.nomi_attivi() and "read_file" in r.nomi_attivi(),
      str(r.nomi_attivi()))

print("\n[3] Shell: programmi ammessi e sostituzioni")
pol.attiva({"shell": ["git", "echo", "npm"]})
check("un programma consentito passa", pol.motivo_blocco("git status") is None,
      str(pol.motivo_blocco("git status")))
check("due comandi consentiti passano",
      pol.motivo_blocco("git status && npm test") is None,
      str(pol.motivo_blocco("git status && npm test")))
check("un programma non consentito viene fermato",
      pol.motivo_blocco("curl https://esempio") is not None)
check("basta un comando non consentito in mezzo",
      pol.motivo_blocco("git status; rm -rf .") is not None)
check("un separatore dentro le virgolette non spezza",
      pol.motivo_blocco('echo "a; b"') is None,
      str(pol.motivo_blocco('echo "a; b"')))
check("un'assegnazione davanti non nasconde il programma",
      pol.motivo_blocco("FOO=1 git status") is None,
      str(pol.motivo_blocco("FOO=1 git status")))
check("il .exe non cambia il nome",
      pol.motivo_blocco("git.exe status") is None,
      str(pol.motivo_blocco("git.exe status")))
check("$(...) fuori dalle virgolette e' rifiutato",
      pol.motivo_blocco("echo $(whoami)") is not None)
check("$(...) dentro le virgolette DOPPIE e' rifiutato",
      pol.motivo_blocco('echo "$(whoami)"') is not None,
      "la shell esegue la sostituzione anche dentro le doppie")
check("i backtick sono rifiutati", pol.motivo_blocco("echo `whoami`") is not None)
check("in virgolette singole la sostituzione e' testo",
      pol.motivo_blocco("echo '$(whoami)'") is None,
      str(pol.motivo_blocco("echo '$(whoami)'")))
pol.disattiva()
check("senza policy la shell non ha limiti",
      pol.motivo_blocco("curl https://esempio; rm -rf /") is None)

pol.attiva({"nega_shell": ["rm -rf", "sudo"]})
check("il deny blocca anche se il programma e' consentito",
      pol.motivo_blocco("git status; rm -rf .") is not None)
check("il deny e' una sottostringa, non un programma",
      pol.motivo_blocco("echo 'sudo'") is not None)
check("il resto passa", pol.motivo_blocco("git status") is None)
pol.disattiva()

print("\n[4] run_shell: il divieto arriva prima del comando")
pol.attiva({"shell": ["git"]})
tool = default_registry().get("run_shell")
fuori = tool.handler(command="curl https://esempio", timeout=5)
check("run_shell non esegue un comando fuori allowlist",
      fuori.startswith("NON ESEGUITO"), fuori[:120])
check("e dice che e' la policy", "policy" in fuori, fuori[:120])
pol.disattiva()

print("\n[5] Il bot persiste la policy, e la sessione la applica")


class ProviderFinto:
    def __init__(self):
        self.name = "finto"
        self.model = "finto-1"
        self.tool_visti = []
        self.policy_vista = None

    def chat(self, messages, tools=None, **kw):
        # Solo la chiamata del turno: l'estrazione di memoria puo'
        # chiamare lo stesso provider dopo, senza tool, e se
        # sovrascrivesse qui il test guarderebbe la chiamata sbagliata.
        if tools:
            self.tool_visti = [nome_tool(t) for t in tools]
            self.policy_vista = pol.corrente()
        return LLMResponse(content="fatto", model=self.model)


b = bt.crea("PolicyBot", policy={
    "tools": ["read_file"],
    "shell": ["git"],
    "nega_shell": ["rm -rf"],
})
check("il bot torna con la policy", b.get("policy", {}).get("tools") == ["read_file"],
      str(b.get("policy")))
check("la policy riletta e' la stessa",
      (bt.per_id(b["id"]) or {}).get("policy") == b["policy"],
      str((bt.per_id(b["id"]) or {}).get("policy")))
agg = bt.aggiorna(b["id"], policy={"tools": ["run_shell"], "nega_shell": ["sudo"]})
check("la modifica sostituisce la policy",
      agg.get("policy", {}).get("tools") == ["run_shell"]
      and agg.get("policy", {}).get("shell") == [],
      str(agg.get("policy")))

prov = ProviderFinto()
s = Session(provider=prov, registry=default_registry(),
            system_prompt="sei un agente",
            config=LoopConfig(max_iterations=2))
s.imposta_policy({"tools": ["read_file"]})
check("la sessione parte", s.send("ciao"))
check("il turno finisce", s.wait(timeout=10))
check("il modello vede solo il tool consentito",
      prov.tool_visti == ["read_file"], str(prov.tool_visti))
check("la policy e' attiva nel thread del turno",
      prov.policy_vista == {"tools": ["read_file"], "nega_tools": [],
                            "shell": [], "nega_shell": []},
      str(prov.policy_vista))
check("e non resta attiva fuori dal turno", pol.corrente()["tools"] == [],
      str(pol.corrente()))

check("la sessione senza policy vede piu' di un tool",
      len(default_registry().nomi_attivi()) > 1)

print("\n[6] Un database vecchio viene migrato senza perdere i bot")
vecchio = os.path.join(_TMP, "bots_vecchio.db")
conn = sqlite3.connect(vecchio)
conn.executescript("""
CREATE TABLE bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL, provider TEXT NOT NULL DEFAULT '',
    modello TEXT NOT NULL DEFAULT '', persona TEXT NOT NULL DEFAULT '',
    progetto TEXT NOT NULL DEFAULT '', profilo TEXT NOT NULL DEFAULT '',
    parla_con TEXT NOT NULL DEFAULT '',
    creato REAL NOT NULL, aggiornato REAL NOT NULL
);
INSERT INTO bots (nome, creato, aggiornato) VALUES ('Vecchio', 1, 1);
""")
conn.commit()
conn.close()
originale = bt.percorso_db
try:
    bt.percorso_db = lambda: vecchio
    letto = bt.per_id(1)
finally:
    bt.percorso_db = originale
check("il bot vecchio si legge ancora",
      (letto or {}).get("nome") == "Vecchio", str(letto))
check("e senza policy non ha limiti",
      (letto or {}).get("policy") == pol.normalizza(None),
      str((letto or {}).get("policy")))

print(f"\n{'='*50}\n{PASS and 'PASS' if not FAIL else 'FAIL'}: "
      f"{len(PASS)} passati, {len(FAIL)} falliti")
for f in FAIL:
    print(f"  FALLITO: {f}")
sys.exit(1 if FAIL else 0)
