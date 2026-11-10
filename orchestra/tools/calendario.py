"""Tool calendario: leggere, scrivere e sincronizzare l'agenda.

PERCHE' UN TOOL E NON SOLO UN MODULO

Un modulo che sa leggere un .ics non serve a niente se l'agente non sa che
esiste: l'elenco degli strumenti attivi e' la mappa che ha di se stesso.
Questa e' la lezione del ponte Telegram, dove il codice c'era e l'agente
rispondeva "non posso". Quindi il tool c'e', sta in tutti i profili, e la
descrizione dice esplicitamente cosa fare quando un evento non c'e'.

DOVE STA IL FILE

Senza `file`, si lavora su `calendario.ics` nella cartella dati di
Orchestra: un calendario suo, che nessun altro programma tocca. Con
`file` si legge un .ics esportato (Google, Apple, Outlook) passando dal
confine dei percorsi come tutti gli altri tool.

I CALENDARI SINCRONIZZATI SONO IN SOLA LETTURA

Un abbonamento (`aggiungi_fonte`) scarica una copia e la unisce alle
letture, marcata con `fonte`. Cancellare un evento che viene da fuori e'
un errore dichiarato, non un silenzio: la cancellazione vera si fa nel
calendario di origine, e qui si sincronizza di nuovo. Fingere di averla
fatta sarebbe peggio che non farla.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..types import Tool
from ._guard import _safe_path
import orchestra.calendario as cal
import orchestra.calendario_sync as sync


def _istante(valore: str) -> tuple[dt.datetime, bool]:
    """(quando, tutto il giorno) da una data scritta in modo umano."""
    v = (valore or "").strip()
    if not v:
        raise ValueError("data mancante")
    tutto_il_giorno = ":" not in v
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d",
                    "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(v, formato), tutto_il_giorno
        except ValueError:
            continue
    raise ValueError(
        f"data non riconosciuta: '{v}'. Usa AAAA-MM-GG, oppure "
        f"AAAA-MM-GG HH:MM.")


def _file(file: str) -> str:
    """Il percorso del calendario: quello dell'utente, o quello di Orchestra."""
    if (file or "").strip():
        return str(_safe_path(file.strip()))
    return cal.percorso_default()


def _elenco(eventi: list[dict[str, Any]], titolo: str) -> str:
    if not eventi:
        return f"{titolo}: nessun evento."
    righe = [f"{titolo} ({len(eventi)}):"]
    righe.extend("  " + cal.formatta(ev) for ev in eventi)
    return "\n".join(righe)


def _finestra(azione: str, da: str, a: str) -> tuple[dt.datetime, dt.datetime]:
    oggi = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if azione in ("oggi",):
        return oggi, oggi + dt.timedelta(days=1) - dt.timedelta(seconds=1)
    if azione in ("settimana", "prossimi"):
        return oggi, oggi + dt.timedelta(days=7) - dt.timedelta(seconds=1)
    inizio, _ = _istante(da) if da else (oggi, False)
    fine, _ = _istante(a) if a else (inizio + dt.timedelta(days=30), False)
    return inizio, fine


def _uniti(inizio: dt.datetime, fine: dt.datetime, percorso_file: str,
           solo_locale: bool) -> list[dict[str, Any]]:
    """Locali + remoti, ordinati, senza lo stesso evento due volte.

    Un evento importato a mano dal calendario che poi si sincronizza ha lo
    stesso UID in due posti: mostrarlo due volte farebbe credere di avere
    due appuntamenti.
    """
    eventi = cal.eventi(inizio, fine, file=percorso_file)
    for evento in eventi:
        evento["remoto"] = False
    if not solo_locale:
        eventi.extend(sync.eventi_remoti(inizio, fine))
    eventi.sort(key=lambda e: (e["inizio"], e["titolo"]))
    visti: set[tuple[str, dt.datetime]] = set()
    fuori: list[dict[str, Any]] = []
    for evento in eventi:
        chiave = (evento.get("uid") or "", evento["inizio"])
        if chiave[0] and chiave in visti and not evento.get("remoto"):
            # Il locale vince: e' quello che si puo' modificare da qui.
            fuori = [e for e in fuori if (e.get("uid"), e["inizio"]) != chiave]
        elif chiave[0] and chiave in visti:
            continue
        visti.add(chiave)
        fuori.append(evento)
    return fuori


def tool_calendario() -> Tool:
    def handler(azione: str = "oggi", da: str = "", a: str = "",
                testo: str = "", titolo: str = "", inizio: str = "",
                fine: str = "", luogo: str = "", note: str = "",
                id: str = "", file: str = "", nome: str = "",
                url: str = "") -> str:
        azione = (azione or "oggi").strip().lower()
        try:
            if azione in ("fonti", "stato", "sincronizzati"):
                return sync.stato()

            if azione in ("aggiungi_fonte", "abbonati", "sottoscrivi"):
                fonte = sync.aggiungi_fonte(nome, url)
                verbo = "aggiunto" if fonte.get("nuova") else "aggiornato"
                return (f"Calendario {verbo}: {fonte['nome']} · {fonte['url']}. "
                        f"Ora `sincronizza` scarica gli eventi.")

            if azione in ("elimina_fonte", "togli_fonte"):
                if sync.elimina_fonte(nome):
                    return f"Calendario rimosso: {nome}"
                return f"ERRORE: nessun calendario sincronizzato '{nome}'."

            if azione in ("sincronizza", "aggiorna_fonti"):
                esiti = sync.sincronizza(nome)
                if not esiti:
                    return ("Nessun calendario da sincronizzare: aggiungine "
                            "uno con `aggiungi_fonte`.")
                righe = ["Sincronizzazione:"]
                righe.extend(f"  {e['nome']}: {e['esito']}" for e in esiti)
                return "\n".join(righe)

            percorso_file = _file(file)
            solo_locale = bool((file or "").strip())

            if azione in ("oggi", "settimana", "prossimi", "periodo"):
                inizio_f, fine_f = _finestra(azione, da, a)
                eventi = _uniti(inizio_f, fine_f, percorso_file, solo_locale)
                if azione == "oggi":
                    etichetta = "Oggi " + inizio_f.strftime("%d/%m/%Y")
                elif azione == "periodo":
                    etichetta = (inizio_f.strftime("%d/%m/%Y")
                                 + " - " + fine_f.strftime("%d/%m/%Y"))
                else:
                    etichetta = "Prossimi 7 giorni"
                return _elenco(eventi, etichetta)

            if azione in ("cerca", "trova"):
                cerca = (testo or titolo or "").strip()
                if not cerca:
                    return "ERRORE: per cercare serve `testo`."
                inizio_f = dt.datetime.now() - dt.timedelta(days=1)
                eventi = _uniti(inizio_f, inizio_f + dt.timedelta(days=365),
                                percorso_file, solo_locale)
                ago = cerca.lower()
                trovati = [e for e in eventi
                           if ago in (e["titolo"] + " " + e["luogo"] + " "
                                      + e["note"]).lower()]
                return _elenco(trovati, f"Eventi con '{cerca}'")

            if azione in ("aggiungi", "crea", "segna"):
                quando, tutto_il_giorno = _istante(inizio)
                finito = None
                if (fine or "").strip():
                    finito, _ = _istante(fine)
                salvato = cal.aggiungi(
                    titolo, quando, finito, luogo=luogo, note=note,
                    tutto_il_giorno=tutto_il_giorno, file=percorso_file)
                dove = salvato["file"]
                extra = f" in {dove}" if dove != cal.percorso_default() else ""
                return ("Evento aggiunto" + extra + ": "
                        + cal.formatta(salvato))

            if azione in ("elimina", "cancella", "togli"):
                if not (id or "").strip():
                    return ("ERRORE: serve `id` (l'identificativo dell'evento, "
                            "quello che compare dopo 'id').")
                if cal.elimina(id, file=percorso_file):
                    return f"Evento eliminato: {id}"
                ora = dt.datetime.now()
                remoto = next(
                    (e for e in sync.eventi_remoti(
                        ora - dt.timedelta(days=365),
                        ora + dt.timedelta(days=365))
                     if e.get("uid") == id), None)
                if remoto:
                    return (f"ERRORE: questo evento viene dal calendario "
                            f"sincronizzato '{remoto['fonte']}' e da qui non "
                            f"si cancella. Cancellalo li', poi `sincronizza`.")
                return f"ERRORE: nessun evento con id {id}."

            return ("ERRORE: azione sconosciuta. Usa: oggi, settimana, "
                    "periodo, cerca, aggiungi, elimina, fonti, "
                    "aggiungi_fonte, elimina_fonte, sincronizza.")
        except PermissionError as e:
            return f"ERRORE: {e}"
        except Exception as e:  # noqa: BLE001 - un tool non fa cadere il turno
            return f"ERRORE: {type(e).__name__}: {e}"

    return Tool(
        name="calendario",
        description=(
            "Reads and writes the user's calendar, stored as an .ics file "
            "(the format every calendar app can import and export). The "
            "`azione` values are: `oggi` and `settimana` (what is coming), "
            "`periodo` (da, a), `cerca` (testo), `aggiungi` (titolo, inizio, "
            "fine optional, luogo, note), `elimina` (id), plus the "
            "subscriptions: `fonti` (what is subscribed), `aggiungi_fonte` "
            "(nome, url of an iCal link), `elimina_fonte` (nome), "
            "`sincronizza` (fonte optional — necessary before new remote "
            "events appear). A subscribed calendar is remote and read-only: "
            "its events are marked with the source and cannot be deleted "
            "here, say so instead of pretending. Dates are 'AAAA-MM-GG' or "
            "'AAAA-MM-GG HH:MM'; without an hour the event is all-day. "
            "Without `file` it uses Orchestra's own calendar; with `file` it "
            "reads an .ics exported from another app. Use it whenever the "
            "user asks what they have on a day, or asks to be reminded of a "
            "date. Never invent an event: if the answer is empty, say the "
            "day is empty."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {"type": "string", "description":
                           "oggi|settimana|periodo|cerca|aggiungi|elimina|"
                           "fonti|aggiungi_fonte|elimina_fonte|sincronizza "
                           "(today|week|range|search|add|delete|sources|"
                           "add_source|remove_source|sync)."},
                "da": {"type": "string", "description":
                       "Start of the range (for periodo)."},
                "a": {"type": "string", "description":
                      "End of the range (for periodo)."},
                "testo": {"type": "string", "description":
                          "Text to look for (for cerca)."},
                "titolo": {"type": "string", "description":
                           "Event title (for aggiungi)."},
                "inizio": {"type": "string", "description":
                           "Start: AAAA-MM-GG or AAAA-MM-GG HH:MM (for aggiungi)."},
                "fine": {"type": "string", "description":
                         "End, same format. Omit for one hour / the whole day."},
                "luogo": {"type": "string", "description":
                          "Where it happens (for aggiungi)."},
                "note": {"type": "string", "description":
                         "Free notes (for aggiungi)."},
                "id": {"type": "string", "description":
                       "Event id shown after 'id' (for elimina)."},
                "file": {"type": "string", "description":
                         "Path of an .ics file, when not using Orchestra's own."},
                "nome": {"type": "string", "description":
                         "Short name of a subscribed calendar, e.g. 'lavoro'."},
                "url": {"type": "string", "description":
                        "iCal link of a subscribed calendar (http/https/webcal)."},
            },
            "required": [],
        },
        handler=handler,
    )
