"""La tabella delle rotte: il motore da solo, e l'inventario del server.

La seconda parte e' quella che conta davvero: l'elenco congelato delle 130
rotte che il server aveva prima di passare alla tabella. Senza, un ramo
perso durante uno spostamento non lo vedrebbe nessuno fino a quando un
pulsante della UI smette di funzionare — ed e' esattamente il difetto che
la catena di elif aveva.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.rotte import ErroreRotte, Tabella  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))


def solleva(fn, tipo=ErroreRotte):
    try:
        fn()
    except tipo:
        return True
    return False


# L'inventario: tutto quello che il server sapeva servire prima della
# tabella. Una rotta che sparisce da qui e' una rotta che sparisce dalla
# UI, e va tolta da questo elenco di proposito.
ATTESE = frozenset({
    "POST /api/allega",
    "POST /api/annulla",
    "POST /api/autostart/disable",
    "POST /api/autostart/enable",
    "GET /api/autostart/status",
    "POST /api/bench",
    "GET /api/backup",
    "POST /api/backup/crea",
    "POST /api/backup/ripristina",
    "GET /api/bench/status",
    "GET /api/bots",
    "POST /api/bots/aggiorna",
    "POST /api/bots/attiva",
    "POST /api/bots/avvia",
    "POST /api/bots/crea",
    "POST /api/bots/elimina",
    "POST /api/budget",
    "POST /api/budget/reset",
    "POST /api/cancel",
    "GET /api/capabilities",
    "GET /api/capacita",
    "GET /api/categorie",
    "GET /api/chiavi",
    "POST /api/chiavi",
    "POST /api/council/consiglia",
    "GET /api/council/pdf",
    "GET /api/council/roster",
    "POST /api/council/start",
    "GET /api/council/status",
    "GET /api/council/tavolo",
    "POST /api/cron/create",
    "POST /api/cron/delete",
    "GET /api/cron/jobs",
    "POST /api/cron/run",
    "POST /api/cron/scheduler/start",
    "GET /api/cron/scheduler/status",
    "POST /api/cron/scheduler/stop",
    "POST /api/cron/update",
    "POST /api/diagnosi/run",
    "POST /api/diagnosi/stato",
    "GET /api/diff",
    "POST /api/dipendenze/installa",
    "GET /api/dipendenze/stato",
    "POST /api/dipendenze/stato",
    "GET /api/goal/ready",
    "POST /api/goal/run-next",
    "POST /api/goal/start",
    "GET /api/goal/status",
    "POST /api/goal/stop",
    "GET /api/identita",
    "POST /api/identita",
    "POST /api/iterazioni",
    "GET /api/lavori",
    "POST /api/lavori/annulla",
    "POST /api/lavori/riprova",
    "POST /api/lavori/scarta",
    "POST /api/lavori/unisci",
    "GET /api/locali",
    "POST /api/mcp/add",
    "POST /api/mcp/connect",
    "POST /api/mcp/connect_all",
    "POST /api/mcp/delete",
    "POST /api/mcp/disconnect",
    "POST /api/mcp/presets",
    "POST /api/mcp/prompts",
    "POST /api/mcp/resources",
    "POST /api/mcp/servers",
    "POST /api/mcp/status",
    "POST /api/mcp/tools",
    "GET /api/memoria",
    "POST /api/memoria",
    "POST /api/memoria/aggiungi",
    "POST /api/memoria/cerca",
    "POST /api/memoria/elimina",
    "POST /api/memoria/modifica",
    "POST /api/memoria/ottimizza",
    "POST /api/model",
    "GET /api/modelli",
    "GET /api/models",
    "GET /api/nous/auth/disconnect",
    "POST /api/nous/auth/start",
    "GET /api/nous/auth/status",
    "POST /api/permessi",
    "POST /api/permesso",
    "POST /api/permesso/prova",
    "POST /api/piano",
    "GET /api/prior",
    "GET /api/progetti",
    "POST /api/progetti/elimina",
    "POST /api/progetti/file",
    "POST /api/progetti/registra",
    "POST /api/progetto",
    "POST /api/prova",
    "POST /api/provider",
    "POST /api/reasoning",
    "GET /api/remote/info",
    "POST /api/remote/info",
    "POST /api/remote/start",
    "GET /api/remote/status",
    "POST /api/remote/status",
    "POST /api/remote/stop",
    "POST /api/reset",
    "GET /api/riepilogo",
    "POST /api/risposta",
    "GET /api/routing",
    "POST /api/routing",
    "GET /api/fallback",
    "POST /api/fallback",
    "POST /api/scheduler/start",
    "GET /api/scheduler/status",
    "POST /api/scheduler/stop",
    "POST /api/send",
    "GET /api/skill",
    "POST /api/skill",
    "GET /api/skill/file",
    "POST /api/skill/file",
    "GET /api/state",
    "POST /api/steer",
    "GET /api/storico",
    "POST /api/storico",
    "POST /api/storico/apri",
    "POST /api/storico/cerca",
    "POST /api/storico/elimina",
    "POST /api/storico/nuova",
    "GET /api/stream",
    "POST /api/stt/install",
    "GET /api/stt/status",
    "GET /api/suggerimenti",
    "POST /api/system",
    "GET /api/tools/profile",
    "GET /api/telegram",
    "POST /api/telegram/collega",
    "POST /api/telegram/scollega",
    "POST /api/telegram/token",
    "POST /api/tempo-turno",
    "POST /api/tools/profile",
    "GET /api/tracce",
    "GET /api/tracce/{id}",
    "POST /api/transcribe",
})


def main() -> int:
    print("[1] Ricerca esatta")
    t = Tabella()

    def gestore_a():
        pass

    def gestore_b():
        pass

    t.registra("GET", "/api/state", gestore_a)
    t.registra("POST", "/api/state", gestore_b)
    trovata = t.cerca("GET", "/api/state")
    check("percorso esatto trovato", trovata is not None)
    check("gestore giusto", trovata is not None and trovata[0].gestore is gestore_a)
    check("nessun parametro", trovata is not None and trovata[1] == {})
    check("percorso ignoto", t.cerca("GET", "/api/nulla") is None)
    check("metodo in minuscolo accettato", t.cerca("get", "/api/state") is not None)

    print("\n[2] Metodo sbagliato: i metodi ammessi")
    check("metodi di /api/state", t.metodi("/api/state") == {"GET", "POST"})
    check("metodi di ignoto", t.metodi("/api/nulla") == set())
    check("GET su rotta solo POST: cerca None", t.cerca("GET", "/api/nulla") is None)
    t.registra("POST", "/api/solo-post", gestore_a)
    check("405 ha i metodi ammessi", t.metodi("/api/solo-post") == {"POST"})

    print("\n[3] Parametri")
    t.registra("GET", "/api/tracce/{id}", gestore_b)
    trovata = t.cerca("GET", "/api/tracce/32")
    check("modello trovato", trovata is not None)
    check("parametro estratto", trovata is not None and trovata[1] == {"id": "32"})
    check("segmento vuoto non combacia", t.cerca("GET", "/api/tracce/") is None)
    check("troppi segmenti non combaciano",
          t.cerca("GET", "/api/tracce/32/altro") is None)
    check("il percorso del modello non e' un valore di id",
          t.cerca("GET", "/api/tracce/{id}") is not None)

    print("\n[4] L'esatto vince sul modello, anche se registrato dopo")
    t2 = Tabella()
    t2.registra("GET", "/api/tracce/{id}", gestore_a)
    t2.registra("GET", "/api/tracce/oggi", gestore_b)
    scelta = t2.cerca("GET", "/api/tracce/oggi")
    check("vince l'esatto", scelta is not None and scelta[0].gestore is gestore_b)
    scelta = t2.cerca("GET", "/api/tracce/12")
    check("il modello resta raggiungibile", scelta is not None and scelta[0].gestore is gestore_a)

    print("\n[5] Doppioni e configurazioni sbagliate")
    t3 = Tabella()
    t3.registra("GET", "/api/x", gestore_a)
    check("doppio esatto rifiutato",
          solleva(lambda: t3.registra("GET", "/api/x", gestore_b)))
    t3.registra("GET", "/api/x/{a}", gestore_a)
    check("doppio modello rifiutato (nome diverso, stessa forma)",
          solleva(lambda: t3.registra("GET", "/api/x/{b}", gestore_b)))
    try:
        t3.registra("POST", "/api/x/{c}", gestore_a)
        stesso_percorso_altro_metodo = True
    except ErroreRotte:
        stesso_percorso_altro_metodo = False
    check("stessa forma su altro metodo ammessa", stesso_percorso_altro_metodo)
    check("metodo sconosciuto rifiutato",
          solleva(lambda: t3.registra("FETCH", "/api/y", gestore_a)))
    check("percorso senza barra rifiutato",
          solleva(lambda: t3.registra("GET", "api/y", gestore_a)))
    check("gestore non chiamabile rifiutato",
          solleva(lambda: t3.registra("GET", "/api/z", "non-una-funzione")))
    check("parametro ripetuto rifiutato",
          solleva(lambda: t3.registra("GET", "/api/w/{id}/{id}", gestore_a)))
    check("verifica() senza problemi su tabella sana", t3.verifica() == [])

    print("\n[6] Il decoratore registra e non cambia la funzione")
    t4 = Tabella()
    from orchestra import rotte as modulo

    vecchia = modulo.ROTTE
    modulo.ROTTE = t4
    try:
        @modulo.rotta("GET", "/api/decorata")
        def gestore(x):
            return x * 2

        check("funzione invariata", gestore(3) == 6)
        check("rotta registrata", t4.cerca("GET", "/api/decorata") is not None)
        check("nome del gestore intatto", t4.tutte()[0].gestore.__name__ == "gestore")
    finally:
        modulo.ROTTE = vecchia

    print("\n[7] Il server vero: inventario e igiene")
    from orchestra import webapp
    tabella = webapp.ROTTE
    presenti = {f"{r.metodo} {r.percorso}" for r in tabella.tutte()}
    # Il conteggio non si controlla a parte: se l'insieme e' uguale ad
    # ATTESE, la lunghezza e' gia' quella. Un "137 rotte" da aggiornare a
    # mano a ogni rotta nuova era solo un secondo posto da sbagliare.
    check("nessuna rotta persa", not (ATTESE - presenti),
          str(sorted(ATTESE - presenti)))
    check("nessuna rotta in piu' non dichiarata", not (presenti - ATTESE),
          str(sorted(presenti - ATTESE)))
    check("verifica() pulita", tabella.verifica() == [], str(tabella.verifica()))
    check("tutte le rotte sono /api/",
          all(r.percorso.startswith("/api/") for r in tabella.tutte()))
    check("ogni gestore e' un metodo del Handler",
          all(getattr(webapp.Handler, r.gestore.__name__, None) is r.gestore
              for r in tabella.tutte()))
    check("login e logout restano fuori dalla tabella",
          "POST /api/login" not in presenti and "POST /api/logout" not in presenti)

    print("\n[8] Il pannello MCP riceve il catalogo")

    class _FintoHandler:
        def __init__(self):
            self.out = None
            self.code = None

        def _json(self, obj, code=200):
            self.out, self.code = obj, code

    finto = _FintoHandler()
    webapp.Handler._r_post_mcp_presets(
        finto, "/api/mcp/presets", {}, None)
    ids = {p.get("id") for p in (finto.out or {}).get("presets", [])}
    check("la rotta restituisce i preset", finto.code == 200 and bool(ids),
          str(finto.out)[:200])
    check("il catalogo include i programmi locali",
          {"unreal", "godot", "blender"}.issubset(ids), str(sorted(ids)))

    # La rotta e' la seconda barriera: anche chi chiama l'API direttamente
    # non deve poter aggiungere un preset potente senza la conferma che la
    # UI raccoglie con il checkbox.
    finto = _FintoHandler()
    webapp.Handler._r_post_mcp_add(
        finto, "/api/mcp/add",
        {"preset": "git", "valori": {"cartella": "D:/progetti/app"}}, None)
    check("un preset potente senza conferma viene rifiutato",
          finto.code == 409
          and (finto.out or {}).get("richiede_conferma") is True,
          str(finto.out))
    check("il rifiuto spiega perche' serve la conferma",
          "conferma" in str((finto.out or {}).get("error", "")),
          str(finto.out))

    # Anche un server gia' configurato (magari da una versione precedente,
    # senza un campo "richiede_conferma" salvato) non deve partire con la
    # sola chiamata /connect: il flag si ricava dal preset nel catalogo.
    from orchestra import mcp as mcp_mod
    vecchio_find = mcp_mod._find_config
    vecchio_connect = mcp_mod.connect
    esistente = {
        "id": "git-esistente", "name": "Git esistente", "preset": "git",
        "transport": "stdio", "command": "comando-che-non-deve-partire",
    }
    chiamate = []
    mcp_mod._find_config = lambda sid: esistente if sid == "git-esistente" else None
    mcp_mod.connect = lambda sid, timeout=20.0: (chiamate.append(sid)
                                                  or {"ok": True})
    try:
        finto = _FintoHandler()
        webapp.Handler._r_post_mcp_connect(
            finto, "/api/mcp/connect", {"id": "git-esistente"}, None)
        check("un server potente gia' aggiunto non parte senza conferma",
              finto.code == 409 and not chiamate, str(finto.out))
        finto = _FintoHandler()
        webapp.Handler._r_post_mcp_connect(
            finto, "/api/mcp/connect",
            {"id": "git-esistente", "conferma": True}, None)
        check("con la conferma esplicita la connessione parte",
              finto.code == 200 and chiamate == ["git-esistente"],
              str(finto.out))

        # Config molto vecchia: nessun campo preset, ma id/nome sono
        # quelli del preset potente.
        legacy = {
            "id": "git", "name": "Git", "transport": "stdio",
            "command": "comando-che-non-deve-partire",
        }
        mcp_mod._find_config = lambda sid: legacy if sid == "git" else None
        chiamate.clear()
        finto = _FintoHandler()
        webapp.Handler._r_post_mcp_connect(
            finto, "/api/mcp/connect", {"id": "git"}, None)
        check("una config vecchia senza preset non parte senza conferma",
              finto.code == 409 and not chiamate, str(finto.out))

        # Anche la rotta "Connetti tutti" deve saltare i preset protetti.
        vecchio_load = mcp_mod._load_config
        mcp_mod._load_config = lambda: [esistente]
        try:
            finto = _FintoHandler()
            webapp.Handler._r_post_mcp_connect_all(
                finto, "/api/mcp/connect_all", {}, None)
            risultati = (finto.out or {}).get("results", [])
            check("connect_all salta il preset potente",
                  finto.code == 200 and len(risultati) == 1
                  and risultati[0].get("skipped") is True, str(finto.out))
        finally:
            mcp_mod._load_config = vecchio_load

        # Un server normale passa senza conferma.
        normale = {
            "id": "normal-existing", "name": "normale",
            "transport": "stdio", "command": "comando-finto",
        }
        chiamate.clear()
        mcp_mod._find_config = lambda sid: normale if sid == "normal-existing" else None
        finto = _FintoHandler()
        webapp.Handler._r_post_mcp_connect(
            finto, "/api/mcp/connect", {"id": "normal-existing"}, None)
        check("un server normale si connette senza conferma",
              finto.code == 200 and chiamate == ["normal-existing"],
              str(finto.out))
    finally:
        mcp_mod._find_config = vecchio_find
        mcp_mod.connect = vecchio_connect

    print("\n" + "=" * 60)
    print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
    if FAIL:
        print("FALLITI:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
