"""Quello che resta: conversazioni salvate, tracce dei turni, diff del turno,
riepilogo, memoria.

I gestori sono metodi della classe `RotteStoria`, che `Rotte` compone
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
class RotteStoria:
    @rotta("GET", "/api/tracce")
    def _r_get_tracce(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        # Le tracce recenti: la diagnosi dopo il fatto. "Perché quel
        # task ha sbagliato" senza doverlo ripetere. I filtri sono
        # nella query e vengono applicati alla query SQL, non dopo:
        # un turno fallito di ieri non deve sparire dietro cinquanta
        # turni riusciti di oggi.
        import urllib.parse as _up

        from .traccia import ultime

        q = _up.parse_qs(_up.urlparse(self.path).query)
        esito = ((q.get("esito") or [""])[0] or "").strip() or None
        solo_errori = ((q.get("errori") or [""])[0] or "").strip() \
            in ("1", "true", "si", "sì")
        try:
            limite = int((q.get("limite") or ["50"])[0])
        except (TypeError, ValueError):
            limite = 50
        self._json({"tracce": ultime(limite=limite, esito=esito,
                                      solo_errori=solo_errori)})

    @rotta("GET", "/api/riepilogo")
    def _r_get_riepilogo(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        # L'ultimo riepilogo di turno: esito, file, token, costo.
        from . import riepilogo

        self._json({"riepilogo": riepilogo.ultimo()})

    @rotta("GET", "/api/diff")
    def _r_get_diff(self, path: str, body: dict[str, Any],
                    s: Any) -> None:
        # Le modifiche del turno in corso, con le righe cambiate.
        # Il confine lo segna l'Agent a inizio turno; qui si legge e
        # si calcola il diff al momento della richiesta, cosi' la
        # vista mostra lo stato vero del file, non quello di meta'
        # turno.
        from . import checkpoint

        self._json({"modifiche": checkpoint.modifiche_turno()})

    @rotta("GET", "/api/tracce/{id}")
    def _r_get_tracce_id(self, path: str, body: dict[str, Any],
                         s: Any) -> None:
        try:
            tid = int(path.rsplit("/", 1)[-1])
        except ValueError:
            self._json({"error": "id non valido"}, 400)
            return
        from .traccia import apri
        t = apri(tid)
        if t is None:
            self._json({"error": "traccia non trovata"}, 404)
            return
        self._json(t)

    @rotta("GET", "/api/storico")
    def _r_get_storico(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        # In GET perche' e' una lettura: il pannello lo carica da
        # solo quando si apre. Registrata solo fra i POST rispondeva
        # 404 a una richiesta che il browser faceva in GET -- e il
        # sintomo era "il pannello resta vuoto", che non dice niente
        # del motivo.
        try:
            elenco = (self.app._storico.elenco(limite=200)
                      if self.app._storico else [])
            self._json({
                "sessioni": elenco,
                "attiva": getattr(self.app.session, "_sessione_id", None),
            })
        except Exception as e:
            self._json({"error": str(e)}, 500)

    @rotta("GET", "/api/memoria")
    def _r_get_memoria(self, path: str, body: dict[str, Any],
                       s: Any) -> None:
        from .memoria import stato as stato_memoria
        fuori = stato_memoria()
        # Le statistiche dell'indice: quanti fatti sono morti. Sono il
        # motivo per cui l'indice esiste — non la velocità, che è
        # rumore, ma sapere cosa non serve più.
        try:
            from .memoria_indice import indice_memoria
            st = indice_memoria().statistiche()
            fuori["indice"] = {
                "totale": st["totale"],
                "mai_usati": st["mai_usati"],
                "in_scadenza": [x["testo"] for x in st["in_scadenza"]],
                "piu_usati": st["piu_usati"],
                "byte_file": st["byte_file"],
            }
        except Exception as e:
            fuori["indice"] = {"errore": str(e)}
        self._json(fuori)

    @rotta("POST", "/api/storico")
    def _r_post_storico(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # Elenco delle conversazioni. Solo GET: la lista si scrive
        # da sola a fine turno, non c'e' niente da mandare.
        try:
            elenco = self.app._storico.elenco(limite=200) if self.app._storico else []
            self._json({
                "sessioni": elenco,
                "attiva": getattr(self.app.session, "_sessione_id", None),
            })
        except Exception as e:
            self._json({"error": str(e)}, 500)

    @rotta("POST", "/api/storico/cerca")
    def _r_post_storico_cerca(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        # Ricerca full-text nelle conversazioni passate. `sessioni` è
        # sempre presente, vuoto se non c'è query: la UI distingue
        # "sto cercando" da "sto guardando la lista".
        storico_db = self.app._storico
        q = (body.get("query") or "").strip()
        fuori: dict[str, Any] = {"query": q, "risultati": [], "sessioni": []}
        if q and storico_db is not None:
            try:
                fuori["risultati"] = storico_db.cerca(
                    q, limite=int(body.get("limite") or 30))
            except Exception as e:
                self._json({"error": str(e)}, 500)
                return
        else:
            try:
                fuori["sessioni"] = (storico_db.elenco(limite=200)
                                     if storico_db else [])
                fuori["attiva"] = getattr(self.app.session,
                                          "_sessione_id", None)
            except Exception as e:
                self._json({"error": str(e)}, 500)
                return
        self._json(fuori)

    @rotta("POST", "/api/storico/apri")
    def _r_post_storico_apri(self, path: str, body: dict[str, Any],
                             s: Any) -> None:
        # Apre una conversazione: sostituisce lo stato, non lo
        # accoda. 409 se il turno precedente sta ancora girando.
        try:
            sid = int(body.get("id"))
        except (TypeError, ValueError):
            self._json({"error": "id mancante o non valido"}, 400)
            return
        # Una conversazione appartiene all'identita' che l'ha scritta.
        # Caricarla in un'altra sessione la farebbe continuare dal bot
        # sbagliato, e il salvataggio successivo la lascerebbe col nome
        # del primo bot ma col contenuto del secondo: un misto che non
        # si puo' piu' separare.
        try:
            riga = self.app._storico.sessione(sid) if self.app._storico else None
            proprietario = str((riga or {}).get("bot") or "")
            if riga is not None \
                    and proprietario != (self.app.session.bot or ""):
                nome = proprietario or "l'agente principale"
                self._json({"error": f"questa conversazione appartiene a "
                                    f"{nome}: attivalo prima di aprirla"}, 409)
                return
            ok = self.app.session.carica_sessione(sid)
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        if not ok:
            self._json({"error": "sessione non trovata"}, 404)
            return
        self._json({"ok": True, "snapshot": self.app.session.snapshot()})

    @rotta("POST", "/api/storico/elimina")
    def _r_post_storico_elimina(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        try:
            sid = int(body.get("id"))
        except (TypeError, ValueError):
            self._json({"error": "id mancante o non valido"}, 400)
            return
        attiva = getattr(self.app.session, "_sessione_id", None)
        if self.app._storico is not None:
            self.app._storico.elimina(sid)
        # Se era quella aperta, si riparte da una vuota: lasciarla
        # significherebbe scrivere su una riga che non esiste piu'.
        #
        # ATTENZIONE — qui cascava in un loop: crearne SUBITO una nuova
        # faceva ricomparire una riga in lista, la si eliminava, e lui
        # ne rifaceva un'altra, all'infinito. La sessione attiva NON
        # deve esistere per forza: se elimini l'ultima conversazione,
        # la lista resta vuota. La riga su cui scrivere la si creerà
        # al PROSSIMO messaggio, non adesso — `_salva_su_disco` lo fa
        # già quando serve davvero.
        if sid == attiva:
            self.app.session.reset()
            self.app.session._sessione_id = None
        self._json({"ok": True, "snapshot": self.app.session.snapshot()})

    @rotta("POST", "/api/storico/nuova")
    def _r_post_storico_nuova(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        # Nuova conversazione, senza toccare le vecchie.
        try:
            self.app.session.reset()
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json({"ok": True, "snapshot": self.app.session.snapshot()})

    @rotta("POST", "/api/memoria/cerca")
    def _r_post_memoria_cerca(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        # Ricerca FTS5 dalla UI. `conta_usi=False`: cercare per
        # controllare non vuol dire che il facto serva, e contarlo
        # inquinerebbe la statistica che dice cosa è morto.
        from .tools.memoria import memoria as mem
        from .memoria import stato as stato_memoria
        q = (body.get("query") or "").strip()
        progetto = (body.get("progetto") or "").strip()
        m = mem()
        fuori: dict[str, Any] = {"query": q, "progetto": progetto}
        try:
            righe = m.cerca(q, limite=int(body.get("limite") or 20),
                            conta_usi=False, progetto=progetto)
            fuori["risultati"] = [
                {"testo": r["testo"], "usi": r["usi"],
                 "importante": bool(r["importante"]),
                 "progetto": r.get("progetto", "")} for r in righe]
            st = m.statistiche()
            fuori["indice"] = {"totale": st["totale"],
                               "mai_usati": st["mai_usati"],
                               "byte_file": st["byte_file"]}
        except Exception:
            # il backend a file non ha `cerca`: si torna al filtro per
            # sottostringa, che è quello che faceva prima dell'indice
            if progetto:
                tutti = m.fatti_per_progetto(progetto)
            else:
                tutti = m.fatti() + m.importanti()
            ql = q.lower()
            fuori["risultati"] = [
                {"testo": f, "usi": 0, "importante": f in m.importanti(),
                 "progetto": progetto} for f in tutti if ql in f.lower()][:20]
            fuori["nota"] = "ricerca per sottostringa (indice non disponibile)"
        fuori.update(stato_memoria())
        self._json(fuori)

    @rotta("POST", "/api/memoria/aggiungi")
    def _r_post_memoria_aggiungi(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        # Aggiunge un fatto a mano, dalla barra laterale.
        #
        # Il progetto arriva dal corpo; se manca, si usa quello
        # attivo. Cosi un fatto scritto a mano mentre si lavora sul
        # sito ristorante finisce col suo etichetta senza che
        # l'utente debba ripeterlo ogni volta.
        from .memoria import memoria
        fatto = (body.get("fatto") or "").strip()
        if not fatto:
            self._json({"error": "fatto vuoto"}, 400)
            return
        progetto = (body.get("progetto")
                    or getattr(self.app.session, "progetto", "") or "").strip()
        nuovo = memoria().aggiungi(fatto, origine="manuale",
                                   progetto=progetto)
        from .memoria import stato as stato_memoria
        self._json({"ok": True, "nuovo": nuovo, **stato_memoria()})

    @rotta("POST", "/api/memoria")
    def _r_post_memoria(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        from .memoria import stato as stato_memoria
        self._json(stato_memoria())

    @rotta("POST", "/api/memoria/modifica")
    def _r_post_memoria_modifica(self, path: str, body: dict[str, Any],
                                 s: Any) -> None:
        from .memoria import memoria
        vecchio = (body.get("vecchio") or "").strip()
        nuovo_testo = (body.get("nuovo") or "").strip()
        if not vecchio or not nuovo_testo:
            self._json({"error": "vecchio o nuovo vuoto"}, 400)
            return
        fatto = memoria().modifica(vecchio, nuovo_testo)
        from .memoria import stato as stato_memoria
        self._json({"ok": True, "modificato": fatto, **stato_memoria()})

    @rotta("POST", "/api/memoria/elimina")
    def _r_post_memoria_elimina(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from .memoria import memoria
        fatto = (body.get("fatto") or "").strip()
        if not fatto:
            self._json({"error": "fatto vuoto"}, 400)
            return
        tolto = memoria().elimina(fatto)
        from .memoria import stato as stato_memoria
        self._json({"ok": True, "tolto": tolto, **stato_memoria()})

    @rotta("POST", "/api/memoria/ottimizza")
    def _r_post_memoria_ottimizza(self, path: str, body: dict[str, Any],
                                  s: Any) -> None:
        dry_run = body.get("dry_run", True)
        giorni = int(body.get("giorni_grazia") or 30)
        progetto = (body.get("progetto")
                    or getattr(self.app.session, "progetto", "") or "").strip()
        unisci = bool(body.get("unisci", False))
        from .tools.memoria import memoria as mem
        m = mem()
        ott = getattr(m, "ottimizza_memoria", None)
        if not callable(ott):
            self._json({"error": "indice non disponibile"}, 400)
            return
        provider = None
        if unisci:
            try:
                provider = getattr(self.app.session.agent, "provider", None)
            except Exception:
                provider = None
        res = ott(provider=provider, dry_run=bool(dry_run),
                  giorni_grazia=giorni, progetto=progetto,
                  unisci=unisci and provider is not None)
        from .memoria import stato as stato_memoria
        res.update(stato_memoria())
        self._json(res)
