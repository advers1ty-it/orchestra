"""Il pannello Servizi: una sezione sola, il campo sotto la descrizione.

Prima erano due voci di Opzioni, e la stessa cosa stava in tutte e due:
"Servizi" aveva la riga con il campo della chiave, "Gratis" aveva la
scheda con la descrizione. Il risultato e' che per capire cosa fosse
NVIDIA si cambiava sezione, e per mettere una chiave non si sapeva cosa
si stava attivando.

Qui si esegue il bundle vero in Node, si finge /api/chiavi e si guarda
il DOM: i tre gruppi ci sono, ogni servizio che ha una chiave ha il suo
campo dentro la scheda, i locali non lo hanno, e nessuna chiave
scompare dal pannello.

Il "campo dentro la scheda" e' la parte fragile: e' un albero costruito
a mano, e basta che `schedaServizio` riceva la chiave sbagliata perche'
il campo finisca sul servizio sbagliato — cosa che a occhio, con dieci
schede, non si vede.
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    # `cp` esiste per il solo motivo che la console Windows e' cp1252 e un
    # carattere fuori tabella fa esplodere il test a meta' stampa, con un
    # errore che parla di encoding e non del check fallito.
    print("  " + ("OK  " if cond else "FAIL") + " " + nome
          + ("" if cond else " -- " + str(dettaglio)))


from _ordine import ORDER  # noqa: E402

joined = "\n;\n".join(
    open(os.path.join(ROOT, "orchestra", "web", n), encoding="utf-8").read()
    for n in ORDER)
harness = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "_dom_provider.js"), encoding="utf-8").read()

# I dati sono quelli veri di keys.FREE_SERVICES, ridotti: se il pannello
# dipendesse da un campo che il server non manda, qui si vedrebbe.
servizi = [
    {"id": "openrouter", "env": "OPENROUTER_API_KEY", "gruppo": "Gratis con chiave",
     "nome": "OpenRouter", "costo": "quasi tutto gratis", "chiave": True,
     "cosa": "Scelta enorme di modelli, con molte varianti gratis.",
     "requisiti": "Account. Serve una chiave.",
     "come": " openrouter.ai/keys"},
    {"id": "nous", "env": "NOUS_API_KEY", "gruppo": "Collegamento diretto",
     "nome": "Nous Research", "costo": "gratis con collegamento Orchestra",
     "chiave": False, "cosa": "Accesso diretto all'inference API di Nous.",
     "requisiti": "Si collega da solo oppure con un token manuale.",
     "come": " premi Collega Nous", "connesso": True},
    {"id": "anthropic", "env": "ANTHROPIC_API_KEY", "gruppo": "A pagamento",
     "nome": "Anthropic", "costo": "a pagamento", "chiave": True,
     "cosa": "I modelli Claude diretti dal produttore.",
     "requisiti": "Account con carta.", "come": " console.anthropic.com"},
    {"id": "ollama", "env": "ORCHESTRA_OLLAMA_URL", "gruppo": "Sul tuo computer",
     "nome": "Ollama", "costo": "gratis, sul tuo computer", "chiave": False,
     "cosa": "Modelli locali, nessuna richiesta esce dal computer.",
     "requisiti": "Ollama installato.", "come": " ollama.com"},
]

chiavi = [
    {"chiave": "OPENROUTER_API_KEY", "etichetta": "OpenRouter",
     "presente": True, "indizio": "...ZxfA"},
    {"chiave": "NOUS_API_KEY", "etichetta": "Nous Research (token manuale)",
     "presente": False, "indizio": ""},
    {"chiave": "ANTHROPIC_API_KEY", "etichetta": "Anthropic",
     "presente": False, "indizio": ""},
    {"chiave": "ARTIFICIAL_ANALYSIS_KEY", "etichetta": "Artificial Analysis",
     "presente": True, "indizio": "...9ab1"},
    {"chiave": "ORCHESTRA_MAX_SECONDI_TURNO",
     "etichetta": "Tempo massimo per turno (secondi, 0 = nessun limite)",
     "presente": False, "indizio": ""},
    {"chiave": "ORCHESTRA_OLLAMA_URL", "etichetta": "Indirizzo Ollama",
     "presente": False, "indizio": ""},
]

probe = """
(async () => {
  const OUT = { errori: [] };
  const payload = %s;

  // Il pannello chiede anche permessi, autostart, skill, modelli e
  // motori locali. Qui interessa /api/chiavi; per tutto il resto una
  // risposta vuota basta a non far esplodere il disegno, che e' l'unica
  // cosa che questo test misura.
  globalThis.fetch = async (u) => {
    const ok = (o) => ({ ok: true, status: 200, json: async () => o,
                         text: async () => JSON.stringify(o) });
    if (u === "/api/chiavi") return ok(payload);
    if (u === "/api/models") return ok({ provider: "openrouter", current: "x",
                                         models: [] });
    if (String(u).startsWith("/api/modelli")) return ok({ modelli: [] });
    if (String(u).startsWith("/api/skill")) return ok({ lista_scaricate: [],
                                                        lista_generate: [] });
    return ok({});
  };

  const lista = document.getElementById("servizi-lista");
  if (!lista) { OUT.errore = "servizi-lista non c'e'"; console.log("SERVUI" + JSON.stringify(OUT)); return; }

  try { await caricaOpzioni(); } catch (e) { OUT.errori.push("caricaOpzioni: " + e); }

  const nodi = [];
  const cammina = (n, dentro) => {
    if (!n) return;
    nodi.push({ nodo: n, dentro });
    for (const c of (n.children || [])) cammina(c, n);
  };
  cammina(lista, null);

  const gruppi = nodi.filter(x => String(x.nodo.className || "") === "gratis-gruppo")
                     .map(x => x.nodo.textContent);
  OUT.gruppi = gruppi;

  // Le schede, per nome: testo e campo devono stare nella stessa.
  const schede = nodi.filter(x => String(x.nodo.className || "").split(" ").includes("gratis-scheda"));
  const schedaDi = (nome) => schede.find(x =>
    String(x.nodo.children && x.nodo.children[0] ? x.nodo.children[0].textContent : "").includes(nome));
  const campoDentro = (nodo) => {
    let trovato = 0;
    const cerca = (n) => {
      if (!n) return;
      if (String(n.className || "").split(" ").includes("chiave-input")) trovato++;
      for (const c of (n.children || [])) cerca(c);
    };
    cerca(nodo);
    return trovato;
  };
  const inputDentro = (nodo) => {
    let out = null;
    const cerca = (n) => {
      if (!n || out) return;
      if (String(n.className || "").split(" ").includes("chiave-input")) { out = n; return; }
      for (const c of (n.children || [])) cerca(c);
    };
    cerca(nodo);
    return out;
  };

  const open = schedaDi("OpenRouter");
  OUT.openCampi = open ? campoDentro(open.nodo) : -1;
  OUT.openDescrizione = open ? String(open.nodo.textContent).includes("Scelta enorme") : null;
  OUT.openPresente = open ? !!(inputDentro(open.nodo) && inputDentro(open.nodo).placeholder.indexOf("lascia vuoto") >= 0) : null;
  OUT.openPassword = open ? !!(inputDentro(open.nodo) && inputDentro(open.nodo).type === "password") : null;

  const anth = schedaDi("Anthropic");
  OUT.anthCampi = anth ? campoDentro(anth.nodo) : -1;
  OUT.anthSegnaposto = anth && inputDentro(anth.nodo) ? inputDentro(anth.nodo).placeholder : null;

  const oll = schedaDi("Ollama");
  OUT.ollCampi = oll ? campoDentro(oll.nodo) : -1;
  OUT.ollDescrizione = oll ? String(oll.nodo.textContent).includes("Modelli locali") : null;

  const nous = schedaDi("Nous Research");
  OUT.nousCampi = nous ? campoDentro(nous.nodo) : -1;
  OUT.nousCollega = nous ? String(nous.nodo.textContent).includes("Collega Nous")
                            || String(nous.nodo.textContent).includes("Ricollega") : null;

  // L'indirizzo di Ollama e' un'impostazione, non un segreto: il campo
  // deve essere in chiaro, e stare nella sua scheda.
  OUT.ollUrlInChiaro = oll && inputDentro(oll.nodo) ? inputDentro(oll.nodo).type : null;

  // Nessuna chiave persa: Artificial Analysis non e' un servizio, ma ha
  // un campo suo; l'impostazione dei secondi pure.
  OUT.altre = gruppi.indexOf("Altre chiavi") >= 0;
  const art = schede.find(x => String(x.nodo.textContent).includes("Artificial Analysis"));
  OUT.artificialCampo = art ? campoDentro(art.nodo) : -1;
  const sec = schede.find(x => String(x.nodo.textContent).includes("Tempo massimo per turno"));
  OUT.secondiCampo = sec ? campoDentro(sec.nodo) : -1;
  OUT.secondiTesto = sec && inputDentro(sec.nodo) ? inputDentro(sec.nodo).type : null;

  // Il gruppo giusto per ognuno: la fusione non deve rimescolare le cose.
  OUT.ordineGruppi = gruppi;
  OUT.openDopoGratis = gruppi.indexOf("Gratis") >= 0
    && schede.indexOf(open) > 0
    && gruppi.indexOf("A pagamento") > gruppi.indexOf("Gratis");

  OUT.numeroSchede = schede.length;
  console.log("SERVUI" + JSON.stringify(OUT));
})();
""" % json.dumps({"chiavi": chiavi, "servizi_gratis": servizi,
                   "nota_gratis": "", "catalogo": {"modelli": 12, "gratuiti": 7},
                   "motori": [], "provider": "openrouter", "model": "",
                   "reasoning": "", "tool_profile": None, "budget": {}})

f = tempfile.mktemp(suffix=".js")
with open(f, "w", encoding="utf-8") as fh:
    fh.write(harness + "\n" + joined + "\n" + probe)
proc = subprocess.run(["node", f], capture_output=True, text=True, timeout=120)
try:
    os.unlink(f)
except OSError:
    pass

print("[1] Il bundle disegna i servizi in tre gruppi")
if proc.returncode != 0:
    check("il bundle gira in Node", False, proc.stderr[-400:])
else:
    check("il bundle gira in Node", True)
    riga = [l for l in proc.stdout.splitlines() if l.startswith("SERVUI")]
    if not riga:
        check("il probe ha risposto", False, proc.stdout[-300:])
    else:
        o = json.loads(riga[-1][6:])
        check("nessun errore durante il disegno", not o.get("errori"),
              str(o.get("errori"))[:200])
        check("i gruppi sono Gratis, A pagamento, Sul tuo computer",
              o.get("gruppi") == ["Gratis", "A pagamento", "Sul tuo computer",
                                  "Altre chiavi"],
              str(o.get("gruppi")))
        check("e il gruppo delle chiavi senza servizio sta in fondo",
              o.get("altre") is True, str(o.get("gruppi")))
        check("le schede sono i quattro servizi piu' le due chiavi",
              o.get("numeroSchede") == 6, str(o.get("numeroSchede")))

print("\n[2] La chiave sta sotto la descrizione, nella stessa scheda")
check("OpenRouter ha un campo e una sola descrizione",
      o.get("openCampi") == 1 and o.get("openDescrizione") is True,
      f"campi={o.get('openCampi')} descrizione={o.get('openDescrizione')}")
check("la chiave gia' salvata si dice senza mostrarla",
      o.get("openPresente") is True, str(o.get("openPresente")))
check("ed e' un campo password",
      o.get("openPassword") is True, str(o.get("openPassword")))
check("una chiave mancante invita a incollarla",
      "incolla" in str(o.get("anthSegnaposto")), str(o.get("anthSegnaposto")))
check("e Anthropic, che e' a pagamento, ha il suo campo",
      o.get("anthCampi") == 1, str(o.get("anthCampi")))

print("\n[3] I locali e i collegamenti diretti non chiedono chiavi")
# Ollama non chiede una chiave, ma ha un indirizzo configurabile: il
# campo c'e' ed e' in chiaro, con il testo giusto.
check("Ollama ha il campo dell'indirizzo, non una credenziale",
      o.get("ollCampi") == 1 and o.get("ollUrlInChiaro") == "text",
      f"campi={o.get('ollCampi')} tipo={o.get('ollUrlInChiaro')}")
check("ma la sua descrizione c'e'", o.get("ollDescrizione") is True)
check("l'indirizzo locale si legge in chiaro",
      o.get("ollUrlInChiaro") == "text", str(o.get("ollUrlInChiaro")))
check("Nous ha il suo pulsante di collegamento",
      o.get("nousCollega") is True, str(o.get("nousCollega")))
check("e il token manuale ha comunque il campo",
      o.get("nousCampi") == 1, str(o.get("nousCampi")))

print("\n[4] Nessuna chiave sparisce")
check("Artificial Analysis ha il suo campo",
      o.get("artificialCampo") == 1, str(o.get("artificialCampo")))
check("e l'impostazione dei secondi pure",
      o.get("secondiCampo") == 1, str(o.get("secondiCampo")))
check("e si legge in chiaro, non come una password",
      o.get("secondiTesto") == "text", str(o.get("secondiTesto")))
check("il gruppo Gratis viene prima di A pagamento",
      o.get("openDopoGratis") is True, str(o.get("ordineGruppi")))

print()
print("=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
