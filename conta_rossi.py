"""Conta i pixel rossi di un'immagine.

Uso:  python conta_rossi.py <file.png> [modalita']

Modalita':
  esatto   (default) pixel con R alto, G e B bassi -> il rosso pieno
  soglia   stessi criteri ma con tolleranza, per i JPEG e i bordi sfumati
  dump     elenca i colori presenti con il loro conteggio

Il risultato e' la risposta, non una stima: si contano i pixel uno a uno.
"""

import sys
from collections import Counter
from PIL import Image


def apri(percorso: str) -> Image.Image:
    """Apre e passa a RGB, qualunque cosa sia il file (PNG, JPEG, WEBP...)."""
    return Image.open(percorso).convert("RGB")


def conta_rosso(img: Image.Image, soglia: int = 0) -> tuple[int, int]:
    """Ritorna (pixel rossi, pixel totali).

    Con soglia 0 il rosso e' esatto: R > 150, G e B sotto 100.
    Ogni passo della soglia allarga il corridoio, cosi' un bordo
    anti-aliasing o un JPEG leggermente sfocato vengono contati.
    """
    if soglia:
        hi, lo = 150 - soglia, 100 + soglia
    else:
        hi, lo = 150, 100
    rossi = 0
    for r, g, b in img.getdata():
        if r > hi and g < lo and b < lo:
            rossi += 1
    return rossi, img.width * img.height


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    percorso = sys.argv[1]
    modo = sys.argv[2] if len(sys.argv) > 2 else "esatto"
    img = apri(percorso)
    print(f"{percorso}: {img.width}x{img.height} = {img.width * img.height} pixel")

    if modo == "dump":
        for colore, n in Counter(img.getdata()).most_common(20):
            print(f"  {colore}  x{n}")
        return

    soglia = 40 if modo == "soglia" else 0
    rossi, totali = conta_rosso(img, soglia)
    percentuale = 100.0 * rossi / totali if totali else 0
    print(f"modalita': {modo}")
    print(f"rossi: {rossi} su {totali} ({percentuale:.1f}%)")


if __name__ == "__main__":
    main()
