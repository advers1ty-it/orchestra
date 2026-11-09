"""Tool email: leggere la casella (IMAP) e mandare (SMTP).

Un solo tool con un parametro `azione`, come `cron`. Due tool separati
(lettura e invio) costringerebbero il modello a scegliere prima di
sapere cosa serve, e nel prompt occupano il doppio.

L'invio e' l'unica azione che esce dall'installazione e arriva a una
persona vera. Per questo il tool non manda mai "una prova": se il testo
non c'e', si ferma, e la descrizione dice di usarlo solo quando l'utente
ha chiesto di mandare quella mail.
"""

from __future__ import annotations

from typing import Any

from ..types import Tool
import orchestra.mail as mail_mod


def _righe(messaggi: list[dict[str, Any]]) -> str:
    if not messaggi:
        return "Nessun messaggio con questi filtri."
    fuori: list[str] = []
    for i, m in enumerate(messaggi, 1):
        fuori.append(f"{i}. {m.get('data') or '(data assente)'} · {m.get('da') or '(mittente assente)'}")
        fuori.append(f"   Oggetto: {m.get('oggetto')}")
        anteprima = (m.get("anteprima") or "").strip()
        if anteprima:
            fuori.append(f"   {anteprima}")
        fuori.append("")
    return "\n".join(fuori).rstrip()


def tool_email() -> Tool:
    def handler(
        azione: str = "leggi",
        cartella: str = "INBOX",
        quanti: int = 10,
        da: str = "",
        oggetto: str = "",
        testo: str = "",
        non_letti: bool = False,
        a: str = "",
        cc: str = "",
        corpo: str = "",
        allegati: Any = None,
    ) -> str:
        azione = (azione or "leggi").strip().lower()
        try:
            if azione in ("stato", "status"):
                cfg = mail_mod.configurazione()
                return (f"casella: {cfg['indirizzo']}\n"
                        f"lettura (IMAP): {cfg['imap_host']}:{cfg['imap_port']}\n"
                        f"invio (SMTP): {cfg['smtp_host']}:{cfg['smtp_port']}")

            if azione in ("cartelle", "folders", "elenco_cartelle"):
                nomi = mail_mod.cartelle()
                return "\n".join(nomi) if nomi else "Il server non ha elencato cartelle."

            if azione in ("leggi", "read", "cerca", "search", "ultimi"):
                if isinstance(allegati, str):
                    allegati = [allegati]
                messaggi = mail_mod.leggi(
                    cartella=cartella or "INBOX",
                    quanti=quanti,
                    da=da,
                    oggetto=oggetto,
                    testo=testo,
                    non_letti=bool(non_letti),
                )
                return _righe(messaggi)

            if azione in ("manda", "invia", "send"):
                file_allegati = allegati or []
                if isinstance(file_allegati, str):
                    file_allegati = [file_allegati]
                esito = mail_mod.manda(
                    a=a, oggetto=oggetto, corpo=corpo, cc=cc,
                    allegati=[str(p) for p in file_allegati],
                )
                riga = f"Mail inviata da {esito['da']} a {', '.join(esito['a'])}"
                if esito["cc"]:
                    riga += f" (in copia: {', '.join(esito['cc'])})"
                if esito["allegati"]:
                    riga += f" con allegati: {', '.join(esito['allegati'])}"
                return riga + "."

            return ("ERRORE: azione sconosciuta. Usa: stato, cartelle, leggi, cerca, "
                    "manda.")
        except mail_mod.ErrorePosta as e:
            return f"ERRORE: {e}"
        except Exception as e:  # noqa: BLE001 - il tool non deve far cadere il turno
            return f"ERRORE: {type(e).__name__}: {e}"

    return Tool(
        name="email",
        description=(
            "Reads and sends the user's own mailbox over IMAP and SMTP. Actions: "
            "stato (which account and servers are configured), cartelle (folder "
            "list), leggi/cerca (latest messages, with filters da/oggetto/testo/"
            "non_letti and a folder), manda (send a message: a, cc, oggetto, "
            "corpo, allegati). Sending reaches real people: use manda only when "
            "the user asked to send that message, and never invent recipients or "
            "attachments. If it answers that credentials are missing, tell the "
            "user which variables to set; do not ask for their password in chat."
        ),
        schema={
            "type": "object",
            "properties": {
                "azione": {"type": "string", "description": "stato|cartelle|leggi|cerca|manda (status|folders|read|search|send)."},
                "cartella": {"type": "string", "description": "Mail folder to read (default INBOX)."},
                "quanti": {"type": "integer", "description": "How many messages to return, newest first (default 10, max 20)."},
                "da": {"type": "string", "description": "Filter by sender (partial address or name)."},
                "oggetto": {"type": "string", "description": "Filter by subject text."},
                "testo": {"type": "string", "description": "Filter by text anywhere in the message."},
                "non_letti": {"type": "boolean", "description": "Only unread messages."},
                "a": {"type": "string", "description": "Recipient(s), comma separated (for manda)."},
                "cc": {"type": "string", "description": "Copy recipients, comma separated (for manda)."},
                "corpo": {"type": "string", "description": "Plain-text body (for manda)."},
                "allegati": {"type": "array", "items": {"type": "string"}, "description": "File paths to attach (for manda)."},
            },
            "required": [],
        },
        handler=handler,
    )
