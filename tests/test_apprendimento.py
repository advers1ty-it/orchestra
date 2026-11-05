"""L'apprendimento delle skill: contare, proporre, e non decidere da solo.

Il difetto che questa suite tiene fermo: `skill_genera` esisteva e non lo
chiamava nessuno, quindi la cartella delle skill imparate restava vuota e
il pannello prometteva un apprendimento che non c'era. Qui si verifica
che il conto esista, che la soglia sia quella dichiarata, che una
proposta NON entri nel prompt finche' non e' accettata, e che accettare o
scartare porti davvero dove dice.
"""

import json
import os
import sys
import tempfile
import types

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# Prima di importare orchestra: RADICE delle skill si legge all'import.
TMP = tempfile.mkdtemp(prefix="orchestra_appr_")
os.environ["ORCHESTRA_HOME"] = os.path.join(TMP, "dati")
os.environ["ORCHESTRA_SKILLS"] = os.path.join(TMP, "skills")
os.makedirs(os.environ["ORCHESTRA_SKILLS"], exist_ok=True)

from orchestra import apprendimento as ap          # noqa: E402
from orchestra import skills as sk                  # noqa: E402
from orchestra.session import Session               # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


def evento(tipo, **dati):
    return {"tipo": tipo, "dati": dati}


def turno(comandi, *, ok=True, prefisso="a"):
    """Gli eventi di un turno che esegue questi comandi con run_shell."""
    ev = []
    for i, c in enumerate(comandi):
        ident = f"{prefisso}{i}"
        ev.append(evento("tool_start", name="run_shell",
                         args={"command": c}, id=ident))
        ev.append(evento("tool_end", name="run_shell", ok=ok, id=ident,
                         result=""))
    return ev


print("\n[1] dai eventi ai comandi: solo quelli riusciti, nell'ordine")
ev = [
    evento("tool_start", name="run_shell", args={"command": "npm ci"}, id="1"),
    evento("tool_end", name="run_shell", ok=True, id="1"),
    evento("tool_start", name="run_shell", args={"command": "npm run build"},
           id="2"),
    evento("tool_end", name="run_shell", ok=True, id="2"),
    evento("tool_start", name="run_shell", args={"command": "npm test"},
           id="3"),
    evento("tool_end", name="run_shell", ok=False, id="3"),
    evento("tool_start", name="read_file", args={"percorso": "x"}, id="4"),
    evento("tool_end", name="read_file", ok=True, id="4"),
]
comandi = ap.comandi_da_eventi(ev)
check("tiene solo i comandi riusciti", comandi == ["npm ci", "npm run build"],
      str(comandi))
check("un comando fallito non entra", "npm test" not in comandi)
check("un tool di lettura non e' una procedura",
      all("x" not in c for c in comandi))
check("spazi diversi sono lo stesso comando",
      ap.firma(["npm   test"]) == ap.firma(["npm test"]))
check("comandi diversi sono procedure diverse",
      ap.firma(["npm test"]) != ap.firma(["npm run build"]))

print("\n[2] la soglia: tre volte, non una")
check("prima volta: niente proposta",
      ap.osserva(turno(["make build"]), "compilare") is None)
check("seconda volta: niente proposta",
      ap.osserva(turno(["make build"]), "compilare") is None)
p = ap.osserva(turno(["make build"]), "compilare")
check("terza volta: proposta", p is not None)
if p:
    check("la proposta porta le tre prove", len(p.prove) == 3,
          str(len(p.prove)))
    check("la proposta dice quante volte", p.volte == 3, str(p.volte))
    check("il nome viene dai comandi", p.nome == "make-build", p.nome)
    check("il corpo elenca i passi", "make build" in p.corpo)
    check("la descrizione e' leggibile",
          "3 volte" in p.descrizione, p.descrizione)
check("alla quarta non si ripropone",
      ap.osserva(turno(["make build"]), "compilare") is None)
stato = ap.leggi()
check("lo stato e' su disco",
      os.path.isfile(os.path.join(os.environ["ORCHESTRA_HOME"],
                                  "apprendimento.json")))
check("lo stato ricorda che e' stata proposta",
      any(v.get("proposto") for v in stato["firme"].values()))

print("\n[3] un turno senza comandi non insegna niente")
check("nessun comando, nessuna proposta",
      ap.osserva([], "una domanda") is None)
check("solo comandi falliti, nessuna proposta",
      ap.osserva(turno(["comando-che-fallisce"], ok=False), "x") is None)

print("\n[4] la proposta non entra nel prompt")
i = sk.Indice()
percorso = ap.proponi(i, p)
testo = open(percorso, encoding="utf-8").read()
check("il file dice che e' una proposta", "stato: proposta" in testo)
check("il file porta la firma", "firma:" in testo)
s = i.get(p.nome)
check("l'indice la conosce", s is not None)
check("l'indice sa che e' una proposta", bool(s and s.proposta))
check("non e' fra le attive", p.nome not in [x.nome for x in i.attive()])
check("non compare nel prompt", p.nome not in i.prompt("compilare"))
check("la ricerca non la restituisce",
      p.nome not in [x.nome for x in i.cerca(["make", "build"])])

print("\n[5] accettare la rende vera")
ok, perche = sk.conferma(i, p.nome)
check("conferma riuscita", ok, perche)
s = i.get(p.nome)
check("non e' piu' una proposta", not (s and s.proposta))
attenzione = i.attive()
check("entra fra le attive", p.nome in [x.nome for x in attenzione])
check("entra nel prompt", p.nome in i.prompt("make build compilare"))
ok2, perche2 = sk.conferma(i, p.nome)
check("non si accetta due volte", not ok2, perche2)

print("\n[6] scartare la toglie di mezzo, senza perderla")
p2 = None
for _ in range(3):
    p2 = ap.osserva(turno(["docker compose up -d"]), "avviare lo stack")
if p2:
    ap.proponi(sk.Indice(), p2)
    from orchestra.rotte_skill import _skill_cancella
    i2 = sk.Indice()
    check("la proposta esiste prima dello scarto", i2.get(p2.nome) is not None)
    check("scarto riuscito", _skill_cancella(i2, p2.nome))
    check("dopo lo scarto non e' attiva",
          p2.nome not in [x.nome for x in sk.Indice().attive()])
    cestino = os.path.join(os.environ["ORCHESTRA_SKILLS"], ".cestino")
    trovata = False
    for dirpath, _dirs, files in os.walk(cestino):
        if "SKILL.md" in files:
            trovata = True
    check("e' nel cestino, non cancellata", trovata)
else:
    check("proposta creata per lo scarto", False, "nessuna proposta")

print("\n[7] il gancio di fine turno")
emessi = []


class _Finto:
    _impara = Session._impara_dal_turno

    def __init__(self, esito=""):
        self.agent = types.SimpleNamespace(
            state=types.SimpleNamespace(stopped_because=esito))
        self.bridge = types.SimpleNamespace(
            emit=lambda k, d: emessi.append((k, d)))


reg = types.SimpleNamespace(eventi=turno(["pytest -q"], prefisso="b1"))
turni_prima = sum(1 for v in ap.leggi()["firme"].values()
                  if "pytest -q" in (v.get("comandi") or []))
for n in range(3):
    reg = types.SimpleNamespace(eventi=turno(["pytest -q"], prefisso=f"b{n}"))
    _Finto()._impara("far passare i test", reg)
proposte = [x for x in sk.Indice().tutte() if x.proposta]
check("il gancio crea la proposta", any(x.nome == "pytest-q" for x in proposte),
      str([x.nome for x in proposte]))
check("il gancio lo dice in chat", any("procedura" in str(d).lower()
                                       for _k, d in emessi),
      str(emessi))

emessi.clear()
reg = types.SimpleNamespace(eventi=turno(["flutter build apk"], prefisso="c"))
for n in range(3):
    reg = types.SimpleNamespace(eventi=turno(["flutter build apk"],
                                             prefisso=f"c{n}"))
    _Finto("budget_exceeded")._impara("compilare apk", reg)
check("un turno fermato dal budget non insegna",
      not any("procedura" in str(d).lower() for _k, d in emessi),
      str(emessi))
check("infatti non c'e' la proposta",
      not any(x.nome == "flutter-build-apk"
              for x in sk.Indice().tutte()))

print("\n[8] lo stato non cresce senza fine")
voce = [v for v in ap.leggi()["firme"].values()
        if "pytest -q" in (v.get("comandi") or [])]
check("le prove sono limitate", bool(voce) and len(voce[0].get("prove", [])) <= 3,
      str(voce[0].get("prove") if voce else None))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
