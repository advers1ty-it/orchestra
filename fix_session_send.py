with open('orchestra/session.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    def send(self, user_input: str, allegati: list | None = None) -> bool:
        """Invia un messaggio all'agente. Non blocca.

        Restituisce False se la sessione e' gia' occupata: rifiutiamo il
        secondo turno invece di accodarlo, perche' accodare richieste che
        l'utente non vede e' peggio che dirgli di aspettare.

        `allegati` sono Attachment gia' pronti (foto, pagine di PDF come
        data URL). Vanno sull'UTIMO messaggio utente, non su un nuovo
        messaggio: l'utente ha scritto "estrai i prezzi" e l'immagine
        insieme, e due messaggi separati fanno leggere all'agente
        l'istruzione senza l'allegato, o il contrario.

        Un PDF con testo non viaggia come immagine: finisce nel testo
        del messaggio. Costa zero token ed e' esatto, mentre renderlo
        in immagini costerebbe 1100 token a pagina per un risultato
        peggiore.
        """
        # Instradamento automatico. Prima di occupare la sessione e
        # prima di accodare il messaggio: se lo si facesse dopo, il
        # turno partirebbe col modello sbagliato e la correzione
        # arriverebbe al turno successivo — cioe' mai, perche' nel
        # frattempo hai gia' letto la risposta.
        #
        # Non e' il posto giusto per farlo? Lo e': qui la richiesta
        # dell'utente esiste per intero, e prima non si sa cosa
        # rispondere. Dopo, si sa e si e' tardi.
        if self._routing_attivo and self._scegli_primo is not None \
                and not self._busy:
            scelto = None
            try:
                scelto = self._scegli_primo(user_input)
            except Exception:  # noqa: BLE001
                # Una scelta che fallisce non puo' far fallire il
                # turno: si continua col modello che si ha. Ma si dice
                # — un instradamento che non parte e non lo dice e'
                # un instradamento spento.
                self.bridge.emit("routing", {
                    "modello": "", "categoria": "", "punteggio": None,
                    "prove": None, "scartati": [], "spiegazione": "",
                    "motivo": "instradamento non disponibile",
                })
                scelto = None'''

new = '''    def send(self, user_input: str, allegati: list | None = None, scope: str | None = None) -> bool:
        """Invia un messaggio all'agente. Non blocca.

        Restituisce False se la sessione e' gia' occupata: rifiutiamo il
        secondo turno invece di accodarlo, perche' accodare richieste che
        l'utente non vede e' peggio che dirgli di aspettare.

        `allegati` sono Attachment gia' pronti (foto, pagine di PDF come
        data URL). Vanno sull'UTIMO messaggio utente, non su un nuovo
        messaggio: l'utente ha scritto "estrai i prezzi" e l'immagine
        insieme, e due messaggi separati fanno leggere all'agente
        l'istruzione senza l'allegato, o il contrario.

        Un PDF con testo non viaggia come immagine: finisce nel testo
        del messaggio. Costa zero token ed e' esatto, mentre renderlo
        in immagini costerebbe 1100 token a pagina per un risultato
        peggiore.

        `scope` è la categoria di lavoro scelta nell'header (code, extraction,
        reasoning, ecc.). Se fornito, guida l'instradamento automatico
        invece di lasciarlo indovinare dalle parole chiave.
        """
        # Instradamento automatico. Prima di occupare la sessione e
        # prima di accodare il messaggio: se lo si facesse dopo, il
        # turno partirebbe col modello sbagliato e la correzione
        # arriverebbe al turno successivo — cioe' mai, perche' nel
        # frattempo hai gia' letto la risposta.
        #
        # Non e' il posto giusto per farlo? Lo e': qui la richiesta
        # dell'utente esiste per intero, e prima non si sa cosa
        # rispondere. Dopo, si sa e si e' tardi.
        if self._routing_attivo and self._scegli_primo is not None \
                and not self._busy:
            scelto = None
            try:
                scelto = self._scegli_primo(user_input, scope=scope)
            except Exception:  # noqa: BLE001
                # Una scelta che fallisce non puo' far fallire il
                # turno: si continua col modello che si ha. Ma si dice
                # — un instradamento che non parte e non lo dice e'
                # un instradamento spento.
                self.bridge.emit("routing", {
                    "modello": "", "categoria": "", "punteggio": None,
                    "prove": None, "scartati": [], "spiegazione": "",
                    "motivo": "instradamento non disponibile",
                })
                scelto = None'''

if old in content:
    content = content.replace(old, new)
    with open('orchestra/session.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed send method')
else:
    print('Not found - send method')