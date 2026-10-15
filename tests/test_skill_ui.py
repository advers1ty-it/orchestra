"""Il pannello Skill: API e DOM.

Due livelli, e il secondo e' quello che conta. L'API puo' rispondere
tutto quello che deve e il pannello restare muto — e' gia' successo
con i selettori disabilitati e con ready=true che non abilitava
niente. Per questo il DOM si esamina davvero, in Node, e si controlla
che le righe escano e che i filtri cambino la lista.

Il bundle si carica come nel browser vero: core, panels, main. Se si
testasse solo panels.js, si perderebbe esattamente il difetto che si
vuole trovare.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = 8737
BASE = f"http://127.0.0.1:{PORT}"
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def post(body, path="/api/skill"):
    r = urllib.request.Request(BASE + path, json.dumps(body).encode(),
                               {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return f.status, json.loads(f.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


print("[1] Il server e' in piedi")
try:
    with urllib.request.urlopen(BASE + "/api/state", timeout=10) as f:
        check("risponde", f.status == 200)
except Exception as e:
    check("risponde", False, f"{type(e).__name__}: {e} — il server deve essere avviato")
    print("\nServer non raggiungibile: avvialo con "
          "python3 -m orchestra.cli web --no-browser")
    sys.exit(1)

print("\n[2] L'elenco")
stato, d = post({"azione": "elenca"})
check("va", stato == 200, f"HTTP {stato}: {str(d)[:100]}")
for campo in ("totale", "scaricate", "generate", "categorie",
              "lista_scaricate", "lista_generate", "nel_prompt_max"):
    check(f"c'è il campo {campo}", campo in d, str(list(d))[:110])
check("il totale torna con le liste",
      d.get("totale") == len(d.get("lista_scaricate", []))
      + len(d.get("lista_generate", [])),
      f"{d.get('totale')} vs {len(d.get('lista_scaricate', []))}"
      f"+{len(d.get('lista_generate', []))}")
check("scaricate + generate = totale",
      d.get("scaricate", 0) + d.get("generate", 0) == d.get("totale"),
      f"{d.get('scaricate')}+{d.get('generate')} vs {d.get('totale')}")
prima = (d.get("lista_scaricate") or [{}])[0]
for campo in ("nome", "descrizione", "categoria", "origine", "prove",
              "con_prove", "percorso"):
    check(f"ogni voce ha {campo}", campo in prima, str(list(prima))[:110])
check("il percorso è relativo, non assoluto",
      not str(prima.get("percorso", "")).startswith(("C:", "/", "\\")),
      str(prima.get("percorso"))[:80])
check("il numero nel prompt è reale",
      isinstance(d.get("nel_prompt_max"), int) and d["nel_prompt_max"] > 0,
      str(d.get("nel_prompt_max")))

print("\n[3] Un'azione sconosciuta non passa")
stato, d2 = post({"azione": "aaa"})
check("rifiutata", stato == 400, f"HTTP {stato}")
check("e lo dice quale", "azione" in d2.get("error", ""), str(d2)[:100])
stato3, d3 = post({"azione": "importa"})
check("importa senza cartella rifiutata", stato3 == 400, f"HTTP {stato3}")
check("e chiede la cartella", "cartella" in d3.get("error", ""), str(d3)[:100])
stato4, d4 = post({"azione": "cancella", "nome": "non-esiste-affatto"})
check("cancellare una inesistente è rifiutata", stato4 == 400, f"HTTP {stato4}")

print("\n[4] Importare da uno store")
import shutil
import re
import tempfile
store = tempfile.mkdtemp(prefix="store-ui-")
for n, cat in (("prova-ui-una", "alpha"), ("prova-ui-due", "beta")):
    p = os.path.join(store, cat, n)
    os.makedirs(p, exist_ok=True)
    open(os.path.join(p, "SKILL.md"), "w", encoding="utf-8").write(
        f"---\nname: {n}\ndescription: Skill di prova {n}.\n---\n\n"
        "Procedura di prova. " * 30)
stato, d5 = post({"azione": "importa", "cartella": store, "categoria": "prova"})
check("importa", stato == 200 and d5.get("ok"), f"HTTP {stato}: {str(d5)[:90]}")
check("dice quante", d5.get("importate") == 2, str(d5.get("importate")))
check("e i nomi", set(d5.get("nomi", [])) == {"prova-ui-una", "prova-ui-due"},
      str(d5.get("nomi")))
check("l'elenco torna aggiornato",
      any(s["nome"] == "prova-ui-una" for s in d5["elenco"]["lista_scaricate"]),
      "non nell'elenco")
check("con la categoria giusta",
      any(s["nome"] == "prova-ui-una" and "prova" in s["categoria"]
          for s in d5["elenco"]["lista_scaricate"]),
      str([(s["nome"], s["categoria"]) for s in
           d5["elenco"]["lista_scaricate"] if "prova-ui" in s["nome"]]))

print("\n[5] Aprire una skill")
try:
    with urllib.request.urlopen(
            BASE + "/api/skill/file?nome=prova-ui-una", timeout=20) as f:
        fd = json.loads(f.read())
    check("il testo c'è", len(fd.get("contenuto", "")) > 100,
          str(len(fd.get("contenuto", ""))))
    check("il nome c'è", fd.get("nome") == "prova-ui-una", str(fd.get("nome")))
    check("la lista degli allegati c'è", isinstance(fd.get("allegati"), list))
except urllib.error.HTTPError as e:
    check("il testo c'è", False, f"HTTP {e.code}: {e.read()[:80]}")
try:
    urllib.request.urlopen(BASE + "/api/skill/file?nome=inesistente", timeout=10)
    check("una inesistente è rifiutata", False, "accettata")
except urllib.error.HTTPError as e:
    check("una inesistente è rifiutata", e.code == 404, f"HTTP {e.code}")

print("\n[6] Cancellare va nel cestino, non via")
radice_skill = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "skills")
stato, d6 = post({"azione": "cancella", "nome": "prova-ui-due"})
check("cancella", stato == 200 and d6.get("ok"), f"HTTP {stato}: {str(d6)[:90]}")
check("non c'è più nell'elenco",
      not any(s["nome"] == "prova-ui-due" for s in d6["elenco"]["lista_scaricate"]))
cestini = []
for dp, dirs, _f in os.walk(radice_skill):
    if os.path.basename(dp) == ".cestino":
        cestini.append(dp)
check("i file sono da qualche parte", cestini, "nessun cestino")
if cestini:
    # Ogni cancellazione ha il suo timestamp, quindi la skill sta sotto
    # uno dei sotto-cartelle: si guarda sotto, non al primo livello. Il
    # check guardava list(cestino) e trovava solo i timestamp, e non
    # diceva perche' quello che cercava non c'era.
    trovato = False
    for cestino in cestini:
        for ts in os.listdir(cestino):
            dentro = os.path.join(cestino, ts)
            if os.path.isdir(dentro) and "prova-ui-due" in os.listdir(dentro):
                trovato = True
    check("e dentro al cestino c'è la skill", trovato,
          str([os.listdir(c) for c in cestini])[:110])

print("\n[7] Il DOM: il pannello esiste e si disegna")
# Il bundle gira davvero, in Node, con il DOM finto che gli altri test
# usano gia'. I tre file concatenati nell'ordine del bundle: se si
# testasse solo panels.js, si perderebbe esattamente il difetto che si
# vuole trovare -- una funzione definita e mai chiamata, che si vede
# solo quando tutto il bundle e' insieme.
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ordine import ORDER  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
joined = "\n;\n".join(
    open(os.path.join(ROOT, "orchestra", "web", n), encoding="utf-8").read()
    for n in ORDER)
harness = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "_dom_provider.js"), encoding="utf-8").read()

probe = """
(async () => {
  const OUT = { errori: [] };
  // Quanti handler sono davvero agganciati. Il bundle chiama
  // on($("...")) e il DOM finito registra: qui si conta, invece di
  // fidarsi del testo del sorgente.
  OUT.agganciati = [];
  for (const id of ["skill-ricarica", "skill-importa", "skill-filtro",
                    "opz-tab-modello", "opz-tab-skill", "opz-tab-servizi",
                    "opz-tab-permessi", "opz-tab-gratis", "opzioni-nav"]) {
    const e = document.getElementById(id);
    OUT.agganciati.push([id, !!(e && e._handlers &&
                                  Object.keys(e._handlers).length)]);
  }

  OUT.fn = {
    caricaSkill: typeof caricaSkill,
    disegnaSkill: typeof disegnaSkill,
    collegaSkill: typeof collegaSkill,
    mostraSezione: typeof mostraSezione,
    collegaSezioni: typeof collegaSezioni,
  };

  // elenco finto: una generata con prove, due scaricate
  try {
    skillDati.scaricate = [
      { nome: "pdf-una", descrizione: "Estrae tabelle", categoria: "prod",
        origine: "scaricata", prove: 0, con_prove: false, usata: 2,
        caratteri: 1200, percorso: "percorso/prod/pdf-una/SKILL.md" },
      { nome: "apk-due", descrizione: "Compila un APK", categoria: "dev",
        origine: "scaricata", prove: 0, con_prove: false, usata: 0,
        caratteri: 900, percorso: "percorso/dev/apk-due/SKILL.md" },
    ];
    skillDati.generate = [
      { nome: "mio-metodo", descrizione: "Quello che ho fatto io",
        categoria: "generata", origine: "generata", prove: 2,
        con_prove: true, usata: 1, caratteri: 800,
        percorso: "generate/mio-metodo/SKILL.md" },
    ];
    skillDati.categorie = [{ nome: "prod", skill: 1 }, { nome: "dev", skill: 1 }];
    skillDati.totale = 3;
    skillDati.scaricate_n = 2;
    skillDati.generate_n = 1;
    skillDati.nel_prompt_max = 3;

    disegnaSkill();
    const righe = (id) => {
      const c = document.getElementById(id);
      if (!c) return -1;
      // Le schede contano, la riga "N su M" no: e' un contatore, non un
      // risultato. Contare i figli grezzi faceva fallire il filtro
      // proprio quando funzionava (1 scheda + 1 contatore = 2 nodi).
      return c.children.filter((x) => String(x.className || "").split(" ").includes("skill-carta")).length;
    };
    OUT.scaricate = righe("skill-scaricate");
    OUT.generate = righe("skill-generate");
    OUT.categorie = righe("skill-categorie");
    OUT.riepilogo = document.getElementById("skill-riepilogo").textContent;

    const f = document.getElementById("skill-filtro");
    f.value = "pdf";
    disegnaSkill();
    OUT.dopoFiltro = righe("skill-scaricate");
    f.value = "";
    disegnaSkill();
    OUT.ripristinato = righe("skill-scaricate");
    OUT.conSegno = document.getElementById("skill-generate").textContent.includes("+");

    skillDati.generate = [];
    disegnaSkill();
    OUT.vuotoTesto = document.getElementById("skill-generate").textContent;
  } catch (e) { OUT.erroreSkill = String(e); }

  // --- le sezioni ---------------------------------------------------
  // La parte nuova del pannello: cinque sezioni, una per volta, e il
  // cambio deve funzionare cliccando, non solo se la funzione esiste.
  const visibile = (n) => {
    const e = document.getElementById("opz-sez-" + n);
    return e ? e.getAttribute("hidden") === null : null;
  };
  OUT.sezioni = ["modello", "skill", "servizi", "permessi", "gratis"]
    .map((n) => [n, visibile(n)]);

  const attiva = () => {
    const t = document.querySelector(".opzioni-tab.attiva");
    return t ? t.id : null;
  };
  try {
    OUT.attivaAllInizio = attiva();
    // un click vero sulla tab
    document.getElementById("opz-tab-skill").fire("click");
    OUT.dopoClickSkill = [visibile("modello"), visibile("skill"),
                          visibile("servizi")];
    OUT.tabAttiva = attiva();
    // e un click su una terza
    document.getElementById("opz-tab-permessi").fire("click");
    OUT.dopoClickPermessi = [visibile("skill"), visibile("permessi")];
    OUT.attivaPermessi = attiva();
  } catch (e) { OUT.erroreSezioni = String(e); }

  // una sezione inesistente non deve lasciare tutto nascosto
  try {
    mostraSezione("non-esiste");
    OUT.dopoInesistente = ["modello", "skill", "permessi"].map(visibile);
  } catch (e) { OUT.erroreInesistente = String(e); }

  console.log("SKILLUI" + JSON.stringify(OUT));
})();
"""

f = tempfile.mktemp(suffix=".js")
with open(f, "w", encoding="utf-8") as fh:
    fh.write(harness + "\n" + joined + "\n" + probe)
proc = subprocess.run(["node", f], capture_output=True, text=True, timeout=90)
try:
    os.unlink(f)
except OSError:
    pass

if proc.returncode != 0:
    check("il bundle gira in Node", False, proc.stderr[-300:])
else:
    check("il bundle gira in Node", True)
    riga = [l for l in proc.stdout.splitlines() if l.startswith("SKILLUI")]
    if not riga:
        check("il probe ha risposto", False, proc.stdout[-200:])
    else:
        o = json.loads(riga[-1][7:])
        for chiave in ("erroreSkill", "erroreSezioni", "erroreInesistente"):
            if o.get(chiave):
                check("nessun errore nel probe", False, o[chiave][:150])
        check("mostraSezione esiste", o["fn"].get("mostraSezione") == "function", str(o["fn"]))
        check("collegaSezioni esiste", o["fn"].get("collegaSezioni") == "function", str(o["fn"]))

        # il disegno
        check("tre righe disegnate", o.get("scaricate") == 2, f"scaricate={o.get('scaricate')}")
        check("la generata ha la sua riga", o.get("generate") == 1, f"generate={o.get('generate')}")
        check("il riepilogo conta", "3" in str(o.get("riepilogo", "")), str(o.get("riepilogo"))[:80])
        check("il filtro restringe", o.get("dopoFiltro") == 1, f"dopo filtro={o.get('dopoFiltro')}")
        check("e si ripristina", o.get("ripristinato") == 2, f"ripristinato={o.get('ripristinato')}")
        check("la generata porta il segno +", bool(o.get("conSegno")))
        check("il vuoto spiega, non tace", len(str(o.get("vuotoTesto", ""))) > 30)

        # Gli handler registrati davvero: se uno di questi e' falso,
        # il pulsante non fa niente e la pagina sembra lenta.
        for id_, ok_ in (o.get("agganciati") or []):
            check(f"{id_} ha handler agganciato", bool(ok_),
                  "nessun listener registrato")

        # le sezioni
        sez = dict(o.get("sezioni") or [])
        check("una sezione per voce", len(sez) == 5, str(o.get("sezioni")))
        check("all'inizio e' visibile solo Modello",
              sez.get("modello") is True and sez.get("skill") is False
              and sez.get("gratis") is False, str(sez))
        check("la tab attiva e' quella giusta",
              o.get("attivaAllInizio") == "opz-tab-modello",
              str(o.get("attivaAllInizio")))
        d = o.get("dopoClickSkill") or []
        check("il click apre la sezione giusta",
              len(d) == 3 and d[1] is True and d[0] is False and d[2] is False, str(d))
        check("e la tab attiva segue",
              o.get("tabAttiva") == "opz-tab-skill", str(o.get("tabAttiva")))
        p2 = o.get("dopoClickPermessi") or []
        check("il secondo click apre Permessi",
              len(p2) >= 2 and p2[0] is False and p2[1] is True, str(p2))
        check("e la tab attiva e' Permessi",
              o.get("attivaPermessi") == "opz-tab-permessi",
              str(o.get("attivaPermessi")))
        ini = o.get("dopoInesistente") or []
        check("una sezione inesistente non nasconde tutto",
              any(v is True for v in ini), str(ini))

# I nomi che questo test usa devono esistere nell'HTML vero.
#
# Il pannello Opzioni si e' rotto due volte per un nome scritto a mano:
# `opz-tab-modelo` invece di `opz-tab-modello`, e la sezione `modelo`
# invece di `modello`. In entrambi i casi tredici check fallivano
# insieme e sembrava un problema di logica delle tab: era una lettera,
# in tre punti, in due file, e nessuno dei due lo dichiarava.
#
# Adesso i nomi si leggono dall'HTML, e questo check fallisce se un
# domani ne sposta uno senza aggiornare i test: il messaggio dice
# quale, e quale c'era.
print("\n[9] I nomi che il test usa esistono nell'HTML")
_html = open(os.path.join(ROOT, "orchestra", "web", "index.html"),
              encoding="utf-8").read()
_nomi_usati = ("modello", "skill", "servizi", "permessi", "gratis", "cestino")
for _n in _nomi_usati:
    check(f"data-sez=\"{_n}\" esiste nell'HTML",
          f'data-sez="{_n}"' in _html,
          "il test lo cerca e l'HTML non lo ha: o il nome e' cambiato "
          "dall'ultimo aggiornamento, o il test indovina")
check("l'id della tab modello e' opz-tab-modello",
      'id="opz-tab-modello"' in _html,
      "usato dai check come opz-tab-modello: se qui c'e' un altro "
      "nome, i tredici check del pannello falliscono senza dire perche'")

print("\n[8] Gli elementi del pannello sono nell'HTML")
html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "orchestra", "web", "index.html"), encoding="utf-8").read()
for el in ("skill-riepilogo", "skill-cartella", "skill-importa", "skill-ricarica",
           "skill-categorie", "skill-generate", "skill-scaricate",
           "skill-filtro", "skill-vista"):
    check(f"#{el} c'è", f'id="{el}"' in html, el)
# e i listener ci sono, senza i quali i pulsanti sono inerti: e' il
# difetto dei selettori, che erano disabilitati perche' nessuno li
# guardava
js_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "orchestra", "web", "panels.js"), encoding="utf-8").read()
# Non si guarda la sorgente perche' "la stringa c'e'" non vuol dire
# "l'handler e' agganciato": il difetto era esattamente quello —
# on("skill-ricarica", ...) invece di on($("skill-ricarica"), ...).
# La stringa c'era nel file, il pulsante no. Qui si conta cosa passa
# davvero al DOM, e piu' in basso gli handler vengono contati dopo
# che il bundle e' girato.
check("skill-ricarica ha un handler sull'elemento",
      any('on($("skill-ricarica")' in l for l in js_src.splitlines()),
      "nessun on() sull'elemento")
check("skill-importa ha un handler sull'elemento",
      any('on($("skill-importa")' in l for l in js_src.splitlines()),
      "nessun on() sull'elemento")
check("il filtro ha un handler", "skill-filtro" in js_src and "input" in js_src)
check("e collegaSkill è chiamata", "collegaSkill();" in js_src,
      "definita ma mai chiamata")
check("e anche collegaSezioni", "collegaSezioni();" in js_src,
      "definita ma mai chiamata")
# la barra laterale: cinque voci, tutte con id e data-sez, altrimenti
# il DOM finto non le trova e il test misurerebbe un pannello vuoto
# L'elenco delle sezioni viene letto dall'HTML, non scritto a mano.
# Erano cinque scritte a mano, e sono sei: c'è anche il cestino, che
# nessun check copriva. Poteva sparire e il test sarebbe rimasto
# verde — che è il difetto peggiore di un test: mente sul suo
# stesso oggetto.
SEZIONI = re.findall(r'<section id="opz-sez-([a-z]+)"', html)
TABS = re.findall(r'<button id="opz-tab-([a-z]+)"', html)
check("l'elenco delle sezioni non e' vuoto", SEZIONI, str(SEZIONI))
check("tab e sezioni sono gli stessi, nello stesso ordine",
      SEZIONI == TABS,
      f"sezioni {SEZIONI} / tab {TABS}: una tab senza sezione e' un "
      "pulsante che non apre niente")

for sez in SEZIONI:
    check(f"tab {sez} con id e data-sez",
          f'id="opz-tab-{sez}"' in html and f'data-sez="{sez}"' in html, sez)
    check(f"sezione {sez} con id", f'id="opz-sez-{sez}"' in html, sez)
    # data-sez deve combaciare con l'id: e' il ponte fra la tab e la
    # sezione, e se i due nomi divergono il click apre la sezione
    # sbagliata — o nessuna.
    check(f"sezione {sez}: id e data-sez combaciano",
          re.search(r'<section id="opz-sez-%s"[^>]*data-sez="%s"'
                    % (sez, sez), html) is not None, sez)

# "una sola sezione aperta all'inizio": si conta l'attributo hidden
# nelle sezioni vere, non le occorrenze di una stringa nel file. Il
# primo — e solo il primo — deve essere senza hidden.
_aperte = re.findall(r'<section id="opz-sez-([a-z]+)"(?![^>]*hidden)', html)
check("una sola sezione aperta all'inizio",
      _aperte == [SEZIONI[0]] if SEZIONI else False,
      f"aperte: {_aperte}, la prima dovrebbe essere {SEZIONI[:1]}")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
shutil.rmtree(store, ignore_errors=True)
sys.exit(1 if FAIL else 0)