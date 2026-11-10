"""Calendario: un file .ics, letto e scritto a mano.

PERCHE' UN FILE E NON UN SERVIZIO

Un calendario vero (Google, Outlook) vuole OAuth, un browser, un token che
scade: tre cose che trasformano "segna l'appuntamento" in una procedura di
mezz'ora. Un file `.ics` invece e' testo, lo apre qualunque calendario, e
lo si puo' anche esportare a mano da Google o da Apple. Quindi qui si
legge e si scrive iCalendar, e chi vuole la sincronizzazione esporta il
file dove serve.

CHE COSA SI SUPPORTA DAVVERO

Gli eventi singoli e la ripetizione semplice (RRULE con FREQ, INTERVAL,
COUNT, UNTIL per GIORNALIERO/SETTIMANALE/MENSILE/ANNUALE). Le regole
complesse — BYDAY, BYSETPOS, i fusi con VTIMEZONE — non si inventano: un
evento che le usa viene restituito come singolo, e la cosa si dichiara
invece di far sparire l'appuntamento. Meglio un evento con la data
sbagliata che dice di essere sbagliata, di uno che non c'e'.

I fusi: si scrive sempre ora locale "flottante" (senza `Z`), che e' il
formato che ogni calendario interpreta come "l'ora del posto in cui sei".
Un evento che ARRIVA con `Z` viene convertito nell'ora locale di questa
macchina, perche' l'utente legge l'orologio del suo computer.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import tempfile
import uuid
from typing import Any

from .dati import percorso

NOME_FILE = "calendario.ics"

# Un tetto alle occorrenze generate: una RRULE senza COUNT ne' UNTIL e'
# infinita, e una query su un decennio la farebbe esplodere.
MAX_OCCORRENZE = 5000


def percorso_default() -> str:
    return percorso(NOME_FILE)


# ---------------------------------------------------------------- formati

def _scompatta(testo: str) -> list[str]:
    """Le righe logiche di un .ics (RFC 5545: continuazione con spazio)."""
    righe: list[str] = []
    for grezza in (testo or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if grezza[:1] in (" ", "\t") and righe:
            righe[-1] += grezza[1:]
        elif grezza.strip():
            righe.append(grezza)
    return righe


def _piega(riga: str, massimo: int = 73) -> str:
    """Spezza una riga oltre il limite, contando gli ottetti UTF-8.

    Il limite vero e' 75 ottetti; qui si sta sotto perche' lo spazio di
    continuazione conta anche lui. Un carattere accentato occupa due
    ottetti, quindi contare i caratteri farebbe righe troppo lunghe.
    """
    if len(riga.encode("utf-8")) <= massimo:
        return riga
    pezzi: list[str] = []
    corrente: list[str] = []
    conta = 0
    for ch in riga:
        n = len(ch.encode("utf-8"))
        if conta + n > massimo:
            pezzi.append("".join(corrente))
            corrente, conta = [], 0
        corrente.append(ch)
        conta += n
    if corrente:
        pezzi.append("".join(corrente))
    return "\r\n ".join(pezzi)


def _pulisci(valore: str) -> str:
    return ((valore or "").replace("\\n", "\n").replace("\\N", "\n")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def _scappa(valore: Any) -> str:
    testo = str(valore or "")
    return (testo.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def _quando(valore: str) -> tuple[dt.datetime, bool]:
    """(data e ora, tutto il giorno) da un DTSTART/DTEND."""
    v = (valore or "").strip()
    if not v:
        raise ValueError("data vuota")
    if v.endswith("Z"):
        base = dt.datetime.strptime(v[:-1], "%Y%m%dT%H%M%S")
        return (base.replace(tzinfo=dt.timezone.utc).astimezone()
                .replace(tzinfo=None), False)
    if "T" in v:
        return dt.datetime.strptime(v[:15], "%Y%m%dT%H%M%S"), False
    return dt.datetime.strptime(v[:8], "%Y%m%d"), True


def _ics_data(q: dt.datetime) -> str:
    return q.strftime("%Y%m%d")


def _ics_dataora(q: dt.datetime) -> str:
    return q.strftime("%Y%m%dT%H%M%S")


def _aggiungi_mesi(base: dt.datetime, mesi: int) -> dt.datetime:
    """Somma mesi tenendo il giorno, senza andare oltre fine mese."""
    mese = base.month - 1 + mesi
    anno = base.year + mese // 12
    mese = mese % 12 + 1
    giorni = [31, 29 if (anno % 4 == 0 and (anno % 100 != 0 or anno % 400 == 0))
              else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mese - 1]
    return base.replace(year=anno, month=mese, day=min(base.day, giorni))


# ---------------------------------------------------------------- lettura

def _blocchi(righe: list[str]) -> list[dict[str, str]]:
    """I VEVENT come dizionari di campi (nome in maiuscolo)."""
    eventi: list[dict[str, str]] = []
    corrente: dict[str, str] = {}
    dentro = False
    for riga in righe:
        if riga.upper() == "BEGIN:VEVENT":
            dentro, corrente = True, {}
            continue
        if riga.upper() == "END:VEVENT":
            if dentro:
                eventi.append(corrente)
            dentro, corrente = False, {}
            continue
        if not dentro or ":" not in riga:
            continue
        nome, valore = riga.split(":", 1)
        chiave = nome.split(";", 1)[0].upper()
        corrente[chiave] = valore
        if chiave in ("DTSTART", "DTEND") and ";" in nome:
            corrente[chiave + "PARAM"] = nome.split(";", 1)[1].upper()
    return eventi


def _regola(ev: dict[str, str]) -> dict[str, Any] | None:
    grezza = ev.get("RRULE") or ""
    if not grezza:
        return None
    regola: dict[str, Any] = {"freq": "", "interval": 1, "count": None,
                              "until": None}
    for pezzo in grezza.split(";"):
        if "=" not in pezzo:
            continue
        chiave, valore = pezzo.split("=", 1)
        chiave = chiave.strip().upper()
        if chiave == "FREQ":
            regola["freq"] = valore.strip().upper()
        elif chiave == "INTERVAL":
            try:
                regola["interval"] = max(1, int(valore))
            except ValueError:
                pass
        elif chiave == "COUNT":
            try:
                regola["count"] = max(1, int(valore))
            except ValueError:
                pass
        elif chiave == "UNTIL":
            try:
                regola["until"], _ = _quando(valore)
            except ValueError:
                pass
    if regola["freq"] not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        # BYDAY, BYSETPOS e compagnia: non si indovina. L'evento resta
        # singolo, e chi legge sa che quella e' la prima occorrenza.
        return None
    return regola


def leggi(testo: str) -> list[dict[str, Any]]:
    """Gli eventi del file come dizionari, inizio e fine gia' risolti."""
    fuori: list[dict[str, Any]] = []
    for ev in _blocchi(_scompatta(testo)):
        grezzo = ev.get("DTSTART") or ""
        if not grezzo:
            continue
        try:
            inizio, tutto_il_giorno = _quando(grezzo)
        except ValueError:
            continue
        fine: dt.datetime | None = None
        if ev.get("DTEND"):
            try:
                fine, _ = _quando(ev["DTEND"])
            except ValueError:
                fine = None
        fuori.append({
            "uid": ev.get("UID") or "",
            "titolo": _pulisci(ev.get("SUMMARY") or "(senza titolo)"),
            "inizio": inizio,
            "fine": fine,
            "tutto_il_giorno": tutto_il_giorno,
            "luogo": _pulisci(ev.get("LOCATION") or ""),
            "note": _pulisci(ev.get("DESCRIPTION") or ""),
            "regola": _regola(ev),
        })
    return fuori


def _occorrenze(ev: dict[str, Any], fine_finestra: dt.datetime
                ) -> list[dt.datetime]:
    """Le date in cui questo evento capita, ripetizione compresa.

    Si parte sempre dal DTSTART: e' cosi' che la regola e' definita, e
    contare le occorrenze da li' e' l'unico modo di rispettare COUNT.
    """
    inizio: dt.datetime = ev["inizio"]
    regola = ev.get("regola")
    if not regola:
        return [inizio]
    date = [inizio]
    corrente = inizio
    for _ in range(MAX_OCCORRENZE):
        if regola["freq"] == "DAILY":
            corrente = corrente + dt.timedelta(days=regola["interval"])
        elif regola["freq"] == "WEEKLY":
            corrente = corrente + dt.timedelta(weeks=regola["interval"])
        elif regola["freq"] == "MONTHLY":
            corrente = _aggiungi_mesi(corrente, regola["interval"])
        else:
            corrente = _aggiungi_mesi(corrente, 12 * regola["interval"])
        if regola["count"] is not None and len(date) >= regola["count"]:
            break
        if regola["until"] is not None and corrente > regola["until"]:
            break
        if corrente > fine_finestra:
            break
        date.append(corrente)
        # Una regola malata (INTERVAL=0) non deve bloccare il ciclo: il
        # tetto delle occorrenze e i controlli sopra bastano.
    return date


def eventi(da: dt.datetime, a: dt.datetime,
           file: str = "") -> list[dict[str, Any]]:
    """Gli eventi fra `da` e `a` (estremi inclusi), ripetizioni espanse."""
    percorso_file = file or percorso_default()
    try:
        with open(percorso_file, encoding="utf-8", errors="replace") as f:
            grezzo = f.read()
    except OSError:
        return []
    fuori: list[dict[str, Any]] = []
    for ev in leggi(grezzo):
        durata = (ev["fine"] - ev["inizio"]) if ev["fine"] else None
        for quando in _occorrenze(ev, a):
            fine = (quando + durata) if durata else None
            if (fine or quando) < da or quando > a:
                continue
            fuori.append({
                "uid": ev["uid"],
                "titolo": ev["titolo"],
                "inizio": quando,
                "fine": fine,
                "tutto_il_giorno": ev["tutto_il_giorno"],
                "luogo": ev["luogo"],
                "note": ev["note"],
                "ripetuto": bool(ev.get("regola")),
            })
    fuori.sort(key=lambda e: (e["inizio"], e["titolo"]))
    return fuori


# ---------------------------------------------------------------- scrittura

_INTESTAZIONE = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Orchestra//Calendario//IT\r\n"
    "CALSCALE:GREGORIAN\r\n"
)


def _leggi_o_vuoto(percorso_file: str) -> str:
    try:
        with open(percorso_file, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _scrivi_atomico(percorso_file: str, contenuto: str) -> None:
    cartella = os.path.dirname(os.path.abspath(percorso_file)) or "."
    os.makedirs(cartella, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(dir=cartella, suffix=".ics")
    os.close(fd)
    try:
        with open(temporaneo, "w", encoding="utf-8", newline="") as f:
            f.write(contenuto)
        os.replace(temporaneo, percorso_file)
    except Exception:
        try:
            os.unlink(temporaneo)
        except OSError:
            pass
        raise


def aggiungi(titolo: str, inizio: dt.datetime, fine: dt.datetime | None = None,
             *, luogo: str = "", note: str = "", tutto_il_giorno: bool = False,
             file: str = "") -> dict[str, Any]:
    """Aggiunge un evento e torna quello che e' stato scritto."""
    titolo = (titolo or "").strip()
    if not titolo:
        raise ValueError("serve un titolo: un evento senza nome non si ritrova")
    if fine is None:
        fine = inizio + (dt.timedelta(days=1) if tutto_il_giorno
                         else dt.timedelta(hours=1))
    if fine < inizio:
        raise ValueError("la fine e' prima dell'inizio")
    percorso_file = file or percorso_default()
    uid = f"{uuid.uuid4().hex}@orchestra"
    corpo = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        "DTSTAMP:" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "DTSTART:" + (_ics_data(inizio) if tutto_il_giorno
                      else _ics_dataora(inizio)),
        "DTEND:" + (_ics_data(fine) if tutto_il_giorno else _ics_dataora(fine)),
        "SUMMARY:" + _scappa(titolo),
    ]
    if luogo:
        corpo.append("LOCATION:" + _scappa(luogo))
    if note:
        corpo.append("DESCRIPTION:" + _scappa(note))
    corpo.append("END:VEVENT")

    esistente = _leggi_o_vuoto(percorso_file).replace("\r\n", "\n")
    if "BEGIN:VCALENDAR" not in esistente.upper():
        esistente = _INTESTAZIONE
    # L'evento va PRIMA della chiusura: un VEVENT dopo END:VCALENDAR non
    # esiste per nessun calendario, e il file sembrerebbe scritto bene.
    taglio = esistente.upper().rfind("END:VCALENDAR")
    if taglio < 0:
        corpo_file = esistente.rstrip("\n") + "\r\n"
    else:
        corpo_file = (esistente[:taglio].rstrip("\r\n") + "\r\n")
    nuovo = (corpo_file.rstrip("\r\n") + "\r\n"
             + "".join(_piega(r) + "\r\n" for r in corpo)
             + "END:VCALENDAR\r\n")
    _scrivi_atomico(percorso_file, nuovo)
    return {
        "uid": uid, "titolo": titolo, "inizio": inizio, "fine": fine,
        "tutto_il_giorno": tutto_il_giorno, "luogo": luogo, "note": note,
        "file": percorso_file,
    }


def elimina(uid: str, file: str = "") -> bool:
    """Toglie l'evento con quell'UID. False se non c'era."""
    uid = (uid or "").strip()
    if not uid:
        raise ValueError("serve l'id dell'evento")
    percorso_file = file or percorso_default()
    righe = _scompatta(_leggi_o_vuoto(percorso_file))
    fuori: list[str] = []
    dentro = False
    tolto = False
    for riga in righe:
        if riga.upper() == "BEGIN:VEVENT":
            dentro, tenere = True, True
            blocco = [riga]
            continue
        if dentro:
            blocco.append(riga)
            if riga.upper().startswith("UID:") and riga[4:].strip() == uid:
                tenere = False
            if riga.upper() == "END:VEVENT":
                dentro = False
                if tenere:
                    fuori.extend(blocco)
                else:
                    tolto = True
            continue
        fuori.append(riga)
    if not tolto:
        return False
    _scrivi_atomico(percorso_file, "\r\n".join(
        _piega(r) for r in fuori) + "\r\n")
    return True


def formatta(ev: dict[str, Any]) -> str:
    """Una riga leggibile, con l'ora locale e senza secondi inutili."""
    inizio: dt.datetime = ev["inizio"]
    fine: dt.datetime | None = ev.get("fine")
    if ev.get("tutto_il_giorno"):
        quando = inizio.strftime("%Y-%m-%d") + " (tutto il giorno)"
    else:
        quando = inizio.strftime("%Y-%m-%d %H:%M")
        if fine:
            quando += " - " + fine.strftime("%H:%M")
    riga = f"{quando} · {ev['titolo']}"
    if ev.get("luogo"):
        riga += f" ({ev['luogo']})"
    if ev.get("fonte"):
        # Un evento che viene da un calendario sincronizzato si dice: e'
        # la differenza fra un appuntamento tuo e uno che si modifica
        # da un'altra parte.
        riga += f" · da {ev['fonte']}"
    if ev.get("ripetuto"):
        riga += " [ricorrente]"
    if ev.get("uid"):
        riga += f" · id {ev['uid']}"
    return riga
