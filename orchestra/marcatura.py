"""Marcatura dei contenuti sintetici (AI Act, art. 50(2)).

PERCHE' ESISTE

L'art. 50(2) chiede che gli output generati da un sistema di IA siano
marcati in un formato leggibile da una macchina e rilevabili come
generati. Per il testo e il codice la posizione sostenibile e' quella
dell'esclusione "funzione assistiva di editing / nessuna alterazione
sostanziale dei dati del deployer"; per un'immagine prodotta da zero non
c'e' nessuna esclusione che regga.

QUANTO E' ROBUSTO, DETTO CHIARO

Il PNG accetta chunk `tEXt`: si inserisce un chunk con chiave `AI` prima
di `IEND`, e chi legge i metadati lo trova senza decodificare i pixel.
Non e' una filigrana: un ritaglio o una ricodifica lo tolgono. Per
questo accanto al file si scrive sempre anche un `.ai.json`: e' il
metadato che sopravvive alle conversioni, ed e' quello che un
programma legge senza dover capire il formato dell'immagine.

Si marca quello che si puo' marcare ("nei limiti del tecnicamente
fattibile", art. 50(2)): PNG nel file, tutto il resto nel sidecar, e in
entrambi i casi il tool lo dice nel risultato.
"""

from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

# La chiave del chunk tEXt. Corta e stabile: e' quella che si cerca.
CHIAVE = b"AI"


def testo(*, provider: str = "", modello: str = "") -> str:
    """Il valore del metadato, in ASCII.

    tEXt e' Latin-1: un nome di modello con caratteri fuori da Latin-1
    romperebbe il chunk o verrebbe storpiato in silenzio. Si sostituisce
    invece di far fallire la marcatura, perche' un'immagine non marcata
    e' un problema, un carattere sostituito no.
    """
    parti = ["contenuto sintetico generato da Orchestra"]
    if provider:
        parti.append(f"provider={provider}")
    if modello:
        parti.append(f"modello={modello}")
    return "; ".join(parti)


def _chunk(tipo: bytes, dati: bytes) -> bytes:
    """Un chunk PNG: lunghezza, tipo, dati, CRC del tipo+dati."""
    crc = zlib.crc32(tipo + dati) & 0xFFFFFFFF
    return struct.pack(">I", len(dati)) + tipo + dati + struct.pack(">I", crc)


def marca_png(dati: bytes, valore: str) -> bytes:
    """Inserisce il chunk `tEXt` prima di `IEND` e restituisce i byte nuovi.

    Se i byte non sono un PNG, o manca `IEND`, tornano identici: meglio
    un'immagine non marcata che un file corrotto da una marcatura
    scritta a meta'.
    """
    firma = b"\x89PNG\r\n\x1a\n"
    if not dati.startswith(firma):
        return dati
    iend = dati.rfind(b"IEND")
    if iend < 8:
        return dati
    inizio = iend - 4  # la lunghezza del chunk IEND sta quattro byte prima
    testo_chunk = CHIAVE + b"\x00" + valore.encode("latin-1", "replace")
    return dati[:inizio] + _chunk(b"tEXt", testo_chunk) + dati[inizio:]


def leggi_png(dati: bytes) -> dict[str, str]:
    """I chunk tEXt di un PNG, chiave -> valore. Serve ai test e a chi
    verifica la marcatura senza fidarsi del nostro codice di scrittura."""
    fuori: dict[str, str] = {}
    if not dati.startswith(b"\x89PNG\r\n\x1a\n"):
        return fuori
    i = 8
    while i + 8 <= len(dati):
        (lunghezza,) = struct.unpack(">I", dati[i:i + 4])
        tipo = dati[i + 4:i + 8]
        corpo = dati[i + 8:i + 8 + lunghezza]
        if len(corpo) < lunghezza:
            break
        if tipo == b"tEXt" and b"\x00" in corpo:
            chiave, _, valore = corpo.partition(b"\x00")
            fuori[chiave.decode("latin-1", "replace")] = \
                valore.decode("latin-1", "replace")
        i += 12 + lunghezza
    return fuori


def percorso_metadati(percorso: Path) -> Path:
    """`immagini/foo.png` -> `immagini/foo.ai.json`."""
    return percorso.with_name(percorso.stem + ".ai.json")


def scrivi_metadati(percorso: Path, *, prompt: str = "", provider: str = "",
                    modello: str = "", mime: str = "",
                    nel_file: bool = False) -> Path:
    """Il sidecar che dice, senza ambiguita', cosa e' questo file.

    `nel_file` dice se la marcatura e' anche dentro l'immagine: cosi' chi
    legge il JSON sa se puo' fidarsi del file da solo o se il metadato
    esiste solo qui.
    """
    from . import __version__

    meta = {
        "sintetica": True,
        "generata_da": f"Orchestra {__version__}",
        "data": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "modello": modello,
        "mime": mime,
        "prompt": prompt[:2000],
        "marcatura_nel_file": bool(nel_file),
        "nota": ("Contenuto generato da un sistema di intelligenza "
                 "artificiale (Reg. UE 2024/1689, art. 50). Non e' una "
                 "fotografia ne' un disegno di una persona."),
    }
    p = percorso_metadati(percorso)
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")
    return p
