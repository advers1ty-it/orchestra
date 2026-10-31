"""I checkout isolati dei lavori in background.

La promessa: un lavoro di un bot su un progetto git scrive in un worktree
separato, non nella cartella che l'utente ha aperta. Il test usa git vero
in una cartella temporanea, perche' un finto non direbbe niente sul
confine che conta — dove finiscono i file.

Copre anche il legame col turno: la root isolata vale per il turno che
`send` fa partire, non per la sessione, e viene azzerata quando il turno
finisce.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.request

_TMP = tempfile.mkdtemp(prefix="orchestra_worktree_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)
os.environ.pop("ORCHESTRA_WORKTREE", None)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from orchestra import bots as bt  # noqa: E402
from orchestra import lavori as lv  # noqa: E402
from orchestra import progetti as pr  # noqa: E402
from orchestra import webapp  # noqa: E402
from orchestra import worktree as wt  # noqa: E402
from orchestra import LLMResponse, LoopConfig  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import ToolCall  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def git(*args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return (r.stdout or "").strip()


def attendi(pred, timeout=8.0):
    scadenza = time.time() + timeout
    while time.time() < scadenza:
        if pred():
            return True
        time.sleep(0.02)
    return False


def repo_con_commit(nome="repo") -> str:
    base = os.path.join(_TMP, nome)
    os.makedirs(os.path.join(base, "app"), exist_ok=True)
    git("init", "-q", cwd=base)
    git("config", "user.email", "test@example.com", cwd=base)
    git("config", "user.name", "Test", cwd=base)
    with open(os.path.join(base, "README.md"), "w", encoding="utf-8") as f:
        f.write("# repo\n")
    with open(os.path.join(base, "app", "main.py"), "w", encoding="utf-8") as f:
        f.write("print('base')\n")
    git("add", "-A", cwd=base)
    git("commit", "-q", "-m", "base", cwd=base)
    return base


print("\n[1] Un progetto senza git non si isola")

semplice = os.path.join(_TMP, "semplice")
os.makedirs(semplice, exist_ok=True)
check("radice_repo su una cartella normale e' None",
      wt.radice_repo(semplice) is None)
check("prepara su una cartella normale e' None",
      wt.prepara(semplice, 1) is None)

print("\n[2] Un progetto git ha un checkout separato")

repo = repo_con_commit()
progetto = os.path.join(repo, "app")
check("la radice del repo e' quella giusta", wt.radice_repo(progetto) == repo,
      str(wt.radice_repo(progetto)))
info = wt.prepara(progetto, 101)
check("il checkout e' stato creato", bool(info), str(info))
if info:
    check("il ramo e' quello del lavoro",
          info["branch"] == "orchestra/lavoro-101", str(info["branch"]))
    check("il checkout esiste su disco", os.path.isdir(info["percorso"]))
    check("la radice del bot e' la sottocartella del progetto",
          os.path.samefile(info["radice"], os.path.join(info["percorso"], "app")),
          info["radice"])
    check("il checkout contiene HEAD",
          os.path.isfile(os.path.join(info["radice"], "main.py")))
    check("il ramo esiste nel repository",
          "orchestra/lavoro-101" in git("branch", "--list",
                                       "orchestra/lavoro-101", cwd=repo))

    with open(os.path.join(info["radice"], "da-bot.txt"), "w",
              encoding="utf-8") as f:
        f.write("ciao")
    check("il file e' nel checkout isolato",
          os.path.isfile(os.path.join(info["radice"], "da-bot.txt")))
    check("il file NON e' nella cartella dell'utente",
          not os.path.exists(os.path.join(progetto, "da-bot.txt")))
    check("il working tree dell'utente resta pulito",
          git("status", "--porcelain", cwd=repo) == "")

    esito = wt.rimuovi(info)
    check("lo scarto rimuove il checkout", not os.path.exists(info["percorso"]))
    check("lo scarto rimuove il ramo",
          git("branch", "--list", "orchestra/lavoro-101", cwd=repo) == "")
    check("la cartella dell'utente e' intatta",
          os.path.isfile(os.path.join(progetto, "main.py")))
    check("scartare due volte non esplode", wt.rimuovi(info)["ok"] is True)
    check("lo scarto dice cosa ha fatto",
          esito.get("branch") == "orchestra/lavoro-101", str(esito))

print("\n[3] Casi che non si possono isolare")

vuoto = os.path.join(_TMP, "vuoto")
os.makedirs(vuoto, exist_ok=True)
git("init", "-q", cwd=vuoto)
check("un repository senza commit non ha una base",
      wt.radice_repo(vuoto) is None)
try:
    wt.prepara(vuoto, 104)
    check("un repository senza commit non ripiega in silenzio", False)
except wt.WorktreeError:
    check("un repository senza commit non ripiega in silenzio", True)

os.environ["ORCHESTRA_WORKTREE"] = "0"
check("ORCHESTRA_WORKTREE=0 spegne il meccanismo",
      wt.abilitato() is False and wt.prepara(progetto, 102) is None)
os.environ.pop("ORCHESTRA_WORKTREE", None)

try:
    wt.rimuovi({"repo": repo, "percorso": os.path.join(_TMP, "altro"),
                "branch": "x"})
    check("un percorso fuori dalla cartella worktree viene rifiutato", False)
except wt.WorktreeError:
    check("un percorso fuori dalla cartella worktree viene rifiutato", True)

print("\n[4] La root isolata vale per il turno, non per la sessione")


class ProviderBloccato:
    name = "finto"
    model = "finto-1"

    def __init__(self):
        self.entrato = threading.Event()
        self.rilascia = threading.Event()
        self.radici = []

    def chat(self, messages, tools=None, **kw):
        # `_guard._root` e' quello che usano i tool. `tools._root` e'
        # un'altra funzione (un percorso di package), e prenderla qui
        # faceva sembrare rotto l'isolamento che invece funzionava.
        from orchestra.tools._guard import _root
        self.radici.append((threading.current_thread().name, str(_root())))
        self.entrato.set()
        self.rilascia.wait(8)
        return LLMResponse(content="fatto", model=self.model)


checkout = wt.prepara(progetto, 103)
check("c'e' un checkout per il turno", bool(checkout))
if checkout:
    prov = ProviderBloccato()
    sess = Session(provider=prov, registry=default_registry(),
                   system_prompt="SYS", config=LoopConfig(max_iterations=2))
    sess.imposta_progetto("progetto-worktree")
    avviato = sess.send("scrivi", root_isolata=checkout["radice"])
    check("il turno e' partito", avviato is True)
    check("il provider sta girando", prov.entrato.wait(5))
    check("durante il turno la sessione ha la root isolata",
          sess._root_isolata == os.path.abspath(checkout["radice"]),
          sess._root_isolata)
    secondo = sess.send("altro", root_isolata=os.path.join(_TMP, "mai"))
    check("un secondo turno viene rifiutato", secondo is False)
    check("il rifiuto non cambia la root del turno in corso",
          sess._root_isolata == os.path.abspath(checkout["radice"]),
          sess._root_isolata)
    prov.rilascia.set()
    check("il turno finisce", attendi(lambda: not sess.busy))
    radici_turno = [r for nome, r in prov.radici if nome == "orchestra-turn"]
    check("i tool hanno visto il checkout",
          bool(radici_turno) and radici_turno[0] == os.path.abspath(
              checkout["radice"]), str(prov.radici))
    check("a fine turno la root isolata sparisce", sess._root_isolata == "",
          sess._root_isolata)
    wt.rimuovi(checkout)

    # La root del thread non deve restare appiccicata: un turno normale
    # dopo uno isolato deve tornare nella cartella del progetto. Qui il
    # progetto non e' registrato, quindi la root attesa e' vuota.
    prov2 = ProviderBloccato()
    sess2 = Session(provider=prov2, registry=default_registry(),
                    system_prompt="SYS", config=LoopConfig(max_iterations=2))
    sess2.send("normale")
    prov2.entrato.wait(5)
    prov2.rilascia.set()
    attendi(lambda: not sess2.busy)

    sess3 = Session(provider=ProviderBloccato(), registry=default_registry(),
                    system_prompt="SYS", config=LoopConfig(max_iterations=2))
    sess3._root_isolata = os.path.join(_TMP, "sparito")
    try:
        sess3._prepara_root()
        check("un checkout sparito non ripiega in silenzio", False)
    except RuntimeError:
        check("un checkout sparito non ripiega in silenzio", True)

print("\n[5] Il lavoro del bot passa dal checkout, non dal progetto")

pr.registra("progetto-worktree", progetto)
bot = bt.crea("WtBot", progetto="progetto-worktree", persona="prova")
ident = int(bot["id"])
job = lv.accoda("bot", str(ident), {"testo": "crea il file"}, titolo="crea")
lavoro = lv.prossimo("bot", str(ident))
check("il lavoro e' stato preso", bool(lavoro) and lavoro["id"] == job["id"])


class ProviderScrive:
    name = "finto"
    model = "finto-1"

    def __init__(self):
        self.n = 0

    def chat(self, messages, tools=None, **kw):
        self.n += 1
        if self.n == 1:
            return LLMResponse(
                content="scrivo",
                tool_calls=[ToolCall(
                    id="t1", name="write_file",
                    arguments='{"path":"da-bot.txt","content":"ciao"}')],
                model=self.model)
        return LLMResponse(content="fatto", model=self.model)


sess_bot = Session(provider=ProviderScrive(), registry=default_registry(),
                   system_prompt="SYS", config=LoopConfig(max_iterations=4))
sess_bot.imposta_progetto("progetto-worktree")

app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app.env = {}
app.session = None
app.remoto_attivo = False
app.token_remoto = ""
app._bots_runtime = {ident: {"sessione": sess_bot}}
app._sessione_bot = lambda b: sess_bot  # type: ignore[method-assign]

app._esegui_lavoro_bot(ident, lavoro)
chiuso = lv.ottieni(job["id"])
check("il lavoro e' completato",
      bool(chiuso) and chiuso["stato"] == "completato",
      str(chiuso and (chiuso["stato"], chiuso["errore"])))
check("il file NON e' nella cartella dell'utente",
      not os.path.exists(os.path.join(progetto, "da-bot.txt")))
wt_info = ((chiuso or {}).get("checkpoint") or {}).get("worktree") or {}
check("il lavoro registra il checkout",
      bool(wt_info.get("percorso")), str(wt_info))
check("il file e' nel checkout isolato",
      bool(wt_info.get("radice"))
      and os.path.isfile(os.path.join(wt_info["radice"], "da-bot.txt")),
      str(wt_info.get("radice")))
check("il pannello riceve il checkout",
      ((lv.riassunto("bot", str(ident)).get("ultimo") or {})
       .get("worktree") or {}).get("branch") == wt_info.get("branch"))
check("la pulizia trova i checkout senza il tetto del pannello",
      any(x.get("branch") == wt_info.get("branch")
          for x in lv.worktree_di("bot", str(ident))),
      str(lv.worktree_di("bot", str(ident))))

scartato = app.scarta_checkout_lavoro(job["id"])
check("scartare il checkout lo rimuove",
      not os.path.exists(wt_info.get("percorso", "")))
check("il checkpoint dice che e' scartato",
      (((scartato.get("lavoro") or {}).get("checkpoint") or {})
       .get("worktree") or {}).get("scartato") is True, str(scartato))
check("la cartella dell'utente resta intatta",
      os.path.isfile(os.path.join(progetto, "main.py")))

attivo = lv.accoda("bot", str(ident), {"testo": "ancora"})
lv.prossimo("bot", str(ident))
try:
    app.scarta_checkout_lavoro(attivo["id"])
    check("non si scarta il checkout di un lavoro attivo", False)
except RuntimeError:
    check("non si scarta il checkout di un lavoro attivo", True)
lv.completa(attivo["id"], "ok")

# Annullato non significa "fermo": il turno puo' essere ancora in
# chiusura. Scartare il checkout in quel momento lo cancellerebbe sotto
# i piedi del consumatore.
annullato = lv.accoda("bot", str(ident), {"testo": "annullato in chiusura"})
lavoro_ann = lv.prossimo("bot", str(ident))
lv.salva_checkpoint(lavoro_ann["id"], {"worktree": {
    "repo": repo,
    "percorso": os.path.join(os.environ["ORCHESTRA_HOME"], "worktrees",
                              f"w{lavoro_ann['id']}"),
    "branch": "orchestra/lavoro-x",
}})
lv.annulla(lavoro_ann["id"])
app._bots_runtime[ident] = {
    "sessione": types.SimpleNamespace(busy=True)}
try:
    app.scarta_checkout_lavoro(lavoro_ann["id"])
    check("non si scarta un turno annullato ancora in chiusura", False)
except RuntimeError:
    check("non si scarta un turno annullato ancora in chiusura", True)
app._bots_runtime[ident] = {"sessione": sess_bot}

# Se il checkout non si crea, il lavoro deve FALLIRE. Ripiegare sulla
# cartella dell'utente sarebbe il danno che l'isolamento evita.
rotto = lv.accoda("bot", str(ident), {"testo": "checkout impossibile"})
lavoro_rotto = lv.prossimo("bot", str(ident))
dest_rotto = os.path.join(os.environ["ORCHESTRA_HOME"], "worktrees",
                          f"w{lavoro_rotto['id']}")
os.makedirs(dest_rotto, exist_ok=True)
app._esegui_lavoro_bot(ident, lavoro_rotto)
chiuso_rotto = lv.ottieni(rotto["id"])
check("un checkout impossibile fa fallire il lavoro",
      bool(chiuso_rotto) and chiuso_rotto["stato"] == "fallito",
      str(chiuso_rotto and (chiuso_rotto["stato"], chiuso_rotto["errore"])))
check("l'errore dice che e' il checkout",
      "checkout" in ((chiuso_rotto or {}).get("errore") or "").lower(),
      str((chiuso_rotto or {}).get("errore")))
check("non ha ripiegato scrivendo nel progetto",
      not os.path.exists(os.path.join(progetto, "da-bot.txt")))
shutil.rmtree(dest_rotto, ignore_errors=True)

# Il bot propone il merge DOPO aver verificato; non unisce da solo.
class ProviderPropone:
    name = "finto"
    model = "finto-1"

    def __init__(self):
        self.n = 0

    def chat(self, messages, tools=None, **kw):
        self.n += 1
        if self.n == 1:
            return LLMResponse(
                content="scrivo",
                tool_calls=[ToolCall(
                    id="p1", name="write_file",
                    arguments='{"path":"da-proporre.txt","content":"ciao"}')],
                model=self.model)
        if self.n == 2:
            return LLMResponse(
                content="verifico",
                tool_calls=[ToolCall(
                    id="p2", name="proponi_merge",
                    arguments=json.dumps({
                        "riepilogo": "creato da-proporre.txt",
                        "verifica": "test: 3 passed",
                    }))],
                model=self.model)
        return LLMResponse(content="pronto", model=self.model)


prop = lv.accoda("bot", str(ident), {"testo": "proponi"}, titolo="proponi")
lavoro_prop = lv.prossimo("bot", str(ident))
sess_prop = Session(provider=ProviderPropone(),
                    registry=default_registry(),
                    system_prompt="SYS", config=LoopConfig(max_iterations=6))
sess_prop.imposta_progetto("progetto-worktree")
app._sessione_bot = lambda b: sess_prop  # type: ignore[method-assign]
app._esegui_lavoro_bot(ident, lavoro_prop)
chiuso_prop = lv.ottieni(prop["id"])
merge = ((chiuso_prop or {}).get("checkpoint") or {}).get("merge") or {}
check("il bot registra una proposta di merge",
      bool(merge.get("pronto")) and merge.get("riepilogo")
      == "creato da-proporre.txt", str(merge))
check("la proposta porta la verifica dichiarata",
      merge.get("verifica") == "test: 3 passed", str(merge))
check("la proposta non unisce da sola",
      not merge.get("unito") and not os.path.exists(
          os.path.join(progetto, "da-proporre.txt")))
check("il pannello riceve la proposta",
      ((lv.riassunto("bot", str(ident)).get("ultimo") or {})
       .get("merge") or {}).get("pronto") is True)

unito = app.unisci_lavoro(prop["id"])
check("l'utente puo' unire il ramo proposto",
      bool(unito.get("ok")) and bool(unito.get("commit")), str(unito))
check("il file e' arrivato nel progetto",
      os.path.isfile(os.path.join(progetto, "da-proporre.txt")))
chiuso_prop = lv.ottieni(prop["id"])
merge_dopo = ((chiuso_prop or {}).get("checkpoint") or {}).get("merge") or {}
check("il lavoro ricorda di essere stato unito",
      merge_dopo.get("unito") is True and bool(merge_dopo.get("commit")),
      str(merge_dopo))
doppio = app.unisci_lavoro(prop["id"])
check("unire due volte non crea un secondo merge",
      doppio.get("gia_unito") is True, str(doppio))
app.scarta_checkout_lavoro(prop["id"])
check("dopo il merge il checkout si puo' scartare",
      os.path.isfile(os.path.join(progetto, "da-proporre.txt")))

print("\n[6] La rotta HTTP dello scarto")
porta = socket.socket()
porta.bind(("127.0.0.1", 0))
PORT = porta.getsockname()[1]
porta.close()
server = None
try:
    webapp.Handler.app = app
    server = webapp.ThreadingHTTPServer(("127.0.0.1", PORT), webapp.Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    BASE = f"http://127.0.0.1:{PORT}"

    def richiesta(corpo, percorso="/api/lavori/scarta"):
        req = urllib.request.Request(
            BASE + percorso,
            data=json.dumps(corpo).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    stato_http, d = richiesta({"id": job["id"]})
    check("POST /api/lavori/scarta risponde", stato_http == 200,
          f"{stato_http} {str(d)[:120]}")
    check("la rotta dice che era gia' scartato",
          d.get("gia_scartato") is True, str(d)[:160])

    senza = lv.accoda("bot", "999", {"testo": "senza checkout"})
    w = lv.prossimo("bot", "999")
    lv.completa(w["id"], "ok")
    stato_http, d = richiesta({"id": senza["id"]})
    check("un lavoro senza checkout risponde 400", stato_http == 400,
          f"{stato_http} {str(d)[:120]}")

    occupato = lv.accoda("bot", "998", {"testo": "attivo"})
    lv.prossimo("bot", "998")
    stato_http, d = richiesta({"id": occupato["id"]})
    check("un lavoro attivo risponde 409", stato_http == 409,
          f"{stato_http} {str(d)[:120]}")
    lv.completa(occupato["id"], "ok")

    stato_http, d = richiesta({"id": prop["id"]},
                              "/api/lavori/unisci")
    check("POST /api/lavori/unisci risponde", stato_http == 200,
          f"{stato_http} {str(d)[:120]}")
    check("la rotta dice che era gia' unito",
          d.get("gia_unito") is True, str(d)[:160])
    stato_http, d = richiesta({"id": job["id"]}, "/api/lavori/unisci")
    check("un lavoro senza proposta risponde 400", stato_http == 400,
          f"{stato_http} {str(d)[:120]}")
finally:
    if server is not None:
        server.shutdown()
        server.server_close()

print("\n[7] Merge diretto: sporco rifiutato, gia' unito riconosciuto")
repo2 = repo_con_commit("repo_merge")
prog2 = os.path.join(repo2, "app")
info2 = wt.prepara(prog2, 201)
check("c'e' un secondo checkout", bool(info2))
if info2:
    with open(os.path.join(info2["radice"], "nuovo.txt"), "w",
              encoding="utf-8") as f:
        f.write("x")
    git("add", "-A", cwd=info2["radice"])
    git("commit", "-qm", "lavoro del bot", cwd=info2["radice"])
    punta = git("rev-parse", "HEAD", cwd=info2["radice"])
    try:
        wt.unisci(info2, commit_atteso="0" * 40)
        check("non si unisce un ramo cambiato dopo la proposta", False)
    except wt.WorktreeError:
        check("non si unisce un ramo cambiato dopo la proposta", True)

    with open(os.path.join(repo2, "sporco.txt"), "w", encoding="utf-8") as f:
        f.write("modifica dell'utente")
    try:
        wt.unisci(info2)
        check("un progetto sporco non si unisce", False)
    except wt.WorktreeError:
        check("un progetto sporco non si unisce", True)
    os.remove(os.path.join(repo2, "sporco.txt"))

    esito = wt.unisci(info2, commit_atteso=punta)
    check("il merge porta il file nel progetto",
          os.path.isfile(os.path.join(prog2, "nuovo.txt")), str(esito))
    check("il merge non e' gia' unito la prima volta",
          esito.get("gia_unito") is False, str(esito))
    check("il merge produce un commit", bool(esito.get("commit")), str(esito))
    esito2 = wt.unisci(info2)
    check("un secondo merge viene riconosciuto",
          esito2.get("gia_unito") is True, str(esito2))
    check("il working tree resta pulito",
          git("status", "--porcelain", cwd=repo2) == "")
    wt.rimuovi(info2)

shutil.rmtree(_TMP, ignore_errors=True)

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
sys.exit(1 if FAIL else 0)
