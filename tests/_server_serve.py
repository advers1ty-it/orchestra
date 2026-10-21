"""Il server che `_server.py` avvia per le suite HTTP.

Vive in un file separato perche' deve girare in un processo diverso dal
runner: il runner e' il padre, e se il server morisse il runner saprebbe
solo dal codice di uscita. Qui il server parte, dice "sono in piedi" e
serve.

Il silenzio e' voluto: il server scrive su stdout, e il runner lo legge
solo se il server muore. Se il server parlasse durante la suite, il suo
output si mescolerebbe a quello dei test, e una riga di log sembrerebbe
un errore.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.webapp import Handler, ThreadingHTTPServer  # noqa: E402
from orchestra import webapp  # noqa: E402


def main() -> int:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8737
    app = webapp.OrchestraApp.create()
    Handler.app = app
    httpd = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    httpd.daemon_threads = True
    print(f"server di test su {porta}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
