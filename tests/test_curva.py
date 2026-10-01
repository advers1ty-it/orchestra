"""Ogni task della curva deve avere una risposta giusta e una sbagliata.

Un task che non si puo' sbagliare e' peggio di nessun task: segna
tutti come perfetti e non distingue niente. E' successo tre volte —
reason_sched aveva due risposte valide, extract_cappi non diceva cosa
mettere nel campo, e un verificatore accettava una risposta sbagliata.

Qui ogni task viene eseguito due volte: con la soluzione giusta deve
passare, e con almeno una sbagliata deve fallire. Una soluzione
sbagliata che passa e' il difetto piu' subdolo di tutti, perche' il
task sembra funzionare e non misura.

Le soluzioni sbagliate sono scritte a mano, non generate: una soluzione
"sbagliata" generata da uno script sbaglierebbe insieme alla verifica e
il test passerebbe senza dire niente.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.tasks_curva import TASK_CURVA  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


# Le soluzioni sbagliate: ognuna e' sbagliata per un motivo diverso, e
# il motivo e' scritto perche' se un domani la "sbagliata" diventa
# giusta, il test non se ne accorge ma tu sì.
SBAGLIATE = {
    "code_l1": {
        "fib.py": "def fib(n):\n    if n < 2:\n        return 1\n    return fib(n-1) + fib(n-2)\n",
    },
    "code_l2": {
        # la divisione per zero: passa i due casi con i numeri
        "media.py": "def media(xs):\n    n = [x for x in xs if x is not None]\n"
                    "    return sum(n) / len(n)\n",
    },
    "code_l3": {
        # None davanti invece che in fondo. La prima versione di questa
        # "sbagliata" usava (v is None, v), che mette i None in fondo:
        # cio' che il compito chiede. Non era una soluzione sbagliata,
        # era giusta — e il test l'ha detto invece di passare.
        "ordina.py": "def ordina(xs):\n    return sorted(xs, key=lambda v: (v is not None, v))\n",
    },
    "reason_l2": {
            # Cy: la risposta che si scrive dimenticando che Ada ha gia' C.
            # Non e' irrilevante come sembra guardandola — e' l'errore vero,
            # quello che un modello fa contando i vincoli senza propagarli.
            "risposta.txt": "Cy\n",
        },
    "reason_l3": {
        # conta Cy come se avesse fatto B
        "risultato.json": '{"Ada": "2 1 0", "Bo": "1 1 1", "Cy": "0 1 0"}\n',
    },
    "extract_l2": {
        # divide sul separatore e perde i decimali con la virgola
        "totale.json": '{"somma": 120.5}\n',
    },
    "extract_l3": {
        # arrotonda a due decimali e non vede lo scarto
        "reporting.json": '{"esito": "coerente"}\n',
    },
    "write_l2": {
        # le sezioni ci sono, ma il tetto e' saltato
        "avviso.md": "## Cosa e' successo\nSi e' verificato un problema "
                      "imprevisto.\n\n## Cosa non fare\nNon tentare operazioni "
                      "manuali finche' non e' stato verificato.\n\n## Cosa fare\n"
                      "Attendere l'intervento del tecnico.\n",
    },
    # solo il primo dei tre: il caso in cui ci si ferma dopo averne
    # scritto uno. Non scrive nessun file, cosi' non coincide con la
    # soluzione giusta su nessun nome.
    "tool_l1": {},
    "tool_l2": {
        # riscritto ma con la riga vuota lasciata in mezzo
        "numeri.txt": "1\n2\n\n3\n4\n",
    },
}

GIUSTE = {
    "code_l1": {
        "fib.py": "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n"
                  "        a, b = b, a + b\n    return a\n"
                  "if __name__ == '__main__':\n    print(fib(10))\n",
    },
    "code_l2": {
        "media.py": "def media(xs):\n    n = [x for x in xs if x is not None]\n"
                    "    if not n:\n        return None\n    return sum(n) / len(n)\n",
    },
    "code_l3": {
        "ordina.py": "def ordina(xs):\n    n = [x for x in xs if x is not None]\n"
                     "    n.sort()\n    return n + [x for x in xs if x is None]\n",
    },
    # La risposta giusta e' Bo: Ada fa C, Bo non fa B, quindi Bo fa A.
    # Cy e' la risposta plausibile sbagliata — e' il nome che resta se
    # si dimentica che Ada ha gia' preso C.
    "reason_l2": {"risposta.txt": "Bo\n"},
    "reason_l3": {
        "risultato.json": '{"Ada": "2 1 0", "Bo": "1 1 1", "Cy": "1 0 0"}\n',
    },
    "extract_l2": {
        "ordini.csv": ("cliente;totale;data\n"
                       '"Rossi, Mario";120,50;2026-01-15\n'
                       "Bianchi;80,00;2026-01-15\n"
                       '"Verdi, Anna";200,25;2026-02-01\n'
                       "Neri;50,00;2026-02-01\n"),
        "totale.json": '{"somma": 450.75}\n',
    },
    "extract_l3": {
        "conto.csv": ("voce;importo\n"
                      "totale;100,00\n"
                      "dettaglio;40,00\n"
                      "dettaglio;60,03\n"),
        "reporting.json": '{"differenza": 0.03, "riga": 3}\n',
    },
    "write_l2": {
        "avviso.md": ("## Cosa e' successo\nUn tubo si e' rotto.\n\n"
                      "## Cosa non fare\nNon aprire la saracinesca.\n\n"
                      "## Cosa fare\nChiudere la saracinesca.\n"),
    },
    "tool_l1": {
        "uno/uno.txt": "uno\n", "due/due.txt": "due\n", "tre/tre.txt": "tre\n",
    },
    "tool_l2": {"numeri.txt": "1\n2\n3\n4\n"},
}


def scenario(task, file: dict) -> tuple[bool, str]:
    d = tempfile.mkdtemp()
    if task.setup:
        task.setup(d)
    for nome, contenuto in file.items():
        p = os.path.join(d, nome)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(contenuto)
    return task.verify(d)


print(f"[1] La curva: {len(TASK_CURVA)} task, livelli dichiarati nell'id")
ids = [t.id for t in TASK_CURVA]
check("gli id sono unici", len(set(ids)) == len(ids), str(ids))
check("ogni id ha il livello", all(
    any(t.id.endswith(f"_l{n}") for n in (1, 2, 3)) for t in TASK_CURVA),
    str([t.id for t in TASK_CURVA if not any(t.id.endswith(f"_l{n}") for n in (1,2,3))]))
cat = {}
for t in TASK_CURVA:
    cat.setdefault(t.category, []).append(t.id)
for c, ts in sorted(cat.items()):
    print(f"   {c:12} {' '.join(x.split('_')[-1] for x in ts)}")

print("\n[2] Ogni task ha una soluzione giusta, e passa")
for t in TASK_CURVA:
    g = GIUSTE.get(t.id)
    if g is None:
        check(f"{t.id}: soluzione giusta presente", False, "manca nel test")
        continue
    ok, det = scenario(t, g)
    check(f"{t.id}: la soluzione giusta passa", ok, det)

print("\n[3] Ogni task ha una soluzione sbagliata, e viene bocciata")
# Il passaggio che rende la curva una curva: se una soluzione
# ragionevemente sbagliata passasse, il task misurerebbe niente.
for t in TASK_CURVA:
    k = SBAGLIATE.get(t.id)
    if k is None:
        check(f"{t.id}: soluzione sbagliata presente", False, "manca nel test")
        continue
    ok, det = scenario(t, k)
    check(f"{t.id}: la soluzione sbagliata fallisce", not ok,
          f"PASSATA — il task non misura niente ({det[:70]})")

print("\n[4] Le soluzioni sbagliate sono davvero diverse dalle giuste")
for tid, sb in SBAGLIATE.items():
    gi = GIUSTE.get(tid, {})
    comune = set(sb) & set(gi)
    identiche = [n for n in comune if sb[n] == gi[n]]
    check(f"{tid}: le soluzioni non coincidono", not identiche, str(identiche))
    check(f"{tid}: la soluzione giusta esiste", bool(gi))



# ==========================================================================
# Il punteggio per livello
# ==========================================================================
print("\n[5] Il punteggio per livello risponde alla domanda giusta")
import orchestra.benchmark as B  # noqa: E402


def rr(task_id, ok, modello="m1"):
    return B.RunResult(model=modello, task_id=task_id, category="code", passed=ok,
                       detail="", seconds=1.0, prompt_tokens=1, completion_tokens=1,
                       cost_usd=0.0, tool_calls=1, tool_errors=0, stopped_because="fine",
                       unusable=False)


# Due modelli con lo STESSO punteggio complessivo, ma con limiti
# diversi: il primo sbaglia subito, il secondo solo al livello 3. Un
# punteggio unico li mette sulla stessa riga — e sono due modelli da
# usare in modo opposto.
# Due modelli con lo stesso totale e una distribuzione opposta: il
# primo sbaglia subito e regge il livello 3, il secondo regge i primi
# due e crolla all'ultimo. Un punteggio unico li mette sulla stessa
# riga, e sono due modelli da usare in modo opposto.
a = [rr("code_l1", False, "debole"), rr("code_l2", False, "debole"),
     rr("code_l3", True, "debole")]
b = [rr("code_l1", True, "solido"), rr("code_l2", False, "solido"),
     rr("code_l3", False, "solido")]
pa = B.per_livello(a)["debole"]["per_livello"]
pb = B.per_livello(b)["solido"]["per_livello"]
check("stesso totale, punteggi diversi",
      sum(pa[k]["passati"] for k in pa) == sum(pb[k]["passati"] for k in pb),
      "il caso non parte da pari")
check("ma 'debole' ha il buco all'inizio",
      pa["l1"]["score"] == 0.0 and pa["l3"]["score"] == 1.0, str(pa))
check("e 'solido' all'inizio e' pieno",
      pb["l1"]["score"] == 1.0 and pb["l3"]["score"] == 0.0, str(pb))
check("la base e' dichiarata per ogni livello",
      all("totali" in v and "passati" in v for v in pa.values()), str(pa))
check("e un task senza livello va in '?', non sparisce",
      "?" in B.per_livello([rr("vecchio_task", True, "x")])["x"]["per_livello"])

# Un modello che il provider riserva ad altri client non entra: e' una
# misura che non e' sua, e misurerebbe una soglia, non una capacita'
def riservato_run(task_id):
    r = rr(task_id, False, "riservato")
    r.unusable = True          # il provider lo riserva ad altri client
    return r


riservato = B.per_livello([riservato_run("code_l1"), riservato_run("code_l2")])
check("un modello riservato non ha livelli", "riservato" not in riservato,
      str(riservato))
check("e un modello normale accanto a lui c'e' ancora",
      len(B.per_livello([riservato_run("code_l1"), rr("code_l1", True, "normale")])) == 1,
      "il filtro ha mangiato anche quello che si poteva misurare")

print("\n[6] I task nuovi sono nel benchmark e non sostituiscono gli altri")
tutti = B.tasks_for()
vecchi = {"reason_logic", "reason_sched", "code_fib", "write_struttura"}
check("i task vecchi ci sono ancora", vecchi <= {t.id for t in tutti},
      str(vecchi - {t.id for t in tutti}))
check("e la curva e' dentro", len([t for t in tutti if t.id.endswith(("_l1", "_l2", "_l3"))]) == 10)
check("il totale e' cresciuto, non sostituito", len(tutti) >= 30, str(len(tutti)))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
