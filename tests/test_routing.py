"""L'instradamento deve scegliere il giusto E dire perché.

Un instradamento automatico che non spiega le sue scelte è un
rifiuto di responsabilità: quando tre settimane dopo il risultato è
sbagliato, l'unica cosa che resta è spegnere tutto. Quindi qui si
verifica la metà noiosa — che scelga il modello giusto — e quella
che conta di più — che dica perché, e cosa ha scartato.

E si verifica il caso in cui NON c'è dato: un modello non misurato in
una categoria non è "il migliore", è l'unico disponibile, e la
differenza è la stessa che c'è fra "so" e "indovino".
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.routing import (  # noqa: E402
    MINIMO_PROVE, SOGLIA_DI_CAMBIO, categoria, il_successivo, instrada,
)

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


class Info:
    def __init__(self, mid, gratis=True, tools=True):
        self.id = mid
        self.short = mid.split("/")[-1]
        self.is_free = gratis
        self.supports_tools = tools


class Prof:
    def __init__(self, mid, scores=None, livelli=None, gratis=True, tools=True):
        self.info = Info(mid, gratis, tools)
        self.scores = scores or {}
        self.livelli = livelli or {}
        self.frazioni = {}
        self.task_per_cat = {}


class Cat:
    def __init__(self, profili):
        self.models = {p.info.id: p for p in profili}

    def with_tools(self):
        return [p for p in self.models.values() if p.info.supports_tools is not False]


def catalogo_pieno():
    return Cat([
        Prof("bravo/code", {"code": 1.0, "reasoning": 0.6}, {"code": "l1", "reasoning": "l2"}),
        Prof("medio/code", {"code": 0.8}, {"code": "l2"}),
        Prof("scarso/code", {"code": 0.5}, {"code": "l3"}),
        Prof("mattone/code", {"code": 0.95}, {"code": "l1"}),
    ])


print("[1] La categoria viene dalla richiesta, non da un modello")
check("estrazione", categoria("leggi il file e tira fuori i dati") == "extraction")
check("scrittura", categoria("riscrivi il documento") == "writing")
check("ragionamento", categoria("perche questo fallisce") == "reasoning")
check("web", categoria("fai una pagina html") == "web")
check("app", categoria("react native build") == "app")
check("il default e' code", categoria("fammi una cosa qualsiasi") == "code")
check("e una richiesta vuota non spacca", categoria("") == "code")

print("\n[2] Sceglie il migliore fra i MISURATI")
s = instrada(catalogo_pieno(), "fammi una funzione")
check("sceglie il punteggio piu' alto", s.modello == "bravo/code", str(s.modello))
check("e lo dichiara", s.punteggio == 100.0, str(s.punteggio))
check("la categoria e' quella giusta", s.categoria == "code", s.categoria)
check("cammina verso la stessa", "perché" in s.spiega() or "perche" in s.spiega())

print("\n[3] E sa chi ha scartato, e perché")
scartati = [x["modello"] for x in s.scartati]
check("ha scartato qualcuno", len(s.scartati) > 0, str(s.scartati))
check("e il motivo è un confronto di punteggio",
      any("contro" in x["motivo"] for x in s.scartati),
      str([x["motivo"] for x in s.scartati][:2]))

print("\n[4] Un modello non misurato NON viene scelto come migliore")
cat = catalogo_pieno()
cat.models["nonmisurato/code"] = Prof("nonmisurato/code")
s2 = instrada(cat, "fammi una funzione")
check("il non misurato non vince", s2.modello != "nonmisurato/code", str(s2.modello))

print("\n[5] Se nessuno è misurato, si sceglie — e si dice che è a caso")
vuoto = Cat([Prof("solo1/code"), Prof("solo2/code")])
s3 = instrada(vuoto, "fammi una funzione")
check("sceglie comunque", s3.modello in ("solo1/code", "solo2/code"), str(s3.modello))
check("ma non dichiara un punteggio", s3.punteggio is None, str(s3.punteggio))
check("e il motivo lo dice chiaramente",
      "non perché sia il migliore" in s3.motivo or "per mancanza" in s3.motivo,
      s3.motivo)

print("\n[6] Poche prove: si sceglie, ma dichiarando che è poco")
# 2 prove e un 100%: il numero dice poco, e scegliere come se dicesse
# tutto e' il difetto. Con piu' prove lo stesso modello vince per
# merito.
pochi = Cat([Prof("poco/code", {"code": 1.0}, {"code": "l1"}),
             Prof("altro/code", {"code": 0.6, "js": 0.6}, {"code": "l2", "js": "l2"})])
s4 = instrada(pochi, "fammi una funzione")
check("sceglie comunque un modello", s4.modello is not None, str(s4.modello))
check("ma il motivo lo dichiara",
      "poche prove" in s4.motivo or "poco misurato" in s4.motivo, s4.motivo)
check("e la soglia è dichiarata", MINIMO_PROVE == 3, str(MINIMO_PROVE))

print("\n[7] Il vincolo 'solo gratis' scarta i pagati e lo dice")
cat = catalogo_pieno()
cat.models["pagato/code"] = Prof("pagato/code", {"code": 0.99}, {"code": "l3"}, gratis=False)
s5 = instrada(cat, "fammi una funzione", solo_gratis=True)
check("sceglie un gratis", cat.models[s5.modello].info.is_free, s5.modello)
check("e il pagato e' fra gli scartati",
      any(x["modello"] == "pagato/code" and "pagamento" in x["motivo"]
          for x in s5.scartati),
      str(s5.scartati))

print("\n[8] Il ripiego: il successivo per la stessa categoria")
cat = catalogo_pieno()
prima = instrada(cat, "fammi una funzione")
dopo = il_successivo(prima, cat)
check("il ripiego e' diverso", dopo.modello != prima.modello,
      f"{prima.modello} e poi {dopo.modello}")
check("ed e' il secondo per punteggio", dopo.modello == "mattone/code",
      str(dopo.modello))
check("la soglia di cambio e' dichiarata", SOGLIA_DI_CAMBIO == 2,
      str(SOGLIA_DI_CAMBIO))

print("\n[9] Nessun modello: una Scelta, non un'errore")
niente = Cat([Prof("solo/code", tools=False)])
s6 = instrada(niente, "fammi una cosa")
check("non solleva", True)
check("e dice che non c'e'", s6.modello is None or s6.motivo,
      f"{s6.modello} / {s6.motivo}")
check("la spiegazione resta leggibile", isinstance(s6.spiega(), str))

print("\n[10] La spiegazione si può mostrare a chi chiede")
cat = catalogo_pieno()
t = instrada(cat, "fammi una funzione").spiega()
check("ha il modello", "bravo/code" in t, t[:80])
check("ha il perché", "perché:" in t or "perche:" in t, t[:120])
check("ha gli scartati", "scartato" in t, t[-160:])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)