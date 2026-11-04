"""Le immagini generate dichiarano di essere generate (AI Act, art. 50(2)).

Non si verifica "c'e' una funzione che marca": si costruisce un PNG
minimo valido, lo si marca, e si rilegge con un parser indipendente da
quello che l'ha scritto. Se il chunk fosse storto, il PNG si aprirebbe
male in un browser e nessuno se ne accorgerebbe finche' non e' tardi.
"""

import json
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from orchestra import marcatura  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def png_minimo(colore=(255, 0, 0)) -> bytes:
    """Un PNG 1x1 davvero valido: firma, IHDR, IDAT con i pixel, IEND."""

    def chunk(tipo: bytes, dati: bytes) -> bytes:
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, RGB 8 bit
    # ogni riga comincia con il byte di filtro
    idat = zlib.compress(b"\x00" + bytes(colore))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def chunk_del_png(dati: bytes) -> list[tuple[bytes, int, bool]]:
    """(tipo, lunghezza, crc_valido) per ogni chunk, letto a mano.

    Il CRC si ricalcola: un chunk aggiunto con un CRC sbagliato e' un
    file che alcuni lettori rifiutano, e il nostro parser potrebbe non
    accorgersene.
    """
    out = []
    i = 8
    while i + 12 <= len(dati):
        (n,) = struct.unpack(">I", dati[i:i + 4])
        tipo = dati[i + 4:i + 8]
        corpo = dati[i + 8:i + 8 + n]
        (crc,) = struct.unpack(">I", dati[i + 8 + n:i + 12 + n])
        out.append((tipo, n, crc == (zlib.crc32(tipo + corpo) & 0xFFFFFFFF)))
        i += 12 + n
    return out


base = png_minimo()
check("il PNG di partenza e' valido", all(c[2] for c in chunk_del_png(base)),
      str(chunk_del_png(base)))

print("\n[1] La marcatura entra nel file, e non lo rompe")
marcato = marcatura.marca_png(base, marcatura.testo(provider="openai",
                                                    modello="gpt-image-1"))
chunks = chunk_del_png(marcato)
check("tutti i chunk hanno un CRC valido", all(c[2] for c in chunks),
      str([c for c in chunks if not c[2]]))
tipi = [c[0] for c in chunks]
check("IHDR resta il primo chunk", tipi[0] == b"IHDR", str(tipi[:2]))
check("IEND resta l'ultimo chunk", tipi[-1] == b"IEND", str(tipi[-2:]))
check("c'e' un tEXt in piu'", tipi.count(b"tEXt") == 1, str(tipi))

testi = marcatura.leggi_png(marcato)
check("il metadato ha la chiave AI", "AI" in testi, str(list(testi)))
check("dice che il contenuto e' sintetico",
      "sintetico" in testi.get("AI", ""), testi.get("AI", ""))
check("nomina il provider e il modello",
      "openai" in testi.get("AI", "") and "gpt-image-1" in testi.get("AI", ""),
      testi.get("AI", ""))
def senza_testo(dati: bytes) -> bytes:
    """Lo stesso PNG senza i chunk tEXt: deve tornare identico a quello
    di partenza, byte per byte, o la marcatura ha toccato i pixel."""
    out = dati[:8]
    i = 8
    while i + 12 <= len(dati):
        (n,) = struct.unpack(">I", dati[i:i + 4])
        tipo = dati[i + 4:i + 8]
        fine = i + 12 + n
        if tipo != b"tEXt":
            out += dati[i:fine]
        i = fine
    return out


check("i pixel non cambiano", senza_testo(marcato) == base)

print("\n[2] Cio' che non e' un PNG non si tocca")
jpeg = b"\xff\xd8\xff\xe0" + b"0" * 40
check("un JPEG torna identico", marcatura.marca_png(jpeg, "x") == jpeg)
rotto = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
check("un PNG senza IEND torna identico",
      marcatura.marca_png(rotto, "x") == rotto)
check("leggere un non-PNG non solleva", marcatura.leggi_png(jpeg) == {})

print("\n[3] Il sidecar dice la verita' senza dover capire l'immagine")
with tempfile.TemporaryDirectory() as tmp:
    percorso = Path(tmp) / "immagini" / "gatto.png"
    percorso.parent.mkdir(parents=True)
    percorso.write_bytes(marcato)
    meta_path = marcatura.scrivi_metadati(
        percorso, prompt="un gatto", provider="openai",
        modello="gpt-image-1", mime="image/png", nel_file=True)
    check("il file e' accanto all'immagine",
          meta_path.name == "gatto.ai.json" and meta_path.parent == percorso.parent,
          str(meta_path))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    check("e' dichiarato sintetico", meta.get("sintetica") is True)
    check("nomina il generatore",
          str(meta.get("generata_da", "")).startswith("Orchestra "),
          str(meta.get("generata_da")))
    check("conserva il prompt", meta.get("prompt") == "un gatto")
    check("dice che la marcatura e' anche nel file",
          meta.get("marcatura_nel_file") is True)
    check("spiega in italiano cosa vuol dire", "intelligenza artificiale"
          in str(meta.get("nota", "")))
    # il sidecar non deve schiacciare un JSON dell'utente
    (Path(tmp) / "immagini" / "gatto.json").write_text("{}", encoding="utf-8")
    meta2 = marcatura.scrivi_metadati(percorso, provider="x")
    check("non tocca un gatto.json che c'era gia'",
          (Path(tmp) / "immagini" / "gatto.json").read_text(encoding="utf-8")
          == "{}" and meta2.name == "gatto.ai.json")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
