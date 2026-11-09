"""Backup e ripristino dei dati di Orchestra.

Cosa salva, e cosa no. Salva la cartella dati di UN'INSTALLAZIONE —
cronologia, memoria, bot, lavori, collegamenti Telegram, budget, cron —
e, se richiesto, il `.env` con le chiavi. Non salva il codice: quello si
reinstalla, e copiarlo sopra un'altra versione sarebbe proprio il guasto
da cui si sta scappando.

PIU' INSTALLAZIONI

Orchestra tiene i dati separati per installazione, in una sottocartella
per ciascuna: e' giusto, perche' due copie in due cartelle diverse non
sono la stessa cosa. Ma l'hash di quella sottocartella non dice a quale
percorso corrisponde, e chi ha l'installazione in AppData, una su D: e
due server di prova non puo' scegliere "quale salvare" guardando un
codice. Percio' ogni cartella dati porta un `installazione.json` con il
percorso scritto dentro, e qui si puo' elencare, scegliere e salvare
tutte le installazioni — per percorso, non per hash.

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
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from typing import Any

from . import __version__
from .dati import cartella_dati, installazioni
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


class InstallazioneSconosciuta(RuntimeError):
    """Il profilo chiesto non e' una di quelle installazioni."""


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


# ---------------------------------------------------------------------------
# Quale installazione
# ---------------------------------------------------------------------------

def _voce(percorso_dati: str) -> dict[str, Any]:
    """La voce di `installazioni()` che corrisponde a questa cartella."""
    cercata = os.path.abspath(percorso_dati)
    for voce in installazioni():
        if os.path.abspath(voce["dati"]) == cercata:
            return voce
    return {"id": os.path.basename(cercata.rstrip("\\/")), "dati": cercata,
            "percorso": "", "corrente": False, "file": 0, "byte": 0,
            "modificato": 0.0}


def _dati(installazione: str | None) -> str:
    """Da un id, un percorso o niente, alla cartella dati giusta.

    Accetta il percorso dell'installazione (`D:\\orchestra`), il percorso
    della cartella dati, o l'id della cartella: sono le tre cose che
    l'utente ha sotto gli occhi, e chiedergli proprio l'unica che non
    puo' ricordare (l'hash) sarebbe una domanda senza risposta.
    """
    scelta = str(installazione or "").strip()
    if not scelta:
        return cartella_dati()
    if os.path.isdir(scelta):
        return os.path.abspath(scelta)
    normalizzata = os.path.normcase(os.path.abspath(scelta))
    for voce in installazioni():
        if os.path.normcase(voce["dati"]) == normalizzata:
            return voce["dati"]
        if os.path.normcase(os.path.abspath(voce["id"])) == normalizzata:
            return voce["dati"]
        if voce.get("percorso") and os.path.normcase(
                os.path.abspath(voce["percorso"])) == normalizzata:
            return voce["dati"]
    raise InstallazioneSconosciuta(
        f"installazione sconosciuta: {scelta}. Usa `orchestra backup --elenco` "
        "per vedere quali ci sono, con i loro percorsi.")


def _env_per(percorso_dati: str) -> str:
    """Il `.env` di quella installazione, se si sa dov'e'.

    Il `.env` sta nella cartella del codice, non in quella dei dati: per
    una installazione diversa dalla corrente lo si ricava dal percorso
    registrato. Se non c'e', si salva senza chiavi invece di prendere
    per sbaglio quelle di un'altra installazione.
    """
    if os.path.abspath(percorso_dati) == os.path.abspath(cartella_dati()):
        return ENV_PATH
    voce = _voce(percorso_dati)
    radice = str(voce.get("percorso") or "")
    if not radice:
        return ""
    candidato = os.path.join(radice, "orchestra", ".env")
    return candidato if os.path.isfile(candidato) else ""


def _nome_sicuro(testo: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", testo).strip("-.")[:40] or "profilo"


def _nome_libero(percorso: str) -> str:
    """Un nome che non esiste ancora, con un contatore se serve.

    Due backup nello stesso secondo ("Salva tutti" subito dopo "Salva
    questa") scriverebbero lo STESSO file. Non e' solo un backup perso:
    il ripristino apre l'archivio, poi crea il backup di sicurezza, e se
    quel nome coincide con l'archivio che sta leggendo lo tronca mentre
    lo legge — con l'archivio corrotto a meta' strada.
    """
    if not os.path.exists(percorso):
        return percorso
    radice, estensione = os.path.splitext(percorso)
    for n in range(2, 1000):
        candidato = f"{radice}-{n}{estensione}"
        if not os.path.exists(candidato):
            return candidato
    return f"{radice}-{int(time.time())}{estensione}"


# ---------------------------------------------------------------------------
# Contenuto
# ---------------------------------------------------------------------------

def elenco(con_chiavi: bool = True,
           installazione: str | None = None) -> list[dict[str, Any]]:
    """Cosa finirebbe nell'archivio. Non lo crea: lo elenca.

    Serve a poter dire all'utente cosa sta salvando prima di salvarlo, e
    a fare un controllo vero dopo. Una lista di file che esiste solo
    dentro `crea` non la si puo' ne' mostrare ne' verificare.
    """
    cartella = _dati(installazione)
    env_file = _env_per(cartella) if con_chiavi else ""
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
    if env_file and os.path.isfile(env_file):
        try:
            byte = os.path.getsize(env_file)
        except OSError:
            byte = 0
        voci.append({"nome": ".env", "byte": byte, "chiavi": True})
    return voci


def crea(destinazione: str = "", *, con_chiavi: bool = True,
         installazione: str | None = None) -> dict[str, Any]:
    """Scrive un archivio con i dati di un'installazione. Torna dove e cosa.

    La destinazione predefinita e' una cartella `backup` dentro la
    cartella dati di QUELL'installazione: un file creato dove capita (la
    cartella del progetto, il Desktop) finisce nel primo `git add` o
    nella prima pulizia.
    """
    cartella = _dati(installazione)
    voce = _voce(cartella)
    env_file = _env_per(cartella) if con_chiavi else ""
    if not (destinazione or "").strip():
        base = os.path.join(cartella, "backup")
        os.makedirs(base, exist_ok=True)
        etichetta = _nome_sicuro(os.path.basename(cartella.rstrip("\\/")))
        destinazione = _nome_libero(
            os.path.join(base, f"orchestra-{etichetta}-{_adesso()}.zip"))
    destinazione = os.path.abspath(os.path.expanduser(destinazione))
    os.makedirs(os.path.dirname(destinazione) or ".", exist_ok=True)

    voci = elenco(con_chiavi, installazione=cartella)
    if not voci:
        raise RuntimeError("non c'e' niente da salvare: la cartella dati e' vuota")

    manifesto = {
        "formato": FORMATO,
        "versione": __version__,
        "creato": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "con_chiavi": bool(voci and any(v["chiavi"] for v in voci)),
        "installazione": {
            "id": voce.get("id") or "",
            "dati": cartella,
            "percorso": voce.get("percorso") or "",
        },
        "file": [{"nome": v["nome"], "byte": v["byte"]} for v in voci],
    }

    with zipfile.ZipFile(destinazione, "w", zipfile.ZIP_DEFLATED) as z:
        for voce_file in voci:
            nome = voce_file["nome"]
            if voce_file["chiavi"]:
                z.write(env_file, "config/.env")
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
        "installazione": voce.get("id") or os.path.basename(cartella),
        "profilo": voce.get("percorso") or cartella,
        "dati": cartella,
    }


def crea_tutte(*, con_chiavi: bool = True) -> list[dict[str, Any]]:
    """Un archivio per ogni installazione. Non si ferma alla prima che va male.

    Un profilo che non si riesce a salvare (cartella illeggibile, disco
    pieno) non deve impedire il salvataggio degli altri: si raccoglie
    l'errore e si prosegue, e l'elenco finale dice quali sono andati e
    quali no.
    """
    esiti: list[dict[str, Any]] = []
    for voce in installazioni():
        base = {"installazione": voce.get("id") or "",
                "profilo": voce.get("percorso") or voce["dati"],
                "dati": voce["dati"]}
        try:
            esito = crea("", con_chiavi=con_chiavi, installazione=voce["dati"])
            esiti.append({**esito, "esito": "ok"})
        except Exception as e:  # noqa: BLE001 - un profilo non ferma gli altri
            esiti.append({**base, "esito": "errore", "errore": str(e)})
    return esiti


# ---------------------------------------------------------------------------
# Archivi sul disco
# ---------------------------------------------------------------------------

def _info_archivio(percorso_archivio: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "percorso": percorso_archivio,
        "nome": os.path.basename(percorso_archivio),
        "versione": "",
        "creato": "",
        "con_chiavi": False,
        "file": 0,
    }
    try:
        info["byte"] = os.path.getsize(percorso_archivio)
        info["modificato"] = os.path.getmtime(percorso_archivio)
    except OSError:
        info["byte"] = 0
        info["modificato"] = 0
    try:
        with zipfile.ZipFile(percorso_archivio) as z:
            manifesto = _manifesto(z)
        info["versione"] = str(manifesto.get("versione") or "")
        info["creato"] = str(manifesto.get("creato") or "")
        info["con_chiavi"] = bool(manifesto.get("con_chiavi"))
        info["file"] = len(manifesto.get("file") or [])
    except Exception:  # noqa: BLE001 - un file rotto si elenca lo stesso
        info["rotto"] = True
    return info


def archivi(installazione: str | None = None) -> list[dict[str, Any]]:
    """Gli archivi presenti nelle cartelle `backup`, dal piu' recente.

    Serve all'interfaccia: un ripristino si fa quasi sempre da un
    archivio che e' gia' la', e elencarli evita di dover digitare un
    percorso a mano.
    """
    voci = [{"id": _voce(_dati(installazione))["id"],
             "dati": _dati(installazione),
             "percorso": _voce(_dati(installazione)).get("percorso") or ""}] \
        if installazione else installazioni()
    risultati: list[dict[str, Any]] = []
    for voce in voci:
        cartella = os.path.join(voce["dati"], "backup")
        try:
            nomi = sorted(os.listdir(cartella))
        except OSError:
            continue
        for nome in nomi:
            if not nome.lower().endswith(".zip"):
                continue
            pieno = os.path.join(cartella, nome)
            if not os.path.isfile(pieno):
                continue
            risultati.append({
                **_info_archivio(pieno),
                "installazione": voce.get("id") or "",
                "profilo": voce.get("percorso") or voce["dati"],
                "dati": voce["dati"],
            })
    risultati.sort(key=lambda a: -float(a.get("modificato") or 0))
    return risultati


# ---------------------------------------------------------------------------
# Ripristino
# ---------------------------------------------------------------------------

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


def ripristina(archivio: str, *, con_chiavi: bool = True,
               installazione: str | None = None) -> dict[str, Any]:
    """Rimette i dati di un archivio. Torna cosa ha scritto e la sicurezza.

    Si ripristina nella cartella dati indicata; senza indicazioni, in
    quella corrente. NON si segue il percorso scritto nell'archivio: un
    backup fatto su D: e riaperto qui non deve svuotare l'installazione
    che sta girando solo perche' il nome coincide. Il percorso di
    provenienza si legge nel risultato e nel MANIFEST, e chi vuole
    ripristinare altrove lo dice.
    """
    archivio = os.path.abspath(os.path.expanduser(archivio))
    if not os.path.isfile(archivio):
        raise RuntimeError(f"archivio non trovato: {archivio}")
    destinazione_dati = _dati(installazione)
    with zipfile.ZipFile(archivio) as z:
        manifesto = _manifesto(z)
        nomi = [n for n in z.namelist() if n.startswith("dati/") and _sicuro(n)]
        if not nomi:
            raise RuntimeError("l'archivio non contiene dati")

        # Backup di sicurezza PRIMA di toccare: se fallisce, si smette.
        # Su una cartella dati vuota non c'e' niente da proteggere, e non
        # e' un errore: e' il primo ripristino su un computer nuovo.
        try:
            sicurezza = crea("", con_chiavi=bool(con_chiavi),
                             installazione=destinazione_dati)
        except RuntimeError:
            if elenco(con_chiavi=False, installazione=destinazione_dati):
                raise
            sicurezza = {"percorso": ""}

        scritti: list[str] = []
        for nome in nomi:
            destinazione = os.path.join(destinazione_dati, nome[len("dati/"):])
            os.makedirs(os.path.dirname(destinazione) or destinazione_dati,
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
            env_target = _env_per(destinazione_dati) or ENV_PATH
            with z.open("config/.env") as src:
                dati_env = src.read()
            os.makedirs(os.path.dirname(env_target) or ".", exist_ok=True)
            with open(env_target, "wb") as dst:
                dst.write(dati_env)
            chiavi = True

    provenienza = manifesto.get("installazione") or {}
    return {
        "ripristinati": len(scritti),
        "file": scritti,
        "sicurezza": sicurezza["percorso"],
        "chiavi": chiavi,
        "versione": manifesto.get("versione") or "",
        "creato": manifesto.get("creato") or "",
        "dati": destinazione_dati,
        "profilo": _voce(destinazione_dati).get("percorso") or destinazione_dati,
        "da": str(provenienza.get("percorso") or provenienza.get("dati") or ""),
    }


def posizione_predefinita(installazione: str | None = None) -> str:
    """Dove finisce un backup se non si dice altro. Solo per mostrarlo."""
    return os.path.join(_dati(installazione), "backup")
