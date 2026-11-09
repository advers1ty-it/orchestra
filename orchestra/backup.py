"""Backup e ripristino dei dati di Orchestra.

Cosa salva, e cosa no. Salva la cartella dati — cronologia, memoria,
bot, lavori, collegamenti Telegram, budget, cron — e, se richiesto, il
`.env` con le chiavi, che senza un backup vanno reinserite a mano una
per una. Non salva il codice: quello si reinstalla, e copiarlo sopra
un'altra versione sarebbe proprio il guasto da cui si sta scappando.

Perche' i database non si copiano con `shutil.copy`. Con il journal WAL
il `.db` da solo puo' non contenere le ultime scritture: la copia
sembra completa, il backup "riesce", e l'incompletezza si scopre al
ripristino — cioe' nel momento peggiore. Si usa l'API di backup di
sqlite3, che legge da una connessione e produce un file consistente.

Il ripristino fa un backup di sicurezza PRIMA di toccare qualsiasi cosa.
Un ripristino che va storto non deve lasciare l'utente con meta' dei
dati di ieri e meta' di oggi, e senza il file di prima.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from typing import Any

from . import __version__
from .dati import cartella_dati, percorso
from .percorsi import ENV_PATH

# La versione del formato dell'archivio. Un archivio con un numero
# diverso non si apre "sperando che vada": si dice che e' di un'altra
# versione e si lascia stare i dati.
FORMATO = 1

# I file che il journal WAL lascia accanto al database. Non si salvano —
# sono il journal, non i dati — ma al ripristino vanno tolti: un -wal
# vecchio accanto a un .db nuovo confonde sqlite al primo avvio.
JOURNAL = ("-wal", "-shm", "-journal")

ESTENSIONI_DB = (".db", ".sqlite3")


def _adesso() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _db(percorso_file: str) -> bool:
    return percorso_file.lower().endswith(ESTENSIONI_DB)


def _copia_db(origine: str, destinazione: str) -> None:
    """Copia un database in modo consistente, anche con il WAL attivo."""
    src = sqlite3.connect(origine)
    try:
        dst = sqlite3.connect(destinazione)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def elenco(con_chiavi: bool = True) -> list[dict[str, Any]]:
    """Cosa finirebbe nell'archivio. Non lo crea: lo elenca.

    Serve a poter dire all'utente cosa sta salvando prima di salvarlo, e
    a fare un controllo vero dopo. Una lista di file che esiste solo
    dentro `crea` non la si puo' né mostrare né verificare.
    """
    cartella = cartella_dati()
    voci: list[dict[str, Any]] = []
    try:
        nomi = sorted(os.listdir(cartella))
    except OSError:
        nomi = []
    for nome in nomi:
        pieno = os.path.join(cartella, nome)
        if not os.path.isfile(pieno):
            continue
        if any(nome.lower().endswith(j) for j in JOURNAL):
            continue
        try:
            byte = os.path.getsize(pieno)
        except OSError:
            byte = 0
        voci.append({"nome": nome, "byte": byte, "chiavi": False})
    if con_chiavi and os.path.isfile(ENV_PATH):
        try:
            byte = os.path.getsize(ENV_PATH)
        except OSError:
            byte = 0
        voci.append({"nome": ".env", "byte": byte, "chiavi": True})
    return voci


def crea(destinazione: str = "", *, con_chiavi: bool = True) -> dict[str, Any]:
    """Scrive un archivio con tutti i dati. Torna dove e cosa.

    La destinazione predefinita e' una cartella `backup` dentro la
    cartella dati: un file creato dove capita (la cartella del progetto,
    il Desktop) finisce nel primo `git add` o nella prima pulizia.
    """
    cartella = cartella_dati()
    if not (destinazione or "").strip():
        base = os.path.join(cartella, "backup")
        os.makedirs(base, exist_ok=True)
        destinazione = os.path.join(base, f"orchestra-{_adesso()}.zip")
    destinazione = os.path.abspath(os.path.expanduser(destinazione))
    os.makedirs(os.path.dirname(destinazione) or ".", exist_ok=True)

    voci = elenco(con_chiavi)
    if not voci:
        raise RuntimeError("non c'e' niente da salvare: la cartella dati e' vuota")

    manifesto = {
        "formato": FORMATO,
        "versione": __version__,
        "creato": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "con_chiavi": bool(con_chiavi and os.path.isfile(ENV_PATH)),
        "file": [{"nome": v["nome"], "byte": v["byte"]} for v in voci],
    }

    with zipfile.ZipFile(destinazione, "w", zipfile.ZIP_DEFLATED) as z:
        for voce in voci:
            nome = voce["nome"]
            if voce["chiavi"]:
                z.write(ENV_PATH, "config/.env")
                continue
            origine = os.path.join(cartella, nome)
            if _db(origine):
                # In una cartella temporanea: `zip.write` vuole un file
                # gia' completo, e il backup di sqlite ne produce uno.
                fd, temporaneo = tempfile.mkstemp(suffix=".db")
                os.close(fd)
                try:
                    _copia_db(origine, temporaneo)
                    z.write(temporaneo, "dati/" + nome)
                finally:
                    try:
                        os.remove(temporaneo)
                    except OSError:
                        pass
            else:
                z.write(origine, "dati/" + nome)
        z.writestr("MANIFEST.json",
                   json.dumps(manifesto, ensure_ascii=False, indent=2))

    return {
        "percorso": destinazione,
        "file": len(voci),
        "byte": os.path.getsize(destinazione),
        "con_chiavi": manifesto["con_chiavi"],
        "creato": manifesto["creato"],
    }


def _manifesto(z: zipfile.ZipFile) -> dict[str, Any]:
    try:
        dati = json.loads(z.read("MANIFEST.json").decode("utf-8"))
    except KeyError:
        raise RuntimeError(
            "questo archivio non e' un backup di Orchestra: manca "
            "MANIFEST.json") from None
    except (ValueError, UnicodeDecodeError):
        raise RuntimeError("il MANIFEST.json dell'archivio e' illeggibile") from None
    if int(dati.get("formato") or 0) != FORMATO:
        raise RuntimeError(
            f"backup in un formato che questa versione non conosce "
            f"({dati.get('formato')!r}, atteso {FORMATO})")
    return dati


def _sicuro(nome: str) -> bool:
    """Un nome di file dentro l'archivio che non esce dalla cartella dati."""
    if not nome or nome.startswith("/") or "\\" in nome:
        return False
    parti = nome.split("/")
    return bool(parti) and all(p not in ("", ".", "..") for p in parti)


def ripristina(archivio: str, *, con_chiavi: bool = True) -> dict[str, Any]:
    """Rimette i dati di un archivio. Torna cosa ha scritto e la sicurezza.

    Un ripristino sovrascrive: e' quello che significa. Per non
    trasformare un archivio sbagliato in dati persi, prima si salva lo
    stato attuale — se la sicurezza non si riesce a creare, non si
    ripristina niente.
    """
    archivio = os.path.abspath(os.path.expanduser(archivio))
    if not os.path.isfile(archivio):
        raise RuntimeError(f"archivio non trovato: {archivio}")
    with zipfile.ZipFile(archivio) as z:
        manifesto = _manifesto(z)
        nomi = [n for n in z.namelist() if n.startswith("dati/") and _sicuro(n)]
        if not nomi:
            raise RuntimeError("l'archivio non contiene dati")

        # Backup di sicurezza PRIMA di toccare: se fallisce, si smette.
        # Su una home vuota non c'e' niente da proteggere, e non e' un
        # errore: e' il primo ripristino su un computer nuovo.
        try:
            sicurezza = crea("", con_chiavi=bool(con_chiavi))
        except RuntimeError:
            if elenco(con_chiavi=False):
                raise
            sicurezza = {"percorso": ""}
        cartella = cartella_dati()
        scritti: list[str] = []
        for nome in nomi:
            destinazione = os.path.join(cartella, nome[len("dati/"):])
            os.makedirs(os.path.dirname(destinazione) or cartella,
                        exist_ok=True)
            if _db(destinazione):
                # I journal di un database vecchio non valgono per quello
                # nuovo: lasciarli significa far leggere a sqlite pagine
                # che non c'entrano.
                for suffisso in JOURNAL:
                    try:
                        os.remove(destinazione + suffisso)
                    except OSError:
                        pass
            with z.open(nome) as src, open(destinazione, "wb") as dst:
                shutil.copyfileobj(src, dst)
            scritti.append(os.path.basename(destinazione))

        chiavi = False
        if con_chiavi and "config/.env" in z.namelist():
            with z.open("config/.env") as src:
                dati = src.read()
            with open(ENV_PATH, "wb") as dst:
                dst.write(dati)
            chiavi = True

    return {
        "ripristinati": len(scritti),
        "file": scritti,
        "sicurezza": sicurezza["percorso"],
        "chiavi": chiavi,
        "versione": manifesto.get("versione") or "",
        "creato": manifesto.get("creato") or "",
    }


def posizione_predefinita() -> str:
    """Dove finisce un backup se non si dice altro. Solo per mostrarlo."""
    return os.path.join(cartella_dati(), "backup")


def _non_usato() -> str:
    # `percorso` non serve piu' qui (si usa la cartella direttamente),
    # ma l'import resta perche' e' l'unica funzione che garantisce che la
    # cartella esista anche quando si chiede solo `elenco`.
    return percorso("backup")
