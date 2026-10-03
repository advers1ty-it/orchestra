"""Il selettore custom: struttura, e i due modi in cui può non esistere.

Il difetto che questo file copre l'ho già commesso una volta. Il primo
versione lasciava il <select> nativo visibile e apriva il pannello
sopra: non si vedeva niente, e non per un motivo di cache. Al click il
browser apre il SUO menu, disegnato dal sistema, e quel popup sta
sempre sopra qualsiasi elemento della pagina. Il pannello era sotto,
funzionante, e invisibile. Ctrl+F5 non lo avrebbe cambiato mai.

E il secondo difetto, più subdolo: `.mp-wrap` senza `position:
relative`. Il CSS del pannello c'era ed era corretto, ma senza un
containing block il posizionamento è relativo alla PAGINA, e il
pannello sarebbe comparso nell'angolo in alto a sinistra invece che
sotto il bottone. Colonne giuste, coordinate sbagliate.

Entrambi sono difetti che non si vedono guardando il JavaScript: sono
il modo in cui due pezzi separati si contradicono.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(ROOT, "orchestra", "web", "index.html"),
            encoding="utf-8").read()
CSS = open(os.path.join(ROOT, "orchestra", "web", "app.css"),
           encoding="utf-8").read()

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def blocco_css(selettore):
    """Il corpo della regola, per poterci cercare dentro."""
    if selettore not in CSS:
        return ""
    return CSS.split(selettore)[1].split("}")[0]


print("[1] Il select nativo esiste, ma non si vede")
check("c'e'", 'id="model-pick"' in HTML,
      "il server legge il suo value: senza, non sa quale modello e' in uso")
check("e' dichiarato nascosto", "mp-nascosto" in HTML,
      "un select visibile apre il proprio menu e copre il pannello")
nascosto = blocco_css(".mp-nascosto")
check("con una tecnica che lo nasconde", len(nascosto.strip()) > 0,
      "manca la regola CSS")
check("SENZA display:none", "display: none" not in nascosto,
      "display:none lo toglie anche dal percorso di tabulazione")
check("e con clip, che lo tiene raggiungibile", "clip" in nascosto,
      "senza clip resta un box 1px visibile")
check("tabindex negato", 'tabindex="-1"' in HTML,
      "il campo nascosto non deve essere nel percorso di tabulazione")

print("\n[2] Il bottone e' la cosa che si vede")
check("esiste", 'id="model-btn"' in HTML)
check("e ha l'etichetta del modello", 'id="model-label"' in HTML)
check("ed e' un bottone, non un div",
      "<button" in HTML.split('id="model-btn"')[0][-40:],
      "un div non si raggiunge col Tab e non ha focus visibile")
check("type=button", 'type="button"' in HTML,
      "senza, dentro un form parte il submit invece di aprire il menu")
check("dichiara il ruolo", 'aria-haspopup="listbox"' in HTML)
check("e se e' aperto", 'aria-expanded' in HTML)

print("\n[3] Il contenitore ha un punto di riferimento")
wrap = blocco_css(".mp-wrap")
check("mp-wrap ha position: relative", "position: relative" in wrap,
      "senza, il pannello si posiziona rispetto alla PAGINA e compare "
      "nell'angolo in alto a sinistra invece che sotto il bottone")
check("ed e' un blocco che contiene il bottone", "inline-block" in wrap
      or "block" in wrap, "senza il bottone e il pannello si sovrappongono")

print("\n[4] Il pannello si posiziona sotto il bottone")
pop = blocco_css(".mp-pop")
check("e' posizionato", "position: absolute" in pop)
check("sta in primo piano", "z-index" in pop)

# Il difetto che e' successo: `.mp-pop` aveva `display:none` e si mostrava
# solo con la classe `.aperta`, che il JavaScript non aggiungeva MAI.
# Il pannello veniva costruito intero — cercatore, 400 righe, tutto —
# e restava invisibile per sempre. Il bottone sembrava non fare niente.
#
# Non e' un dettaglio di CSS: e' un contratto fra due file, e la parte
# che lo faceva rispettare era in uno solo dei due.
print("\n[4b] Il pannello, quando esiste, si VEDE")
check("niente display:none sul pannello", "display: none" not in pop,
      "il pannello si crea gia' aperto: uno stato in cui esiste e' "
      "aperto, e display:none obbliga a una classe che va ricordata "
      "dall'altra parte")
check("e nessuna classe che lo debba mostrare",
      "mp-pop.aperta" not in CSS and "aperta" not in pop,
      "una classe che il JS non mette rende il pannello invisibile")
js = open(os.path.join(ROOT, "orchestra", "web", "modelpick.js"),
          encoding="utf-8").read()
check("il JS crea il pannello con appendChild", "mpPop.appendChild" in js
      or "mpWrap.appendChild(mpPop)" in js)
check("e lo toglie chiudendo", "mpPop.remove()" in js,
      "senza remove il pannello si accumula a ogni apertura")
check("e ha un'altezza massima con scroll",
      "max-height" in blocco_css(".mp-lista")
      and "overflow-y" in blocco_css(".mp-lista"),
      "senza, 400 righe fanno una pagina lunghissima. Sta sulla lista, "
      "non sul pannello: e' la lista a scorrere, il campo della ricerca "
      "e il piede restano fermi in alto e in basso")

print("\n[5] E non copre tutto quello che deve coprire")
check("il badge del punteggio ha una classe", ".mp-bench" in CSS)
check("il nome ha la sua", ".mp-name" in CSS)
check("e il campo della ricerca", ".mp-cerca" in CSS,
      "il cercatore e' il motivo per cui il pannello esiste")

print("\n[6] E resta un fallback, se il pannello non parte")
# Se il JavaScript non parte, il bottone deve comunque dire QUALE
# modello e' in uso: altrimenti la pagina si apre e non sai cosa
# sta rispondendo. Il select nascosto non lo mostra, e il bottone
# parte dalla stessa etichetta.
check("l'etichetta ha un testo iniziale", "modello" in HTML.split('id="model-label"')[1][:80],
      "a pagina vuota il bottone direbbe niente")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)