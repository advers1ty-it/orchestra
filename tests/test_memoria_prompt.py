"""La memoria che arriva davvero al modello.

Tre difetti veri, uno per sezione:

1. `## Importanti` era cucito nel prompt di sistema alla creazione della
   sessione (vedi `webapp._make_session`). Una regola salvata dopo non
   entrava piu' finche' la sessione non veniva ricostruita: su un bot
   acceso da giorni, mai. Il caso riportato: "usa sempre il calendario di
   nova gestionale", detto e ripetuto, e il bot che continuava a usare
   il calendario di Orchestra.

2. Un fatto scritto come regola finiva in `## Fatti`, che NON entra nel
   prompt. Il modello rispondeva "salvato in memoria" e dal turno dopo
   non lo leggeva piu' nessuno: la memoria era un archivio, mai una
   preferenza.

3. Niente diceva al modello di consultare la memoria PRIMA di agire, e
   quindi agiva col tool piu' ovvio (`calendario`) e la preferenza
   restava in archivio.

4. E le regole gia' salvate prima di questa correzione erano in
   `## Fatti`, che non entra nel prompt: un passaggio le sposta in
   `## Importanti` quando il file viene letto o riscritto. Il test
   parte da un `memory.md` vecchio, non da un fatto appena aggiunto.

Niente rete, niente dati veri: la memoria e' un file in una cartella
temporanea, e il provider non viene mai chiamato (la sessione non fa un
turno, si chiama `_aggiorna_prompt` a mano).
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from orchestra import memoria as memoria_mod            # noqa: E402
from orchestra import memoria_indice as memoria_indice_mod  # noqa: E402
from orchestra import webapp as webapp_mod              # noqa: E402
from orchestra.session import LoopConfig, Session       # noqa: E402
from orchestra.tools import SYSTEM_PROMPT, default_registry  # noqa: E402
from orchestra.tools import memoria as tool_mem         # noqa: E402
from orchestra.types import LLMResponse, Message        # noqa: E402

# La funzione vera, prima che i test la sostituiscano: serve alla
# sezione [6], che deve provare il percorso di produzione.
MEMORIA_VERA = tool_mem.memoria

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


class ProviderFinto:
    name = "finto"
    model = "finto-1"

    def chat(self, messages, tools=None, **kw):
        raise AssertionError("il test non fa turni: nessuna chiamata al modello")


def nuova_memoria() -> memoria_mod.Memoria:
    """Una memoria usa-e-getta, mai quella di chi lancia i test.

    Il blocco del prompt legge `memoria()` dal modulo dei tool: si
    sostituisce quella, o il test scriverebbe nella memoria vera.
    """
    cartella = tempfile.mkdtemp(prefix="orch-memoria-")
    m = memoria_mod.Memoria(percorso=os.path.join(cartella, "memory.md"))
    tool_mem.memoria = lambda: m
    return m


def nuova_sessione() -> Session:
    return Session(provider=ProviderFinto(), registry=default_registry(),
                   system_prompt="BASE-STABILE",
                   config=LoopConfig(max_iterations=2))


def volatile_di(sess: Session) -> str:
    return next((m.content for m in sess.agent.state.messages
                 if m.role == "system" and m.name == "__contesto__"), "")


def prefisso_di(sess: Session) -> str:
    return sess.agent.state.messages[0].content


REGOLA = "Da ora in poi usa solo il calendario di nova gestionale"

# ---------------------------------------------------------------------------
print("\n[1] La memoria si rilegge a ogni turno, non alla creazione")

m = nuova_memoria()
s = nuova_sessione()
s.agent.state.messages = [
    Message(role="system", content="BASE-STABILE"),
    Message(role="user", content="ricordami domani alle 11 di scrivere a Emanuela"),
]
s.agent._aggiorna_prompt()
prima = volatile_di(s)
check("prima della regola, il prompt volatile non la contiene",
      "gestionale" not in prima, prima[:160])
check("il prefisso stabile resta quello", prefisso_di(s) == "BASE-STABILE")

m.aggiungi(REGOLA)
s.agent.state.messages[-1] = Message(
    role="user", content="ricordami dopodomani alle 9 la stessa cosa")
s.agent._aggiorna_prompt()
dopo = volatile_di(s)
check("una regola salvata durante la sessione entra al turno dopo",
      "nova gestionale" in dopo, dopo[:200])
check("e dice che e' memoria, non un fatto del progetto",
      "Cose che valgono sempre" in dopo, dopo[:200])
check("la memoria NON finisce nel prefisso (che e' costruito all'avvio)",
      "nova gestionale" not in prefisso_di(s))
check("il prefisso e' ancora identico", prefisso_di(s) == "BASE-STABILE")

# Il caso "memory.md cambiato a mano": il file viene riletto (mtime), e il
# turno successivo vede il testo nuovo senza riavviare niente.
m.scrivi(m.leggi().replace("nova gestionale", "nuova gestione"))
s.agent.state.messages[-1] = Message(role="user", content="e anche venerdì")
s.agent._aggiorna_prompt()
cambiato = volatile_di(s)
check("cambiando memory.md a mano il prompt cambia",
      "nuova gestione" in cambiato and "nova gestionale" not in cambiato,
      cambiato[:200])

check("il prompt costruito all'avvio non porta la memoria",
      "nuova gestione" not in webapp_mod._prompt_base())

# ---------------------------------------------------------------------------
print("\n[2] Un fatto scritto come regola finisce in ## Importanti")

CASI_REGOLA = [
    "Da ora in poi usa solo il calendario di nova gestionale",
    "Usa sempre il fornitore Rossi per le stampe",
    "Solo il cliente CEI può approvare i preventivi",
    "Non usare mai il tono scherzoso con questo cliente",
    # Le altre due formule della lista, che senza un caso qui sarebbero
    # codice che nessuno prova.
    "Preferisco il tono informale nelle email ai clienti",
    "Regola: le bozze si mandano solo al cliente CEI",
]
for fatto in CASI_REGOLA:
    caso = nuova_memoria()
    caso.aggiungi(fatto)
    check(f"regola riconosciuta: {fatto[:38]}...",
          fatto in caso.importanti(), str(caso.importanti())[:160])

sezioni = nuova_memoria()
sezioni.aggiungi(REGOLA)
testo = sezioni.leggi()
check("nel file la regola sta sotto ## Importanti",
      "## Importanti" in testo
      and testo.index("## Importanti") < testo.index(REGOLA), testo[-200:])

normale = nuova_memoria()
dato = "Il sito del ristorante ha 12 pagine"
normale.aggiungi(dato)
check("un fatto normale resta in ## Fatti, fuori dal prompt",
      dato not in normale.importanti() and dato in normale.fatti(),
      str(normale.importanti())[:160])

# Il marcatore sta in fondo alla riga e si riconosce ancorato: un
# `[auto]` scritto DENTRO il fatto e' testo, non burocrazia.
con_tag = nuova_memoria()
regola_con_tag = "Da ora in poi usa il tag [auto] per le bozze dei post"
con_tag.aggiungi(regola_con_tag)
check("un `[auto]` dentro il testo del fatto non viene mangiato",
      regola_con_tag in con_tag.importanti(),
      str(con_tag.importanti())[:200])
check("e la riga resta promossa dall'euristica",
      dict(con_tag.importanti_con_origine()).get(regola_con_tag) == "auto",
      str(con_tag.importanti_con_origine())[:200])

fatto_con_tag = nuova_memoria()
tag_nel_fatto = "Il cliente usa il tag [auto] nei post del blog"
fatto_con_tag.aggiungi(tag_nel_fatto)
check("un fatto normale con `[auto]` nel testo resta intero",
      tag_nel_fatto in fatto_con_tag.fatti(),
      str(fatto_con_tag.fatti())[:200])

marcato = nuova_memoria()
marcato.aggiungi("Il cliente vuole le fatture a fine mese", importante=True)
check("priorita' alta esplicita continua a funzionare",
      "fatture a fine mese" in " ".join(marcato.importanti()))

# Il messaggio che l'utente legge dal telefono deve dire che la regola vale.
parlante = nuova_memoria()
strumento = tool_mem.tool_memoria()
msg = strumento.handler(azione="aggiungi", fatto=REGOLA)
check("il tool dice che e' una regola e resta nel prompt",
      "regola" in msg and "priorità alta" in msg, msg)
check("e il fatto e' davvero negli Importanti",
      "gestionale" in " ".join(parlante.importanti()))

msg2 = strumento.handler(azione="aggiungi", fatto=dato)
check("un fatto normale non viene spacciato per regola",
      "regola" not in msg2 and "priorità alta" not in msg2, msg2)

# ---------------------------------------------------------------------------
print("\n[3] Il prompt dice di cercare in memoria prima di agire")

riga = next((r for r in SYSTEM_PROMPT.splitlines()
             if "memoria" in r.lower() and "prima" in r.lower()), "")
check("c'e' una riga che manda a cercare in memoria prima di eseguire",
      bool(riga), SYSTEM_PROMPT[-400:])
check("nomina il tool e l'azione",
      "`memoria`" in riga and "cerca" in riga.lower(), riga[:200])
check("e dice perche': una preferenza puo' essere in memoria",
      "preferenza" in riga.lower(), riga[:240])

# ---------------------------------------------------------------------------
print("\n[4] Un memory.md vecchio si sistema da solo")

VECCHIO = """# Memoria di Orchestra

Quello che Orchestra sa di te e non deve chiederti due volte.

## Fatti

- Da ora in poi usa solo il calendario di nova gestionale  [progetto:nova]  _agente_  <!-- 2026-11-10 -->
- Il sito del ristorante ha 12 pagine  <!-- 2026-11-11 -->

## Importanti

- Lavora su Windows  <!-- 2026-11-09 -->
"""


def memoria_da_file(contenuto: str) -> memoria_mod.Memoria:
    """Una memoria che nasce dal file di un'installazione vecchia."""
    cartella = tempfile.mkdtemp(prefix="orch-vecchia-")
    percorso = os.path.join(cartella, "memory.md")
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(contenuto)
    m = memoria_mod.Memoria(percorso=percorso)
    tool_mem.memoria = lambda: m
    return m


vecchia = memoria_da_file(VECCHIO)
old = vecchia.leggi()          # la lettura fa il passaggio
check("leggendo, la regola vecchia passa fra gli Importanti",
      "gestionale" in " ".join(vecchia.importanti()),
      str(vecchia.importanti())[:160])
check("e non e' piu' nella sezione Fatti",
      old.index("## Importanti") < old.index("gestionale")
      and old.count("gestionale") == 1, old[-300:])
check("data e progetto della riga sopravvivono",
      "[progetto:nova]" in old and "<!-- 2026-11-10 -->" in old, old[-300:])
check("un fatto normale resta dov'era",
      old.index("12 pagine") < old.index("## Importanti"), old[-300:])
check("le regole gia' importanti non si spostano",
      "Lavora su Windows" in old)
check("il passaggio non si ripete all'infinito",
      vecchia.migra_regole() == 0 and vecchia.leggi() == old)
check("e la regola finisce davvero nel blocco del prompt",
      "gestionale" in tool_mem.blocco_prompt_completo(),
      tool_mem.blocco_prompt_completo()[:200])

origini = dict(vecchia.importanti_con_origine())
check("la regola migrata risulta promossa dall'euristica",
      origini.get("Da ora in poi usa solo il calendario di nova gestionale")
      == "auto", str(origini)[:220])
check("un fatto gia' importante resta scelto a mano",
      origini.get("Lavora su Windows") == "mano", str(origini)[:220])
check("il marcatore sta nella riga e non nel testo del fatto",
      "[auto]" in old and all("[auto]" not in t for t in origini))

senza = memoria_da_file("## Fatti\n\n- Da ora in poi usa solo la rubrica Nova\n")
senza.leggi()
nuovo = senza.leggi()
check("se `## Importanti` non c'e' viene creata",
      "## Importanti" in nuovo and "rubrica Nova" in " ".join(senza.importanti()),
      nuovo)

# Il percorso del pannello: il file viene SOSTITUITO, non riletto. Senza
# il passaggio dentro `scrivi`, un file vecchio incollato a mano resterebbe
# con le regole in `## Fatti` fino al riavvio.
incollata = memoria_da_file("## Fatti\n\n- Il sito ha 3 pagine\n")
incollata.scrivi(VECCHIO)
# Si guarda il FILE, non `importanti()`: una lettura successiva potrebbe
# sistemare il testo passando dal percorso di lettura, e il controllo
# direbbe "ok" anche se la scrittura non fa niente. Qui l'unico modo per
# cui la regola puo' essere gia' sotto `## Importanti` e' il passaggio
# dentro `scrivi`.
with open(incollata.percorso, encoding="utf-8") as f:
    su_disco = f.read()
check("un file vecchio incollato dal pannello si sistema subito",
      su_disco.index("## Importanti") < su_disco.index("gestionale")
      and su_disco.count("gestionale") == 1, su_disco[-260:])

salvata = memoria_da_file("## Fatti\n\n- Solo il cliente CEI approva i preventivi\n")
salvata.aggiungi("Il sito ha 4 sezioni")
check("anche salvando un fatto il file vecchio si sistema",
      "CEI" in " ".join(salvata.importanti()),
      str(salvata.importanti())[:160])
check("e il fatto nuovo resta in Fatti, non fra le regole",
      all("4 sezioni" not in r for r in salvata.importanti()),
      str(salvata.importanti())[:160])

# ---------------------------------------------------------------------------
print("\n[5] Se l'elenco e' tagliato lo dice, e le regole scelte a mano restano")

piena = nuova_memoria()
# Abbastanza regole automatiche da sfondare il tetto di 1.000 caratteri:
# quattordici righe da ~85 caratteri sono ~1.190.
AUTO_FATTI = [f"Da ora in poi usa sempre il fornitore numero {i:02d} "
              f"per le stampe del cliente {i:02d}" for i in range(1, 15)]
for f in AUTO_FATTI:
    piena.aggiungi(f)
MANO_FATTO = "La fattura del cliente CEI va intestata a Studio CEI Srl"
piena.aggiungi(MANO_FATTO, importante=True)

coppie = dict(piena.importanti_con_origine())
check("una regola promossa e' marcata auto",
      coppie.get(AUTO_FATTI[0]) == "auto", str(coppie)[:220])
check("una regola scritta a mano e' marcata mano",
      coppie.get(MANO_FATTO) == "mano", str(coppie)[:220])
check("il marcatore non sporca il testo del fatto",
      all("[auto]" not in t for t in coppie))
check("nemmeno `importanti()` lo mostra",
      all("[auto]" not in t for t in piena.importanti()))

blocco = tool_mem.blocco_prompt()
righe = blocco.splitlines()
avvisi = [r for r in righe if "fuori da questo elenco" in r]
fatti = [r for r in righe if r not in avvisi]
check("l'elenco dice di essere tagliato", len(avvisi) == 1, blocco[-260:])
check("dice quante regole restano fuori",
      bool(avvisi) and re.search(r"altre (\d+) regole", avvisi[0]),
      str(avvisi)[:220])
check("e come trovarle (`memoria`)",
      bool(avvisi) and "`memoria`" in avvisi[0], str(avvisi)[:220])
check("la regola scritta a mano resta nel prompt",
      MANO_FATTO in blocco, blocco[:320])
check("e viene prima delle promosse dall'euristica",
      MANO_FATTO in blocco and AUTO_FATTI[0] in blocco
      and blocco.index(MANO_FATTO) < blocco.index(AUTO_FATTI[0]),
      blocco[:320])
check("nessun fatto arriva tagliato a meta'",
      all(r[2:] in coppie for r in fatti), str(fatti)[:220])
check("le righe dei fatti stanno dentro il tetto",
      sum(len(r) + 1 for r in fatti) <= tool_mem.TETTO_PROMPT,
      str(sum(len(r) + 1 for r in fatti)))
mancanti = len(coppie) - len(fatti)
check("il conto dei fuori e' quello dei fatti che mancano",
      mancanti > 0 and bool(avvisi)
      and int(re.search(r"altre (\d+) regole", avvisi[0]).group(1)) == mancanti,
      f"mancanti {mancanti}, avviso {avvisi}")
presenti = [r[2:] for r in fatti]
check("nessuna regola scelta a mano e' stata lasciata fuori",
      all(t in presenti for t, origine in coppie.items()
          if origine == "mano"), str(coppie)[:220])
check("e fuori restano proprio le promozioni automatiche",
      all(t in presenti for t, origine in coppie.items()
          if origine == "mano")
      and any(t not in presenti for t, origine in coppie.items()
              if origine == "auto"))

# ---------------------------------------------------------------------------
print("\n[6] Con l'indice FTS attivo, che e' il percorso vero in produzione")


def memoria_indiciata(contenuto: str | None = None):
    """La memoria come la vede l'agente: `indice_memoria()` sopra il file.

    Le altre sezioni iniettano un `Memoria` a mano; in produzione
    `tools.memoria.memoria()` passa da qui, e un test che non ci passa
    non dice niente su quello che gira davvero.
    """
    cartella = tempfile.mkdtemp(prefix="orch-indice-")
    percorso = os.path.join(cartella, "memory.md")
    if contenuto is not None:
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(contenuto)
    sorgente = memoria_mod.Memoria(percorso=percorso)
    indice = memoria_indice_mod.IndiceMemoria(
        sorgente=sorgente,
        percorso=os.path.join(cartella, "memoria_indice.db"))
    tool_mem.memoria = MEMORIA_VERA
    tool_mem.indice_memoria = lambda: indice
    return sorgente, indice


_sorgente, indice = memoria_indiciata()
check("il tool passa dall'indice, non dal file",
      tool_mem.memoria() is indice)

# Il fatto entra dal tool, come in produzione: handler -> indice -> file.
tool_mem.tool_memoria().handler(azione="aggiungi", fatto=REGOLA)
check("l'indice dice la stessa cosa del prompt, non 'nessuna regola'",
      REGOLA in indice.importanti(), str(indice.importanti())[:200])
check("l'origine letta dall'indice e' 'auto'",
      dict(indice.importanti_con_origine()).get(REGOLA) == "auto",
      str(indice.importanti_con_origine())[:220])
check("e la regola e' nel blocco del prompt",
      REGOLA in tool_mem.blocco_prompt(), tool_mem.blocco_prompt()[:220])

_sorgente2, indice2 = memoria_indiciata()
for f in AUTO_FATTI:
    indice2.aggiungi(f, origine="agente")
indice2.aggiungi(MANO_FATTO, importante=True, origine="agente")

blocco = tool_mem.blocco_prompt()
righe = blocco.splitlines()
avvisi = [r for r in righe if "fuori da questo elenco" in r]
fatti = [r for r in righe if r not in avvisi]
check("la regola scritta a mano resta e viene prima delle promosse",
      MANO_FATTO in blocco and AUTO_FATTI[0] in blocco
      and blocco.index(MANO_FATTO) < blocco.index(AUTO_FATTI[0]),
      blocco[:320])
check("l'avviso di taglio c'e' e il conto e' quello dei fatti che mancano",
      bool(avvisi) and int(re.search(r"altre (\d+) regole", avvisi[0]).group(1))
      == len(indice2.importanti_con_origine()) - len(fatti),
      f"avviso {avvisi}, fatti {len(fatti)}")

# Un memory.md vecchio, con l'indice: la migrazione deve avvenire al primo
# giro, quando la produzione costruisce l'indice sopra il file.
vecchia_src, _vecchia_idx = memoria_indiciata(VECCHIO)
check("all'avvio con l'indice, il file vecchio viene migrato",
      "gestionale" in " ".join(vecchia_src.importanti()),
      str(vecchia_src.importanti())[:200])


# Un backend registrato che non conosce l'origine (l'interfaccia
# documentata chiede solo leggi/scrivici/elimina): il blocco non deve
# sparire, si legge l'elenco nudo e si tratta come scelto a mano.
class BackendSenzaOrigine:
    def importanti(self):
        return ["Lavora su Windows"]

    def importanti_con_origine(self):
        raise RuntimeError("backend vecchio")


tool_mem.memoria = lambda: BackendSenzaOrigine()
check("un backend senza origine non fa sparire il blocco",
      "Lavora su Windows" in tool_mem.blocco_prompt(),
      tool_mem.blocco_prompt()[:200])
tool_mem.memoria = MEMORIA_VERA

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
