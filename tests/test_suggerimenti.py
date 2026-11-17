"""I pulsanti di fine turno: prompt gia' scritti, mai inventati.

Il difetto che previene: un pulsante che promette "controlla cosa puo'
essersi rotto" e incolla un prompt generico. Sembra che qualcuno abbia
guardato, e non e' vero — quindi il test guarda DENTRO il prompt: i file
veri, il comando del test vero, e nessun test inventato quando non c'e'.
"""

from __future__ import annotations

import os
import sys
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

os.environ.setdefault("ORCHESTRA_HOME",
                      tempfile.mkdtemp(prefix="orchestra_sug_"))

from orchestra import suggerimenti as sg  # noqa: E402


PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def per_id(lista):
    return {p["id"]: p for p in lista}


# Una radice finta, con i test solo per alcuni file: e' l'unico modo per
# provare "esiste il test giusto" senza dipendere da questo repository.
casa = tempfile.mkdtemp(prefix="sug-radice-")
os.makedirs(os.path.join(casa, "tests"), exist_ok=True)
for nome in ("test_skills.py", "test_agent.py"):
    with open(os.path.join(casa, "tests", nome), "w", encoding="utf-8") as f:
        f.write("# finto\n")

TURNO = {
    "file": [
        {"percorso": "orchestra/skills.py", "stato": "modificato",
         "aggiunte": 12, "tolte": 3},
        {"percorso": "docs/note.md", "stato": "nuovo",
         "aggiunte": 4, "tolte": 0},
    ],
    "esito_testo": "finito",
    "errori": 0,
}

print("\n== un turno che ha toccato dei file ==")

lista = sg.proposte(TURNO, radice=casa, stato_git=lambda: [])
p = per_id(lista)
check("c'e' la verifica", "verifica" in p, str(list(p)))
check("c'e' la revisione", "revisione" in p, str(list(p)))
check("senza modifiche non committate niente commit", "commit" not in p,
      str(list(p)))
check("il seguito chiude la lista", lista[-1]["id"] == "seguito",
      str([x["id"] for x in lista]))
check("tre pulsanti", len(lista) == 3, str(len(lista)))

ver = p["verifica"]["prompt"]
check("nomina il file toccato", "orchestra/skills.py (+12/-3)" in ver,
      ver[:200])
check("conta i file", "ha toccato 2 file" in ver, ver[:200])
check("nomina il test che lo copre", "python tests/test_skills.py" in ver,
      ver[:200])
check("chiede il giro intero", "python tests/run_all.py" in ver, ver[:200])
check("non corregge da solo", "Non correggere niente" in ver, ver[-120:])

print("\n== un file senza test non ne inventa uno ==")

senza = {"file": [{"percorso": "docs/note.md", "stato": "nuovo",
                   "aggiunte": 4, "tolte": 0}]}
v2 = per_id(sg.proposte(senza, radice=casa, stato_git=lambda: []))["verifica"]
check("lo dice invece di inventare",
      "non c'e' un test che ne porta il nome" in v2["prompt"],
      v2["prompt"][:300])
check("nessun comando di test inventato",
      "python tests/" not in v2["prompt"], v2["prompt"][:300])

print("\n== con modifiche non committate arriva il commit ==")

lista = sg.proposte(TURNO, radice=casa,
                    stato_git=lambda: ["orchestra/skills.py", "a.py"])
p = per_id(lista)
check("c'e' il commit", "commit" in p, str(list(p)))
check("quattro pulsanti al massimo", len(lista) == 4, str(len(lista)))
check("il prompt nomina i file non committati",
      "orchestra/skills.py" in p["commit"]["prompt"], p["commit"]["prompt"])
check("e vieta il push", "Non pushare" in p["commit"]["prompt"],
      p["commit"]["prompt"])

print("\n== nessun turno, repo pulito: resta il seguito ==")

lista = sg.proposte({}, radice=casa, stato_git=lambda: [])
check("un pulsante solo", len(lista) == 1, str([x["id"] for x in lista]))
check("ed e' il seguito", lista[0]["id"] == "seguito",
      str([x["id"] for x in lista]))

print("\n== nessun turno, ma modifiche non committate ==")

lista = sg.proposte({}, radice=casa, stato_git=lambda: ["x.py"])
check("la revisione guarda il diff non committato",
      "revisione" in per_id(lista), str([x["id"] for x in lista]))
check("e non c'e' la verifica, che parla dei file del turno",
      "verifica" not in per_id(lista), str([x["id"] for x in lista]))

print("\n== un turno finito male lo dice nel prompt ==")

male = dict(TURNO, esito_testo="fermato: troppi errori di fila", errori=3)
v3 = per_id(sg.proposte(male, radice=casa, stato_git=lambda: []))["verifica"]
check("conta gli errori di tool", "3 errori di tool" in v3["prompt"],
      v3["prompt"][:200])
check("riporta l'esito", "troppi errori di fila" in v3["prompt"],
      v3["prompt"][:200])

print("\n== troppi file: si nominano i primi e si dice quanti restano ==")

molti = {"file": [{"percorso": f"orchestra/m{i}.py", "aggiunte": 1, "tolte": 0}
                  for i in range(10)]}
v4 = per_id(sg.proposte(molti, radice=casa, stato_git=lambda: []))["verifica"]
check("nomina al massimo quattro file",
      v4["prompt"].count("orchestra/m") == sg.NOMINATI,
      v4["prompt"][:300])
check("e dice quanti ne restano", "e altri 6" in v4["prompt"],
      v4["prompt"][:300])

print("\n== ogni pulsante porta un prompt utilizzabile ==")

lista = sg.proposte(TURNO, radice=casa, stato_git=lambda: ["a.py", "b.py"])
check("id tutti diversi", len({x["id"] for x in lista}) == len(lista),
      str([x["id"] for x in lista]))
check("titoli corti e non vuoti",
      all(0 < len(x["titolo"]) <= 60 for x in lista),
      str([x["titolo"] for x in lista]))
check("prompt lunghi abbastanza da dire qualcosa",
      all(len(x["prompt"]) > 150 for x in lista),
      str([len(x["prompt"]) for x in lista]))
check("nessun segnaposto al posto dei dati",
      all("{" not in x["prompt"] and "?" != x["prompt"].strip() for x in lista),
      str([x["prompt"][:60] for x in lista]))

print("\n== il massimo vale anche quando ce ne sarebbero di piu' ==")

check("con massimo=2 ne tornano due",
      len(sg.proposte(TURNO, radice=casa,
                      stato_git=lambda: ["a.py"], massimo=2)) == 2)
check("con massimo=0 nessuno",
      sg.proposte(TURNO, radice=casa,
                  stato_git=lambda: ["a.py"], massimo=0) == [])

print("\n== leggere il git vero non solleva ==")

check("una cartella senza repo torna vuota",
      sg.sporchi(tempfile.mkdtemp(prefix="sug-norepo-")) == [])
check("una radice che non esiste torna vuota",
      sg.sporchi(os.path.join(casa, "non-esiste")) == [])

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
