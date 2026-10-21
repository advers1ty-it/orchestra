"""Il browser scarica piu' file sullo stesso collegamento HTTP/1.1.

curl ne chiede uno alla volta. Il browser, dopo index.html, ne chiede
 quattro in parallelo — spesso riutilizzando una connessione sola.

Se il server tiene la connessione aperta (HTTP/1.1) e sbaglia qualcosa
nella risposta, il browser blocca i file successivi. Testiamo quindi
esattamente quello: una connessione, piu' richieste in sequenza.
"""

import socket
import sys
import time

import os
HOST, PORT = "127.0.0.1", int(os.environ.get("ORCHESTRA_TEST_PORT", "8737"))


def raw_get(sock, path):
    """Una richiesta HTTP/1.1 sulla connessione data."""
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120\r\n"
        "Accept: */*\r\n"
        "Connection: keep-alive\r\n"
        "\r\n"
    )
    sock.sendall(req.encode())
    # leggiamo gli header
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            return None, b"", b"connessione chiusa prima degli header"
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0]
    hdrs = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, _, v = ln.partition(":")
            hdrs[k.strip().lower()] = v.strip()

    n = int(hdrs.get("content-length", "0"))
    body = rest
    while len(body) < n:
        chunk = sock.recv(4096)
        if not chunk:
            break
        body += chunk
    return status, hdrs, body[:n]


print("=== 1) una connessione, quattro richieste in sequenza ===")
s = socket.create_connection((HOST, PORT), timeout=15)
s.settimeout(15)
try:
    for path in ["/", "/app.css", "/core.js", "/panels.js", "/main.js"]:
        t0 = time.time()
        status, hdrs, body = raw_get(s, path)
        dt = (time.time() - t0) * 1000
        if status is None:
            print(f"  {path:14} FALLITO: {body}")
            break
        declared = hdrs.get("content-length", "?")
        ctype = hdrs.get("content-type", "?")
        flag = "" if declared == str(len(body)) else "  <<< CONTENT-LENGTH DIVERSO!"
        print(f"  {path:14} {status.split(' ',1)[1]:8} "
              f"len={declared:>6} ricevuti={len(body):>6} {dt:5.0f}ms {ctype[:34]}{flag}")
finally:
    s.close()

print("\n=== 2) connessioni separate, come se il browser le usasse in parallelo ===")
socks = []
try:
    for path in ["/app.css", "/core.js", "/panels.js", "/main.js"]:
        try:
            sk = socket.create_connection((HOST, PORT), timeout=15)
            sk.settimeout(15)
            socks.append(sk)
            status, hdrs, body = raw_get(sk, path)
            ok = len(body) > 0
            print(f"  {path:14} {status.split(' ',1)[1]:8} "
                  f"{len(body):>6} byte  {'ok' if ok else 'VUOTO'}")
        except Exception as e:
            print(f"  {path:14} ERRORE: {type(e).__name__}: {e}")
finally:
    for sk in socks:
        sk.close()

print("\n=== 3) il server regge richieste ripetute? (100 in sequenza) ===")
s = socket.create_connection((HOST, PORT), timeout=15)
s.settimeout(15)
ok = fail = 0
try:
    for i in range(100):
        try:
            status, hdrs, body = raw_get(s, "/core.js")
            if status and len(body) == int(hdrs.get("content-length", "-1")) and len(body) > 0:
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
            break
    print(f"  riuscite {ok}/100, fallite {fail}")
    if fail:
        print("  -> il server si e' rotto: e' questo il bug")
finally:
    s.close()
