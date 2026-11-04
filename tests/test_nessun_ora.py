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


from _web import pannelli  # noqa: E402

js = pannelli()

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
# Il punto vero: senza, il menu mente sul modello o servizio attivo e
# la divergenza si scopre alla prima risposta.
#
# Non si legge il sorgente: si esegue il bundle con un DOM finto, si
# tenta davvero il cambio e il server risponde con un errore. Una
# finestra di N caratteri dopo `on(optModel` era la versione
# precedente, e si era staccata dal codice: cercava `caricaModelli`,
# che nel frattempo e' diventato `caricaOpzioni` — la funzione che
# rimette il modello VERO, e quindi la cosa giusta. Il test era rosso
# su un codice corretto.
import json  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

from _ordine import ORDER  # noqa: E402

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RADICE, "orchestra", "web")
dom = open(os.path.join(RADICE, "tests", "_dom_provider.js"), encoding="utf-8").read()
bundle = "\n;\n".join(open(os.path.join(WEB, f), encoding="utf-8").read()
                      for f in ORDER)
probe = open(os.path.join(RADICE, "tests", "_probe_menu_errore.js"),
             encoding="utf-8").read()
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                 encoding="utf-8") as fh:
    fh.write(dom + "\n" + bundle + "\n" + probe)
    script = fh.name
try:
    # encoding: node scrive UTF-8, e su Windows text=True decodifica in
    # cp1252 — i caratteri accentati arriverebbero corrotti e i
    # confronti fallirebbero per un motivo che non e' del codice.
    r = subprocess.run(["node", script], capture_output=True,
                       encoding="utf-8", timeout=90)
finally:
    try:
        os.unlink(script)
    except OSError:
        pass
righe = [l for l in r.stdout.split("\n") if l.strip().startswith("{")]
if not righe:
    print(r.stdout[-500:])
    print(r.stderr[-500:])
    check("il probe gira", False, "nessun risultato dal nodo")
    d = {"passi": {}}
else:
    check("il probe gira", True)
    d = json.loads(righe[-1])
p = d.get("passi", {})

check("il cambio modello arriva al server",
      p.get("modelloChiesto") == "openrouter/x2", str(p.get("modelloChiesto")))
check("e il menu torna al modello vero, non resta su quello nuovo",
      p.get("modelloDopo") == "openrouter/x1" == p.get("modelloIniziale"),
      f"iniziale={p.get('modelloIniziale')} dopo={p.get('modelloDopo')}")
# L'errore viene scritto DOPO il ripristino: se fosse prima,
# caricaOpzioni() lo cancellerebbe e l'utente vedrebbe solo il menu
# tornato indietro senza sapere perche'.
check("l'errore del server resta visibile",
      "modello non disponibile" in (p.get("modelloMsg") or ""),
      str(p.get("modelloMsg")))
check("ed e' scritto in rosso",
      "rosso" in (p.get("modelloClasse") or ""), str(p.get("modelloClasse")))

print("\n[5] Anche il servizio")
check("il cambio servizio arriva al server",
      p.get("servizioChiesto") == "groq", str(p.get("servizioChiesto")))
check("i due menu tornano al servizio vero",
      p.get("servizioDopo") == ["openrouter", "openrouter"],
      str(p.get("servizioDopo")))
check("lo stato vero lo dice il server, non il menu",
      p.get("servizioPrima") == ["openrouter", "openrouter"],
      str(p.get("servizioPrima")))
check("l'errore del servizio resta visibile",
      "agente occupato" in (p.get("servizioMsg") or ""),
      str(p.get("servizioMsg")))
check("e il colore e' quello dell'errore",
      "rosso" in (p.get("servizioClasse") or ""), str(p.get("servizioClasse")))
check("nessun errore durante l'esecuzione",
      d.get("errori") == [], str(d.get("errori")))

print("\n[6] Il colore verde distingue ancora 'cambiato' da 'nessuna notizia'")
check("verde sul cambio riuscito",
      'optMsg.className = "small verde"' in js)
check("rosso sul fallito", 'optMsg.className = "small rosso"' in js)

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)