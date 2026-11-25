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
import threading
import time

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

os.environ.setdefault("ORCHESTRA_HOME",
                      tempfile.mkdtemp(prefix="orchestra_sug_"))

from orchestra import suggerimenti as sg  # noqa: E402
from orchestra.types import LLMResponse  # noqa: E402


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

print("\n== le proposte dinamiche vengono dal turno, non da uno scheletro ==")


class ProviderFinto:
    """Un modello che risponde, o che cade, senza rete."""

    def __init__(self, risposta="", errore=None):
        self.risposta = risposta
        self.errore = errore
        self.chiamate = 0
        self.prompt = ""

    def chat(self, messages, tools=None, **kw):
        self.chiamate += 1
        self.prompt = messages[0].content
        if self.errore:
            raise self.errore
        return LLMResponse(content=self.risposta, model="finto")


def rie(ts):
    return dict(TURNO, ts=ts, traccia_id=ts)


CONVERSAZIONE = (
    "user: i consigli di fine turno sono sempre gli stessi, rendili dinamici\n"
    "assistant: ho aggiunto il generatore; resta da decidere se il modello "
    "deve scriverli a ogni turno o solo quando cambia qualcosa."
)

RISPOSTA = '''Ecco:
```json
{"proposte": [
  {"titolo": "Decidi quando rigenerarli", "prompt": "Confronta le due strade per i consigli: a ogni turno, oppure solo quando cambia qualcosa. Costi e latenza da una parte, freschezza dall'altra; dimmi quale sceglieresti e perche'."},
  {"titolo": "Scrivi il messaggio d'errore", "prompt": "Riscrivi il messaggio che compare quando il modello dei consigli non risponde, in modo che dica cosa e' successo e cosa fare, senza la parola errore."},
  {"titolo": "Prova il caso senza provider", "prompt": "Aggiungi al test il caso in cui il provider manca del tutto e verifica che restino le quattro proposte fisse, senza chiamate."}
]}
```'''

p_din = ProviderFinto(RISPOSTA)
lista = sg.proposte(rie(1), radice=casa, stato_git=lambda: [],
                    provider=p_din, conversazione=CONVERSAZIONE)
check("il modello viene interrogato", p_din.chiamate == 1,
      str(p_din.chiamate))
check("tornano le proposte del modello, non le fisse",
      len(lista) == 3 and lista[0]["titolo"] == "Decidi quando rigenerarli"
      and all(x["id"].startswith("dinamico-") for x in lista),
      str([x["titolo"] for x in lista]))
check("il prompt del modello porta l'ultimo scambio",
      "sempre gli stessi" in p_din.prompt
      and "resta da decidere" in p_din.prompt, p_din.prompt[:300])
check("e i fatti del turno: file e test che li coprono",
      "orchestra/skills.py" in p_din.prompt
      and "python tests/test_skills.py" in p_din.prompt,
      p_din.prompt[:500])
check("chiede di non allargare il lavoro",
      "Non allargare il lavoro" in p_din.prompt, p_din.prompt[:300])
check("lascia il commit al suo pulsante, fuori dai consigli",
      "Non proporre di fare commit" in p_din.prompt, p_din.prompt[:400])
check("senza modifiche non committate niente commit",
      "commit" not in {x["id"] for x in lista},
      str([x["id"] for x in lista]))

# La cache: due consumatori (finestra e telefono) per lo stesso turno non
# pagano due volte e non vedono due liste diverse.
prima = p_din.chiamate
lista2 = sg.proposte(rie(1), radice=casa, stato_git=lambda: [],
                     provider=p_din, conversazione=CONVERSAZIONE)
check("lo stesso turno non richiama il modello", p_din.chiamate == prima,
      str(p_din.chiamate))
check("e da la stessa lista",
      [x["prompt"] for x in lista2] == [x["prompt"] for x in lista],
      str([x["titolo"] for x in lista2]))

# Un turno nuovo e' una domanda nuova.
sg.proposte(rie(2), radice=casa, stato_git=lambda: [],
            provider=p_din, conversazione=CONVERSAZIONE + "\nuser: ok")
check("un turno nuovo richiama il modello", p_din.chiamate == prima + 1,
      str(p_din.chiamate))

print("\n== il commit non prende il posto di un consiglio ==")

lista_c = sg.proposte(rie(11), radice=casa,
                      stato_git=lambda: ["orchestra/suggerimenti.py"],
                      provider=ProviderFinto(RISPOSTA),
                      conversazione="modifiche da committare")
check("con git sporco il commit c'e'",
      len(lista_c) == 4 and lista_c[-1]["id"] == "commit",
      str([x["id"] for x in lista_c]))
check("e i tre consigli del modello restano tutti",
      [x["titolo"] for x in lista_c[:3]]
      == ["Decidi quando rigenerarli", "Scrivi il messaggio d'errore",
          "Prova il caso senza provider"],
      str([x["titolo"] for x in lista_c]))
check("il commit nomina i file veri",
      "orchestra/suggerimenti.py" in lista_c[-1]["prompt"],
      lista_c[-1]["prompt"][:200])

lista_due = sg.proposte(rie(12), radice=casa, stato_git=lambda: ["a.py"],
                        provider=ProviderFinto(RISPOSTA),
                        conversazione="due posti", massimo=2)
check("con due posti restano un consiglio e il commit",
      len(lista_due) == 2 and lista_due[0]["id"].startswith("dinamico-")
      and lista_due[-1]["id"] == "commit",
      str([x["id"] for x in lista_due]))

print("\n== se il modello non risponde, restano le proposte vere ==")

rotto = ProviderFinto(errore=RuntimeError("giu'"))
tot = per_id(sg.proposte(rie(3), radice=casa, stato_git=lambda: [],
                         provider=rotto, conversazione=CONVERSAZIONE))
check("un provider che solleva non rompe niente",
      "verifica" in tot and "seguito" in tot, str(list(tot)))

storto = ProviderFinto("Non ho capito, ecco un testo qualsiasi.")
tot2 = per_id(sg.proposte(rie(4), radice=casa, stato_git=lambda: [],
                          provider=storto, conversazione=CONVERSAZIONE))
check("una risposta non-JSON ricade sulle fisse", "verifica" in tot2,
      str(list(tot2)))

una = ProviderFinto('{"proposte":[{"titolo":"Solo una","prompt":"'
                    + "x" * 80 + '"}]}')
tot3 = per_id(sg.proposte(rie(5), radice=casa, stato_git=lambda: [],
                          provider=una, conversazione=CONVERSAZIONE))
check("una proposta sola non e' una scelta: si ricade sulle fisse",
      "verifica" in tot3, str(list(tot3)))

senza_prov = per_id(sg.proposte(rie(6), radice=casa, stato_git=lambda: [],
                                conversazione=CONVERSAZIONE))
check("senza provider restano le fisse", "verifica" in senza_prov,
      str(list(senza_prov)))
vuota = ProviderFinto(RISPOSTA)
sg.proposte(rie(7), radice=casa, stato_git=lambda: [],
            provider=vuota, conversazione="")
check("senza conversazione il modello non viene chiamato",
      vuota.chiamate == 0, str(vuota.chiamate))

lungo = RISPOSTA.replace("Decidi quando rigenerarli", "D" * 80)
lista4 = sg.proposte(rie(9), radice=casa, stato_git=lambda: [],
                     provider=ProviderFinto(lungo),
                     conversazione="titoli lunghi")
check("i titoli stanno nei 60 caratteri di Telegram",
      all(len(x["titolo"]) <= 60 for x in lista4),
      str([len(x["titolo"]) for x in lista4]))

print("\n== due richieste insieme per lo stesso turno pagano una volta ==")

lento = ProviderFinto(RISPOSTA)
_chat_vera = lento.chat


def _chat_lenta(messages, tools=None, **kw):
    time.sleep(0.3)
    return _chat_vera(messages, tools=tools, **kw)


lento.chat = _chat_lenta
esiti = []


def _chiama():
    esiti.append(sg.proposte(rie(10), radice=casa, stato_git=lambda: [],
                             provider=lento, conversazione="due consumatori"))


fili = [threading.Thread(target=_chiama) for _ in range(2)]
for filo in fili:
    filo.start()
for filo in fili:
    filo.join(10)
check("due richieste parallele, una sola chiamata al modello",
      lento.chiamate == 1, str(lento.chiamate))
check("e tutte e due ricevono i consigli",
      len(esiti) == 2 and all(len(x) == 3 for x in esiti),
      str([len(x) for x in esiti]))

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + str(FAIL))
    sys.exit(1)
