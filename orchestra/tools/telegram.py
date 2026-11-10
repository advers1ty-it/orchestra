"""Tool telegram_invia: scrivere nella chat Telegram collegata.

PERCHE' UN TOOL E NON LA SHELL

`orchestra/telegram.py` sa gia' mandare (`Api.send_message`): e' il ponte
che recapita ogni risposta. Ma il ponte e' codice, non un'istruzione:
l'elenco degli strumenti attivi E' la mappa che l'agente ha di se stesso,
e Telegram non c'era. Il sintomo visto davvero, non ipotetico, e' un
agente che risponde "non posso inviarti messaggi su Telegram" mentre la
sua risposta viaggia proprio su quel ponte. Lo stesso ragionamento per
cui `email` sta in tutti i profili ("un profilo che la toglie costringe
l'agente a dire 'non posso leggere la posta' a chi gliel'ha chiesto")
vale qui, e vale di piu': qui l'agente deve poter scrivere per primo,
non solo rispondere.

LA CREDENZIALE NON ENTRA NEL CONTESTO

Token e chat stanno in `telegram.db`, nella cartella dati. Il tool li
legge e li usa qui dentro: il modello non vede il token, non lo puo'
stampare in chat e non lo puo' mettere in un file. Un tool che
chiedesse il token all'utente sarebbe la stessa cosa che non averlo.
"""

from __future__ import annotations

from typing import Any

from ..types import Tool
import orchestra.telegram as tg


def _bot_predefinito() -> int:
    """Di chi e' la chat, quando il chiamante non lo dice.

    E' il bot che sta eseguendo il turno: un bot che lavora scrive nella
    propria chat, non in quella dell'agente principale. Fuori da un turno
    (un cron, un goal) la sessione corrente non c'e', e allora resta
    l'agente principale — che e' anche l'unico che puo' avere una chat
    senza essere un bot.
    """
    from ..bots import BASE_ID
    from ..session import sessione_corrente

    try:
        sess = sessione_corrente()
        ident = getattr(sess, "bot_id", None)
        if ident is not None:
            return int(ident)
    except Exception:  # noqa: BLE001 - il default deve valere sempre
        pass
    return int(BASE_ID)


def _invia(testo: str, bot_id: int | None = None) -> str:
    """Manda il testo, spezzandolo se supera il limite di Telegram."""
    testo = (testo or "").strip()
    if not testo:
        return "ERRORE: testo vuoto: non c'e' niente da mandare."
    try:
        ident = int(bot_id) if bot_id is not None else _bot_predefinito()
    except (TypeError, ValueError):
        ident = _bot_predefinito()
    token = tg.token_di(ident)
    chat, nome = tg.chat_di(ident)
    if not token:
        return ("ERRORE: nessun bot Telegram collegato. Il token si salva in "
                "Opzioni -> Bot -> Telegram, e non va incollato qui.")
    if not chat:
        return ("ERRORE: il bot ha un token ma nessuna chat collegata. Si "
                "collega da Opzioni -> Bot -> Telegram con il QR: il codice "
                "compare solo sullo schermo del computer.")
    api = tg.Api(token)
    pezzi = tg.dividi(testo)
    for pezzo in pezzi:
        try:
            # Come il ponte: l'HTML rende leggibile quello che il modello
            # scrive in markdown, e se Telegram lo rifiuta si manda il
            # testo nudo invece di perdere il messaggio.
            api.send_message(chat, tg.per_telegram(pezzo), parse_mode="HTML")
        except tg.ErroreTelegram as e:
            if int(getattr(e, "codice", 0) or 0) != 400:
                raise
            api.send_message(chat, tg.semplice(pezzo))
    dove = nome or chat
    parti = f", in {len(pezzi)} parti" if len(pezzi) > 1 else ""
    return (f"Messaggio mandato su Telegram a {dove} "
            f"({len(testo)} caratteri{parti}).")


def tool_telegram() -> Tool:
    def handler(testo: str = "", bot_id: Any = None) -> str:
        try:
            return _invia(testo, bot_id)
        except tg.ErroreTelegram as e:
            return f"ERRORE: Telegram ha rifiutato il messaggio: {e}"
        except Exception as e:  # noqa: BLE001 - un tool non fa cadere il turno
            return f"ERRORE: {type(e).__name__}: {e}"

    return Tool(
        name="telegram_invia",
        description=(
            "Sends a message on Telegram to the user's own chat, the one "
            "already linked to this bot. Use it to write proactively: a "
            "scheduled job that reports something, a result that arrives "
            "after the turn, or an alert the user asked for. It also works "
            "from a turn that did not come from Telegram. No token or chat "
            "id is needed and none should be asked for: it uses the link "
            "already saved. `testo` is the real message as the user will "
            "read it on the phone — never a placeholder or a test string. "
            "It answers where the message went; if it says no chat is "
            "linked, tell the user to link one from Opzioni > Bot > Telegram."
        ),
        schema={
            "type": "object",
            "properties": {
                "testo": {
                    "type": "string",
                    "description": ("The message body, in the user's language. "
                                    "Required."),
                },
                "bot_id": {
                    "type": "integer",
                    "description": ("Which bot's Telegram chat to use. Omit for "
                                    "the bot running this turn."),
                },
            },
            "required": ["testo"],
        },
        handler=handler,
    )
