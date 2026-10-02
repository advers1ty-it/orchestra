import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.verificatori_js import esegui_node, node_disponibile, v_esegui_js  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def scenario(codice, prove, nome="sol.js", funzione="media"):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, nome), "w", encoding="utf-8") as f:
        f.write(codice)
    return v_esegui_js(nome, funzione, prove)(d)


print("[0] Node c'è")
check("node è installato", node_disponibile())

GIUSTO = """
function media(xs) {
  const n = xs.filter(x => x !== null && x !== undefined);
  if (n.length === 0) return null;
  return n.reduce((a, b) => a + b, 0) / n.length;
}
"""

SBAGLIATO = """
function media(xs) {
  const n = xs.filter(x => x !== null && x !== undefined);
  return n.reduce((a, b) => a + b, 0) / n.length;
}
"""

MEZZO = """
function media(xs) {
  const n = xs.filter(x => x !== null && x !== undefined);
  if (n.length === 0) return 0;
  return n.reduce((a, b) => a + b, 0) / n.length;
}
"""

PROVE = [([[1, 2, 3]], 2.0), ([[None, 5]], 5.0), ([[]], None), ([[None, None]], None)]

print("\n[1] Il codice giusto passa")
if node_disponibile():
    ok, det = scenario(GIUSTO, PROVE)
    check("tutte le prove passano", ok, det)

    print("\n[2] E quello sbagliato viene bocciato")
    ko, det = scenario(SBAGLIATO, PROVE)
    check("il caso lista vuota prende il buggy", not ko,
          "il codice con NaN e' passato: il verificatore non verifica")
    check("e il messaggio dice quale prova", "prove sbagliate" in det, det)
    mezzo, _ = scenario(MEZZO, PROVE)
    check("il 0 al posto di None prende il mezzo", not mezzo,
          "0 invece di null: la prova esiste per questo")

print("\n[3] Quello che non regge")
if node_disponibile():
    d = tempfile.mkdtemp()
    ok, det = v_esegui_js("mancante.js", "media", PROVE)(d)
    check("distingue il file mancante", not ok and "non esiste" in det, det)

    ciclo = "function media(xs) {\n  while (true) {}\n}\n"
    ok2, det2 = scenario(ciclo, PROVE)
    check("un ciclo infinito non blocca tutto", not ok2, det2)
    check("e lo dice", "non termina" in det2 or "timeout" in det2.lower(), det2)

    rotto = "function media(xs)\n  return 1;\n}\n"
    ok3, det3 = scenario(rotto, PROVE)
    check("un errore di sintassi e' un fallimento pulito", not ok3, det3)
    check("e lo nomina", "caricamento" in det3 or "SyntaxError" in det3, det3)

    # una funzione che non c'è
    mancante = "function altra() { return 1; }\n"
    ok4, det4 = scenario(mancante, PROVE)
    check("una funzione assente e' un fallimento, non uno zero",
          not ok4 and "manca" in det4, det4)

print("\n[4] module.exports viene riconosciuto")
if node_disponibile():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "m.js"), "w", encoding="utf-8") as f:
        f.write("module.exports = function(xs) { return xs.length; }\n")
    out = v_esegui_js("m.js", "media", [([[1, 2]], 2)])(d)
    # il nome non combacia ma l'export c'e': l'alternativa e' accettata
    ok, det = out
    check("un export anonimo funziona comunque", ok, det)

print("\n[5] Il confronto dei numeri")
import orchestra.verificatori_js as VJ  # noqa: E402
check("0.30000000000000004 vale 0.3", VJ._uguale(0.30000000000000004, 0.3))
check("ma 3 e '3' no", not VJ._uguale("3", 3))
check("e le liste si confrontano elemento a elemento", VJ._uguale([1, 2.0], [1.0, 2]))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)