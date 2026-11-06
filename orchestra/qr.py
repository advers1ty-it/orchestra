"""I codici QR, senza dipendenze.

PERCHE' SCRITTO A MANO

Il codice che finisce in un QR e' quello di collegamento a Telegram: chi
lo inquadra prende il controllo della chat del bot. Le due alternative
erano peggiori. Una libreria in piu' da installare su ogni macchina per
disegnare un rettangolo di quadratini neri. Oppure un servizio esterno
(`api.qrserver.com`, che l'app gia' usa per un altro QR): comodo, ma
vorrebbe dire mandare a un terzo proprio il codice che apre il bot, e
fidarsi che quel terzo non lo registri. Qui il codice non esce dalla
macchina.

CHE COSA SI IMPLEMENTA

Il minimo che serve per un link: modo byte (il testo cosi' com'e'),
correzione d'errore livello L (il link sta in un QR piccolo e lo si
inquadra da uno schermo pulito), versioni 1-10. Il resto dello standard
— modi numerico e alfanumerico, versioni grandi, livelli M/Q/H — qui
non servirebbe e sarebbe codice che nessuno prova.

Il livello L corregge il 7% dei moduli: poco, ma un QR letto da uno
schermo non ha graffi. Se un giorno servisse di piu', `EC_LIVELLI`
accetta anche M senza toccare altro.
"""

from __future__ import annotations

# Capacita' in byte per versione, livello L: [versione] -> byte di dati.
CAPACITA = {
    1: 17, 2: 32, 3: 53, 4: 78, 5: 106,
    6: 134, 7: 154, 8: 192, 9: 230, 10: 271,
}

# Struttura dei blocchi per versione, livello L:
# (codeword di dati per blocco, numero di blocchi, codeword di correzione
#  per blocco). Le versioni con due misure di blocco (10) stanno in
# `BLOCCHI_MISTI`.
BLOCCHI = {
    1: (19, 1, 7), 2: (34, 1, 10), 3: (55, 1, 15), 4: (80, 1, 20),
    5: (108, 1, 26), 6: (68, 2, 18), 7: (78, 2, 20), 8: (97, 2, 24),
    9: (116, 2, 30),
}
# Versione 10: due blocchi da 68 e due da 69, 18 di correzione ciascuno.
BLOCCHI_MISTI = {10: (2, 68, 2, 69, 18)}

# Dove vanno i pattern di allineamento (centri), per versione.
ALLINEAMENTO = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30),
    6: (6, 34), 7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46),
    10: (6, 28, 50),
}

# Livello L = 01 nei bit del formato.
_LIVELLO_L = 0b01


class ErroreQR(ValueError):
    """Il testo non entra in un QR che sappiamo disegnare."""


# ===================================================================
#  Aritmetica in GF(256), per la correzione d'errore
# ===================================================================
def _moltiplica(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _generatore(grado: int) -> list[int]:
    """Il polinomio generatore di Reed-Solomon di quel grado.

    E' il prodotto di (x - a^i) per i che va da 0 a grado-1. Le potenze
    di alfa si portano avanti una alla volta: `1 << i` smette di essere
    un elemento del campo appena supera 255, e moltiplicare per quello
    darebbe coefficienti sbagliati senza segnalare niente.
    """
    poly = [1]
    alfa = 1
    for _ in range(grado):
        nuovo = [0] * (len(poly) + 1)
        for j, coefficiente in enumerate(poly):
            nuovo[j] ^= coefficiente
            nuovo[j + 1] ^= _moltiplica(coefficiente, alfa)
        poly = nuovo
        alfa = _moltiplica(alfa, 2)
    return poly


def _correzione(dati: list[int], grado: int) -> list[int]:
    """Le codeword di correzione per un blocco di dati."""
    gen = _generatore(grado)
    resto = list(dati) + [0] * grado
    for i in range(len(dati)):
        fattore = resto[i]
        if not fattore:
            continue
        for j, coefficiente in enumerate(gen):
            resto[i + j] ^= _moltiplica(coefficiente, fattore)
    return resto[len(dati):]


# ===================================================================
#  Dal testo ai codici
# ===================================================================
def _versione(lunghezza: int) -> int:
    for versione, capacita in sorted(CAPACITA.items()):
        if lunghezza <= capacita:
            return versione
    raise ErroreQR(f"testo troppo lungo per un QR di questa "
                   f"implementazione ({lunghezza} byte, massimo "
                   f"{max(CAPACITA.values())})")


def _dati_codewords(versione: int) -> int:
    """Quanti codeword di dati ha quella versione, somma dei blocchi."""
    if versione in BLOCCHI_MISTI:
        primo_n, primo_len, secondo_n, secondo_len, _corr = \
            BLOCCHI_MISTI[versione]
        return primo_n * primo_len + secondo_n * secondo_len
    lunghezza, quanti, _corr = BLOCCHI[versione]
    return lunghezza * quanti


def _bit(dati: bytes, versione: int) -> list[int]:
    """Modalita' byte: indicatore, lunghezza, dati, terminatore, riempimento."""
    bit: list[int] = []

    def scrivi(valore: int, quanti: int) -> None:
        for i in range(quanti - 1, -1, -1):
            bit.append((valore >> i) & 1)

    scrivi(0b0100, 4)
    # Sotto la versione 10 la lunghezza sta in 8 bit, da 10 in su in 16.
    scrivi(len(dati), 8 if versione < 10 else 16)
    for byte in dati:
        scrivi(byte, 8)

    # La capacita' che conta e' quella dei codeword di dati del blocco,
    # non i byte utili: `CAPACITA` e' gia' scontata dell'intestazione, e
    # usarla qui farebbe rifiutare testi che entrano benissimo.
    capacita_bit = _dati_codewords(versione) * 8
    if len(bit) > capacita_bit:
        raise ErroreQR("i dati non entrano nella versione scelta")
    # Terminatore: fino a quattro zeri, poi si allinea al byte.
    scrivi(0, min(4, capacita_bit - len(bit)))
    while len(bit) % 8:
        bit.append(0)

    codici = [int("".join(str(b) for b in bit[i:i + 8]), 2)
              for i in range(0, len(bit), 8)]
    # I due byte di riempimento si alternano: e' quello che dice lo
    # standard, e serve a non avere lunghi tratti uniformi che
    # confondono il lettore.
    riempimento = (0xEC, 0x11)
    i = 0
    # Il riempimento va fino ai codeword di dati del BLOCCO, non ai byte
    # utili: sono due numeri diversi (34 contro 32 in versione 2), e
    # fermarsi prima lascia i blocchi corti e la correzione calcolata
    # su dati che non ci sono.
    while len(codici) < _dati_codewords(versione):
        codici.append(riempimento[i % 2])
        i += 1
    return codici


def _blocchi(codici: list[int], versione: int) -> tuple[list[int], int]:
    """Interlaccia dati e correzione come vuole lo standard."""
    if versione in BLOCCHI_MISTI:
        primo_n, primo_len, secondo_n, secondo_len, correzione = \
            BLOCCHI_MISTI[versione]
        blocchi: list[list[int]] = []
        posizione = 0
        for _ in range(primo_n):
            blocchi.append(codici[posizione:posizione + primo_len])
            posizione += primo_len
        for _ in range(secondo_n):
            blocchi.append(codici[posizione:posizione + secondo_len])
            posizione += secondo_len
        per_blocco = correzione
    else:
        lunghezza, quanti, per_blocco = BLOCCHI[versione]
        blocchi = [codici[i * lunghezza:(i + 1) * lunghezza]
                   for i in range(quanti)]

    correzioni = [_correzione(b, per_blocco) for b in blocchi]
    finale: list[int] = []
    for i in range(max(len(b) for b in blocchi)):
        for b in blocchi:
            if i < len(b):
                finale.append(b[i])
    for i in range(per_blocco):
        for c in correzioni:
            finale.append(c[i])
    return finale, versione


# ===================================================================
#  La matrice
# ===================================================================
def _nuova_matrice(dimensione: int) -> tuple[list[list[int | None]],
                                             list[list[bool]]]:
    moduli: list[list[int | None]] = [[None] * dimensione
                                      for _ in range(dimensione)]
    riservati = [[False] * dimensione for _ in range(dimensione)]
    return moduli, riservati


def _riserva_formato(moduli, riservati, dimensione: int) -> None:
    """Segna come occupate le celle del formato, PRIMA dei dati.

    Il formato si scrive alla fine (dipende dalla maschera), ma le sue
    celle non sono dati: se non le si riserva prima, i bit dei dati ci
    finiscono dentro, vengono sovrascritti, e tutto il resto della
    matrice slitta di una posizione. Un QR che sembra un QR e non si
    legge.
    """
    # Prima copia: attorno al pattern in alto a sinistra, un tratto
    # verticale (colonna 8) e uno orizzontale (riga 8).
    coordinate = [(i, 8) for i in range(6)]
    coordinate += [(7, 8), (8, 8), (8, 7)]
    coordinate += [(8, 14 - i) for i in range(9, 15)]
    # Seconda copia: otto celle in fondo alla riga 8, sette in fondo
    # alla colonna 8. Il modulo sempre scuro a (dimensione-8, 8) NON fa
    # parte della copia: contarlo due volte lascierebbe una cella libera
    # e farebbe slittare di uno tutti i bit dei dati — un QR che sembra
    # un QR e nessun lettore che lo legge.
    coordinate += [(8, dimensione - 1 - i) for i in range(8)]
    coordinate += [(dimensione - 15 + i, 8) for i in range(8, 15)]
    coordinate.append((dimensione - 8, 8))
    for riga, colonna in coordinate:
        riservati[riga][colonna] = True


def _riserva_versione(moduli, riservati, versione: int) -> None:
    """Come il formato, per i due blocchi che dicono la versione (>= 7)."""
    if versione < 7:
        return
    dimensione = len(moduli)
    for i in range(18):
        riga, colonna = i // 3, i % 3
        riservati[dimensione - 11 + colonna][riga] = True
        riservati[riga][dimensione - 11 + colonna] = True


def _trova_pattern(moduli, riservati, riga: int, colonna: int) -> None:
    dimensione = len(moduli)
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = riga + r, colonna + c
            if not (0 <= rr < dimensione and 0 <= cc < dimensione):
                continue
            # L'anello esterno e il nucleo da 3x3 sono scuri; l'anello
            # in mezzo e il bordo di separazione sono chiari.
            dentro = 0 <= r <= 6 and 0 <= c <= 6
            scuro = dentro and (r in (0, 6) or c in (0, 6)
                               or (2 <= r <= 4 and 2 <= c <= 4))
            moduli[rr][cc] = 1 if scuro else 0
            riservati[rr][cc] = True


def _timing(moduli, riservati) -> None:
    dimensione = len(moduli)
    for i in range(8, dimensione - 8):
        scuro = 1 if i % 2 == 0 else 0
        for riga, colonna in ((6, i), (i, 6)):
            moduli[riga][colonna] = scuro
            riservati[riga][colonna] = True


def _allineamento(moduli, riservati, versione: int) -> None:
    centri = ALLINEAMENTO.get(versione, ())
    dimensione = len(moduli)
    for riga in centri:
        for colonna in centri:
            # I tre angoli con i pattern di posizione non li vogliono.
            if ((riga == 6 and colonna == 6)
                    or (riga == 6 and colonna == dimensione - 7)
                    or (riga == dimensione - 7 and colonna == 6)):
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    rr, cc = riga + r, colonna + c
                    if not (0 <= rr < dimensione and 0 <= cc < dimensione):
                        continue
                    # Anello scuro, dentro chiaro, nucleo scuro.
                    scuro = max(abs(r), abs(c)) != 1
                    moduli[rr][cc] = 1 if scuro else 0
                    riservati[rr][cc] = True


def _fmt(versione: int, maschera: int) -> int:
    """I 15 bit del formato: livello, maschera, e cinque di controllo."""
    dati = (_LIVELLO_L << 3) | maschera
    resto = dati
    for _ in range(10):
        resto = (resto << 1) ^ ((resto >> 9) * 0x537)
    return ((dati << 10) | resto) ^ 0x5412


def _versione_bit(versione: int) -> int:
    resto = versione
    for _ in range(12):
        resto = (resto << 1) ^ ((resto >> 11) * 0x1F25)
    return (versione << 12) | resto


def _formato(moduli, riservati, versione: int, maschera: int) -> None:
    dimensione = len(moduli)
    bit = _fmt(versione, maschera)

    def metti(riga: int, colonna: int, indice: int) -> None:
        moduli[riga][colonna] = (bit >> indice) & 1
        riservati[riga][colonna] = True

    # Copia attorno al pattern in alto a sinistra.
    for i in range(6):
        metti(i, 8, i)
    metti(7, 8, 6)
    metti(8, 8, 7)
    metti(8, 7, 8)
    for i in range(9, 15):
        metti(8, 14 - i, i)
    # E la seconda copia, divisa fra l'angolo in basso a sinistra e
    # quello in alto a destra.
    for i in range(8):
        metti(8, dimensione - 1 - i, i)
    for i in range(8, 15):
        metti(dimensione - 15 + i, 8, i)
    # Il modulo sempre scuro: senza, un lettore non capisce dove
    # finisce la griglia. Va scritto come valore, non come bit del
    # formato: `metti` prende un indice, e passargli 1 scriverebbe il
    # secondo bit del formato — quasi sempre uguale a 1, quindi quasi
    # sempre giusto: il tipo di errore che passa inosservato fino al
    # primo testo che lo rende visibile.
    moduli[dimensione - 8][8] = 1
    riservati[dimensione - 8][8] = True


def _versione_info(moduli, riservati, versione: int) -> None:
    if versione < 7:
        return
    dimensione = len(moduli)
    bit = _versione_bit(versione)
    for i in range(18):
        valore = (bit >> i) & 1
        riga = i // 3
        colonna = i % 3
        moduli[dimensione - 11 + colonna][riga] = valore
        riservati[dimensione - 11 + colonna][riga] = True
        moduli[riga][dimensione - 11 + colonna] = valore
        riservati[riga][dimensione - 11 + colonna] = True


def _metti_dati(moduli, riservati, codici: list[int], versione: int) -> None:
    dimensione = len(moduli)
    bit: list[int] = []
    for codice in codici:
        for i in range(7, -1, -1):
            bit.append((codice >> i) & 1)

    indice = 0
    colonna = dimensione - 1
    verso_su = True
    while colonna > 0:
        if colonna == 6:  # la colonna dei tempi non e' dati
            colonna -= 1
        righe = range(dimensione - 1, -1, -1) if verso_su \
            else range(dimensione)
        for riga in righe:
            for c in (colonna, colonna - 1):
                if riservati[riga][c]:
                    continue
                moduli[riga][c] = bit[indice] if indice < len(bit) else 0
                indice += 1
        verso_su = not verso_su
        colonna -= 2


MASCHERE = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


def _applica_maschera(moduli, riservati, maschera: int) -> None:
    funzione = MASCHERE[maschera]
    for riga, fila in enumerate(moduli):
        for colonna, valore in enumerate(fila):
            if riservati[riga][colonna] or valore is None:
                continue
            if funzione(riga, colonna):
                moduli[riga][colonna] = valore ^ 1


def _penalita(moduli: list[list[int]]) -> int:
    """Quanto e' difficile da leggere questa matrice (meno e' meglio).

    Le quattro regole dello standard: tratti lunghi, blocchi 2x2,
    sequenze che sembrano un pattern di posizione, e squilibrio fra
    scuro e chiaro.
    """
    dimensione = len(moduli)
    punti = 0
    for verso in ("righe", "colonne"):
        for i in range(dimensione):
            fila = (moduli[i] if verso == "righe"
                    else [moduli[r][i] for r in range(dimensione)])
            # Regola 1: cinque o piu' moduli uguali di fila.
            run = 1
            for j in range(1, dimensione):
                if fila[j] == fila[j - 1]:
                    run += 1
                else:
                    if run >= 5:
                        punti += 3 + (run - 5)
                    run = 1
            if run >= 5:
                punti += 3 + (run - 5)
            # Regola 3: 1011101 con quattro zeri accanto.
            testo = "".join(str(v) for v in fila)
            for modello in ("10111010000", "00001011101"):
                inizio = testo.find(modello)
                while inizio != -1:
                    punti += 40
                    inizio = testo.find(modello, inizio + 1)
    # Regola 2: blocchi 2x2 dello stesso colore.
    for r in range(dimensione - 1):
        for c in range(dimensione - 1):
            v = moduli[r][c]
            if v == moduli[r][c + 1] == moduli[r + 1][c] \
                    == moduli[r + 1][c + 1]:
                punti += 3
    # Regola 4: scuro e chiaro devono somigliarsi.
    scuri = sum(1 for fila in moduli for v in fila if v)
    percentuale = scuri * 100 // (dimensione * dimensione)
    punti += 10 * (abs(percentuale - 50) // 5)
    return punti


def matrice(testo: str, *, maschera: int | None = None) -> list[list[int]]:
    """La matrice di moduli (1 scuro, 0 chiaro) per questo testo.

    `maschera` forzata serve ai test: scegliendo la stessa maschera di
    un altro encoder si possono confrontare le matrici bit per bit,
    mentre lasciandola scegliere a due implementazioni diverse i
    risultati sono diversi e ugualmente validi.
    """
    dati = testo.encode("utf-8")
    versione = _versione(len(dati))
    codici = _bit(dati, versione)
    interlacciati, _ = _blocchi(codici, versione)

    dimensione = versione * 4 + 17
    moduli, riservati = _nuova_matrice(dimensione)
    # Ordine obbligato: prima i pattern fissi (che riservano le loro
    # celle), poi i dati nelle celle libere, poi formato e versione,
    # che stanno sopra celle gia' riservate.
    _trova_pattern(moduli, riservati, 0, 0)
    _trova_pattern(moduli, riservati, 0, dimensione - 7)
    _trova_pattern(moduli, riservati, dimensione - 7, 0)
    _allineamento(moduli, riservati, versione)
    _timing(moduli, riservati)
    _riserva_formato(moduli, riservati, dimensione)
    _riserva_versione(moduli, riservati, versione)
    _metti_dati(moduli, riservati, interlacciati, versione)

    candidate: list[tuple[int, int]] = []
    for numero in ([maschera] if maschera is not None else range(8)):
        prova = [fila[:] for fila in moduli]
        riservati_prova = [fila[:] for fila in riservati]
        _applica_maschera(prova, riservati_prova, numero)
        _formato(prova, riservati_prova, versione, numero)
        _versione_info(prova, riservati_prova, versione)
        finale = [[0 if v is None else int(v) for v in fila] for fila in prova]
        candidate.append((_penalita(finale), numero))
        if maschera is not None:
            return finale
        if numero == 0:
            migliore = finale
            migliore_punti = _penalita(finale)
        elif candidate[-1][0] < migliore_punti:
            migliore = finale
            migliore_punti = candidate[-1][0]
    return migliore


def svg(testo: str, *, modulo: int = 6, bordo: int = 4) -> str:
    """Il QR come SVG: si scala senza sfocare, e si stampa bene.

    Un modulo per pixel in un PNG a 300 px e' illeggibile su uno
    schermo ad alta densita'; l'SVG no, e pesa meno.
    """
    moduli = matrice(testo)
    lato = len(moduli)
    lato_totale = (lato + bordo * 2) * modulo
    pezzi = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{lato_totale}" '
        f'height="{lato_totale}" viewBox="0 0 {lato_totale} {lato_totale}" '
        f'shape-rendering="crispEdges">',
        f'<rect width="{lato_totale}" height="{lato_totale}" fill="#fff"/>',
    ]
    for riga, fila in enumerate(moduli):
        # Rettangoli uniti per riga: un QR ha centinaia di moduli neri,
        # e un `<rect>` per modulo triplica il file senza cambiare un
        # pixel. I tratti contigui diventano un rettangolo solo.
        colonna = 0
        while colonna < lato:
            if not fila[colonna]:
                colonna += 1
                continue
            inizio = colonna
            while colonna < lato and fila[colonna]:
                colonna += 1
            pezzi.append(
                f'<rect x="{(inizio + bordo) * modulo}" '
                f'y="{(riga + bordo) * modulo}" '
                f'width="{(colonna - inizio) * modulo}" height="{modulo}"/>')
    pezzi.append("</svg>")
    # Il nero lo decide il CSS di chi lo mostra: nel tema scuro un QR
    # nero su bianco resta leggibile, ma un `<rect>` senza fill
    # erediterebbe il colore del testo e su fondo scuro diventerebbe
    # bianco su bianco.
    return "".join(pezzi)
