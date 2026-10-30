"""L'identita' dell'agente principale: file, prompt e applicazione a caldo.

Il punto non e' solo salvare un nome su disco. Il difetto che questi
controlli prevengono e' piu' sottile: se l'identita' venisse solo
accodata al prompt esistente, ogni salvataggio la duplicherebbe, e un
utente che cambia la persona tre volte si ritroverebbe tre personaggi
diversi in conflitto. Qui si verifica che il prompt venga ricomposto da
zero (regole + memoria + identita') e che le regole restino davanti.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

_TMP = tempfile.mkdtemp(prefix="orchestra_identita_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import LLMResponse, LoopConfig  # noqa: E402
from orchestra import identita as idt  # noqa: E402
from orchestra import webapp  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import SYSTEM_PROMPT, default_registry  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class ProviderFinto:
    name = "finto"
    model = "finto-1"

    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="ok", model=self.model)


def sessione(prompt="SYS") -> Session:
    return Session(provider=ProviderFinto(), registry=default_registry(),
                   system_prompt=prompt, config=LoopConfig(max_iterations=2))


print("\n[1] Il file: vuoto, normalizzato, con limiti")
check("all'inizio non c'e' identita'", idt.carica() == {"nome": "", "persona": ""},
      str(idt.carica()))
salvato = idt.salva("  Gigi   Rossi ", "  risponde secco  ")
check("il nome si normalizza", salvato["nome"] == "Gigi Rossi", str(salvato))
check("la persona si conserva", salvato["persona"] == "risponde secco")
check("si rilegge dal file", idt.carica() == salvato, str(idt.carica()))
check("il file esiste", os.path.isfile(idt.percorso_file()), idt.percorso_file())

lungo = idt.salva("x" * 100, "p" * 9000)
check("il nome ha un tetto", len(lungo["nome"]) == idt.MAX_NOME, str(len(lungo["nome"])))
check("la persona ha un tetto", len(lungo["persona"]) == idt.MAX_PERSONA,
      str(len(lungo["persona"])))

with open(idt.percorso_file(), "w", encoding="utf-8") as f:
    f.write("{rotto")
check("un file rotto non fa cadere l'agente",
      idt.carica() == {"nome": "", "persona": ""}, str(idt.carica()))

print("\n[2] Il prompt: regole prima, identita' dopo")
base = "REGOLE DI SICUREZZA"
check("senza identita' il prompt resta identico", idt.componi_prompt(base) == base)
solo_nome = idt.componi_prompt(base, "Gigi")
check("basta il nome, senza persona",
      "Sei «Gigi»" in solo_nome and "l'agente principale" in solo_nome,
      solo_nome)
check("le regole restano davanti", solo_nome.startswith(base))
con_persona = idt.componi_prompt(base, "Gigi", "risponde secco")
check("la persona entra nel blocco", "risponde secco" in con_persona)
bot = idt.componi_prompt(base, "Gigi", "risponde secco", bot=True)
check("un bot si presenta come bot", "compito preciso" in bot, bot)
check("l'agente principale no", "compito preciso" not in con_persona, con_persona)

print("\n[3] Una sessione nuova legge l'identita' dal file")
idt.salva("Gigi", "persona salvata")
originale_build = webapp.build_provider
webapp.build_provider = lambda *a, **k: ProviderFinto()
try:
    sess = webapp.OrchestraApp._make_session("finto", "finto-1")
finally:
    webapp.build_provider = originale_build
prompt = sess.agent.system_prompt
check("la sessione nuova ha il nome", "Gigi" in prompt, prompt[:120])
check("e la persona", "persona salvata" in prompt)
check("ma parte dalle regole di Orchestra", prompt.startswith(SYSTEM_PROMPT),
      prompt[:80])

print("\n[4] Salvare a caldo non duplica e non perde la conversazione")
app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app._bot_attivo_id = 0
app._sessione_principale = None
app.session = sessione()
app.session.agent.state.messages.append(
    __import__("orchestra").Message(role="user", content="lavoro in corso"))
d = app.salva_identita("Nuovo", "allegro")
check("il salvataggio risponde", d["nome"] == "Nuovo" and d["persona"] == "allegro",
      str(d))
check("il prompt vivo si aggiorna", "Nuovo" in app.session.agent.system_prompt
      and "allegro" in app.session.agent.system_prompt,
      app.session.agent.system_prompt[-120:])
check("il messaggio di sistema pure",
      "Nuovo" in (app.session.agent.state.messages[0].content or ""),
      (app.session.agent.state.messages[0].content or "")[:80])
check("la conversazione resta",
      any(m.role == "user" and m.content == "lavoro in corso"
          for m in app.session.agent.state.messages))
app.salva_identita("Nuovo", "diverso")
check("cambiare persona non lascia la vecchia",
      "allegro" not in app.session.agent.system_prompt,
      app.session.agent.system_prompt[-160:])
check("e mette la nuova", "diverso" in app.session.agent.system_prompt)
check("il blocco non si duplica a ogni salvataggio",
      app.session.agent.system_prompt.count("Sei «Nuovo»") == 1,
      app.session.agent.system_prompt[-300:])
check("il file riflette l'ultimo salvataggio",
      idt.carica() == {"nome": "Nuovo", "persona": "diverso"}, str(idt.carica()))
app.salva_identita("", "")
check("svuotare l'identita' toglie il blocco dal prompt",
      "Sei «" not in app.session.agent.system_prompt
      and "diverso" not in app.session.agent.system_prompt,
      app.session.agent.system_prompt[-200:])

print("\n[5] Con un bot attivo si aggiorna il principale, non il bot")
app2 = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
principale = sessione("PRINCIPALE")
bot_sess = sessione("BOT")
app2._bot_attivo_id = 7
app2._sessione_principale = principale
app2.session = bot_sess
app2.bot_attivo = lambda: {"id": 7, "nome": "Gigi"}
app2.salva_identita("Capo", "calmo")
check("il bot attivo non viene toccato",
      bot_sess.agent.system_prompt == "BOT", bot_sess.agent.system_prompt[:50])
check("il principale conservato viene aggiornato",
      "Capo" in principale.agent.system_prompt
      and "calmo" in principale.agent.system_prompt,
      principale.agent.system_prompt[-120:])

print("\n[6] Le rotte HTTP")
app_http = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app_http.env = {"ORCHESTRA_PROVIDER": "finto", "ORCHESTRA_MODEL": "finto-1"}
app_http.session = sessione()
app_http.ready = True
app_http.error = ""
app_http.remoto_attivo = False
app_http.token_remoto = ""
app_http._storico = None
app_http._bots_runtime = {}
app_http._bot_attivo_id = 0
app_http._sessione_principale = None
app_http._bots_lavori = {}
app_http._bots_lavori_lock = threading.RLock()
app_http._registro_allegati = {}
webapp.Handler.app = app_http


def porta_libera():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    n = s.getsockname()[1]
    s.close()
    return n


def richiesta(percorso, corpo=None):
    dati = None
    intestazioni = {}
    if corpo is not None:
        dati = json.dumps(corpo).encode("utf-8")
        intestazioni["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + percorso, data=dati,
                                 headers=intestazioni,
                                 method="POST" if dati else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


BASE = f"http://127.0.0.1:{porta_libera()}"
server = webapp.ThreadingHTTPServer(
    ("127.0.0.1", int(BASE.rsplit(":", 1)[1])), webapp.Handler)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(0.3)
try:
    stato, d = richiesta("/api/identita")
    check("GET risponde", stato == 200 and d.get("ok") is True, f"{stato} {d}")
    check("GET porta i campi", "nome" in d and "persona" in d, str(d))

    stato, d = richiesta("/api/identita",
                         {"nome": "  HttpCapo ", "persona": "  via http "})
    check("POST salva", stato == 200 and d.get("nome") == "HttpCapo"
          and d.get("persona") == "via http", f"{stato} {d}")
    check("POST aggiorna la sessione viva",
          "HttpCapo" in app_http.session.agent.system_prompt)

    stato, d = richiesta("/api/identita")
    check("GET rilegge il salvataggio",
          d.get("nome") == "HttpCapo" and d.get("persona") == "via http", str(d))

    stato, d = richiesta("/api/bots")
    check("il menu in testa riceve il nome dell'agente principale",
          stato == 200 and (d.get("principale") or {}).get("nome") == "HttpCapo",
          f"{stato} {str(d)[:160]}")
finally:
    server.shutdown()
    server.server_close()

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
shutil.rmtree(_TMP, ignore_errors=True)
sys.exit(1 if FAIL else 0)
