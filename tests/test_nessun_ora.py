"""Il menu a tendina dice gia' quale servizio e modello sono attivi.

Una riga che ripete "ora: groq" sotto un menu che dice "groq" non
aggiunge niente: e' la stessa informazione due volte, e la seconda con
meno affidabilita' perche' viene da una richiesta che potrebbe essere
superata da un'altra.

Quello che resta e' l'errore, perche' il menu da solo non dice PERCHE'.
E il menu deve tornare indietro quando il cambio fallisce: se dice
"Groq" e la chat risponde con OpenRouter, la divergenza si vede solo
alla prima risposta e sembra un errore di rete.
"""

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


js = io.open(os.path.join(ROOT, "orchestra", "web", "panels.js"),
             encoding="utf-8").read()

print("[1] Nessun 'ora:' che ripete il menu")
check("non c'e' piu' nessun 'ora: '", '"ora: "' not in js,
      "trovato: " + str(js.count('"ora: "')) + " volte")
# e neppure con apostrofo, se mai
check("ne' con l'apostrofo", "'ora: '" not in js)

print("\n[2] Ma il ramo di successo esiste ancora ed e' silenzioso")
# Se eliminare il messaggio avesse tolto anche il ramo, un cambio
# riuscito non lascerebbe traccia: e non sapresti se e' andato.
check("il cambio servizio ha ancora un ramo di successo",
      'optMsg.className = "small verde"' in js)
check("che ora svuota il testo",
      'optMsg.textContent = ""' in js)
check("il cambio modello anche",
      js.count('optMsg.textContent = ""') >= 2,
      str(js.count('optMsg.textContent = ""')))

print("\n[3] L'errore resta, e dice perche'")
check("cambio fallito", "cambio fallito" in js)
check("servizio non piu' disponibile",
      "non piu' disponibile" in js)
check("nessuna chiave API", "nessuna chiave API" in js)

print("\n[4] Il menu torna indietro quando il cambio fallisce")
# Il punto vero: senza, il menu mente sul servizio attivo e la
# divergenza si scopre alla prima risposta.
#
# Si guarda DENTRO la funzione giusta. Cercando in tutto il file si
# trova la prima "if (!r.ok) {" e la prima "} catch (e) {", che sono
# in altre funzioni: il test guardava il codice sbagliato e segnalava
# un difetto che non c'era. Un test che sbaglia il bersaglio e' peggio
# di nessun test, perche' blocca la correzione di un codice giusto.
def dentro(funzione: str, fine: int = 4000) -> str:
    i = js.find(funzione)
    return js[i:i + fine] if i > 0 else ""

modello = dentro("on(optModel, \"change\"")
check("il cambio modello ripristina il menu dopo un errore",
      "caricaModelli" in modello and "if (!r.ok)" in modello,
      modello[:150].replace("\n", " ") if modello else "funzione non trovata")

servizio = dentro("async function cambiaServizio")
check("il cambio servizio ripristina il menu dopo un errore",
      "caricaOpzioni()" in servizio and "cambio fallito" in servizio,
      servizio[:150].replace("\n", " ") if servizio else "funzione non trovata")

print("\n[5] L'errore viene scritto DOPO il ripristino")
# Se il testo dell'errore fosse scritto prima, il ripristino lo
# cancellerebbe: si chiamerebbe caricaOpzioni() che ricarica le
# opzioni e azzera i messaggi, e l'utente vedrebbe solo il menu
# tornato indietro senza sapere perche'.
for nome, fine in (("cambio servizio", js.find("cambio fallito: \" + e")),
                   ("cambio modello", js.find('optMsg.textContent = d.error'))):
    ok = True
    if fine > 0:
        torno = js.rfind("caricaOpzioni()", 0, fine)
        ok = torno > 0
    check(f"{nome}: l'errore resta visibile dopo il ripristino", ok,
          "il ripristino potrebbe azzerare il testo")

print("\n[6] Il colore verde distingue ancora 'cambiato' da 'nessuna notizia'")
check("verde sul cambio riuscito",
      'optMsg.className = "small verde"' in js)
check("rosso sul fallito", 'optMsg.className = "small rosso"' in js)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)