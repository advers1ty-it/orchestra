"""Il pannello Servizi: una sezione sola, il campo sotto la descrizione.

Prima erano due voci di Opzioni, e la stessa cosa stava in tutte e due:
"Servizi" aveva la riga con il campo della chiave, "Gratis" aveva la
scheda con la descrizione. Il risultato e' che per capire cosa fosse
NVIDIA si cambiava sezione, e per mettere una chiave non si sapeva cosa
si stava attivando.

Qui si esegue il bundle vero in Node, si finge /api/chiavi e si guarda
il DOM: i tre gruppi ci sono, ogni servizio che ha una chiave ha il suo
campo dentro la scheda, e nessuna chiave compare due volte.

Il doppione e' il difetto da temere: se il legame servizio-chiave si
rompe, la stessa chiave ricompare in "Altre chiavi" sotto la scheda che
la spiega, e il pannello chiede due volte la stessa cosa. Per questo
l'ultimo blocco non usa dati inventati ma `keys.FREE_SERVICES` e
`keys.stato()` veri: se il campo "env" sparisce da un servizio, il test
lo vede.
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

PROBE = """
(async () => {
  const OUT = { errori: [], gruppi: [], righe: [] };

  globalThis.fetch = async (u) => {
    const ok = (o) => ({ ok: true, status: 200, json: async () => o,
                         text: async () => JSON.stringify(o) });
    if (u === "/api/chiavi") return ok(%s);
    if (u === "/api/models") return ok({ provider: "openrouter", current: "x",
                                         models: [] });
    if (String(u).startsWith("/api/modelli")) return ok({ modelli: [] });
    if (String(u).startsWith("/api/skill")) return ok({ lista_scaricate: [],
                                                        lista_generate: [] });
    return ok({});
  };

  const lista = document.getElementById("servizi-lista");
  if (!lista) { OUT.errore = "servizi-lista non c'e'"; console.log("SERVUI" + JSON.stringify(OUT)); return; }
  try { await caricaOpzioni(); } catch (e) { OUT.errori.push("caricaOpzioni: " + String(e)); }

  const cls = (n) => String((n && n.className) || "").split(" ");
  const testo = (n) => String((n && n.textContent) || "");

  // La lista si legge come la vede chi guarda: nell'ordine, con il gruppo
  // in cui ogni scheda capita. Cosi' un gruppo vuoto o una scheda
  // rimasta fuori si notano senza indovinare la struttura.
  for (const n of (lista.children || [])) {
    if (cls(n).includes("gratis-gruppo")) { OUT.gruppi.push(testo(n)); continue; }
    if (!cls(n).includes("gratis-scheda")) continue;
    const gruppo = OUT.gruppi.length ? OUT.gruppi[OUT.gruppi.length - 1] : null;
    const nome = testo(n.children && n.children[0] && n.children[0].children &&
                       n.children[0].children[0]);
    let campi = 0, tipo = null, link = null, nota = null;
    const cerca = (x) => {
      if (!x) return;
      if (cls(x).includes("chiave-input")) { campi++; tipo = x.type; }
      if (String(x.tagName || "").toUpperCase() === "A" && !link) link = String(x.href || "");
      if (cls(x).includes("chiave-stato")) nota = testo(x);
      for (const y of (x.children || [])) cerca(y);
    };
    cerca(n);
    OUT.righe.push({ gruppo, nome, campi, tipo, link, nota, testo: testo(n) });
  }
  console.log("SERVUI" + JSON.stringify(OUT));
})();
"""


def esegui(payload):
    """Esegue il bundle con una risposta finta di /api/chiavi."""
    f = tempfile.mktemp(suffix=".js")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(harness + "\n" + joined + "\n" + PROBE % json.dumps(payload))
    proc = subprocess.run(["node", f], capture_output=True, text=True,
                          timeout=120)
    try:
        os.unlink(f)
    except OSError:
        pass
    if proc.returncode != 0:
        return {"errori": ["node: " + (proc.stderr or "")[-400:]]}
    riga = [l for l in proc.stdout.splitlines() if l.startswith("SERVUI")]
    if not riga:
        return {"errori": ["nessuna risposta: " + (proc.stdout or "")[-300:]]}
    return json.loads(riga[-1][6:])


def riga(nome, o, gruppo=None):
    for r in o.get("righe", []):
        if r["nome"] == nome and (gruppo is None or r["gruppo"] == gruppo):
            return r
    return None


# I dati del primo blocco sono un sottoinsieme scritto a mano: servono a
# fissare il disegno, non a dire cosa c'e' nel catalogo. Il catalogo vero
# arriva nell'ultimo blocco.
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
     "come": " premi Collega Nous qui sotto", "connesso": True},
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
    {"chiave": "ANTHROPIC_API_KEY", "etichetta": "Anthropic",
     "presente": False, "indizio": ""},
    {"chiave": "NOUS_API_KEY", "etichetta": "Nous Research (token manuale)",
     "presente": False, "indizio": ""},
    {"chiave": "ORCHESTRA_OLLAMA_URL", "etichetta": "Indirizzo Ollama",
     "presente": False, "indizio": ""},
    {"chiave": "ARTIFICIAL_ANALYSIS_KEY", "etichetta": "Artificial Analysis",
     "presente": True, "indizio": "...9ab1", "dove": ""},
    # il server dice "dove": questa ha gia' il suo campo in Modello
    {"chiave": "ORCHESTRA_MAX_SECONDI_TURNO",
     "etichetta": "Tempo massimo per turno (secondi, 0 = nessun limite)",
     "presente": False, "indizio": "", "dove": "Modello"},
]

o = esegui({"chiavi": chiavi, "servizi_gratis": servizi, "nota_gratis": "",
            "catalogo": {"modelli": 12, "gratuiti": 7}, "motori": [],
            "provider": "openrouter", "model": "", "reasoning": "",
            "tool_profile": None, "budget": {}})

print("[1] Il bundle disegna i servizi in tre gruppi")
check("il bundle gira in Node", not o.get("errori"), str(o.get("errori"))[:300])
check("nessun errore durante il disegno", not o.get("errori"),
      str(o.get("errori"))[:200])
check("i gruppi sono Gratis, A pagamento, Sul tuo computer",
      o.get("gruppi") == ["Gratis", "A pagamento", "Sul tuo computer",
                          "Altre chiavi"],
      str(o.get("gruppi")))
check("le schede sono i quattro servizi piu' la chiave orfana",
      len(o.get("righe", [])) == 5, len(o.get("righe", [])))

print("\n[2] La chiave sta sotto la descrizione, nella stessa scheda")
open_ = riga("OpenRouter", o, "Gratis")
check("OpenRouter ha un campo e una sola descrizione",
      open_ and open_["campi"] == 1
      and "Scelta enorme" in open_["testo"],
      f"campi={open_ and open_['campi']} desc={'Scelta enorme' in (open_ or {}).get('testo', '')}")
check("la chiave gia' salvata si dice senza mostrarla",
      "configurata" in (open_ or {}).get("nota", ""), (open_ or {}).get("nota"))
check("ed e' un campo password",
      (open_ or {}).get("tipo") == "password", (open_ or {}).get("tipo"))
check("e il posto dove prendere la chiave e' un link cliccabile",
      (open_ or {}).get("link") == "https://openrouter.ai/keys",
      (open_ or {}).get("link"))
anth = riga("Anthropic", o, "A pagamento")
check("una chiave mancante invita a incollarla",
      anth and anth["campi"] == 1, (anth or {}).get("campi"))

print("\n[3] I locali e i collegamenti diretti non chiedono chiavi")
oll = riga("Ollama", o, "Sul tuo computer")
check("Ollama ha il campo dell'indirizzo, non una credenziale",
      oll and oll["campi"] == 1 and oll["tipo"] == "text",
      f"campi={(oll or {}).get('campi')} tipo={(oll or {}).get('tipo')}")
check("e non dice 'manca la chiave' su un indirizzo",
      oll and "chiave" not in (oll.get("nota") or ""), (oll or {}).get("nota"))
nous = riga("Nous Research", o, "Gratis")
check("Nous ha il suo pulsante di collegamento",
      nous and "Collega Nous" in nous["testo"], (nous or {}).get("testo", "")[:80])
check("e non un link a un sito: si collega da qui",
      nous and nous.get("link") is None, (nous or {}).get("link"))

print("\n[4] Nessuna chiave sparisce e nessuna compare due volte")
art = riga("Artificial Analysis", o, "Altre chiavi")
check("Artificial Analysis ha il suo campo",
      art and art["campi"] == 1, (art or {}).get("campi"))
sec = riga("Tempo massimo per turno (secondi, 0 = nessun limite)", o)
check("il tempo massimo per turno non si ripete qui",
      sec is None, (sec or {}).get("gruppo"))
# ...e non sparisce dal pannello: il suo campo e' nel tab Modello, in
# minuti. Se quel campo se ne andasse, "dove" in keys.py sarebbe una
# bugia e la chiave non avrebbe piu' nessun posto dove essere scritta.
index = open(os.path.join(ROOT, "orchestra", "web", "index.html"),
             encoding="utf-8").read()
check("perche' il suo campo e' in Modello, in minuti",
      'id="opt-max-minuti"' in index)
check("il gruppo Gratis viene prima di A pagamento",
      o.get("gruppi", [])[:3] == ["Gratis", "A pagamento", "Sul tuo computer"],
      str(o.get("gruppi")))

# ------------------------------------------------------------------ catalogo vero
# `env` e' il legame fra un servizio e la sua chiave. Se manca, la chiave
# non viene riconosciuta come gia' mostrata e ricompare in "Altre chiavi":
# due riquadri per la stessa cosa, uno che spiega e uno che chiede.
from orchestra import keys  # noqa: E402

stato = keys.stato(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "_dati_test", ".env"), {})
vero = esegui({"chiavi": stato, "servizi_gratis": keys.FREE_SERVICES,
               "nota_gratis": "", "catalogo": {}, "motori": [], "provider": "",
               "model": "", "tool_profile": None, "budget": {}})

print("\n[5] Con il catalogo vero ogni chiave ha un riquadro solo")
check("il catalogo vero si disegna", not vero.get("errori"),
      str(vero.get("errori"))[:300])
nomi = [r["nome"] for r in vero.get("righe", [])]
doppi = sorted({n for n in nomi if nomi.count(n) > 1})
check("nessun servizio spiegato due volte", not doppi, str(doppi))

legate = {s.get("env") for s in keys.FREE_SERVICES}
attese = [k["etichetta"] for k in stato
          if k["chiave"] not in legate and not k.get("dove")]
altre = [r["nome"] for r in vero.get("righe", []) if r["gruppo"] == "Altre chiavi"]
check("in 'Altre chiavi' resta solo cio' che non e' un servizio",
      altre == attese, f"trovate={altre} attese={attese}")
ospiti = [k["etichetta"] for k in stato if k.get("dove")]
ripetute = [n for n in ospiti if n in nomi]
check("e nessuna chiave che vive in un'altra sezione compare qui",
      not ripetute, str(ripetute))

servizi_con_chiave = [s for s in keys.FREE_SERVICES if s.get("chiave")]
senza_campo = [s["nome"] for s in servizi_con_chiave
               if not (riga(s["nome"], vero) or {}).get("campi")]
check("ogni servizio che chiede una chiave ha il suo campo",
      not senza_campo, str(senza_campo))
senza_link = [s["nome"] for s in keys.FREE_SERVICES
              if not (riga(s["nome"], vero) or {}).get("link")
              and s.get("come", "").strip().count(".") and
              " " not in s.get("come", "").strip()]
check("e il link per prenderla, quando c'e' un indirizzo",
      not senza_link, str(senza_link))

print()
print("=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
