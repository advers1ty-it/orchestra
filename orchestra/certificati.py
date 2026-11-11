"""Le autorita' di certificazione che servono a Orchestra, e come si guarda.

Perche' questo modulo esiste.

Orchestra parla HTTPS con la standard library (`urllib`), e la standard
library **non porta con se' un elenco di CA**: su Windows interroga il trust
store di sistema (`ssl.enum_certificates("ROOT")`), che e' esattamente il
posto da cui Windows prende i certificati per il browser. Un Windows appena
installato pero' non ha tutte le radici: ha quelle dell'immagine di
installazione, e le altre arrivano da Windows Update, che su una macchina
nuova non e' ancora passato.

Il sintomo e' cattivo, perche' non somiglia alla sua causa.
`api.telegram.org` manda la catena **completa**, root self-signed compresa
(verificato: tre certificati, l'ultimo e' `Go Daddy Root Certificate
Authority - G2` firmato da se stesso). Se quella root non e' nello store,
OpenSSL risponde `CERTIFICATE_VERIFY_FAILED: self-signed certificate in
certificate chain`, `telegram.py` lo riporta come "rete non raggiungibile",
e chi legge va a cercare firewall e proxy mentre il guasto e' un elenco di
certificati incompleto.

Sta qui e non dentro `telegram.py` perche' serve a due chiamanti diversi:
l'errore dell'app deve poter dire "certificato", e l'installer deve poterlo
controllare **prima** che l'utente arrivi al token del bot. Una copia della
logica in due posti e' il modo in cui i due messaggi divergono.

Si esegue anche come file (`python orchestra/certificati.py`), non solo come
modulo: l'installer lo lancia cosi' per non importare il pacchetto, che
all'import fa la migrazione dei dati e registra l'installazione. Guardare
dei certificati non deve avere effetti collaterali.
"""

from __future__ import annotations

import os
import sys

if __name__ == "__main__" and os.path.dirname(os.path.abspath(__file__)) in sys.path:
    # Eseguito come file, la sua cartella e' in sys.path e copre la stdlib
    # (`orchestra/types.py` oscura `types`, e l'import di `re` dentro `enum`
    # muore con "partially initialized module"). Stessa riga di update.py,
    # stesso motivo, prima di qualsiasi altro import: e' quello che
    # permette all'installer di chiamarlo senza importare il pacchetto.
    sys.path.remove(os.path.dirname(os.path.abspath(__file__)))

import hashlib
import json
import socket
import ssl
import tempfile
from pathlib import Path

WINDOWS = sys.platform.startswith("win")

# Le radici che servono davvero, con l'impronta SHA-1 del certificato DER —
# cioe' il "thumbprint" che Windows mostra nella finestra del certificato.
# Si confronta con l'impronta e non col nome: il nome e' un testo, e un
# testo si puo' scrivere in due modi ("Go Daddy" / "GoDaddy") senza che sia
# un altro certificato. L'impronta e' il certificato.
RADICI = (
    {
        "nome": "Go Daddy Root Certificate Authority - G2",
        "sha1": "47BEABC922EAE80E78783462A79F45C254FDE68B",
        "host": "api.telegram.org",
        "perche": "bot Telegram (api.telegram.org)",
        "nota": "Telegram la manda dentro la catena: se manca, la catena "
                "finisce in un certificato self-signed che OpenSSL rifiuta",
    },
)

# Cosa dicono i tre esiti di `prova`. Sono tre perche' sono tre rimedi
# diversi: aggiornare le radici, installare la CA dell'intercettore,
# o guardare la rete.
ESITI = {
    "ok": "collegamento verificato",
    "certificato": "certificato non attendibile",
    "rete": "rete non raggiungibile",
}


def impronte() -> dict[str, str] | None:
    """Le impronte SHA-1 delle radici nello store di sistema, o None.

    `ssl.enum_certificates` esiste solo su Windows: e' l'unico sistema in
    cui Python prende le CA dal sistema invece che da un file. Altrove
    (macOS, Linux) c'e' un file di CA e il problema non si presenta, quindi
    None qui vuol dire "non c'e' niente da controllare", non "errore".
    """
    elenca = getattr(ssl, "enum_certificates", None)
    if elenca is None:
        return None
    try:
        voci = elenca("ROOT") or []
    except Exception:  # noqa: BLE001 - uno store illeggibile e' "non so", non un guasto
        return None
    fuori: dict[str, str] = {}
    for voce in voci:
        der = voce[0]
        fuori[hashlib.sha1(der).hexdigest().upper()] = "ROOT"
    return fuori


def stato(radici: tuple[dict, ...] = RADICI) -> dict:
    """Quali radici richieste ci sono e quali mancano.

    `radici` e' un parametro e non una costante letta dentro solo perche'
    i test devono poter chiedere di una radice che non esiste: provare il
    ramo "manca" con la radice vera significherebbe provarlo solo sulle
    macchine rotte, cioe' mai.
    """
    trovate = impronte()
    voci: list[dict] = []
    mancanti: list[str] = []
    for radice in radici:
        presente = bool(trovate) and radice["sha1"].upper() in trovate
        voci.append({**radice, "presente": presente})
        if not presente:
            mancanti.append(radice["nome"])
    return {
        "sistema": sys.platform,
        "store": "Windows ROOT" if trovate is not None else "non disponibile",
        "voci": len(trovate or {}),
        "radici": voci,
        "mancanti": mancanti,
    }


def prova(host: str, secondi: float = 8.0) -> tuple[str, str]:
    """Handshake vero con `host`: ("ok" | "certificato" | "rete", dettaglio).

    Serve a distinguere i due casi che l'utente vede uguali. `urllib`
    trasforma tutto in un errore di rete; qui il certificato ha un tipo
    suo (`SSLCertVerificationError`), e un errore di verifica non e' un
    timeout: il server ha risposto.
    """
    contesto = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=secondi) as grezzo:
            with contesto.wrap_socket(grezzo, server_hostname=host) as tls:
                tls.getpeercert()
        return "ok", ""
    except ssl.SSLCertVerificationError as e:
        return "certificato", str(e)
    except (ssl.SSLError, OSError) as e:
        return "rete", f"{type(e).__name__}: {e}"


def ripara(destinazione: Path | None = None) -> tuple[bool, str]:
    """Scarica le radici da Windows Update e le importa nello store.

    Le due meta' sono diverse di permessi: `-generateSSTFromWU` scrive solo
    un file e funziona da utente normale, `-addstore -f root` tocca lo store
    di sistema e senza amministratore risponde "accesso negato". L'installer
    le lancia da una finestra elevata per questo, e il messaggio d'errore
    deve dirlo: "non riuscito" senza "serve amministratore" manda a cercare
    un problema di rete che non c'e'.
    """
    if not WINDOWS:
        return False, "solo Windows ha uno store di sistema da aggiornare"
    import subprocess

    percorso = Path(destinazione or (Path(tempfile.gettempdir())
                                     / "orchestra-radici.sst"))
    try:
        scarica = subprocess.run(
            ["certutil", "-generateSSTFromWU", str(percorso)],
            text=True, capture_output=True, timeout=300)
    except FileNotFoundError:
        return False, "certutil non trovato: non e' un Windows completo?"
    except subprocess.TimeoutExpired:
        return False, "download delle radici troppo lento (300s)"
    if scarica.returncode != 0 or not percorso.exists():
        return False, ("download delle radici non riuscito (Windows Update "
                       "raggiungibile?): " + _coda(scarica))
    try:
        importa = subprocess.run(
            ["certutil", "-addstore", "-f", "root", str(percorso)],
            text=True, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        return False, "importazione delle radici troppo lenta (300s)"
    finally:
        try:
            percorso.unlink()
        except OSError:
            pass
    if importa.returncode != 0:
        return False, ("importazione non riuscita (serve amministratore): "
                       + _coda(importa))
    return True, "radici scaricate e importate nello store di sistema"


def _coda(esito) -> str:  # noqa: ANN001 - CompletedProcess, senza import a vuoto
    """Le ultime righe dell'output, che sono quelle che dicono il perche'."""
    righe = ((esito.stdout or "") + (esito.stderr or "")).strip().splitlines()
    return " ".join(riga.strip() for riga in righe[-3:]) or f"codice {esito.returncode}"


def report(dati: dict) -> str:
    """Il referto da console: ASCII puro, di proposito.

    La console dell'installer non e' UTF-8 (codepage 850/1252): un trattino
    lungo o un accento fanno fallire la stampa con UnicodeEncodeError, e
    l'installer vedrebbe un errore di Python al posto del referto.
    """
    a_posto = len(dati["radici"]) - len(dati["mancanti"])
    righe = [f"certificati: {a_posto}/{len(dati['radici'])} a posto "
             f"(store: {dati['store']})"]
    for voce in dati["radici"]:
        segno = "ok   " if voce["presente"] else "MANCA"
        righe.append(f"  {segno} {voce['nome']} - {voce['perche']}")
    if dati["mancanti"]:
        righe.append("  Per aggiungerle, da PowerShell come amministratore:")
        righe.append('    certutil -generateSSTFromWU "%TEMP%\\radici.sst"')
        righe.append('    certutil -addstore -f root "%TEMP%\\radici.sst"')
    return "\n".join(righe)


def _main(argv: list[str]) -> int:
    if "--json" in argv:
        dati = stato()
        print(json.dumps(dati, indent=2))
        return 1 if dati["mancanti"] else 0
    if "--ripara" in argv:
        fatto, messaggio = ripara()
        print(messaggio)
        dati = stato()
        print(report(dati))
        return 0 if fatto and not dati["mancanti"] else 1
    if "--prova" in argv:
        posizione = argv.index("--prova")
        host = argv[posizione + 1] if len(argv) > posizione + 1 else RADICI[0]["host"]
        esito, dettaglio = prova(host)
        print(f"{ESITI[esito]}: {host}" + (f" - {dettaglio}" if dettaglio else ""))
        return 0 if esito == "ok" else 1
    dati = stato()
    print(report(dati))
    return 1 if dati["mancanti"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
