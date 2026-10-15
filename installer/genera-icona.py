"""Genera installer/orchestra.ico senza dipendenze (solo stdlib).

Motivo: un'icona .ico puo' contenere PNG compressi, quindi basta
struct+zlib. Il disegno e' volutamente geometrico (rettangolo stondato
blu notte + 5 barre oro): resta leggibile da 16 a 256 px, dove i
dettagli fini sparirebbero comunque.

Rigenera con:  python installer/genera-icona.py
"""

import os
import struct
import zlib

QUI = os.path.dirname(os.path.abspath(__file__))

BLU = (15, 27, 45, 255)
ORO = (200, 169, 94, 255)


def png(w, h, pixel):
    righe = []
    for y in range(h):
        riga = bytearray(b"\x00")
        for x in range(w):
            riga += struct.pack("4B", *pixel(x, y))
        righe.append(bytes(riga))
    raw = b"".join(righe)

    def chunk(tipo, dati):
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def disegno(size):
    r = size * 0.22          # raggio angoli
    alte = [0.42, 0.66, 0.94, 0.66, 0.42]
    n = len(alte)
    passo = size / (n + 1)
    larg = max(2, int(size * 0.10))

    def dentro(x, y):
        # dentro il rettangolo stondato?
        cx = min(max(x, r), size - r)
        cy = min(max(y, r), size - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def pixel(x, y):
        if not dentro(x + 0.5, y + 0.5):
            return (0, 0, 0, 0)
        for i, h in enumerate(alte):
            bx = (i + 1) * passo
            bh = h * size * 0.62
            if (abs(x + 0.5 - bx) <= larg / 2
                    and abs(y + 0.5 - size / 2) <= bh / 2):
                return ORO
        return BLU

    return png(size, size, pixel)


def ico(immagini):
    testata = [struct.pack("<HHH", 0, 1, len(immagini))]
    offset = 6 + 16 * len(immagini)
    corpo = []
    for dati, (w, h) in immagini:
        testata.append(struct.pack("<BBBBHHII", w % 256, h % 256,
                                   0, 0, 1, 32, len(dati), offset))
        offset += len(dati)
        corpo.append(dati)
    return b"".join(testata) + b"".join(corpo)


def main():
    misure = [16, 32, 48, 256]
    immagini = [(disegno(s), (s, s)) for s in misure]
    fuori = os.path.join(QUI, "orchestra.ico")
    with open(fuori, "wb") as fh:
        fh.write(ico(immagini))
    print(f"scritta {fuori} ({os.path.getsize(fuori)} byte)")


if __name__ == "__main__":
    main()
