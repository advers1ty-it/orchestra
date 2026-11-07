"""I comandi Telegram visti dal lato della sessione.

Il ponte, da solo, sa chi ha scritto e cosa rispondere; non sa fermare
un turno ne' cambiare un modello. Qui si prova quella meta', con una
sessione finta: nessun provider, nessuna chiave, nessuna rete.

Le cose che contano sono tre. `/stop` deve fermare un turno che dal
telefono non si fermerebbe altrimenti. `/modello` non deve poter
scrivere nel bot un nome che non esiste: un modello inventato non
risponde 400, costruisce un client valido che fallisce alla prima
chiamata, e sembra un problema di rete. E lo stato che si manda su
Telegram deve dire cosa sta succedendo, non ripetere il log del turno.
"""

import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

os.environ["ORCHESTRA_HOME"] = tempfile.mkdtemp(prefix="orch_tgc_")

import orchestra.bots as bots_mod  # noqa: E402
import orchestra.domande as domande  # noqa: E402
import orchestra.nous_auth as nous_auth  # noqa: E402
import orchestra.telegram as tg  # noqa: E402
import orchestra.webapp as webapp  # noqa: E402
from orchestra import session as session_mod  # noqa: E402


# Sul computer di chi sviluppa puo' esserci un collegamento Nous vero (il
# token sta in un file, non nell'env): un test che elenca i servizi
# cambierebbe risultato da una macchina all'altra. Qui "collegato" vuol
# dire solo "la chiave e' nel dizionario che il test ha costruito".
nous_auth.get_nous_credentials = lambda _env=None: ("", "")

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" -- {dettaglio}" if dettaglio and not cond else ""))


def cp(testo):
    """Un testo stampabile: la console di Windows non e' UTF-8.

    Il menu dei modelli contiene il segno di spunta, che in cp1252 non
    esiste: un test che fallisce non deve morire mentre scrive perche'
    ha fallito.
    """
    return str(testo).encode("cp1252", "replace").decode("cp1252")


class Stato:
    def __init__(self):
        self.messages = []


class Agente:
    def __init__(self):
        self.state = Stato()
        self.modalita_piano = False


class BridgeEventiFinto:
    """Il `bridge` di una Session: qui vive `stream`, come in EventBridge.

    Prima questo metodo stava sulla sessione finta, e la sessione vera non
    ce l'ha: il finto era piu' generoso del vero, quindi il turno Telegram
    passava i test e moriva in chat con "'Session' object has no attribute
    'stream'". Un finto che offre un metodo che il vero non ha non prova
    niente.
    """

    def __init__(self, sessione):
        self.sessione = sessione

    def stream(self, timeout=0.4):
        sess = self.sessione

        def genera():
            while True:
                if sess.eventi:
                    ev = sess.eventi.pop(0)
                    if ev.get("kind") == "idle":
                        sess.busy = False
                    yield ev
                    if ev.get("kind") == "idle":
                        return
                    continue
                # Come il bridge vero: uno stream non finisce da solo,
                # manda keepalive finche' qualcuno non chiude.
                yield {"kind": "keepalive", "data": {}, "seq": -1, "ts": 0}

        return genera()


class SessioneFinta:
    """Quello che le funzioni Telegram usano di una Session, e niente altro."""

    def __init__(self):
        self.busy = False
        self.bridge = BridgeEventiFinto(self)
        self.modello = "gpt-4o-mini"
        self.agent = Agente()
        self.steer_chiamate = []
        self.cancellata = False
        self.resettata = False
        self.coda_piena = False
        self.testo = ""
        self.allegati = None
        self.eventi = []
        self.mandato = False

    def modello_in_uso(self):
        return self.modello

    def steer(self, testo):
        if self.coda_piena:
            return False
        self.steer_chiamate.append(testo)
        return True

    def cancel(self):
        self.cancellata = True
        return True

    def reset(self):
        if self.busy:
            raise RuntimeError("sessione occupata")
        self.resettata = True

    def send(self, testo, allegati=None):
        if self.busy:
            return False
        self.busy = True
        self.mandato = True
        self.testo = testo
        self.allegati = allegati
        return True


class Messaggio:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class CatalogoFinto:
    def __init__(self, modelli):
        self.models = {m: object() for m in modelli}


def app_finta(sessione=None):
    app = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
    app.env = {"ORCHESTRA_PROVIDER": "openrouter",
               "ORCHESTRA_MODEL": "gpt-4o-mini"}
    app._bots_runtime = {}
    app._catalog_per_provider = {
        "openrouter": CatalogoFinto(["gpt-4o-mini", "gpt-4o",
                                     "claude-3-5-sonnet"])}
    sess = sessione or SessioneFinta()
    app._sessione_bot = lambda _b: sess
    app.sessione = sess
    return app, sess


bot = bots_mod.crea(nome="Prova")
app, sess = app_finta()

print("\n[1] scegliere un modello da un nome scritto a mano")
check("un nome esatto si trova",
      webapp._scegli_modello("gpt-4o-mini",
                             ["gpt-4o-mini", "gpt-4o"]) == ("gpt-4o-mini", ""))
check("le maiuscole non contano",
      webapp._scegli_modello("GPT-4o",
                             ["gpt-4o-mini", "gpt-4o"]) == ("gpt-4o", ""))
check("un pezzo di nome basta se ne resta uno",
      webapp._scegli_modello("sonnet",
                             ["gpt-4o", "claude-3-5-sonnet"])[0]
      == "claude-3-5-sonnet")
ambiguo, errore = webapp._scegli_modello("gpt-4", ["gpt-4o-mini", "gpt-4o"])
check("un nome ambiguo non si indovina", ambiguo == "" and "gpt-4o" in errore,
      errore)
vuoto, errore2 = webapp._scegli_modello("pippo", ["gpt-4o-mini"])
check("un nome che non esiste viene rifiutato", vuoto == "" and "pippo" in errore2,
      errore2)
check("senza catalogo si accetta, lo dira' chi chiama",
      webapp._scegli_modello("qualsiasi-cosa", []) == ("qualsiasi-cosa", ""))

print("\n[2] la coda del testo per il messaggio di stato")
check("un testo corto resta com'e'", webapp._coda("ciao", 100) == "ciao")
lungo = "prima parte che non serve piu' " + "parola " * 60
coda = webapp._coda(lungo, 40)
check("un testo lungo si taglia dalla testa", coda.startswith("..."), coda[:20])
check("e non supera il limite chiesto", len(coda) <= 43, str(len(coda)))
check("senza tagliare una parola a meta'",
      coda.endswith("parola"), coda[-12:])

print("\n[3] /stop ferma un turno, e non lo inventa se non c'e'")
sess.busy = False
risposta = app.telegram_comando(bot["id"], "stop")
check("senza turno in corso lo dice",
      "Nessun turno" in risposta and "/scollega" in risposta, risposta)
check("e non chiama cancel", sess.cancellata is False)
sess.busy = True
risposta = app.telegram_comando(bot["id"], "stop")
check("con un turno in corso lo ferma", sess.cancellata is True, risposta)
sess.busy = False

print("\n[4] /steer: solo dentro un turno, e mai oltre la coda")
risposta = app.telegram_comando(bot["id"], "steer", "")
check("senza testo spiega l'uso", "Uso: /steer" in risposta, risposta)
risposta = app.telegram_comando(bot["id"], "steer", "vai piano")
check("fuori da un turno non accoda", "Nessun turno" in risposta, risposta)
check("e non chiama steer", sess.steer_chiamate == [],
      str(sess.steer_chiamate))
check("fuori da un turno non prende nemmeno il testo",
      "vai piano" not in str(sess.steer_chiamate), str(sess.steer_chiamate))
sess.busy = True
risposta = app.telegram_comando(bot["id"], "steer", "vai piano")
check("dentro un turno la guida arriva",
      sess.steer_chiamate == ["vai piano"], str(sess.steer_chiamate))
check("e la risposta lo dice", "Guida inviata" in risposta, risposta)
sess.coda_piena = True
risposta = app.telegram_comando(bot["id"], "steer", "ancora")
check("a coda piena lo dice invece di perdere il messaggio",
      "piena" in risposta, risposta)
sess.coda_piena = False
sess.busy = False

print("\n[5] /nuova non butta via un turno in corso")
sess.busy = True
risposta = app.telegram_comando(bot["id"], "nuova")
check("con un turno in corso rifiuta", "/stop" in risposta, risposta)
check("e non resetta", sess.resettata is False)
sess.busy = False
risposta = app.telegram_comando(bot["id"], "nuova")
check("a sessione ferma resetta", sess.resettata is True, risposta)
check("e lo dice", "Nuova conversazione" in risposta, risposta)

print("\n[6] /modello: il menu a bottoni, e nessun nome inventato")
modulo = app.telegram_comando(bot["id"], "modello")
check("senza argomento si apre il menu", isinstance(modulo, dict), cp(modulo))
righe_menu = (modulo.get("tastiera") if isinstance(modulo, dict) else None) or []
check("i modelli sono pulsanti, non una riga di nomi",
      len(righe_menu) == 3, str(len(righe_menu)))
check("il modello in uso e' segnato e viene per primo",
      bool(righe_menu) and "gpt-4o-mini" in righe_menu[0][0]["testo"],
      cp(righe_menu))
pulsanti = [v for riga in righe_menu for v in riga]
check("i pulsanti portano un indice, non il nome del modello",
      bool(pulsanti) and all(v["dati"].startswith("m:openrouter:")
                             for v in pulsanti), cp(pulsanti))
check("e il testo dice che si tocca",
      "Tocca un modello" in str((modulo or {}).get("testo", "")), cp(modulo))
risposta = app.telegram_comando(bot["id"], "modello", "modello-inventato")
check("un modello inventato viene rifiutato",
      "inventato" in risposta and "Nessun modello" in risposta, risposta)
check("e il bot resta com'era",
      (bots_mod.per_id(bot["id"]) or {}).get("modello", "") == "",
      str((bots_mod.per_id(bot["id"]) or {}).get("modello")))
risposta = app.telegram_comando(bot["id"], "modello", "sonnet")
salvato = (bots_mod.per_id(bot["id"]) or {}).get("modello", "")
check("un pezzo di nome non ambiguo cambia il modello",
      salvato == "claude-3-5-sonnet", salvato)
check("e lo dice", "Modello cambiato" in risposta, risposta)
sess.busy = True
risposta = app.telegram_comando(bot["id"], "modello", "gpt-4o")
check("a turno in corso non cambia niente", "turno in corso" in risposta,
      risposta)
sess.busy = False
# L'indice e' quello alfabetico del catalogo: "claude-3-5-sonnet" e' il
# primo. Un pulsante vecchio deve continuare a puntare allo stesso
# modello anche dopo che quello in uso e' cambiato.
risposta = app.telegram_comando(bot["id"], "modello", "cb:m:openrouter:0")
check("toccare un modello lo salva senza scriverne il nome",
      (bots_mod.per_id(bot["id"]) or {}).get("modello") == "claude-3-5-sonnet",
      str((bots_mod.per_id(bot["id"]) or {}).get("modello")))
check("e la conferma lo dice", "Modello cambiato" in risposta, cp(risposta))

print("\n[7] /stato dice le tre cose utili, non il log")
risposta = app.telegram_comando(bot["id"], "stato")
check("c'e' il modello in uso", "gpt-4o-mini" in risposta, risposta)
check("c'e' il provider", "openrouter" in risposta, risposta)
check("e se sta lavorando", "libero" in risposta, risposta)
sess.busy = True
check("quando lavora lo dice", "al lavoro" in app.telegram_comando(
    bot["id"], "stato"))
sess.busy = False

print("\n[8] il turno su Telegram: eventi -> una riga di stato")
app, sess = app_finta()
# Il contratto che il primo giro in chat ha violato: gli eventi si leggono
# dal bridge, e la Session non offre un `stream()` suo. Se il finto se lo
# inventasse, questo blocco tornerebbe verde su un metodo che il vero non ha.
check("la sessione finta non inventa un metodo che Session non ha",
      hasattr(sess.bridge, "stream") and not hasattr(sess, "stream"),
      "gli eventi stanno su bridge.stream")
sess.eventi = []
testi = []


def send_con_eventi(testo, allegati=None):
    sess.busy = True
    sess.mandato = True
    sess.testo = testo
    sess.allegati = allegati
    sess.agent.state.messages = [Messaggio("user", testo),
                                 Messaggio("assistant", "Ho letto i test.")]
    sess.eventi = [
        {"kind": "thinking", "data": {"iteration": 2}},
        {"kind": "ragionamento", "data": {"testo": "devo guardare i test"}},
        {"kind": "tool_start", "data": {"name": "run_shell"}},
        {"kind": "contenuto", "data": {"testo": "Ho letto i test"}},
        {"kind": "idle", "data": {"busy": False}},
    ]
    return True


sess.send = send_con_eventi
visti_stato = []


def avanz(testo, azione=None):
    visti_stato.append((testo, azione))


risposta = app.telegram_turno(bot["id"], "leggi i test", None, avanz)
testi = [t for t, a in visti_stato if a is None]
azioni_viste = [a for _t, a in visti_stato if a]
# Il turno adesso torna anche i file prodotti (`{testo, file}`): il testo
# resta l'ultima frase dell'assistente, e i file si controllano a parte.
check("la risposta finale e' l'ultima dell'assistente",
      (risposta or {}).get("testo") == "Ho letto i test.", risposta)
check("e dice quali file ha prodotto", "file" in (risposta or {}), risposta)
check("il turno ha visto il testo giusto", sess.testo == "leggi i test",
      sess.testo)
check("lo stato e' stato aggiornato mentre girava", bool(testi), str(len(testi)))
primo = testi[0] if testi else ""
insieme = "\n".join(testi)
check("lo stato nomina il bot", "Prova" in primo, primo)
check("e il giro", "giro 2" in primo, primo)
check("il tool che parte e' un'azione a se'",
      any("run_shell" in a for a in azioni_viste), cp(str(azioni_viste)))
check("senza incollare tutto il ragionamento",
      "pensa:" in insieme and all(len(t) < 600 for t in testi),
      str([len(t) for t in testi]))

print("\n[21] il servizio scelto nel menu /modello non si perde per strada")
# Il menu fa scegliere PRIMA il servizio e POI il modello, e il difetto
# era proprio qui: si salvava il modello e non il servizio, quindi il
# "modello cambiato" era vero e /stato mostrava quello di prima, perche'
# la sessione successiva lo chiedeva al servizio vecchio (dove quell'id
# non esiste) e ripiegava su un altro. Due cose vere, e nessuna delle due
# era quello che l'utente aveva chiesto.
app.telegram_modelli = lambda _p: ["flint-v1.0:free", "gpt-4o"]
esito_servizio = app.telegram_comando(bot["id"], "modello",
                                      "cb:m:groq:0")
salvato = bots_mod.per_id(bot["id"]) or {}
check("il servizio toccato prima del modello resta",
      salvato.get("provider") == "groq", str(salvato.get("provider")))
check("e il modello salvato e' quello di quel servizio",
      salvato.get("modello") == "flint-v1.0:free",
      str(salvato.get("modello")))
check("la conferma dice anche su quale servizio",
      "groq" in esito_servizio.lower(), cp(esito_servizio))
bots_mod.aggiorna(bot["id"], modello=sess.modello)

print("\n[22] una foto a un modello che non la legge non parte")
# Flint e' text-only: dichiarato dal servizio, scritto nel catalogo. Da
# Telegram il controllo non c'era, quindi la foto partiva lo stesso e il
# modello rispondeva con sicurezza a una domanda su un'immagine che non
# aveva ricevuto.
from types import SimpleNamespace  # noqa: E402


class CatalogoVisione:
    def __init__(self):
        self.models = {
            "cieco": SimpleNamespace(
                info=SimpleNamespace(supports_vision=False)),
            "vede": SimpleNamespace(
                info=SimpleNamespace(supports_vision=True)),
            # I due che possono essere proposti: uno con la vista e
            # gratis, uno gratis ma con poco contesto, uno a pagamento.
            "gratis-vl": SimpleNamespace(
                info=SimpleNamespace(supports_vision=True, is_free=True,
                                     context_length=1_000_000)),
            "gratis-piccolo": SimpleNamespace(
                info=SimpleNamespace(supports_vision=True, is_free=True,
                                     context_length=8_000)),
            "caro-vl": SimpleNamespace(
                info=SimpleNamespace(supports_vision=True, is_free=False,
                                     context_length=2_000_000)),
            # Anonimo e in prova: dichiara tutto e non e' un rimedio su cui
            # contare (crouton-alpha dichiara le immagini e non le vede).
            # Contesto enorme, cosi' senza il filtro arriverebbe primo.
            "stealth/nuovo-alpha": SimpleNamespace(
                info=SimpleNamespace(supports_vision=True, is_free=True,
                                     context_length=4_000_000)),
            # Gratis, con la visione ma senza tool-calling: risponderebbe
            # a una foto e non saprebbe lavorare.
            "senza-tool": SimpleNamespace(
                info=SimpleNamespace(supports_vision=True, is_free=True,
                                     supports_tools=False,
                                     context_length=3_000_000)),
            "boh": object(),  # il catalogo non dichiara niente
        }


app._carica_catalogo = lambda forza=False: CatalogoVisione()
# Il blocco [21] ha lasciato il bot su groq: qui lo si riporta al
# servizio dell'applicazione. Il consiglio propone modelli del SERVIZIO
# in uso — un id di un altro servizio e' un comando che non trova
# niente — e nella cache c'e' solo quello che serve a questo blocco.
bots_mod.aggiorna(bot["id"], provider="openrouter")
app._catalog_per_provider = {"openrouter": CatalogoVisione()}
sess.modello = "cieco"
mandati = []
sess.send = lambda *_a, **_k: mandati.append(1) or True
allegato_foto = SimpleNamespace(immagini=["data:image/jpeg;base64,AAAA"])
rifiuto = app.telegram_turno(bot["id"], "cosa vedi?", [allegato_foto])
check("un modello senza vista lo dice invece di indovinare",
      isinstance(rifiuto, str) and "non legge le immagini" in rifiuto,
      cp(str(rifiuto)))
check("e non manda il turno", mandati == [], str(len(mandati)))
# Un rifiuto che non dice cosa fare lascia l'utente a cercare fra
# centinaia di modelli. La proposta e' la strada per uscirne.
check("e propone un modello gratis che la legge, gia' come comando",
      "gratis-vl" in str(rifiuto) and "/modello" in str(rifiuto),
      cp(str(rifiuto)))
check("proponendo solo modelli del servizio in uso",
      app.modelli_vision_gratis("openrouter", 3) == ["gratis-vl",
                                                    "gratis-piccolo"]
      and app.modelli_vision_gratis("un-altro-servizio", 3) == [],
      str(app.modelli_vision_gratis("un-altro-servizio", 3)))
check("senza proporre quello a pagamento (ne' un altro cieco)",
      "caro-vl" not in str(rifiuto) and "cieco" not in str(rifiuto).replace(
          "cieco non legge", ""), cp(str(rifiuto)))
check("ne' un modello stealth in prova, ne' uno senza tool-calling",
      "stealth/" not in str(rifiuto) and "senza-tool" not in str(rifiuto),
      cp(str(rifiuto)))
check("i candidati sono solo gratis con la vista, i piu' capienti prima",
      app.modelli_vision_gratis("", 3) == ["gratis-vl", "gratis-piccolo"],
      str(app.modelli_vision_gratis("", 3)))
check("dalla finestra il consiglio nomina il menu, non un comando",
      "menu in alto" in app.consiglio_visione()
      and "/modello" not in app.consiglio_visione(),
      cp(app.consiglio_visione()))
check("e su Telegram propone il comando pronto da toccare",
      "/modello gratis-vl" in app.consiglio_visione(da_telegram=True),
      cp(app.consiglio_visione(da_telegram=True)))
# Senza nessun candidato il consiglio resta una frase, non una riga
# vuota: meglio dire "scegline un altro" che non dire niente.
_app_vuota, _ = app_finta()
_app_vuota._catalog_per_provider = {}
_app_vuota._carica_catalogo = lambda forza=False: SimpleNamespace(models={})
check("senza candidati il consiglio non resta muto",
      "menu in alto" in _app_vuota.consiglio_visione(),
      cp(_app_vuota.consiglio_visione()))
check("e su Telegram manda comunque a /modello",
      "/modello" in _app_vuota.consiglio_visione(da_telegram=True),
      cp(_app_vuota.consiglio_visione(da_telegram=True)))
check("il catalogo sa che un altro modello le legge",
      app.modello_legge_immagini(SimpleNamespace(
          modello_in_uso=lambda: "vede")) is True)
check("un modello che il catalogo non conosce non si blocca",
      app.modello_legge_immagini(SimpleNamespace(
          modello_in_uso=lambda: "boh")) is None)
check("senza immagini il controllo non c'entra",
      app.modello_legge_immagini(sess) is False)

# La scheda puo' mentire. `stealth/crouton-alpha` dichiara di leggere le
# immagini e, provato, ha risposto come se la foto non ci fosse: una
# smentita registrata vale piu' della scheda, che e' l'unica cosa che il
# servizio dichiara. Senza questo, il rifiuto non scattava e la foto
# arrivava a un modello che non la vedeva.
_mentito = SimpleNamespace(modello_in_uso=lambda: "stealth/crouton-alpha")
check("una scheda smentita da una prova non viene creduta",
      app.modello_legge_immagini(_mentito) is False)
check("e il motivo e' una frase pronta, non un booleano",
      "non le ha viste" in app.vista_smentita(_mentito),
      cp(app.vista_smentita(_mentito)))
check("per un modello normale non c'e' nessuna smentita",
      app.vista_smentita(SimpleNamespace(
          modello_in_uso=lambda: "vede")) == "")

# Lo stesso id puo' stare su due servizi con capacita' diverse. Prima si
# guardava dove capitava — l'ordine del dizionario delle cache — e si
# poteva rispondere con la scheda di un servizio che la sessione non
# stava nemmeno chiamando.
def _info_vista(vista):
    return SimpleNamespace(info=SimpleNamespace(
        supports_vision=vista, is_free=True, context_length=1000,
        supports_tools=True))


_cat_app = SimpleNamespace(models={"doppio": _info_vista(False)})
_cat_prov = SimpleNamespace(models={"doppio": _info_vista(True)})
app._carica_catalogo = lambda forza=False: _cat_app
app._catalog_per_provider = {"openrouter": _cat_prov}
check("lo stesso id su due servizi: dice la scheda del servizio in uso",
      app.modello_legge_immagini(SimpleNamespace(
          modello_in_uso=lambda: "doppio")) is True)
# Un servizio diverso in cache non deve decidere per quello in uso, e
# nemmeno l'ordine in cui le cache sono state lette.
app._catalog_per_provider = {"un-altro": _cat_prov}
check("un altro servizio in cache non risponde al posto suo",
      app.modello_legge_immagini(SimpleNamespace(
          modello_in_uso=lambda: "doppio")) is False)
app._carica_catalogo = lambda forza=False: CatalogoVisione()
app._catalog_per_provider = {"openrouter": CatalogoVisione()}

print("\n[9] un turno fermato non produce una risposta finta")
app, sess = app_finta()


def send_fermato(testo, allegati=None):
    sess.busy = True
    sess.mandato = True
    sess.eventi = [
        {"kind": "contenuto", "data": {"testo": "sto scrivendo"}},
        {"kind": "cancel_requested", "data": {}},
        {"kind": "idle", "data": {"busy": False}},
    ]
    return True


sess.send = send_fermato
risposta = app.telegram_turno(bot["id"], "lavora", None, None)
check("un turno fermato dice di essere stato fermato",
      risposta == "Turno interrotto.", risposta)

print("\n[10] un turno gia' occupato non ne fa partire un secondo")
app, sess = app_finta()
sess.busy = True
risposta = app.telegram_turno(bot["id"], "seconda richiesta", None, None)
check("lo dice invece di accodare", "ancora lavorando" in risposta, risposta)
check("e non manda niente", sess.mandato is False)

print("\n[11] un turno che muore senza dire di aver finito")
app, sess = app_finta()


def send_muto(testo, allegati=None):
    # Nessun `idle`: la sessione si ferma e basta. Il ponte non deve
    # restare ad aspettare la scadenza da quindici minuti.
    sess.busy = True
    sess.mandato = True
    sess.agent.state.messages = [Messaggio("assistant", "fatto comunque")]
    sess.eventi = [{"kind": "contenuto", "data": {"testo": "fatto"}}]
    threading.Timer(0.2, _sblocca).start()
    return True


def _sblocca():
    sess.busy = False


sess.send = send_muto
inizio = time.monotonic()
risposta = app.telegram_turno(bot["id"], "lavora", None, None)
passati = time.monotonic() - inizio
check("il turno si chiude da solo",
      (risposta or {}).get("testo") == "fatto comunque", risposta)
check("e non aspetta la scadenza", passati < 10, f"{passati:.1f}s")

print("\n[12] gli allegati arrivano al turno")
app, sess = app_finta()
ricevuti = []


def send_allegati(testo, allegati=None):
    ricevuti.append((testo, allegati))
    sess.busy = True
    sess.mandato = True
    sess.agent.state.messages = [Messaggio("assistant", "ok")]
    sess.eventi = [{"kind": "idle", "data": {"busy": False}}]
    return True


sess.send = send_allegati
app.telegram_turno(bot["id"], "guarda", ["un-allegato"], None)
check("gli allegati passano alla sessione",
      ricevuti == [("guarda", ["un-allegato"])], str(ricevuti))

print("\n[13] il modulo: servizi, pagine, e pulsanti vecchi")


def app_con_servizi(modelli):
    """Un'app con due servizi collegati e un catalogo lungo."""
    app2 = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
    app2.env = {"ORCHESTRA_PROVIDER": "openrouter",
                "ORCHESTRA_MODEL": "gpt-4o-mini",
                "OPENROUTER_API_KEY": "x", "GROQ_API_KEY": "y"}
    app2._bots_runtime = {}
    app2._catalog_per_provider = {
        "openrouter": CatalogoFinto(modelli),
        "groq": CatalogoFinto(["llama-3.3-70b", "llama-3.1-8b"]),
    }
    s = SessioneFinta()
    app2._sessione_bot = lambda _b: s
    app2.sessione = s
    return app2


venti = [f"modello-{i:02d}" for i in range(1, 21)]
app2 = app_con_servizi(venti)
b2 = bots_mod.crea(nome="Prova due")

servizi = app2.telegram_comando(b2["id"], "modello")
righe_srv = (servizi.get("tastiera") if isinstance(servizi, dict) else None) or []
dati_srv = [v["dati"] for riga in righe_srv for v in riga]
check("con piu' servizi si sceglie prima il servizio",
      dati_srv == ["s:openrouter", "s:groq"], str(dati_srv))

# Anthropic non e' fra le chiavi che scrive Opzioni: se il menu leggesse
# solo quelle, chi ha la sua chiave nel .env non vedrebbe mai il servizio.
app4 = app_con_servizi(["gpt-4o-mini"])
app4.env["ANTHROPIC_API_KEY"] = "sk-ant-x"
b4 = bots_mod.crea(nome="Prova quattro")
menu4 = app4.telegram_comando(b4["id"], "modello")
dati4 = [v["dati"] for riga in (menu4.get("tastiera") or [])
         for v in riga] if isinstance(menu4, dict) else []
check("un servizio collegato compare anche se Opzioni non sa scriverne la chiave",
      "s:anthropic" in dati4, str(dati4))
check("e il servizio in uso e' il primo",
      bool(righe_srv) and righe_srv[0][0]["testo"].endswith("OpenRouter"),
      cp(righe_srv))

pagina1 = app2.telegram_comando(b2["id"], "modello", "cb:s:openrouter")
righe_p1 = (pagina1.get("tastiera") if isinstance(pagina1, dict) else None) or []
modelli_p1 = [v for riga in righe_p1 for v in riga
              if v["dati"].startswith("m:")]
check("una pagina mostra otto modelli", len(modelli_p1) == 8,
      str(len(modelli_p1)))
check("e dice su quante pagine siamo",
      "pagina 1/3" in str((pagina1 or {}).get("testo", "")), cp(pagina1))
nav1 = [v["dati"] for riga in righe_p1 for v in riga
        if not v["dati"].startswith("m:")]
check("c'e' il modo di andare avanti", "p:openrouter:1" in nav1, str(nav1))
check("e quello di cambiare servizio", "S" in nav1, str(nav1))

fine = app2.telegram_comando(b2["id"], "modello", "cb:p:openrouter:2")
righe_f = (fine.get("tastiera") if isinstance(fine, dict) else None) or []
modelli_f = [v for riga in righe_f for v in riga if v["dati"].startswith("m:")]
nav_f = [v["dati"] for riga in righe_f for v in riga
         if not v["dati"].startswith("m:")]
check("l'ultima pagina ha il resto", len(modelli_f) == 4, str(len(modelli_f)))
check("non c'e' un avanti oltre la fine", "p:openrouter:3" not in nav_f,
      str(nav_f))
check("ma si torna indietro", "p:openrouter:1" in nav_f, str(nav_f))

scelta = modelli_f[0]["dati"] if modelli_f else ""
risposta = app2.telegram_comando(b2["id"], "modello", "cb:" + scelta)
check("un pulsante applica esattamente quel modello",
      "Modello cambiato" in risposta
      and (bots_mod.per_id(b2["id"]) or {}).get("modello") in venti,
      cp(risposta))

risposta = app2.telegram_comando(b2["id"], "modello", "cb:m:openrouter:99")
check("un indice che non esiste non applica niente",
      "non e' piu'" in risposta, cp(risposta))
risposta = app2.telegram_comando(b2["id"], "modello", "cb:S")
check("\"Cambia servizio\" riporta ai servizi",
      isinstance(risposta, dict) and len(risposta.get("tastiera") or []) == 2,
      cp(risposta))
risposta = app2.telegram_comando(b2["id"], "modello", "cb:x")
check("chiudere il modulo non cambia niente",
      "non ho cambiato niente" in str((risposta or {}).get("testo", ""))
      if isinstance(risposta, dict) else "non ho cambiato niente" in risposta,
      cp(risposta))

# Un catalogo vero puo' avere centinaia di modelli (Nous ne dichiara
# 354): un menu di quarantacinque pagine non lo scorre nessuno.
sessanta = [f"m-{i:03d}" for i in range(60)]
app3 = app_con_servizi(sessanta)
b3 = bots_mod.crea(nome="Prova tre")
menu3 = app3.telegram_comando(b3["id"], "modello", "cb:s:openrouter")
check("il menu non si allunga a dismisura",
      isinstance(menu3, dict) and "pagina 1/5" in menu3.get("testo", ""),
      cp(menu3))
check("e dice quanti restano fuori, senza nasconderlo",
      isinstance(menu3, dict) and "altri 20" in menu3.get("testo", ""),
      cp(menu3))

app2.telegram_modelli = lambda _p: []
risposta = app2.telegram_comando(b2["id"], "modello", "cb:s:openrouter")
check("se il catalogo non risponde lo dice, e non finge zero modelli",
      "Non riesco a leggere" in risposta, cp(risposta))


print("\n[15] il canale: la domanda va a chi sta lavorando, e al suo telefono")


class BridgeFinto:
    def __init__(self):
        self.eventi = []

    def emit(self, kind, data):
        self.eventi.append((kind, data))


class SessCanale:
    def __init__(self, bot_id):
        self.bot_id = bot_id
        self.bridge = BridgeFinto()


class PonteCanale:
    attivo = True

    def __init__(self, visti):
        self.visti = visti

    def chiedi_in_chat(self, tipo, dati):
        self.visti.append((tipo, dati))
        return True


app1 = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app1.session = SessCanale(0)
visti = []
app1._telegram_ponti = {3: PonteCanale(visti)}
sess3 = SessCanale(3)
session_mod._CORRENTE.sess = sess3
app1._canale_agente("permission_request", {"id": "p9"})
session_mod._CORRENTE.sess = None
check("la domanda va nel bridge della sessione al lavoro, non in quello principale",
      [e[0] for e in sess3.bridge.eventi] == ["permission_request"]
      and app1.session.bridge.eventi == [],
      str((sess3.bridge.eventi, app1.session.bridge.eventi)))
check("e alla chat Telegram di quella sessione, non di un'altra",
      visti == [("permission_request", {"id": "p9"})], str(visti))

# Senza una sessione al lavoro si torna al comportamento di prima.
visti.clear()
app1._canale_agente("domanda_utente", {"id": "d9"})
check("fuori da un turno la domanda va all'agente principale",
      [e[0] for e in app1.session.bridge.eventi] == ["domanda_utente"],
      str(app1.session.bridge.eventi))
check("e non a un bot che non c'entra", visti == [], str(visti))

print("\n[16] toccare un permesso in chat: decide quello giusto, una volta sola")


class GateFinto:
    def __init__(self):
        self.risposte = []
        self.in_attesa = True

    def rispondi(self, rid, scelta):
        if not self.in_attesa:
            return False
        self.risposte.append((rid, scelta))
        self.in_attesa = False
        return True


app2b, _sess2 = app_finta()
gate = GateFinto()
app2b.gate = gate
voce = tg.sospendi(bot["id"], {"tipo": "permesso", "id": "p1"})
esito = app2b.telegram_tocco(bot["id"], "d:s:" + voce["token"])
check("toccare 'sessione' risponde 'sessione'",
      gate.risposte == [("p1", "sessione")], str(gate.risposte))
check("e lo dice in chat", "sessione" in esito, cp(esito))

# Il pulsante di una richiesta vecchia: stesso disegno, token diverso.
voce = tg.sospendi(bot["id"], {"tipo": "permesso", "id": "p2"})
prima = len(gate.risposte)
esito = app2b.telegram_tocco(bot["id"], "d:w:aaaa")
check("un pulsante vecchio non decide la richiesta nuova",
      len(gate.risposte) == prima, str(gate.risposte))
check("e lo dice invece di applicarlo", "non e' piu' aperta" in esito, cp(esito))

# Chi ha risposto dal computer: qui non c'e' piu' nessuno che aspetta.
tg.chiudi(bot["id"])
gate.in_attesa = False
voce = tg.sospendi(bot["id"], {"tipo": "permesso", "id": "p3"})
esito = app2b.telegram_tocco(bot["id"], "d:u:" + voce["token"])
check("se il turno ha gia' rinunciato lo dice, invece di fingere",
      "Troppo tardi" in esito, cp(esito))
tg.pulisci_sospesi(bot["id"])

print("\n[17] toccare un'opzione, o scrivere la risposta")
domanda = domande.crea("nome o name?", ["nome", "name"])
voce = tg.sospendi(bot["id"], {"tipo": "domanda", "id": domanda["id"],
                               "opzioni": domanda["opzioni"]})
esito = app2b.telegram_tocco(bot["id"], "r:1:" + voce["token"])
check("toccare un'opzione consegna il testo di quell'opzione",
      domande.attendi(domanda["id"], timeout=0.5) == "name", cp(esito))
check("e la domanda non e' piu' aperta", tg.sospeso(bot["id"]) is None)

# Il piano: si approva toccando, ma spesso si corregge a parole.
piano = domande.crea("Piano: 1) leggo 2) scrivo", ["Approva il piano", "No"],
                     tipo="piano")
voce = tg.sospendi(bot["id"], {"tipo": "domanda", "id": piano["id"],
                               "opzioni": piano["opzioni"]})
esito = app2b.telegram_risposta_testo(bot["id"], "cambia il passo 2 in ordine")
check("scrivere la risposta la consegna",
      domande.attendi(piano["id"], timeout=0.5) == "cambia il passo 2 in ordine",
      cp(esito))

# Un permesso aperto: il testo non dice per quanto vale.
voce = tg.sospendi(bot["id"], {"tipo": "permesso", "id": "p4"})
esito = app2b.telegram_risposta_testo(bot["id"], "si'")
check("una riga di testo non decide un permesso",
      "pulsanti" in esito, cp(esito))
check("e la richiesta resta aperta", tg.sospeso(bot["id"]) is not None)
tg.pulisci_sospesi(bot["id"])
scaduta = app2b.telegram_risposta_testo(bot["id"], "si'")
check("senza nessuna domanda aperta lo dice",
      "nessuna domanda" in scaduta, cp(scaduta))

print("\n[18] l'agente principale si collega anche lui (id 0)")
base = bots_mod.agente_base()
check("l'agente principale ha un id che nessun bot usera'",
      base["id"] == bots_mod.BASE_ID == 0 and bots_mod.per_id(0) is None,
      str(base))
check("e per_id_agente lo trova",
      (bots_mod.per_id_agente(0) or {}).get("id") == 0, str(base))
check("senza confondere i bot veri",
      (bots_mod.per_id_agente(bot["id"]) or {}).get("nome") == bot["nome"],
      str(bots_mod.per_id_agente(bot["id"])))

app0 = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app0.env = {"ORCHESTRA_PROVIDER": "openrouter",
            "ORCHESTRA_MODEL": "gpt-4o-mini"}
app0._bots_runtime = {}
app0._catalog_per_provider = {
    "openrouter": CatalogoFinto(["gpt-4o-mini", "gpt-4o"])}
sess0 = SessioneFinta()
app0.session = sess0
stato0 = app0.telegram_comando(0, "stato")
check("i comandi funzionano sull'agente principale",
      isinstance(stato0, str) and "Modello" in stato0, cp(stato0))
check("e la sessione sa di essere la 0", sess0.bot_id == 0,
      str(getattr(sess0, "bot_id", None)))

scelti = []
app0.switch_model = lambda m, **kw: scelti.append((m, kw))
esito = app0.telegram_comando(0, "modello", "gpt-4o")
check("cambiare modello all'agente principale passa dal cambio vero",
      [m for m, _kw in scelti] == ["gpt-4o"], str(scelti))
check("e dice di essere l'agente principale, non il bot del pannello",
      scelti and scelti[0][1].get("agente_principale") is True, str(scelti))
check("e lo dice senza parlare di bot", "bot" not in esito.lower()
      or "agente principale" in esito.lower(), cp(esito))
check("ed e' una scelta dell'utente, non un ripiego",
      scelti and scelti[0][1].get("scelta_utente") is True, str(scelti))

print("\n[23] una scelta a mano spegne l'instradamento automatico")
# Il difetto vero visto dall'utente: /modello cambia, /stato conferma, poi
# un messaggio e /stato torna al modello di prima. L'instradamento
# automatico risceglie a ogni invio e scrive la sua scelta nel .env:
# il modello scelto a mano durava UNA richiesta. La finestra lo spegneva
# gia' (rotta /api/model), Telegram no — e da li' non c'era nessun modo
# di accorgersene se non guardando /stato dopo.


class SessioneRouting:
    """Solo l'interruttore: qui serve sapere se qualcuno lo tocca."""

    def __init__(self):
        self._routing_attivo = True
        self.chiamate = []

    def instradamento_attivo(self, attivo=True):
        self.chiamate.append(bool(attivo))
        self._routing_attivo = bool(attivo)


app_r = webapp.OrchestraApp.__new__(webapp.OrchestraApp)
app_r.env = {"ORCHESTRA_MODEL": "gpt-4o-mini"}
app_r.session = SessioneRouting()
# Il .env vero non si tocca: si punta a uno temporaneo e si rimette a
# posto. Un test che scrive nella configurazione di chi lo lancia non e'
# un test, e' un guasto che si scopre al riavvio.
_env_vero = webapp.ENV_PATH
webapp.ENV_PATH = os.path.join(tempfile.mkdtemp(prefix="orch_env_"), ".env")
check("all'inizio l'instradamento e' acceso",
      app_r.session._routing_attivo is True)
check("una scelta a mano lo spegne", app_r.zittisci_instradamento() is True)
check("e l'interruttore e' davvero spento",
      app_r.session._routing_attivo is False,
      str(app_r.session.chiamate))
check("la scelta resta scritta per il prossimo avvio",
      app_r.env.get("ORCHESTRA_ROUTING") == "off",
      str(app_r.env.get("ORCHESTRA_ROUTING")))
check("spegnerlo due volte non e' un errore",
      app_r.zittisci_instradamento() is False)
_righe_env = open(webapp.ENV_PATH, encoding="utf-8").read()
check("e la scelta e' scritta anche nel file, non solo in memoria",
      "ORCHESTRA_ROUTING=off" in _righe_env, cp(_righe_env[-120:]))
webapp.ENV_PATH = _env_vero

sess0._routing_attivo = False
scelti.clear()
esito_spento = app0.telegram_comando(0, "modello", "gpt-4o")
check("e la conferma lo dice, invece di lasciarlo scoprire da /stato",
      "Instradamento automatico spento" in esito_spento, cp(esito_spento))
check("e non promette piu' che vale 'dalla prossima richiesta'",
      "prossima richiesta" not in esito_spento, cp(esito_spento))

print("\n[19] un turno vero, con la Session vera, non muore piu' sullo stream")
# Il giro in chat ha rotto qui: `telegram_turno` leggeva gli eventi con
# `sess.stream`, che la Session vera non ha. I blocchi sopra usavano una
# sessione finta con un `stream` inventato, quindi erano verdi lo stesso.
# Qui la sessione e' quella di produzione e l'unica cosa finta e' il
# provider: se il turno chiama un metodo che non esiste, si vede.
from orchestra import LoopConfig  # noqa: E402
from orchestra.session import Session  # noqa: E402
from orchestra.tools import default_registry  # noqa: E402
from orchestra.types import LLMResponse  # noqa: E402


class ProviderFinto:
    name = "finto"
    model = "finto-1"

    def chat(self, messages, tools=None, **kw):
        return LLMResponse(content="Ciao, sono qui.", model=self.model)


sess_vera = Session(provider=ProviderFinto(),
                    registry=default_registry(),
                    system_prompt="sei un agente",
                    config=LoopConfig(max_iterations=2))
app, _ = app_finta(sess_vera)
errore = ""
try:
    esito = app.telegram_turno(bot["id"], "ciao", None, None)
except Exception as e:  # noqa: BLE001 - se muore, deve dirlo, non sparire
    esito, errore = None, f"{type(e).__name__}: {e}"
check("il turno finisce invece di sollevare", not errore, errore)
risposta = ((esito or {}).get("testo") if isinstance(esito, dict)
            else str(esito or ""))
check("e la risposta e' quella del modello, non una scusa",
      "Ciao, sono qui." in risposta, cp(risposta))
check("la sessione vera non e' rimasta occupata",
      sess_vera.busy is False, str(sess_vera.busy))

print("\n[20] ogni tool che parte diventa un'azione da mandare in chat")
# La cronaca su Telegram non e' il messaggio riscritto: ogni tool che
# parte deve arrivare come azione a se', con nome e argomento. Qui si
# guarda l'accoppiata vera fra gli eventi della Session e quello che il
# ponte riceve, che e' il punto in cui i due lati si possono perdere.
from orchestra.types import Tool, ToolCall, ToolRegistry  # noqa: E402


class ProviderConTool:
    name = "finto"
    model = "finto-1"

    def __init__(self):
        self.chiamate = 0

    def chat(self, messages, tools=None, **kw):
        self.chiamate += 1
        if self.chiamate == 1:
            return LLMResponse(
                content="", model=self.model,
                tool_calls=[ToolCall(id="c1", name="eco",
                                     arguments='{"comando": "pytest -q"}')])
        return LLMResponse(content="Fatto.", model=self.model)


registro = ToolRegistry()
registro.register(Tool(name="eco", description="ripete", schema={},
                       handler=lambda **_: "ok"))
sess_tool = Session(provider=ProviderConTool(), registry=registro,
                    system_prompt="sei un agente",
                    config=LoopConfig(max_iterations=3))
app2, _ = app_finta(sess_tool)
visti = []
app2.telegram_turno(bot["id"], "prova un tool", None,
                    lambda testo, azione=None: visti.append((testo, azione)))
azioni = [a for _t, a in visti if a]
check("il tool che parte arriva come azione",
      len(azioni) == 1 and "eco" in azioni[0], cp(str(azioni)))
check("con l'argomento che dice cosa sta facendo",
      any("pytest" in a for a in azioni), cp(str(azioni)))
check("e l'azione non si ripete a ogni evento dopo",
      len(azioni) == 1, cp(str(len(azioni))))

print()
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("falliti:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
