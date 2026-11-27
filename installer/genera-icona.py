"""Genera icon-192.png e installer/orchestra.ico dalla resa 512 di icon.svg.

Il disegno vive in web/icon.svg; web/icon-512.png e' la sua resa. Tutte
le altre misure si ricavano da quella, cosi' SVG, PNG e ICO non possono
divergere. Se cambi il disegno, riesporta prima la 512.

Pillow e' gia' una dipendenza del progetto (requirements.txt).

Rigenera con:  python installer/genera-icona.py
"""

import os

from PIL import Image

QUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(QUI), "orchestra", "web")
SORGENTE = os.path.join(WEB, "icon-512.png")
MISURE_ICO = (16, 32, 48, 256)


def main():
    with Image.open(SORGENTE) as im:
        im = im.convert("RGBA")
        if im.size != (512, 512):
            raise SystemExit(f"{SORGENTE}: attesa 512x512, trovata {im.width}x{im.height}")

        png192 = os.path.join(WEB, "icon-192.png")
        im.resize((192, 192), Image.Resampling.LANCZOS).save(png192, optimize=True)

        ico = os.path.join(QUI, "orchestra.ico")
        im.save(ico, format="ICO", sizes=[(s, s) for s in MISURE_ICO])

    print(f"scritte {png192} e {ico}")


if __name__ == "__main__":
    main()
