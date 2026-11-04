"""Il lavoro sul disco e le identita' che lo fanno: progetto attivo, file,
bot, lavori, identita' dell'agente.

I gestori sono metodi della classe `RotteProgetti`, che `Rotte` compone
insieme alle altre. Le rotte si dichiarano con `@rotta` accanto al codice
che le serve; la tabella e il dispatch stanno in `rotte.py` e in
`webapp.Handler._instrada`.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from .rotte import rotta


# Le rotte: percorso e metodo nel decoratore, il corpo
# sotto. Il commento sopra ogni gestore dice perche' esiste.
class RotteProgetti:
    @rotta("GET", "/api/progetti")
    def _r_get_progetti(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # L'elenco dei progetti registrati, e quale e' attivo.
        # Va in GET e non in POST perche' e' una lettura, e la UI
        # lo chiede all'avvio per riempire la lista.
        self._json({"ok": True,
                    "progetti": self.app._elenco_progetti(),
                    "attivo": self.app._progetto_attivo()})

    @rotta("GET", "/api/identita")
    def _r_get_identita(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # Nome e persona dell'agente principale. Sta accanto a /api/bots
        # perche' il menu in testa ha bisogno di entrambi per dire chi
        # sta parlando quando non c'e' un bot attivo.
        self._json({"ok": True, **self.app.identita()})

    @rotta("GET", "/api/bots")
    def _r_get_bots(self, path: str, body: dict[str, Any],
                    s: Any) -> None:
        # I bot salvati, chi e' attivo, e i valori che servono al form
        # (provider validi, progetti registrati). Una lettura sola per
        # disegnare tutto il pannello: due richieste per una schermata
        # che si apre di rado sono due occasioni di restare a meta'.
        try:
            from .providers import KNOWN_PROVIDERS

            self._json({
                "ok": True,
                "bots": self.app.elenco_bot(),
                "attivo": self.app.bot_attivo(),
                # Il nome dell'agente principale serve al menu in
                # testa: senza, dopo averlo personalizzato il menu
                # continuerebbe a dire "agente principale".
                "principale": self.app.identita(),
                "providers": sorted(KNOWN_PROVIDERS),
                "progetti": [p.get("nome") for p in self.app._elenco_progetti()],
            })
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    @rotta("GET", "/api/lavori")
    def _r_get_lavori(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        # La coda durevole, in sola lettura. Il pannello Bot legge il
        # riassunto dentro /api/bots; questa rotta serve a chi vuole
        # vedere i singoli lavori (e ai test del motore).
        from . import lavori as lavori_mod
        import urllib.parse as _up

        # `urlparse` e non `split("?", 1)[1]`: la rotta deve
        # rispondere anche senza query, altrimenti un client che la
        # chiama “nuda” prende un IndexError invece dell'elenco.
        query = _up.parse_qs(_up.urlparse(self.path).query)
        tipo = (query.get("tipo") or [""])[0].strip() or None
        chiave = (query.get("chiave") or [""])[0].strip() or None
        try:
            limite = int((query.get("limite") or ["50"])[0])
        except (TypeError, ValueError):
            limite = 50
        self._json({"ok": True,
                    "lavori": lavori_mod.elenca(
                        tipo=tipo, chiave=chiave, limite=limite)})

    @rotta("POST", "/api/identita")
    def _r_post_identita(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        try:
            dati = self.app.salva_identita(
                body.get("nome") or "", body.get("persona") or "")
        except (OSError, ValueError) as e:
            self._json({"error": f"identita' non salvata: {e}"}, 400)
            return
        self._json({"ok": True, **dati})

    @rotta("POST", "/api/bots/crea")
    def _r_post_bots_crea(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        campi = {k: body.get(k) for k in
                 ("nome", "provider", "modello", "persona", "progetto",
                  "profilo", "parla_con", "policy") if k in body}
        try:
            b = self.app.crea_bot(**campi)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        self._json({"ok": True, "bot": b})

    @rotta("POST", "/api/bots/attiva")
    def _r_post_bots_attiva(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        try:
            risultato = self.app.attiva_bot(body.get("id"))
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        self._json(risultato)

    @rotta("POST", "/api/bots/aggiorna")
    def _r_post_bots_aggiorna(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        campi = {k: body.get(k) for k in
                 ("nome", "provider", "modello", "persona", "progetto",
                  "profilo", "parla_con", "policy") if k in body}
        try:
            b = self.app.aggiorna_bot(body.get("id"), **campi)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        if b is None:
            self._json({"error": "bot inesistente"}, 404)
            return
        self._json({"ok": True, "bot": b})

    @rotta("POST", "/api/bots/elimina")
    def _r_post_bots_elimina(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        try:
            fatto = self.app.elimina_bot(body.get("id"))
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        if not fatto:
            self._json({"error": "bot inesistente"}, 404)
            return
        self._json({"ok": True})

    @rotta("POST", "/api/bots/avvia")
    def _r_post_bots_avvia(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        # Un compito in background, senza cambiare l'identita' attiva.
        try:
            risultato = self.app.avvia_lavoro_bot(
                body.get("id"), body.get("testo") or "")
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        self._json(risultato)

    @rotta("POST", "/api/lavori/unisci")
    def _r_post_lavori_unisci(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        try:
            risultato = self.app.unisci_lavoro(body.get("id"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json(risultato)

    @rotta("POST", "/api/lavori/scarta")
    def _r_post_lavori_scarta(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        try:
            risultato = self.app.scarta_checkout_lavoro(body.get("id"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json(risultato)

    @rotta("POST", "/api/lavori/riprova")
    def _r_post_lavori_riprova(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        try:
            lavoro = self.app.riprova_lavoro(body.get("id"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json({"ok": True, "lavoro": lavoro})

    @rotta("POST", "/api/lavori/annulla")
    def _r_post_lavori_annulla(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        try:
            lavoro = self.app.annulla_lavoro(body.get("id"))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json({"ok": True, "lavoro": lavoro})

    @rotta("POST", "/api/progetto")
    def _r_post_progetto(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        # POST {progetto: nome}: imposta il progetto attivo.
        # La risposta porta anche i progetti conosciuti (per il
        # datalist) e quanti fatti ne ha: e' quello che il campo
        # mostra sotto, e senza l'utente non sa se il progetto
        # esiste davvero o e' solo una parola.
        # Lettura vs scrittura: una POST senza la chiave "progetto"
        # (il frontend la manda vuota per rileggere lo stato) NON
        # deve cambiare il progetto attivo. Se la trattassimo come
        # "progetto = ''" azzereremmo il progetto a ogni refresh
        # della sidebar — ed e' esattamente il bug che faceva restare
        # la sidebar su "nessun progetto" anche dopo il riconoscimento
        # automatico.
        scrive = "progetto" in body and body.get("progetto") is not None
        if scrive:
            nome = str((body.get("progetto") or "")).strip()
            try:
                from . import progetti as _pr
                if nome and not _pr.percorso_di(nome):
                    return self._json({"error":
                                       f"progetto sconosciuto: {nome}"}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 400)
        else:
            nome = self.app._progetto_attivo()
        if self.app.session is None:
            return self._json({"error": "nessuna sessione"}, 409)
        if scrive:
            try:
                self.app.session.imposta_progetto(nome)
                if nome:
                    from . import progetti as _pr
                    _pr.tocca(nome)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 400)
        n_fatti = 0
        try:
            from .memoria import memoria
            n_fatti = len(memoria().fatti_per_progetto(nome))
        except Exception:  # noqa: BLE001
            n_fatti = 0
        return self._json({
            "ok": True,
            "attivo": nome,
            "n_fatti": n_fatti,
            # QUI i progetti sono NOMI, non dizionari: e' la lista
            # per il datalist del campo, che vuole stringhe. Il
            # GET /api/progetti invece restituisce i dizionari
            # interi, perche' li disegna. Due forme per lo stesso
            # campo, ma su due endpoint diversi — e i due consumatori
            # sono diversi.
            "progetti": [p.get("nome") for p in self.app._elenco_progetti()],
        })

    @rotta("POST", "/api/progetti/registra")
    def _r_post_progetti_registra(self, path: str, body: dict[str, Any],
                                  s: Any) -> None:
        self._json(self.app._api_progetti_registra(body))

    @rotta("POST", "/api/progetti/elimina")
    def _r_post_progetti_elimina(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        self._json(self.app._api_progetti_elimina(body))

    @rotta("POST", "/api/progetti/file")
    def _r_post_progetti_file(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        self._json(self.app._api_progetti_file(body))
