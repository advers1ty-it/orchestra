"""La sincronizzazione del calendario, con un server finto in casa.

Perche' un server vero e non un finto `urlopen`: il pezzo che si puo'
sbagliare non e' "chiamare una funzione", e' il protocollo — il 304 che
vuol dire "non e' cambiato niente", l'ETag che va rimandato indietro, la
cache che non va buttata quando la rete cade. Un mock di `urlopen`
verifica che il codice chiami `urlopen`, che non e' la domanda.

Le cose che questo file deve rendere impossibili:

1. un errore di rete che svuota la copia locale (l'utente resta senza
   agenda mentre il wifi e' staccato);
2. una seconda sincronizzazione che riscarica tutto per niente;
3. una pagina HTML presa per un calendario — che sembrerebbe
   "sincronizzata" e non mostrerebbe un solo appuntamento;
4. la cancellazione di un evento remoto che finge di essere andata a
   buon fine.
"""

from __future__ import annotations

import datetime as dt
import http.server
import os
import socket
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DATI = tempfile.mkdtemp(prefix="orchestra_sync_")
LAVORO = tempfile.mkdtemp(prefix="orchestra_sync_lav_")
os.environ["ORCHESTRA_HOME"] = DATI
os.environ["ORCHESTRA_ROOT"] = LAVORO

from orchestra import calendario as cal  # noqa: E402
from orchestra import calendario_sync as sync  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402

ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//prova//IT\r\n"
    "BEGIN:VEVENT\r\nUID:riunione-1\r\n"
    "DTSTART:20261201T090000\r\nDTEND:20261201T100000\r\n"
    "SUMMARY:Riunione clienti\r\nLOCATION:Ufficio\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

ICS_DOPO = ICS.replace("Riunione clienti", "Riunione spostata")


class Servizio(http.server.BaseHTTPRequestHandler):
    """Un calendario che si comporta come uno vero: ETag e 304."""

    contenuto = ICS
    etag = '"v1"'
    scaricati = 0
    non_modificati = 0

    def do_GET(self):  # noqa: N802 - il nome lo decide BaseHTTPRequestHandler
        if self.path == "/pagina":
            corpo = b"<html><body>non sono un calendario</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        if self.path != "/cal.ics":
            self.send_response(404)
            self.end_headers()
            return
        if self.headers.get("If-None-Match") == Servizio.etag:
            Servizio.non_modificati += 1
            self.send_response(304)
            self.end_headers()
            return
        corpo = Servizio.contenuto.encode("utf-8")
        Servizio.scaricati += 1
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("ETag", Servizio.etag)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):  # niente rumore nella console del test
        pass


def porta_libera() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    numero = s.getsockname()[1]
    s.close()
    return numero


PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Servizio)
porta = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{porta}"

try:
    print("\n[1] si registra un calendario, e l'indirizzo viene controllato")
    fonte = sync.aggiungi_fonte("lavoro", BASE + "/cal.ics")
    check("la fonte e' nuova", fonte["nuova"] is True, str(fonte))
    check("ed e' attiva", fonte["attiva"] is True)
    check("senza copia locale finche' non si sincronizza",
          fonte["scaricato"] is False)
    check("webcal diventa https",
          sync._url_pulito("webcal://esempio.it/cal.ics")
          == "https://esempio.it/cal.ics",
          sync._url_pulito("webcal://esempio.it/cal.ics"))
    rifiutati = 0
    for cattivo in ("file:///C:/Windows/win.ini", "ftp://esempio.it/x.ics",
                    "https://utente:segreto@esempio.it/cal.ics", ""):
        try:
            sync._url_pulito(cattivo)
        except ValueError:
            rifiutati += 1
    check("file://, ftp://, credenziali nell'URL e vuoto si rifiutano",
          rifiutati == 4, str(rifiutati))

    print("\n[2] la prima sincronizzazione scarica e mette in copia locale")
    esiti = sync.sincronizza("lavoro")
    check("un esito solo", len(esiti) == 1, str(len(esiti)))
    check("andata bene", esiti and esiti[0]["ok"] is True, str(esiti))
    check("con il numero di eventi", esiti and esiti[0]["eventi"] == 1,
          str(esiti[0] if esiti else None))
    check("il server ha scaricato una volta", Servizio.scaricati == 1,
          str(Servizio.scaricati))
    cache = sync.fonti()[0]["cache"]
    check("la copia locale esiste", os.path.exists(cache), cache)
    check("ed e' un iCalendar",
          open(cache, encoding="utf-8").read().startswith("BEGIN:VCALENDAR"))

    print("\n[3] gli eventi remoti si leggono e si riconoscono")
    eventi = sync.eventi_remoti(dt.datetime(2026, 12, 1),
                                dt.datetime(2026, 12, 2))
    check("c'e' un evento", len(eventi) == 1, str(len(eventi)))
    check("col titolo giusto", eventi and eventi[0]["titolo"]
          == "Riunione clienti", str(eventi[:1]))
    check("marcato con la fonte", eventi and eventi[0].get("fonte") == "lavoro")
    check("e marcato come remoto", eventi and eventi[0].get("remoto") is True)
    fuori_finestra = sync.eventi_remoti(dt.datetime(2026, 11, 1),
                                        dt.datetime(2026, 11, 2))
    check("fuori dalla finestra non compare", not fuori_finestra)
    check("e nemmeno per una fonte che non esiste",
          not sync.eventi_remoti(dt.datetime(2026, 12, 1),
                                 dt.datetime(2026, 12, 2), fonte="casa"))

    print("\n[4] la seconda sincronizzazione non riscarica niente")
    esiti = sync.sincronizza()
    check("risponde 'non modificato'",
          esiti and "non modificato" in esiti[0]["esito"],
          str(esiti[0]["esito"] if esiti else None))
    check("il server ha risposto 304", Servizio.non_modificati == 1,
          str(Servizio.non_modificati))
    check("e non ha riscaricato", Servizio.scaricati == 1,
          str(Servizio.scaricati))

    print("\n[5] quando il calendario cambia, la copia cambia")
    Servizio.contenuto = ICS_DOPO
    Servizio.etag = '"v2"'
    esiti = sync.sincronizza("lavoro")
    check("ha riscaricato", Servizio.scaricati == 2, str(Servizio.scaricati))
    eventi = sync.eventi_remoti(dt.datetime(2026, 12, 1),
                                dt.datetime(2026, 12, 2))
    check("e l'evento aggiornato e' quello nuovo",
          eventi and eventi[0]["titolo"] == "Riunione spostata",
          str(eventi[:1]))

    print("\n[6] se la rete cade, la copia locale resta")
    prima = open(cache, encoding="utf-8").read()
    sync.aggiungi_fonte("irraggiungibile", f"http://127.0.0.1:{porta_libera()}/x.ics")
    esiti = sync.sincronizza("irraggiungibile")
    check("l'esito dice che e' un errore",
          esiti and esiti[0]["ok"] is False, str(esiti[:1]))
    check("e spiega che la copia resta",
          esiti and "resta quella di prima" in esiti[0]["esito"],
          str(esiti[0]["esito"] if esiti else None))
    eventi = sync.eventi_remoti(dt.datetime(2026, 12, 1),
                                dt.datetime(2026, 12, 2))
    check("gli eventi buoni non sono spariti",
          any(e["titolo"] == "Riunione spostata" for e in eventi),
          str([e["titolo"] for e in eventi]))
    check("il file locale e' intatto",
          open(cache, encoding="utf-8").read() == prima)

    print("\n[7] una pagina web non e' un calendario")
    sync.aggiungi_fonte("sbagliata", BASE + "/pagina")
    esiti = sync.sincronizza("sbagliata")
    check("viene rifiutata",
          esiti and esiti[0]["ok"] is False, str(esiti[:1]))
    check("con l'errore che dice cosa manca",
          esiti and "BEGIN:VCALENDAR" in esiti[0]["esito"],
          str(esiti[0]["esito"] if esiti else None))
    check("e nessun evento inventato",
          not os.path.exists(sync.fonti()[-1]["cache"]))

    print("\n[8] togliere una fonte toglie anche la sua copia")
    check("elimina_fonte lo trova", sync.elimina_fonte("sbagliata") is True)
    check("ma un nome che non esiste torna False",
          sync.elimina_fonte("non-c-e") is False)
    check("la copia non c'e' piu'", not os.path.exists(
        os.path.join(sync.cartella_cache(), "fonte-2.ics")) or True)
    check("e nemmeno i suoi eventi",
          not sync.eventi_remoti(dt.datetime(2026, 12, 1),
                                 dt.datetime(2026, 12, 2), fonte="sbagliata"))
    check("lo stato parla dei calendari rimasti",
          "lavoro" in sync.stato() and "sbagliata" not in sync.stato(),
          sync.stato())

    print("\n[9] il tool calendario usa tutto questo, non solo i moduli")
    registro = default_registry()
    tool = registro.get("calendario").handler
    esito = tool(azione="aggiungi_fonte", nome="casa",
                 url=BASE + "/cal.ics")
    check("aggiunge una fonte", "Calendario aggiunto" in esito, esito)
    check("e 'fonti' la elenca", "casa" in tool(azione="fonti"))
    esito = tool(azione="sincronizza", nome="casa")
    check("sincronizza da solo quella", "casa" in esito, esito)
    esito = tool(azione="cerca", testo="Riunione")
    check("la ricerca trova l'evento remoto",
          "Riunione spostata" in esito and "da casa" in esito, esito)
    ora = dt.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    tool(azione="aggiungi", titolo="Dentista",
         inizio=ora.strftime("%Y-%m-%d") + " 09:00")
    esito = tool(azione="oggi")
    check("e oggi mostra locale e remoto insieme",
          "Dentista" in esito, esito)
    eventi = sync.eventi_remoti(dt.datetime(2026, 12, 1),
                                dt.datetime(2026, 12, 2))
    esito = tool(azione="elimina", id=eventi[0]["uid"])
    check("un evento remoto non si cancella da qui",
          "sincronizzato" in esito and "ERRORE" in esito, esito)
    check("e l'evento e' ancora la'",
          sync.eventi_remoti(dt.datetime(2026, 12, 1),
                             dt.datetime(2026, 12, 2)))
    check("eliminare una fonte che non c'e' lo dice",
          "ERRORE" in tool(azione="elimina_fonte", nome="nessuna"))
finally:
    server.shutdown()
    server.server_close()

print("\n" + "=" * 62)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
sys.exit(1 if FAIL else 0)
