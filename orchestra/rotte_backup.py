"""Backup e ripristino visti dall'interfaccia.

Le rotte espongono quello che fa `orchestra backup`/`restore`, con una
differenza: qui si sceglie il profilo da un elenco che porta il percorso
scritto accanto. Un hash non si sceglie; `D:\\orchestra` sì.

Il ripristino si rifiuta a turno in corso. Sostituire i database mentre
l'agente sta scrivendo non e' una corsa che si vince: e' un file aperto
da due connessioni, e il risultato non e' ne' i dati vecchi ne' quelli
nuovi.
"""

from __future__ import annotations

import os
from typing import Any

from .rotte import rotta


class RotteBackup:
    @rotta("GET", "/api/backup")
    def _r_get_backup(self, path: str, body: dict[str, Any], s: Any) -> None:
        # Una lettura sola per disegnare tutto il pannello: installazioni,
        # archivi gia' presenti, e la cartella dove finiscono i nuovi.
        # Due richieste per una schermata che si apre di rado sono due
        # occasioni di restare a meta'.
        from . import backup as bkp
        from . import dati as dati_mod

        try:
            self._json({
                "ok": True,
                "installazioni": dati_mod.installazioni(),
                "archivi": bkp.archivi(),
                "cartella": bkp.posizione_predefinita(),
            })
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    @rotta("POST", "/api/backup/crea")
    def _r_post_backup_crea(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        # `profilo` accetta il percorso dell'installazione, il percorso
        # della sua cartella dati, o l'id: sono le tre cose visibili
        # nell'elenco. Vuoto = l'installazione che sta girando.
        from . import backup as bkp

        con_chiavi = bool(body.get("con_chiavi", True))
        profilo = str(body.get("profilo") or "").strip()
        try:
            if body.get("tutte"):
                self._json({"ok": True,
                            "esiti": bkp.crea_tutte(con_chiavi=con_chiavi)})
                return
            esito = bkp.crea("", con_chiavi=con_chiavi,
                             installazione=profilo or None)
            self._json({"ok": True, "esiti": [{**esito, "esito": "ok"}]})
        except bkp.InstallazioneSconosciuta as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001 - il pannello deve poterlo dire
            self._json({"error": str(e)}, 500)

    @rotta("POST", "/api/backup/ripristina")
    def _r_post_backup_ripristina(self, path: str, body: dict[str, Any],
                                  s: Any) -> None:
        from . import backup as bkp

        archivio = str(body.get("archivio") or "").strip()
        profilo = str(body.get("profilo") or "").strip()
        if not archivio:
            self._json({"error": "manca l'archivio da ripristinare"}, 400)
            return
        if not bkp.archivio_ammesso(archivio):
            self._json({"error": "archivio non presente nell'elenco dei "
                                 "backup: scegline uno dalla cartella backup"},
                       400)
            return
        sessione = getattr(self.app, "session", None)
        if sessione is not None and getattr(sessione, "busy", False):
            self._json({"error": "c'e' un turno in corso: fermalo prima di "
                                 "ripristinare i dati"}, 409)
            return
        # L'installazione IN USO non si ripristina da qui. Il server tiene
        # aperte le connessioni sqlite (storico le tiene per tutta la
        # vita): sostituire i file sotto di lui lascia la app a scrivere
        # nel file vecchio, e su Windows puo' anche rifiutarsi a meta'
        # strada. Le altre installazioni non hanno nessuno che le tenga
        # aperte, e si possono ripristinare.
        try:
            bersaglio = bkp._dati(profilo or None)
        except bkp.InstallazioneSconosciuta as e:
            self._json({"error": str(e)}, 400)
            return
        if os.path.abspath(bersaglio) == os.path.abspath(bkp.cartella_dati()):
            self._json({"error":
                       "questa e' l'installazione in uso: ferma Orchestra e "
                       "ripristina da terminale con `python -m orchestra.cli "
                       f"restore \"{archivio}\"`. A server acceso i database "
                       "restano aperti, e il ripristino li sostituirebbe "
                       "sotto chi ci sta scrivendo."}, 409)
            return
        try:
            esito = bkp.ripristina(
                archivio,
                con_chiavi=bool(body.get("con_chiavi", False)),
                installazione=profilo or None,
            )
            self._json({"ok": True, **esito})
        except bkp.InstallazioneSconosciuta as e:
            self._json({"error": str(e)}, 400)
        except RuntimeError as e:
            # Archivio estraneo, rotto, di un formato futuro: sono tutti
            # "non si puo' fare", non "il server e' guasto".
            self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)
