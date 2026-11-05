"""Skill e server MCP: cose che l'agente sa fare in piu', e i server esterni
da cui le impara.

I gestori sono metodi della classe `RotteSkill`, che `Rotte` compone
insieme alle altre. Le rotte si dichiarano con `@rotta` accanto al codice
che le serve; la tabella e il dispatch stanno in `rotte.py` e in
`webapp.Handler._instrada`.
"""

from __future__ import annotations

import os
import shutil
import time
import urllib.parse
from typing import Any

from .rotte import rotta


CARTELLA_CESTINO = ".cestino"


def _skill_elenco(indice) -> dict[str, Any]:
    """Le skill, raggruppate per origine e per categoria.

    Il raggruppamento non e' decorativo: sono due domande diverse che
    ti fa. "Cosa posso scaricare" e "cosa ha imparato l'agente" non
    hanno la stessa affidabilita' — le seconde sono affermazioni
    dello stesso agente che le ha prodotte, e portano con se' le
    prove perche' tu possa controllarle. Mischiate in un'unica lista
    non sapresti quale sia quale.
    """
    tutte = indice.tutte()
    # Le proposte sono generata ma non ancora accettate: non stanno con
    # le altre, o sembrerebbero gia' in uso. E non stanno nemmeno fuori
    # dalla risposta: senza una lista loro, il pannello non avrebbe modo
    # di mostrare il pulsante che le rende vere.
    proposte = [s for s in tutte if s.proposta]
    generate = [s for s in tutte
                if s.origine == "generata" and not s.proposta]
    scaricate = [s for s in tutte
                 if s.origine != "generata" and not s.proposta]

    def voce(s) -> dict[str, Any]:
        return {
            "nome": s.nome,
            "descrizione": s.descrizione,
            "categoria": s.categoria,
            "origine": s.origine,
            "prove": len(s.prove),
            "con_prove": s.con_prove,
            "usata": s.volte_usata,
            "caratteri": len(s.corpo),
            # Il percorso arriva per poterlo aprire, ma relativo alla
            # radice: un percorso assoluto nel payload finisce nella
            # pagina, e la pagina non deve dire dove sta il disco.
            "percorso": os.path.relpath(s.percorso, indice.radice),
        }

    categorie: dict[str, int] = {}
    for s in scaricate:
        categorie[s.categoria or "generale"] = \
            categorie.get(s.categoria or "generale", 0) + 1

    return {
        # Anche se _skill() lo aggiunge, qui il campo c'e' sempre: una
        # risposta che a volte ha il cestino e a volte no costringe il
        # frontend a controllare prima di leggere.
        "cestino": [],
        "totale": len(tutte),
        "scaricate": len(scaricate),
        "generate": len(generate),
        "proposte": len(proposte),
        "lista_proposte": [voce(s) for s in proposte],
        "categorie": [{"nome": k, "skill": v}
                      for k, v in sorted(categorie.items())],
        "lista_scaricate": [voce(s) for s in scaricate],
        "lista_generate": [voce(s) for s in generate],
        # Quante entrerebbero nel prompt se il contesto non ci fosse:
        # e' il numero che dice se il prompt e' oggi una riga sola o
        # venti, e cambia da solo quando importi.
        "nel_prompt_max": len(_nel_prompt(indice)),
    }


def _nel_prompt(indice) -> list[str]:
    """I nomi che entrerebbero nel prompt senza contesto.

    Il limite alto serve a capire se oggi stai guardando tre skill o
    ventiquattro: e' il numero che ti dice quanto costa un import,
    e lo dice prima e non dopo.

    La lista si riconosce dalla forma della riga — due spazi, un
    segno facoltativo, poi "nome: descrizione" — e non dal numero
    esatto di spazi. Con quello il parser contava zero righe quando
    l'indentazione cambiava, e il numero tornava 0 senza che nulla
    dicesse perche'. Era gia' successo con i selettori CSS.
    """
    import re
    import orchestra.skills as sk
    p = indice.prompt("", limite=sk.MAX_NEL_PROMPT)
    riga = re.compile(r"^\s{2,}[+\- ]\s+([A-Za-z0-9._-]+):\s")
    return [m.group(1) for m in (riga.match(l) for l in p.splitlines()) if m]


def _cestino_elenco(radice: str) -> list[dict[str, Any]]:
    """Cosa c'e' nel cestino.

    Senza questo, cancellare una skill e' un atto cieco: la UI dice
    "nel cestino" e non c'e' modo di vederlo ne' di recuperarlo. Il
    rischio non e' la perdita di un file, e' che l'utente smette di
    fidarsi del pulsante perche' non sa dove vanno le cose.

    Il nome resta quello della skill, non quello della cartella: e' il
    nome che l'utente conosce, e quello che gli serve per recuperarla.
    """
    import time
    base = os.path.join(radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return []
    fuori = []
    for ts in sorted(os.listdir(base), reverse=True):
        dentro = os.path.join(base, ts)
        if not os.path.isdir(dentro):
            continue
        try:
            quando = int(ts)
        except ValueError:
            quando = 0
        for nome in os.listdir(dentro):
            fuori.append({
                "nome": nome,
                "quando": quando,
                "data": time.strftime("%Y-%m-%d %H:%M",
                                      time.localtime(quando)) if quando else "?",
                "generata": os.path.isdir(
                    os.path.join(dentro, nome, ".generata")),
            })
    return fuori


def _skill_ripristina(indice, nome: str) -> tuple[bool, str]:
    """Rimette una skill dov'era.

    Torna nella sua categoria e nella sua origine, lette dal
    frontmatter: senza, la skill finirebbe sotto "generale" e perderebbe
    la distinzione tra scaricata e generata — che e' la cosa che conta
    quando poi la guardi dal pannello.

    Se una copia e' gia' attiva, la sovrascrive invece di rifiutare.
    Il rifiuto era un difetto: cancellare, rimettere, cancellare
    lascia piu' copie nel cestino, e il secondo ripristino si fermava
    con "gia' presente" mentre la skill che avevi rimosso tu era
    ancora li' — l'utente leggeva un errore dove aveva solo fatto le
    cose che gli avevi detto di fare.
    """
    import shutil
    import time
    import orchestra.skills as _sk
    base = os.path.join(indice.radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return False, "il cestino e' vuoto"
    candidati = []
    for ts in sorted(os.listdir(base), reverse=True):
        dentro = os.path.join(base, ts, nome)
        if os.path.isdir(dentro):
            candidati.append(dentro)
    if not candidati:
        return False, f"nel cestino non c'e' {nome!r}"
    sorgente = candidati[0]

    campi, _corpo = _sk._leggi(os.path.join(sorgente, "SKILL.md"))
    origine = campi.get("origine") or "scaricata"
    cartella = (_sk.CARTELLA_GENERATE if origine == "generata"
                else _sk.CARTELLA_SCARICATE)

    # La categoria e' il percorso RELATIVO alla radice delle skill, non
    # il percorso fino alla cartella. Il frontmatter la contiene gia',
    # ma puo' essere di una versione vecchia che scriveva il percorso
    # intero: leggendola cosi' e usando quella, rimettere due volte la
    # stessa skill produceva generale/giro-due/giro-due/giro-due, e la
    # copia attiva finiva dentro se stessa.
    #
    # Si taglia l'ultimo livello se coincide col nome della skill: e il
    # caso esattamente della copia annidata, e non ci si arriva per
    #logica, si arriva guardando cosa c'era su disco.
    parts = [p for p in (campi.get("categoria") or "generale").split("/")
             if p not in ("", ".", "..", os.sep)]
    while parts and parts[-1] == nome:
        parts.pop()
    if not parts:
        parts = ["generale"]
    categoria = parts
    dest = os.path.join(indice.radice, cartella, *categoria, nome)

    # La copia attiva, se c'e', va nel cestino invece di essere
    # sovrapposta: cosi' non si perde, e il cestino resta la sola
    # copia che il pulsante "cancella tutto" raggiunge.
    if os.path.isdir(dest):
        vecchia = os.path.join(base, str(int(time.time())))
        os.makedirs(vecchia, exist_ok=True)
        try:
            shutil.move(dest, os.path.join(vecchia, nome))
        except OSError as e:
            return False, f"non riesco a liberare il posto: {e}"

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        shutil.move(sorgente, dest)
    except OSError as e:
        return False, f"non riesco a rimetterla: {e}"
    indice._invalida()
    return True, ""


def _cestino_rimuovi(radice: str, nome: str) -> tuple[bool, str]:
    """Cancella una voce dal cestino, per sempre.

    Una voce sola. "Svuota tutto" e' un pulsante separato con una
    conferma separata: mettere le due cose insieme fa perdere roba
    che si voleva tenere. Cancellare dal cestino e' irreversibile, e
    il pulsante deve dirlo.
    """
    import shutil
    base = os.path.join(radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return False, "il cestino e' vuoto"
    for ts in sorted(os.listdir(base), reverse=True):
        dentro = os.path.join(base, ts, nome)
        if os.path.isdir(dentro):
            shutil.rmtree(dentro, ignore_errors=True)
            # svuota anche i timestamp rimasti vuoti, se sono vuoti
            tsdir = os.path.join(base, ts)
            try:
                if not os.listdir(tsdir):
                    os.rmdir(tsdir)
            except OSError:
                pass
            return True, ""
    return False, f"nel cestino non c'e' {nome!r}"


def _cestino_svuota(radice: str) -> tuple[int, str]:
    """Cancella davvero tutto quello che c'e' nel cestino."""
    import shutil
    base = os.path.join(radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return 0, ""
    n = 0
    try:
        for ts in os.listdir(base):
            dentro = os.path.join(base, ts)
            if os.path.isdir(dentro):
                n += len(os.listdir(dentro))
            shutil.rmtree(dentro, ignore_errors=True)
        os.rmdir(base)
    except OSError as e:
        return n, f"svuotato a meta': {e}"
    return n, ""


def _skill_cancella(indice, nome: str) -> bool:
    """Cancella una skill, mettendola nel cestino.

    Mette i file in una cartella `.cestino` accanto alle skill, non
    dentro la cartella della skill: messo dentro, sparisce dall'indice
    insieme al suo stesso cestino, e non si trova piu' da nessuna
    parte. Il sintomo era "la cancellazione funziona e la skill non c'e'
    piu'", che non dice che anche i file sono andati via con lei.

    Una skill cancellata per sbaglio non si ricostruisce, e se era
    scaricata l'unico modo per recuperarla e' un reimport di cento
    file. Il cestino e' una riga, e lo svuoto con un comando quando
    voglio davvero.
    """
    import shutil
    import time
    s = indice.get(nome)
    if not s:
        return False
    cartella = os.path.dirname(s.percorso)
    cestino = os.path.join(indice.radice, CARTELLA_CESTINO,
                           str(int(time.time())))
    os.makedirs(cestino, exist_ok=True)
    try:
        shutil.move(cartella, os.path.join(cestino, nome))
    except OSError:
        return False
    indice._invalida()
    return True


# Le rotte: percorso e metodo nel decoratore, il corpo
# sotto. Il commento sopra ogni gestore dice perche' esiste.
class RotteSkill:

    def _skill(self, body: dict[str, Any]) -> None:
        """Le skill: elenco, importazione, cancellazione.

        Tre cose in una rotta e non tre rotte perche' sono tre operazioni
        sulla stessa lista, e una schermata sola che le fa. Il motivo
        per cui stanno nel backend e non solo in JS e' che l'indice
        vive sul disco: il browser puo' mostrare quello che dice il
        server, ma non puo' decidere cosa esiste — altrimenti la lista
        a schermo e quella che l'agente vede possono divergere, e
        quella che conta e' la seconda.
        """
        try:
            import orchestra.skills as sk
        except Exception as e:
            self._json({"error": f"modulo skill non disponibile: {e}"}, 503)
            return
        azione = str(body.get("azione") or "elenca")
        indice = sk.Indice()

        if azione == "elenca":
            # Anche il cestino, sempre. Il frontend non lo ricava e non
            # lo ricava a parte: il primo caricamento del pannello
            # deve poter dire "3 da recuperare" senza una seconda
            # richiesta, e ogni risposta deve poterlo aggiornare senza
            # sapere quale azione sia stata.
            d = _skill_elenco(indice)
            d["cestino"] = _cestino_elenco(indice.radice)
            self._json(d)
            return

        if azione == "importa":
            cartella = str(body.get("cartella") or "").strip()
            if not cartella:
                self._json({"error": "serve la cartella dello store"}, 400)
                return
            n, nomi = indice.importa(cartella,
                                     categoria=str(body.get("categoria") or ""))
            # La lista dei nomi torna intera: con 103 skill, mostrare
            # i primi dodici e dire "altre 91" costringerebbe a
            # riaprire il pannello per contarle.
            self._json({"ok": True, "importate": n, "nomi": nomi,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "conferma":
            nome = str(body.get("nome") or "").strip()
            ok, perche = sk.conferma(indice, nome)
            if not ok:
                self._json({"error": perche}, 400)
                return
            s = indice.get(nome)
            try:
                from . import apprendimento
                apprendimento.segna_conclusa(
                    getattr(s, "firma", "") if s else "",
                    nome=nome, accettata=True)
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, "accettata": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "scarta":
            nome = str(body.get("nome") or "").strip()
            s = indice.get(nome)
            if not s or not s.proposta:
                self._json({"error": f"{nome!r} non e' una proposta"}, 400)
                return
            if not _skill_cancella(indice, nome):
                self._json({"error": f"non riesco a spostare {nome!r} "
                                     f"nel cestino"}, 500)
                return
            try:
                from . import apprendimento
                apprendimento.segna_conclusa(
                    getattr(s, "firma", ""), nome=nome, accettata=False)
            except Exception:  # noqa: BLE001
                pass
            self._json({"ok": True, "scartata": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "cestino":
            self._json({"ok": True, "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "ripristina":
            nome = str(body.get("nome") or "").strip()
            ok, perche = _skill_ripristina(indice, nome)
            if not ok:
                self._json({"error": perche}, 400)
                return
            self._json({"ok": True, "ripristinata": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "cancella_definitivo":
            nome = str(body.get("nome") or "").strip()
            ok, perche = _cestino_rimuovi(indice.radice, nome)
            if not ok:
                self._json({"error": perche}, 400)
                return
            self._json({"ok": True, "rimossa": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "svuota_cestino":
            n, errore = _cestino_svuota(indice.radice)
            if errore:
                self._json({"error": errore}, 500)
                return
            # Il cestino si rilegge invece di dichiararsi vuoto: se lo
            # svuotamento e' andato a meta' perche' c'era un file che
            # non si poteva toccare, una risposta che dice [] mente, e
            # l'utente crede di aver perso roba che invece c'e' ancora.
            self._json({"ok": True, "rimosse": n,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "cancella":
            nome = str(body.get("nome") or "").strip()
            rimosso = _skill_cancella(indice, nome)
            if not rimosso:
                self._json({"error": f"nessuna skill chiamata {nome!r}, "
                                     f"o non si puo' cancellare"}, 400)
                return
            # Il cestino torna qui e non in una richiesta separata:
            # e' l'azione che lo cambia, quindi e' la risposta che deve
            # dirti com'e' diventato.
            self._json({"ok": True, "rimossa": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        self._json({"error": f"azione sconosciuta: {azione}"}, 400)

    def _skill_file(self) -> None:
        """Il testo di una skill, per aprirla dal pannello.

        Il percorso che arriva e' relativo alla radice delle skill, non
        assoluto, e viene risolto dentro quella radice. Il motivo e'
        che questo endpoint non ha autenticazione e gira su localhost:
        accettare un percorso qualunque sarebbe una porta aperta verso
        il disco, e per leggere un file di testo non serve.

        Si passa per l'indice, che sa dove sta ogni skill: il nome e'
        l'unica cosa che arriva dal browser.
        """
        try:
            import orchestra.skills as sk
        except Exception:
            self._json({"error": "modulo skill non disponibile"}, 503)
            return
        nome = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query).get("nome", [""])[0]
        s = sk.Indice().get(nome)
        if not s:
            self._json({"error": f"nessuna skill chiamata {nome!r}"}, 404)
            return
        try:
            testo = open(s.percorso, encoding="utf-8").read()
        except OSError as e:
            self._json({"error": f"non riesco a leggere: {e}"}, 500)
            return
        # Anche i file che stanno dentro la skill: senza, "Apri"
        # mostrerebbe una procedura che rimanda a documenti che
        # restano irraggiungibili.
        allegati = []
        cartella = os.path.dirname(s.percorso)
        for dp, _dirs, files in os.walk(cartella):
            for f in files:
                if f == "SKILL.md" or f.endswith(".json"):
                    continue
                rel = os.path.relpath(os.path.join(dp, f), cartella)
                try:
                    allegati.append({
                        "nome": rel.replace(os.sep, "/"),
                        "testo": open(os.path.join(dp, f),
                                      encoding="utf-8", errors="replace").read(),
                    })
                except OSError:
                    continue
        self._json({"nome": s.nome, "contenuto": testo, "allegati": allegati})

    @rotta("GET", "/api/skill/file")
    def _r_get_skill_file(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        # Anche in GET: il pulsante "Apri" e' una lettura, non una
        # scrittura. Registrarle solo fra i POST faceva rispondere
        # 404 a una richiesta che il browser faceva in GET — e il
        # sintomo era "il pulsante non fa niente", che non dice
        # nulla del motivo.
        self._skill_file()

    @rotta("GET", "/api/skill")
    def _r_get_skill(self, path: str, body: dict[str, Any],
                     s: Any) -> None:
        # Anche /api/skill in GET: il pannello la carica appena si
        # apre e non ha un corpo da mandare. Con la sola rotta
        # POST, il primo caricamento falliva e la sezione restava
        # muta per sempre, perche' nessun pulsante era premuto.
        q = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query)
        self._skill({"azione": (q.get("azione", [""]) or [""])[0]})

    @rotta("GET", "/api/capacita")
    def _r_get_capacita(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        # Skill e tool insieme, normalizzati. Due tab nella stessa
        # pagina, ma due moduli diversi: il frontend non deve saperlo.
        fuori: dict[str, Any] = {"skill": [], "tool": []}
        try:
            import orchestra.skills as sk
            d = _skill_elenco(sk.Indice())
            if d and not d.get("error"):
                lista = list(d.get("lista_scaricate") or [])
                lista += list(d.get("lista_generate") or [])
                for s in lista:
                    if not isinstance(s, dict):
                        continue
                    fuori["skill"].append({
                        "nome": s.get("nome", ""),
                        "descrizione": s.get("descrizione", ""),
                        "categoria": s.get("categoria", ""),
                        "tipo": "skill",
                    })
        except Exception:
            # Le skill non sono un requisito: senza, la pagina
            # mostra la tab dei tool e non una pagina vuota.
            pass
        try:
            for tool in (self.app.session.registry.active or []):
                fuori["tool"].append({
                    "nome": getattr(tool, "name", ""),
                    "descrizione": getattr(tool, "description", "") or "",
                    "categoria": "strumento",
                    "tipo": "tool",
                })
        except Exception:
            pass
        self._json(fuori)

    @rotta("POST", "/api/skill/file")
    def _r_post_skill_file(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        self._skill_file()

    @rotta("POST", "/api/skill")
    def _r_post_skill(self, path: str, body: dict[str, Any],
                      s: Any) -> None:
        self._skill(body)

    @rotta("POST", "/api/mcp/servers")
    def _r_post_mcp_servers(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import mcp as mcp_mod
        self._json({"servers": mcp_mod.list_servers()})
        return

    @rotta("POST", "/api/mcp/tools")
    def _r_post_mcp_tools(self, path: str, body: dict[str, Any],
                          s: Any) -> None:
        from . import mcp as mcp_mod
        self._json({"tools": mcp_mod.list_tools()})
        return

    @rotta("POST", "/api/mcp/status")
    def _r_post_mcp_status(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        from . import mcp as mcp_mod
        self._json(mcp_mod.stato())
        return

    @rotta("POST", "/api/mcp/resources")
    def _r_post_mcp_resources(self, path: str, body: dict[str, Any],
                              s: Any) -> None:
        # Risorse e prompt sono parte del protocollo, non solo i tool:
        # la UI li mostra accanto ai tool dello stesso server.
        from . import mcp as mcp_mod
        self._json({"resources": mcp_mod.list_resources()})
        return

    @rotta("POST", "/api/mcp/prompts")
    def _r_post_mcp_prompts(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import mcp as mcp_mod
        self._json({"prompts": mcp_mod.list_prompts()})
        return

    @rotta("POST", "/api/mcp/add")
    def _r_post_mcp_add(self, path: str, body: dict[str, Any],
                        s: Any) -> None:
        from . import mcp as mcp_mod
        cfg = body if isinstance(body, dict) else {}
        c = mcp_mod.add_server(cfg)
        self._json({"ok": True, "server": c})
        return

    @rotta("POST", "/api/mcp/delete")
    def _r_post_mcp_delete(self, path: str, body: dict[str, Any],
                           s: Any) -> None:
        from . import mcp as mcp_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        ok = mcp_mod.remove_server(str(jid or ""))
        self._json({"ok": ok})
        return

    @rotta("POST", "/api/mcp/connect")
    def _r_post_mcp_connect(self, path: str, body: dict[str, Any],
                            s: Any) -> None:
        from . import mcp as mcp_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        r = mcp_mod.connect(str(jid or ""))
        self._json(r)
        return

    @rotta("POST", "/api/mcp/disconnect")
    def _r_post_mcp_disconnect(self, path: str, body: dict[str, Any],
                               s: Any) -> None:
        from . import mcp as mcp_mod
        jid = (body.get("id") if isinstance(body, dict) else None)
        ok = mcp_mod.disconnect(str(jid or ""))
        self._json({"ok": ok})
        return

    @rotta("POST", "/api/mcp/connect_all")
    def _r_post_mcp_connect_all(self, path: str, body: dict[str, Any],
                                s: Any) -> None:
        from . import mcp as mcp_mod
        r = mcp_mod.connect_all()
        self._json({"results": r})
        return
