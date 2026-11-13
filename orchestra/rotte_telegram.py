"""Le rotte del ponte Telegram.

Il modello e' quello delle altre rotte: `@rotta` accanto al codice e via.
Qui si fa da ponte fra il pannello Bot e `orchestra/telegram.py`, che
della rete non sa niente e dei bot non sa niente: prende un token, una
chat e una funzione che risponde.
"""

from __future__ import annotations

from typing import Any

from .rotte import rotta


class RotteTelegram:
    @rotta("GET", "/api/telegram")
    def _r_get_telegram(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # Lo stato di tutti i bot in una lettura: il pannello ne mostra
        # uno alla volta, ma il menu dei bot si disegna prima di sapere
        # quale verra' scelto.
        from . import bots as bots_mod
        from . import telegram as tg

        attivi = self.app.telegram_attivi()
        righe = []
        # L'agente principale e' il primo della lista: e' quello che esiste
        # anche senza aver mai creato un bot, ed e' il caso di chi vuole
        # scrivere all'Orchestra di sempre dal telefono.
        voci = [dict(bots_mod.agente_base(), principale=True)]
        voci += [dict(b, principale=False) for b in bots_mod.tutti()]
        for b in voci:
            voce = tg.stato(b["id"])
            voce["nome"] = b["nome"]
            voce["attivo"] = int(b["id"]) in attivi
            voce["in_corso"] = bool(tg.codice_in_corso(b["id"]))
            voce["principale"] = bool(b.get("principale"))
            righe.append(voce)
        self._json({"ok": True, "bots": righe})

    @rotta("POST", "/api/telegram/token")
    def _r_post_telegram_token(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        """Salva il token, dopo averlo fatto verificare a Telegram.

        Un token sbagliato salvato e basta produce un ponte che non
        parte e nessuna traccia del perche': la verifica si fa qui, una
        volta, mentre l'utente sta guardando lo schermo.
        """
        from . import bots as bots_mod
        from . import telegram as tg

        bot = bots_mod.per_id_agente(body.get("id"))
        if not bot:
            self._json({"error": "bot sconosciuto"}, 404)
            return
        token = (body.get("token") or "").strip()
        if not token:
            tg.salva_token(bot["id"], "")
            self.app.telegram_sync()
            self._json({"ok": True, "stato": tg.stato(bot["id"])})
            return
        if not tg.TOKEN_RE.match(token):
            self._json({"error": "questo non sembra un token di Telegram: "
                                 "sono due numeri separati da ':' e una "
                                 "parte lunga. Si copia da @BotFather."}, 400)
            return
        try:
            io = tg.Api(token).get_me(secondi=10)
        except tg.ErroreTelegram as e:
            self._json({"error": f"Telegram ha rifiutato il token: {e}"}, 400)
            return
        try:
            tg.salva_token(bot["id"], token)
            tg.imposta_username(bot["id"], io.get("username") or "")
        except (OSError, ValueError) as e:
            self._json({"error": f"token non salvato: {e}"}, 400)
            return
        self.app.telegram_sync()
        self._json({"ok": True, "stato": tg.stato(bot["id"]),
                    "telegram": io})

    @rotta("POST", "/api/telegram/collega")
    def _r_post_telegram_collega(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        """Genera il codice e il QR per collegare una chat a questo bot."""
        from . import bots as bots_mod
        from . import qr as qr_mod
        from . import telegram as tg

        bot = bots_mod.per_id_agente(body.get("id"))
        if not bot:
            self._json({"error": "bot sconosciuto"}, 404)
            return
        voce = tg.stato(bot["id"])
        if not voce["token"]:
            self._json({"error": "prima salva il token del bot Telegram"}, 400)
            return
        if not voce["username"]:
            # Capita con un token salvato a mano prima che esistesse
            # questo controllo, o se Telegram cambia il nome utente.
            self._json({"error": "Telegram non ha dato un nome utente per "
                                 "questo token: risalva il token."}, 400)
            return
        nuovo = tg.nuovo_codice(bot["id"])
        link = tg.link(voce["username"], nuovo["codice"])
        try:
            disegno = qr_mod.svg(link, modulo=5, bordo=3)
        except qr_mod.ErroreQR as e:
            self._json({"error": str(e)}, 500)
            return
        self._json({
            "ok": True,
            "codice": nuovo["codice"],
            "scade": nuovo["scade"],
            "link": link,
            "username": voce["username"],
            "svg": disegno,
        })

    @rotta("POST", "/api/telegram/scollega")
    def _r_post_telegram_scollega(self, path: str, body: dict[str, Any],
                                  s: Any) -> None:
        """Stacca UNA chat, o tutte se non se ne nomina una.

        Con `chat_id` si revoca una persona sola e le altre continuano a
        scrivere: e' il caso di un bot con piu' chat collegate. Senza,
        stacca tutto — che resta il "togli il telefono da questo bot".

        Una chat che non risulta collegata non e' un successo: rispondere
        `ok` vorrebbe dire aver rimosso qualcosa che non c'era, e chi
        clicca su un elenco vecchio crederebbe di aver revocato la
        persona giusta.
        """
        from . import bots as bots_mod
        from . import telegram as tg

        bot = bots_mod.per_id_agente(body.get("id"))
        if not bot:
            self._json({"error": "bot sconosciuto"}, 404)
            return
        chat = str(body.get("chat_id") or "").strip()
        if chat and not tg.chat_collegata(bot["id"], chat):
            self._json({"error": "questa chat non e' collegata a questo "
                                 "bot: l'elenco e' cambiato, riaprilo"}, 404)
            return
        tg.dimentica_chat(bot["id"], chat or None)
        self._json({"ok": True, "scollegata": chat,
                    "stato": tg.stato(bot["id"])})
