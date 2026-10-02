"""Il tool di delega, e la garanzia che il figlio non lo veda.

Il tetto di profondità è una cosa sola: **il tool `delega` non è nel
registro del figlio**. Non è una riga nel prompt che dice "non
delegare" — quelle il modello le dimentica al quarto passo — e non è
un controllo a runtime che può sbagliare. Semplicemente non c'è, e
quindi non si può chiamare.

Per questo qui si costruisce un registro figlio e si verifica che il
tool non ci sia, invece di fidarsi di un flag.

E c'è la seconda parte, quella meno ovvia: **cosa succede al padre
quando il figlio fallisce**. Il padre riceve un testo, e un testo che
dice "errore" è indistinguibile da un testo che contiene la parola
"errore" in un'analisi. Il Figlio mette l'esito in chiaro davanti,
perché la confusione fra le due è il modo più economico con cui una
delega si rompe senza che nessuno se ne accorga.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.delega import Delegatore, Figlio  # noqa: E402
from orchestra.agent import AgentState  # noqa: E402
from orchestra.types import Message, Tool, ToolRegistry  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


class FiglioFalso:
    """Come l'altro: l'AgentState VERO, non uno inventato.

    Questa classe aveva `.finale`, `.iterazioni` e `.uso` — tre campi
    che AgentState non ha — e i test passavano lo stesso. E' la stessa
    cosa che era successa in test_delega.py: un test che verifica la
    mia immaginazione dell'interfaccia invece dell'interfaccia.
    """

    def __init__(self, risposta="fatto", costo=0.02):
        self.risposta, self.costo, self.ricevuto = risposta, costo, []

    def run(self, t):
        self.ricevuto.append(t)
        return AgentState(
            messages=[Message(role="user", content="domanda"),
                      Message(role="assistant", content=self.risposta)],
            iterations=3,
            stopped_because="risposta_finale",
        )


# --------------------------------------------------------------------------
print("[1] Il tool esiste e ha uno schema che il provider può usare")

def fabbrica_figlio(delegatore):
    """Il figlio come lo costruisce la sessione: registro NUOVO."""
    reg = ToolRegistry()
    reg.register(Tool(
        name="scrivi_file",
        description="Scrive un file.",
        schema={"type": "object", "properties": {"path": {"type": "string"}},
                "required": ["path"]},
        handler=lambda path: f"scritto {path}",
    ))
    def fab(testo):
        return FiglioFalso("risposta del figlio")
    delegatore._fabbrica = fab
    return reg

d = Delegatore(lambda t: FiglioFalso())
reg_padre = ToolRegistry()
reg_padre.register(Tool(
    name="delega",
    description="Affida un compito a un sub-agente.",
    schema={"type": "object",
            "properties": {"obiettivo": {"type": "string"},
                           "contesto": {"type": "string"}},
            "required": ["obiettivo"]},
    handler=lambda obiettivo, contesto="": d.delega(obiettivo, contesto).per_il_padre(),
))

check("il tool si registra", "delega" in reg_padre.all_names())
check("e richiede l'obiettivo",
      reg_padre.get("delega").schema["required"] == ["obiettivo"],
      str(reg_padre.get("delega").schema.get("required")))

print("\n[2] IL FIGLIO NON HA 'delega'. Non un tetto: l'assenza")
reg_figlio = fabbrica_figlio(d)
check("il padre ha delega", "delega" in reg_padre.all_names())
check("il figlio NON ha delega", "delega" not in reg_figlio.all_names(),
      str(reg_figlio.all_names()))
check("e non e' nemmeno inattivabile-per-casualita'",
      reg_figlio.get("delega") is None)
check("il figlio ha comunque i suoi tool",
      "scrivi_file" in reg_figlio.all_names())
# il punto: un figlio che volesse delegare riceverebbe un errore di
# tool sconosciuto, non una risposta vuota
check("e chiamarlo non risponde niente",
      reg_figlio.get("delega") is None,
      "un tool assente non si puo' neanche sbagliare a chiamare")

print("\n[3] La delega attraverso il tool torna al padre")
out = reg_padre.get("delega").handler(obiettivo="quante righe ha a.txt?",
                                      contesto="il file e' a.txt")
check("ha risposto", "risposta del figlio" in out, out[:60])
check("e non aggiunge rumore", out.count("risposta del figlio") == 1, out[:80])

print("\n[4] Un figlio in errore attraverso il tool si dichiara")
d2 = Delegatore(lambda t: (_ for _ in ()).throw(RuntimeError("provider chiuso")))
reg2 = ToolRegistry()
reg2.register(Tool(
    name="delega", description="Affida un compito.",
    schema={"type": "object", "properties": {"obiettivo": {"type": "string"}},
            "required": ["obiettivo"]},
    handler=lambda obiettivo, contesto="": d2.delega(obiettivo, contesto).per_il_padre(),
))
out2 = reg2.get("delega").handler(obiettivo="qualcosa")
check("il padre vede che non e' un risultato",
      "non e' un risultato" in out2, out2[:70])
check("e vede il motivo", "provider chiuso" in out2, out2[:70])
check("NON e' una risposta vuota", out2.strip() != "")

print("\n[5] Il tetto di profondità non e' un contatore: e' l'assenza")
# Anche se qualcuno costruisse per sbaglio un Delegatore con
# profondita 0 per il figlio, il tool non ci sarebbe comunque. E'
# una difesa in profondita: due controlli indipendenti.
reg3 = fabbrica_figlio(Delegatore(lambda t: FiglioFalso(), profondita=1))
check("doppio controllo: il flag dice no", not Delegatore(lambda t: None, profondita=1).puo_delegare()[0])
check("e il registro dice no", "delega" not in reg3.all_names())

print("\n[6] Il resoconto arriva al padre")
d3 = Delegatore(lambda t: FiglioFalso("ok"), tariffa=lambda tk: 0.05)
d3.delega("uno")
r = d3.resoconto()
check("dice quanti figli", "1 deleghe" in r, r)
check("e quanto costano, con la tariffa", "0.05" in r, r)

# Senza tariffa il costo non lo si sa, e il resoconto LO DICE. Prima
# questo test pretendeva 0.05 USD da uno stato che non aveva un campo
# costo, e il modulo rispondeva 0.0: il resoconto dichiarava gratis
# una delega che era a pagamento.
d3b = Delegatore(lambda t: FiglioFalso("ok"))
d3b.delega("uno")
check("senza tariffa lo dichiara sconosciuto",
      "costo non noto" in d3b.resoconto(), d3b.resoconto())

# --------------------------------------------------------------------------
# La stessa verifica, ma sull'app VERA. I test sopra costruiscono una
# fabbrica finta: verificano che il tetto funziona se qualcuno scrive
# la fabbrica bene. Questo verifica che qualcuno l'ha scritta bene.
print("\n[7] Sull'app vera: il padre ha delega, il figlio no")
try:
    from orchestra.webapp import OrchestraApp
    app = OrchestraApp.create()
    check("la delega e' attiva", app.delega_attiva is True, str(app.delega_attiva))
    check("il padre ha delega",
          "delega" in app.session.registry.all_names())
    f = app.session._fabbrica_figlio("quante righe ha a.txt?")
    check("il FIGLIO non ha delega",
          "delega" not in f.registry.all_names(),
          str([n for n in f.registry.all_names() if "deleg" in n]))
    check("ma ha i suoi tool", len(f.registry.all_names()) >= 5,
          str(len(f.registry.all_names())))
    check("e un modello proprio",
          getattr(f.provider, "model", "") != "",
          str(getattr(f.provider, "model", "")))
except Exception as e:  # noqa: BLE001
    check("l'app si costruisce", False, str(e)[:90])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
