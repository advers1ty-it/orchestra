"""Il cambio di servizio dalla chat, verificato eseguendo il bundle.

Non leggendo il sorgente: i selettori vengono popolati davvero, si
cambia davvero dal menu della chat, e si controlla che anche quello
delle Opzioni si allinei. La sincronizzazione e' la parte fragile — due
menu che devono dire la stessa cosa prima e dopo ogni cambio. Se
divergono, l'utente vede un servizio e usa un altro, che e' peggio che
non averlo.
"""

import os
import subprocess
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RADICE, "orchestra", "web")
ORDER = ["core.js", "panels.js", "main.js"]
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


# il bundle e' un unico script, quindi si esegue come uno
src = "\n;\n".join(open(os.path.join(WEB, f), encoding="utf-8").read() for f in ORDER)
dom = open(os.path.join(RADICE, "tests", "_dom_provider.js"), encoding="utf-8").read()
probe = open(os.path.join(RADICE, "tests", "_probe_provider.js"), encoding="utf-8").read()
i = probe.index("const OUT = { errori: [] };")
script = os.path.join(RADICE, "tests", "_run_provider.js")
with open(script, "w", encoding="utf-8") as f:
    f.write(dom + "\n" + src + "\n" + probe[i:])

r = subprocess.run(["node", script], capture_output=True, text=True, timeout=90)
out = r.stdout
if "errori" not in out:
    print(out[:600])
    print(r.stderr[:400])
    print("\n  il probe non ha girato: nessuna verifica")
    sys.exit(1)

import json  # noqa: E402

d = json.loads(out[out.index("{"):out.rindex("}") + 1])
os.unlink(script)

print("[1] I due selettori si popolano con gli stessi servizi")
check("il menu della chat ha voci", len(d["header"]["voci"]) >= 3, str(d["header"]["voci"]))
check("e le stesse del menu Opzioni",
      d["header"]["voci"] == d["opzioni"]["voci"],
      f'{d["header"]["voci"]} vs {d["opzioni"]["voci"]}')
check("entrambi puntano al servizio in uso",
      d["header"]["val"] == d["opzioni"]["val"], f'{d["header"]["val"]} / {d["opzioni"]["val"]}')
check("nessun errore durante il popolamento", d["errori"] == [], str(d["errori"]))

print("\n[2] Cambiare dalla chat cambia davvero il servizio")
check("il backend riceve il servizio scelto", d["dopo"]["servizioBackend"] == "groq",
      str(d["dopo"]["servizioBackend"]))
check("il menu della chat si allinea", d["dopo"]["header"] == "groq", d["dopo"]["header"])
check("e anche quello delle Opzioni", d["dopo"]["opzioni"] == "groq", d["dopo"]["opzioni"])
check("i due dicono la stessa cosa", d["dopo"]["header"] == d["dopo"]["opzioni"])

print("\n[3] Il modello segue il servizio")
# Senza questo, scegli un servizio nuovo e la lista resta quella del
# servizio vecchio: scegli un modello che quel servizio non ha.
check("i modelli della chat sono stati ricaricati",
      len(d["dopo"]["modelliChat"]) >= 2, str(d["dopo"]["modelliChat"]))
check("e la nota dice il servizio nuovo",
      d["dopo"]["nota"].lower().startswith("groq"), d["dopo"]["nota"])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
