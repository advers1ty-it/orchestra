"""Il popup del selettore: cerca, sceglie, e non cambia niente per errore.

Tre rischi, e uno dei tre è quello che costa di piu'.

1. Il popup scrive il value del <select> ma non spara il `change`. Il
   select sembra aggiornato e il modello NON cambia: la chat continua a
   rispondere col vecchio e non c'è nessun errore. E' il difetto più
   insidioso di un menu fatto a mano, perché metà del lavoro c'è.

2. ESC chiude ma lascia il value cambiato. Un menu che al primo refuso
   ti cambia il modello in uso costa un turno di lavoro perso, e non
   capita una volta sola.

3. Il cercatore filtra ma il contatore non torna. Quattro modelli che
   contano come "nessun risultato", o venti che restano visibili sotto
   un filtro che ne mostra cinque.

Il test gira sul bundle vero, in un DOM finto, senza browser.
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "orchestra", "web")

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# --------------------------------------------------------------------------
HARNESS = r"""
// Un DOM finto, ma solo quello che il popup tocca. Niente di piu':
// se il test costruisce un DOM che non somiglia a quello vero,
// verifica se stesso invece del codice.
class El {
  constructor(tag) {
    this.tagName = (tag || "div").toUpperCase();
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.classList = {
      _s: new Set(),
      add: (...c) => c.forEach((x) => this.classList._s.add(x)),
      remove: (...c) => c.forEach((x) => this.classList._s.delete(x)),
      contains: (c) => this.classList._s.has(c),
    };
    this.textContent = "";
    this.value = "";
    this.disabled = false;
  }
  appendChild(n) { this.children.push(n); n._padre = this; return n; }
  // Si stacca davvero dal padre. Con remove() vuoto il popup
  // resterebbe fra i figli e il test direbbe "non si e' chiuso" per
  // un motivo che e' dello stub, non del codice.
    remove() {
    if (this._padre) {
      const i = this._padre.children.indexOf(this);
      if (i >= 0) this._padre.children.splice(i, 1);
      }
    }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  getBoundingClientRect() { return { left: 0, top: 0, bottom: 20, right: 100 }; }
  addEventListener(ev, fn) { (this._ev = this._ev || {})[ev] = fn; }
  fire(ev, init) {
    if (!this._ev || !this._ev[ev]) return;
    const e = Object.assign({ type: ev, preventDefault() {},
                             stopPropagation() {} }, init || {});
    this._ev[ev](e);
  }
  dispatchEvent(ev) { if (this._ev && this._ev[ev.type]) this._ev[ev.type](ev); return true; }
  focus() {}
  scrollIntoView() {}
  setAttribute() {}
}
const elementi = {};
global.document = {
  hidden: false,
  getElementById: (id) => elementi[id] || null,
  createElement: (tag) => new El(tag),
  querySelector: (sel) => {
    if (sel === ".mp-wrap") return global.__mpWrap;
    return null;
  },
  addEventListener: () => {},
};
global.window = global;
global.__mpWrap = new El("div");
global.mpWrap = global.__mpWrap;
global.__log = [];
global.on = (t, ev, fn) => { t.addEventListener(ev, fn); };
global.el = (tag, cls, text) => { const e = new El(tag); if (cls) e.className = cls; e.textContent = text || ""; return e; };
global.$ = (id) => elementi[id] || null;
global.busy = false;
global.print = console.log;
var R_OUT, R_TUTTI, R_CHIUSO, R_OK = false;

global.punteggioPerScope = () => "";

// ---- il <select> reale, con dentro i modelli che il popup elenca
const option = (val, text) => {
  const o = new El("option");
  o.value = val;
  o.text = text;
  o.textContent = text;
  return o;
};
const select = new El("select");
select.options = [
  option("aaa/modello-uno", "modello-uno  88  262k · free"),
  option("bbb/modello-due", "modello-due  62  512k · free"),
  option("ccc/modello-tre", "modello-tre  —  1008k · free"),
  option("ddd/modello-quattro", "modello-quattro  95  66k · $2/1M"),
];
select.value = "aaa/modello-uno";
select.disabled = false;
let changeCount = 0;
select._ev = {};
elementi["model-pick"] = select;
// Il bottone e l'etichetta: ora il popup nasce da un bottone, non dal
// select. E il test deve esistere anche per quelli, altrimenti il
// "custom vero" viene verificato solo a meta'.
const bottone = new El("button");
bottone.disabled = false;
bottone.setAttribute = () => {};
elementi["model-btn"] = bottone;
elementi["model-label"] = new El("span");
global.modelPick = select;   // il popup lo cerca per nome

// punteggi: solo due dei quattro sono misurati
globalThis.modelliPerId = {
  "aaa/modello-uno": { punteggio_unico: { punteggio: 88 } },
  "bbb/modello-due": { punteggio_unico: { punteggio: 62 } },
  "ccc/modello-tre": {},
  "ddd/modello-quattro": { punteggio_unico: { punteggio: 95 } },
};

// change: conta le volte, e cambia davvero il modello in uso
select.addEventListener("change", () => { changeCount++; select.value = select.value; });

__BUNDLE_VAI__
R_OUT = {};
try {
  // --- 1. APRE E CONTENUTO
  mpApri();
  const pop = global.__mpWrap.children[global.__mpWrap.children.length - 1];
  R_OUT.apre = !!pop;
  R_OUT.voci = mpVoci.length;

  // --- 2. IL CERCATORE FILTRA
  const cerca = pop.children[0];
  cerca.value = "due";
  cerca.fire("input", {});
  let visibili = mpVoci.filter((v) => v.nodo.style.display !== "none").length;
  R_OUT.filtroDue = visibili;

  cerca.value = "";
  cerca.fire("input", {});
  visibili = mpVoci.filter((v) => v.nodo.style.display !== "none").length;
  R_TUTTI = visibili;

  // filtro che non trova niente
  cerca.value = "zzzz";
  cerca.fire("input", {});
  R_OUT.zero = mpVoci.filter((v) => v.nodo.style.display !== "none").length;
  cerca.value = "";
  cerca.fire("input", {});

  // --- 3. IL PUNTEGGIO PRESENTE SOLO SE MISURATO
  R_OUT.badge = mpVoci.map((v) => {
    const b = v.nodo.children[0];
    return b ? b.textContent : null;
  });

  // --- 4. LA SCELTA SCRIVE IL VALUE E SPARA IL CHANGE
  const prima = select.value;
  mpScegli("ddd/modello-quattro");
  R_OUT.changeSparato = changeCount > 0;
  R_OUT.valueDopo = select.value;
  R_OUT.valuePrima = prima;
  R_CHIUSO = !global.__mpWrap.children.some((n) => n.classList && n.classList.contains("mp-pop"));
  // "Il popup si e' chiuso" si vede dal DOM, non leggendo `mpAperto`:
  // quello e' un `let` del bundle, vive nel suo scope e da qui non si
  // vede. Un test che lo leggesse dal fuori leggerebbe una variabile
  // sua, sempre undefined, e direbbe "non si chiude" per sempre.
  // La domanda vera e' una sola: nel contenitore resta un popup?

  // --- 5. ESC CHIUDE SENZA CAMBIARE NULLA
  mpApri();
  const vprima = select.value;
  const cprima = changeCount;
  const cerca2 = global.__mpWrap.children[global.__mpWrap.children.length - 1].children[0];
  cerca2.fire("keydown", { key: "Escape", preventDefault: () => {} });
  R_OUT.escChiude = !mpAperto;
  R_OUT.escNonCambia = (select.value === vprima) && (changeCount === cprima);

  // --- 6. FRECCE + ENTER
  mpApri();
  const cerca3 = global.__mpWrap.children[global.__mpWrap.children.length - 1].children[0];
  cerca3.fire("keydown", { key: "ArrowDown", preventDefault: () => {} });
  cerca3.fire("keydown", { key: "ArrowDown", preventDefault: () => {} });
  const c3 = changeCount;
  cerca3.fire("keydown", { key: "Enter", preventDefault: () => {} });
  R_OUT.enterSceglie = changeCount > c3;

  // --- 7. UNA SCELTA VUOTA NON FA NULLA
  const c4 = changeCount;
  mpScegli("");
  R_OUT.vuotoNonSpara = changeCount === c4;

  R_OK = true;
} catch (e) {
  R_OUT.errore = String(e) + "\n" + (e.stack || "");
  R_OK = false;
}
print(JSON.stringify({ok: R_OK, r: R_OUT,
  tutti: R_TUTTI || 0, chiuso: R_CHIUSO}));
"""


def main():
    files = ["core.js", "panels.js", "modelpick.js"]
    src = []
    for n in files:
        with open(os.path.join(WEB, n), encoding="utf-8") as fh:
            src.append(fh.read())
    # solo il popup e i suoi aiuti: gli altri file hanno bisognino del
    # DOM vero e non c'entrano qui
    # Solo modelpick.js, NON core.js.
    #
    # core.js porta dentro la sua `el()` reale, che usa
    # document.createElement: caricandola, ridefiniva il mio stub con
    # un'implementazione che parla col DOM finto a meta' — e cinque
    # check tornavano rossi senza dire niente sul codice.
    #
    # Gli aiuti che il popup usa (`el`, `on`) li mette gia' lo stub,
    # e sono gli stessi che il bundle vero usa: un test che carica
    # l'helper REALE finisce per verificare l'helper e non il popup.
    solo = [s for s in src if "mpApri" in s]
    if not solo:
        print("  nessun sorgente col popup")
        sys.exit(1)
    bundle = "\n;\n".join(solo)

    # Il bundle va DOPO gli stub del DOM e PRIMA delle chiamate: le
    # dichiarazioni `let` del bundle sono in zona morta finche' non
    # arrivano a esecuzione, e un mpApri() chiamato prima leverebbe
    # un ReferenceError che parla di una variabile e non dell'ordine.
    contenuto = HARNESS.replace("__BUNDLE_VAI__", bundle)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(contenuto)
        path = fh.name

    try:
        out = subprocess.run(["node", path], capture_output=True, text=True,
                             timeout=60)
        raw = [l for l in out.stdout.split("\n") if l.strip().startswith("{")]
        if not raw:
            print("  nessun risultato dal nodo")
            print(out.stderr[-600:])
            sys.exit(1)
        d = json.loads(raw[-1])
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if not d.get("ok"):
        check("il popup gira", False, d["r"].get("errore", "")[:200])
    else:
        check("il popup gira", True)

    r = d.get("r", {})

    print("\n[1] Si apre e elenca")
    check("si apre", r.get("apre") is True)
    check("una voce per modello", r.get("voci") == 4, str(r.get("voci")))

    print("\n[2] Il badge c'e' solo dove c'e' il dato")
    badge = r.get("badge") or []
    check("il modello misurato mostra il numero", badge[:1] == ["88"], str(badge[:1]))
    check("il non misurato mostra un trattino", badge[2:3] == ["—"], str(badge[2:3]))
    check("gli altri due hanno il numero", badge[1:2] == ["62"], str(badge[1:2]))

    print("\n[3] Il cercatore filtra davvero")
    check("filtra per nome", r.get("filtroDue") == 1, str(r.get("filtroDue")))
    check("tornano tutti senza filtro", d.get("tutti") == 4, str(d.get("tutti")))
    check("un filtro senza risultati lascia zero", r.get("zero") == 0,
          str(r.get("zero")))

    print("\n[4] Scegliere cambia il modello E avvisa")
    # Il punto piu' importante: se il change non parte, il select mostra
    # un modello e il server continua a rispondere con un altro.
    check("il change parte", r.get("changeSparato") is True,
          "il select si aggiorna ma nessuno riceve la notifica")
    check("e il value cambia", r.get("valueDopo") == "ddd/modello-quattro",
          str(r.get("valueDopo")))
    check("e il popup si chiude", d.get("chiuso") is True, str(d.get("chiuso")))

    print("\n[5] ESC chiude senza cambiare niente")
    check("chiude", r.get("escChiude") is True)
    check("e NON cambia il modello", r.get("escNonCambia") is True,
          "ESC ha cambiato il modello in uso")

    print("\n[6] Frecce ed Enter")
    check("Enter dopo le frecce sceglie", r.get("enterSceglie") is True)

    print("\n[7] Una scelta vuota non fa nulla")
    check("non spara il change", r.get("vuotoNonSpara") is True)

    print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
    if FAIL:
        print("FALLITI:", FAIL)
    sys.exit(1 if FAIL else 0)


main()