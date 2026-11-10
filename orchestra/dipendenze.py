"""Le dipendenze di Orchestra: una lista, letta da `requirements.txt`.

Perche' questo modulo esiste.

Il pannello **Opzioni → Dipendenze** aveva una lista scritta a mano nel
gestore della rotta: `ddgs`, `faster-whisper`, `cloudflared`. Non leggeva
`requirements.txt`, e nessun altro lo leggeva — né l'installer, né
`orchestra update`. Quindi una dipendenza aggiunta al file non arrivava a
nessuno: `Pillow` (0.5.80) e `pypdf` (0.5.81) erano dichiarate e invisibili.
Il sintomo e' cattivo, perche' non somiglia a un guasto: il file e' giusto,
il pannello e' giusto, e il tool dice "installa Pillow" a un utente che nel
pannello non trova Pillow.

La lista sta in un posto solo: `requirements.txt`. Qui si legge, si
interroga `importlib` per lo stato vero, e si tiene una tabella per le
dipendenze che non si installano con pip (cloudflared arriva da winget) e
per le opzionali che non stanno nel file perche' non servono a Orchestra
per partire (`faster-whisper`, che serve solo alla trascrizione).

Il nome mostrato, il pacchetto pip e il modulo da importare non coincidono
sempre — `Pillow` si importa `PIL`, `faster-whisper` si importa
`faster_whisper` — quindi la corrispondenza e' esplicita. Indovinarla con
`nome.replace("-", "_")` funziona per caso fino al primo pacchetto che non
lo rispetta, e poi lo stato dice "da installare" su qualcosa che c'e' gia'.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import sys
from pathlib import Path

# Dove sta `requirements.txt`: la root del progetto, cioe' la cartella che
# contiene il pacchetto `orchestra/`.
ROOT = Path(__file__).resolve().parents[1]

# Se il file non c'e' (installazione da wheel, dove `requirements.txt` non
# viene impacchettato) il pannello non deve restare vuoto: questa e' la
# lista minima che serve a Orchestra per fare il suo lavoro.
ELEMENTARI = (
    ("ddgs", ">=9.0", "ricerca sul web senza chiave"),
    ("Pillow", ">=10.1", "montaggio delle immagini (immagine)"),
    ("pypdf", ">=5.0", "testo dei PDF"),
)

# nome del pacchetto -> modulo da importare, quando non coincidono.
MODULI = {
    "pillow": "PIL",
    "python-dotenv": "dotenv",
    "faster-whisper": "faster_whisper",
    "ddgs": "ddgs",
}

# Cosa serve perche' un tool funzioni: e' la frase che il pannello mostra
# accanto alla dipendenza. Sta qui e non nel file dei requisiti perche' il
# file e' letto anche da pip, che i commenti li ignora ma non li mostra.
PERCHE = {
    "ddgs": "ricerca sul web senza chiave (web_cerca)",
    "pillow": "montaggio delle immagini (immagine)",
    "pypdf": "testo dei PDF (allegati e read_file)",
}

# Dipendenze che non arrivano da pip: si installano con un altro
# programma, e il pannello deve saperlo per non offrire il comando
# sbagliato. `trova` e' la funzione che dice se c'e'.
SISTEMA = (
    {
        "nome": "cloudflared",
        "via": "winget",
        "perche": "tunnel remoto",
        "winget": "Cloudflare.cloudflared",
    },
)

# Opzionali: non stanno in `requirements.txt` perche' Orchestra parte e
# lavora senza. Restano nel pannello perche' e' li' che si scopre che
# esistono.
OPZIONALI = (
    {
        "nome": "faster-whisper",
        "pip": "faster-whisper",
        "modulo": "faster_whisper",
        "perche": "trascrizione audio (STT)",
    },
)


def _voci_requisiti(testo: str) -> list[tuple[str, str]]:
    """(nome, specifica) da un requirements.txt, senza commenti ne' opzioni.

    Volutamente semplice: nomi, extras, specificatori. Le righe che iniziano
    con `-` (`-r`, `--index-url`, `-e`) non sono dipendenze e si saltano;
    un marcatore d'ambiente (`; sys_platform == ...`) si scarta perche' il
    pannello non ha un posto dove mostrarlo.
    """
    voci: list[tuple[str, str]] = []
    for riga in testo.splitlines():
        riga = riga.split("#", 1)[0].strip()
        if not riga or riga.startswith("-"):
            continue
        riga = riga.split(";", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._\-]*)\s*(?:\[[^\]]*\])?\s*(.*)$",
                     riga)
        if not m:
            continue
        nome, specifica = m.group(1), m.group(2).strip()
        voci.append((nome, specifica))
    return voci


def requisiti(root: Path | None = None) -> list[tuple[str, str]]:
    """Le dipendenze pip dichiarate, in ordine di file."""
    percorso = Path(root or ROOT) / "requirements.txt"
    try:
        testo = percorso.read_text(encoding="utf-8")
    except OSError:
        return [(n, s) for n, s, _perche in ELEMENTARI]
    voci = _voci_requisiti(testo)
    return voci or [(n, s) for n, s, _perche in ELEMENTARI]


def _modulo(nome: str) -> str:
    return MODULI.get(nome.lower(), nome.replace("-", "_"))


def _versione(nome: str) -> str:
    try:
        return importlib.metadata.version(nome)
    except Exception:  # noqa: BLE001 - un pacchetto senza metadata c'e' lo stesso
        return "?"


def _stato_pip(nome: str, specifica: str, perche: str) -> dict:
    modulo = _modulo(nome)
    try:
        presente = importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        # Un modulo che solleva all'import (dipendenze native rotte) non e'
        # "assente": e' installato e non funziona. Dire "da installare" a
        # chi ce l'ha gia' manda a reinstallare qualcosa che non e' il
        # problema.
        presente = True
    return {
        "nome": nome,
        "stato": "ok" if presente else "da installare",
        "versione": _versione(nome) if presente else "",
        "via": "pip",
        "specifica": specifica,
        "perche": perche,
        # Il comando esatto: cosi' chi legge il JSON puo' copiarlo, e non
        # deve indovinare se serve `-U` o il nome del pacchetto.
        "comando": f"{sys.executable} -m pip install {nome}{specifica}",
    }


def _trova_cloudflared() -> str:
    import shutil

    trovato = shutil.which("cloudflared")
    if trovato:
        return trovato
    for cand in (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
                 r"C:\Program Files\cloudflared\cloudflared.exe"):
        if Path(cand).exists():
            return cand
    return ""


def stato(root: Path | None = None) -> list[dict]:
    """Lo stato di tutte le dipendenze, per il pannello Opzioni."""
    deps: list[dict] = []
    visti: set[str] = set()
    for nome, specifica in requisiti(root):
        deps.append(_stato_pip(nome, specifica,
                               PERCHE.get(nome.lower(), "")))
        visti.add(nome.lower())
    for voce in SISTEMA:
        percorso = _trova_cloudflared()
        deps.append({
            "nome": voce["nome"],
            "stato": "ok" if percorso else "da installare",
            "versione": "installato" if percorso else "",
            "via": voce["via"],
            "specifica": "",
            "perche": voce["perche"],
            "comando": f"winget install --id {voce['winget']} -e",
            **({"path": percorso} if percorso else {}),
        })
        visti.add(voce["nome"])
    for voce in OPZIONALI:
        if voce["nome"] in visti:
            continue
        deps.append(_stato_pip(voce["nome"], "", voce["perche"]))
    return deps


def comando_installazione(nome: str) -> list[str] | None:
    """Il comando per installare `nome`, o None se non lo conosco.

    Il nome si confronta senza distinzione di maiuscole e con `-` o `_`:
    la UI puo' mandare "faster-whisper" o "faster_whisper", e sbagliare
    su questo non e' un errore dell'utente.
    """
    chiave = (nome or "").strip().lower().replace("_", "-")
    if not chiave:
        return None
    for voce in SISTEMA:
        if voce["nome"].lower().replace("_", "-") == chiave:
            return ["winget", "install", "--id", voce["winget"], "-e",
                    "--silent", "--accept-package-agreements",
                    "--accept-source-agreements"]
    for nome_pkg, specifica in requisiti():
        if nome_pkg.lower().replace("_", "-") == chiave:
            return [sys.executable, "-m", "pip", "install",
                    f"{nome_pkg}{specifica}"]
    for voce in OPZIONALI:
        if voce["nome"].lower().replace("_", "-") == chiave:
            return [sys.executable, "-m", "pip", "install", voce["pip"]]
    return None
