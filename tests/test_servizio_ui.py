"""Il cambio di servizio deve funzionare anche dalla chat.

Prima il selettore del servizio c'era solo nelle Opzioni. Dalla chat si
poteva cambiare il modello ma non il servizio, e la cosa non e' che
manca un menu: e' che due modelli con lo stesso nome su servizi diversi
(qwen3-8b su OpenRouter e su Groq) si confondono, e la richiesta finisce
da un servizio diverso da quello che credevi di aver scelto.

Il punto fragile non e' il menu, e' la SINCRONIZZAZIONE: due selettori
che devono dire la stessa cosa prima e dopo ogni cambio. Se divergono,
l'utente vede un servizio e usa un altro — peggio che non averlo.
"""

import json
import os
import re
import subprocess
import sys

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "orchestra", "web")
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def js(path):
    with open(os.path.join(WEB, path), encoding="utf-8") as f:
        return f.read()


html = js("index.html")
panels = js("panels.js")
core = js("core.js")

print("[1] I due selettori esistono e sono nello stesso punto della UI")
check("il selettore del servizio e' nella barra in alto",
      'id="provider-pick"' in html and html.index('id="provider-pick"') < html.index("<main"),
      "non sta nella barra")
# I commenti fra i due elementi sono documentazione, non controlli:
# contando anche quelli la distanza supera il tetto anche quando i due
# select sono adiacenti nel DOM (e' successo con il commento sopra
# mp-wrap). Si misura il markup vero, non la prosa attorno.
import re as _re  # noqa: E402

_senza_commenti = _re.sub(r"<!--.*?-->", "", html, flags=_re.S)
check("e sta subito prima del modello",
      abs(_senza_commenti.index('id="provider-pick"') -
          _senza_commenti.index('id="model-pick"')) < 400)
check("il selettore del modello e' ancora li", 'id="model-pick"' in html)

print("\n[2] Entrambi agganciano lo stesso cambio")
# Due handler separati con due fetch diversi divergono alla prima
# modifica. Un solo punto di verita' e' l'unica forma che regge.
check("cambia il servizio con una sola azione", "async function cambiaServizio" in panels)
n_da_opzioni = len(re.findall(r'\$\("opt-provider"\), "change"', panels))
n_da_header = len(re.findall(r'\$\("provider-pick"\), "change"', panels))
check("entrichiamo ci chiamano", n_da_opzioni == 1 and n_da_header == 1,
      f"opzioni={n_da_opzioni} header={n_da_header}")
check("nessuno dei due fa la richiesta per conto proprio",
      panels.count('"/api/provider"') == 1,
      f"fetch a /api/provider: {panels.count(chr(34) + '/api/provider' + chr(34))}")

print("\n[3] Dopo il cambio, i due selettori devono dire la stessa cosa")
# Il pericolo reale: l'header resta sul servizio vecchio mentre il
# backend e' gia' passato al nuovo. Sembra funzionare e sbaglia.
check("il cambio aggiorna entrambi i selettori",
      "s.value = p" in panels)
check("disegnaProvider scrive su entrambi",
      "selettori" in panels and "provider-pick" in panels)

print("\n[4] Il modello segue il servizio")
# Senza questo, scegli un servizio nuovo e la lista modelli resta quella
# del servizio vecchio: si sceglie un modello che quel servizio non ha.
check("dopo il cambio ricarica i modelli della chat",
      re.search(r"caricaModelli\(p.*\n?\s*.*loadModels\(\)", panels, re.S) is not None)

print("\n[5] Un cambio rifiutato non lascia il selettore bugiardo")
# Il backend puo' rispondere 409 (agente occupato) o 400 (chiave
# mancante). Senza riallineare, il menu mostra un servizio che non e'
# quello in uso.
#
# Si cerca dentro cambiaServizio, non nel primo `if (!r.ok)` del file:
# ce n'e' uno anche nella prova manuale, e il test prendeva quello
# per sbaglio — misurando il codice giusto mentre pensava di
# controllare quello sbagliato.
inizio_sc = panels.index("async function cambiaServizio")
ramo = panels[inizio_sc:]
ramo = ramo.split("if (!r.ok)")[1].split("\n  }")[0]
check("in caso di errore riallinea il selettore",
      "disegnaProvider(" in ramo, ramo[-140:])

print("\n[6] Nessun selettore usa $() con il prefisso #")
# $() e' getElementById: con il # restituisce null in silenzio. E' gia'
# successo una volta, ed e' il tipo di difetto che non si vede.
for nome, sorgente in (("panels.js", panels), ("core.js", core)):
    catturati = re.findall(r'\$\("#([^"]+)"\)', sorgente)
    check(f"{nome}: nessun id con #", not catturati, str(catturati[:4]))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
