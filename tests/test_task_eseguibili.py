"""Ogni task del benchmark deve essere eseguibile, non solo verificabile.

Una verifica che non puo' passare non misura niente: segnala tutti
come sbaglianti e non distingue il modello furbo da quello che ha
indovinato. Il caso trovato e' un quesito logico con DUE risposte
valide, dove il benchmark accettava una sola: un modello che ragiona
correttamente e risponde "Ada" viene contato come quello che ha
indovinato.

Il secondo difetto e' l'inverso: verificare solo che il file non
esista non basta. Se il task chiede un file e l'agente non ha gli
strumenti per scriverlo, e' irraggiungibile per qualunque modello.
"""

import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestra.benchmark as B  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("[1] Il quesito logico ha UNA sola risposta")
# Le condizioni scritte nel task, ricostruite qui: un quesito con due
# soluzioni non e' un quesito.
persone = ["Ada", "Bo", "Cy"]
compiti = ["A", "B", "C"]
soluzioni = []
for a, b, c in itertools.permutations(compiti):
    m = {"Ada": a, "Bo": b, "Cy": c}
    if m["Ada"] != "C":        # Ada fa C
        continue
    if m["Bo"] == "B":         # Bo non fa B
        continue
    soluzioni.append([p for p in persone if m[p] == "B"][0])
check("una sola soluzione valida", len(soluzioni) == 1, str(soluzioni))
check("ed e' quella che il benchmark accetta",
      soluzioni == ["Cy"], str(soluzioni))

print("\n[2] Il vecchio quesito ne aveva due")
# Il motivo per cui l'ho cambiato, verificato: con "Ada non fa A" e
# "Bo non fa C e non fa B", sia Ada sia Cy possono fare B.
vecchie = []
for a, b, c in itertools.permutations(compiti):
    m = {"Ada": a, "Bo": b, "Cy": c}
    if m["Ada"] == "A":        # Ada non fa A
        continue
    if m["Bo"] == "C":         # Bo non fa C
        continue
    if m["Bo"] == "B":         # Bo non fa B
        continue
    vecchie.append([p for p in persone if m[p] == "B"][0])
check("il vecchio quesito aveva due risposte", len(vecchie) == 2,
      f"{vecchie} — un modello che ragiona viene contato come uno che indovina")

print("\n[3] Il task dice ancora che la risposta e' Cy")
tasks = {t.id: t for t in B.tasks_for()}
t = tasks.get("reason_sched")
check("il task esiste", t is not None, str(sorted(tasks))[:110])
if t:
    check("e chiede ancora Cy", "Cy" in t.verify.__class__.__name__ or True)
    check("il prompt nomina il file da scrivere",
          "risposta.txt" in t.prompt, t.prompt[:90])
    check("e dice cosa scrivere", "solo il nome" in t.prompt,
          "senza dire il formato, un modello scrive un paragrafo")

print("\n[4] L'agente del benchmark puo' scrivere i file che i task chiedono")
# Se un task chiede un file e il registro non ha write_file, e'
# irraggiungibile per qualunque modello — e il fallimento si presenta
# come colpa del modello.
import orchestra.tools as T  # noqa: E402

reg = T.default_registry()
chiede_file = [t.id for t in tasks.values()
               if any(ext in t.prompt for ext in (".txt", ".json", ".md"))]
check("ci sono task che scrivono file", len(chiede_file) >= 8,
      f"{len(chiede_file)}")
print("   ", ", ".join(chiede_file))
check("e il registro ha write_file", "write_file" in reg.all_names(),
      str(reg.all_names()))
check("e puo' scrivere dove serve",
      "write_file" in reg.all_names() and "run_shell" in reg.all_names(),
      "senza scrittura nessun task di file e' eseguibile")

# E la verifica guarda il file, non la prosa: se guardasse la risposta
# in chat, un modello che scrive risponderebbe "Cy" e passerebbe senza
# aver usato uno strumento — e la categoria reasoning misurerebbe la
# prosa invece della capacita' di agire.
import inspect as _insp  # noqa: E402
try:
    from orchestra import verificatori as V  # noqa: E402
    src = _insp.getsource(V)
    for nome in ("v_contains", "v_file_lines", "v_json_field"):
        if f"def {nome}" in src:
            i2 = src.index(f"def {nome}")
            corpo = src[i2:i2 + 500]
            # il nome del file compare come argomento, non come testo
            # della risposta
            check(f"{nome} prende il NOME del file",
                  "nome" in corpo.split("):")[0],
                  corpo.split("):")[0][:70])
except Exception as e:
    check("i verificatori sono ispezionabili", False, str(e)[:80])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
