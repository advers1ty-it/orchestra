"""Il server di test, avviato dal runner e chiuso alla fine.

Le suite che parlano col server vero (allegati, categorie, prezzi, skill UI,
permessi) hanno bisogno di qualcosa che risponda sulla porta 8737. Prima
esistevano due modi, e nessuno dei due era giusto:

- il server era gia' acceso, e allora le suite funzionavano, ma solo se
  per caso non c'era un turno aperto: un 409 vuol dire "occupato", e il
  test lo leggeva come "il server non accetta il file";
- il server non era acceso, e allora le suite fallivano con "connessione
  rifiutata", che sembrava un difetto del codice.

E' la stessa forma del problema che questo runner si e' fatto carico
risolvere per i test che non partono: un test che non ha l'ambiente giusto
segnala un difetto che non c'e'. Un test che segnala difetti inesistenti
e' peggio di un test assente, perche' fa perdere tempo a guardarli.

Qui il server parte da solo, su una porta libera, con un ORCHESTRA_HOME
separato: la cronologia dell'utente non viene toccata, e due suite non
possono litigare per lo stesso turno. La porta la dice l'ambiente, e i
test la leggono (ORCHESTRA_TEST_PORT): chi non la legge resta sul 8737 e
funziona come prima, se il server di sviluppo e' acceso.

Un server che non parte non e' un test rosso: e' un test che non puo'
girare, e si dice. Il runner lo chiude sempre, anche se una suite e' andata
storta.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Le suite HTTP che non hanno bisogno di un turno vero funzionano anche
# senza server: ma per quelle che fanno POST, il server e' la premessa.
# Non e' un "test opzionale": e' l'ambiente in cui il test gira.
PORTA_PREDEFINITA = 8737


def porta_libera() -> int:
    """Una porta libera, cercata dal sistema.

    Non si sceglie un numero a caso: si chiede al sistema una porta che
    nessuno sta usando, e si verifica che sia davvero libera. Il numero
    e' casuale perche' uno fisso puo' essere occupato proprio nella
    corsa, e allora il fallimento sarebbe un "connessione rifiutata" che
    nessuno saprebbe spiegare.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _risponde(porta: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{porta}/api/state", timeout=timeout) as f:
            return f.status == 200
    except Exception:
        return False


class ServerDiTest:
    """Un server Orchestra vivo per la durata della suite."""

    def __init__(self, porta: int, processo: subprocess.Popen,
                 home: str) -> None:
        self.porta = porta
        self.processo = processo
        self.home = home

    def chiudi(self) -> None:
        """Chiude il server. Sempre: anche dopo un errore."""
        try:
            self.processo.terminate()
            try:
                self.processo.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.processo.kill()
                self.processo.wait(timeout=5)
        except Exception:
            pass


def avvia(porta: int | None = None) -> tuple[ServerDiTest | None, str]:
    """Avvia il server di test. Ritorna (server, motivo_del_ritorno).

    Il motivo e' una stringa leggibile perche' la ragione per cui il
    server non parte e' la cosa che il lettore deve sapere: "non e'
    partito" e "non ha potuto partire" sono due fatti diversi.
    """
    if porta is None:
        porta = porta_libera()

    # La porta deve essere LIBERA: se qualcuno risponde gia', non e' un
    # server di test, e usarlo significherebbe parlare con l'applicazione
    # dell'utente (o con un'altra suite) per un test che pretende il
    # contrario. In quel caso si dice e si rinuncia.
    if _risponde(porta, timeout=1.0):
        return None, (f"la porta {porta} e' gia' occupata da un altro "
                      f"server: i test HTTP avrebbero parlato con quello")

    home = os.path.join(HERE, "_dati_test_server")
    os.makedirs(home, exist_ok=True)

    env = dict(os.environ)
    env["ORCHESTRA_HOME"] = home
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"

    script = os.path.join(HERE, "_server_serve.py")
    try:
        proc = subprocess.Popen(
            [sys.executable, script, str(porta)],
            cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:  # noqa: BLE001
        return None, f"non e' partito il processo: {type(e).__name__}: {e}"

    # Si aspetta che risponda: un server che parte ma non serve non
    # serve, e far partire le suite contro un server morto darebbe
    # "connessione rifiutata" su tutto.
    for _ in range(60):
        if proc.poll() is not None:
            out = ""
            try:
                out = (proc.stdout.read() or "")[-800:]
            except Exception:
                pass
            return None, (f"il server e' uscito subito "
                          f"(codice {proc.returncode}){out}")
        if _risponde(porta, timeout=1.0):
            return ServerDiTest(porta, proc, home), ""
        time.sleep(0.5)

    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        pass
    return None, (f"il server non ha risposto entro 30s sulla porta {porta}")
