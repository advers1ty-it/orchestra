"""Le skill: due origini, e le regole che le governano.

I test qui sono severi per scelta. Una skill che entra nel prompt e'
un'istruzione che l'agente segue: se il prompt e' sbagliato, cid' che
l'agente fa e' sbagliato, e l'errore non si vede li' dove e' stato
fatto. Meglio un test che rompe che uno che lascia passare.
"""

import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestra.skills as sk

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


RADICE = tempfile.mkdtemp(prefix="skills-test-")
# L'unico indice del file. Ogni sezione ne creava uno nuovo e
# rileggeva tutto da capo: la 12 poi cercava una skill che solo la 10
# aveva creato, e il fallimento parlava del modulo invece che del
# test. Esiste gia' `i` a creare(), che lo usa per invalidare la cache
# dopo aver scritto.
i = None


def idx() -> sk.Indice:
    global i
    if i is None:
        i = sk.Indice(RADICE)
    return i


def crea(nome, descrizione="Fa una cosa.", corpo="Corpo." * 60,
         categoria="test", origine="scaricata", prove=None, radice=None):
    # ATTENZIONE: "origine" qui e' il valore logico ("scaricata",
    # "generata"), NON il nome della cartella, che e' un altro
    # ("percorso", "generate"). Scrivere in skills/scaricata/ e poi
    # cercare in skills/percorso/ e' il primo modo di scrivere un
    # test che passa vuoto: la skill c'e' su disco, l'indice dice che
    # non esiste, e il guasto sembra nel modulo.
    cartella = sk.CARTELLA_SCARICATE if origine == "scaricata" else sk.CARTELLA_GENERATE
    i = idx() if radice is None else radice
    p = os.path.join(radice or RADICE, cartella, categoria, nome, "SKILL.md")
    sk._scrivi(p, {"name": nome, "description": descrizione,
                   "categoria": categoria, "origine": origine}, corpo)
    if prove:
        sk._prove_scrivi(p, prove)
    i._invalida()
    return i


print("[1] Leggere una skill")
crea("pdf-estrazione", "Estrae tabelle da un PDF scansionato.")
i = idx()
s = i.get("pdf-estrazione")
check("la trova", s is not None)
check("il nome", s and s.nome == "pdf-estrazione")
check("la descrizione", s and "scansionato" in s.descrizione)
check("il corpo c'e'", s and len(s.corpo) > 100)
check("l'origine e' quella giusta", s and s.origine == "scaricata")
check("l'indice non ha residui", len(i.tutte()) == 1, str(i.nomi()))

print("\n[2] Il prompt porta due righe, non il corpo")
# Il punto di tutto il modulo: con 188 skill, il prompt pieno costerebbe
# piu' di 20.000 token a ogni messaggio.
i = idx()
p = i.prompt("estrazione")
check("il prompt esiste", bool(p))
check("NON contiene il corpo", "Corpo.Corpo" not in p, p[:120])
check("contiene il nome", "pdf-estrazione" in p)
check("contiene la descrizione", "scansionato" in p)
check("e spiega come si apre", "skill_leggi" in p)
check("resta corto", len(p) < 600, f"{len(p)} caratteri")

print("\n[3] Il corpo entra quando la skill viene aperta")
# Il compromesso: due righe nel prompt, tutto il resto su richiesta.
i = idx()
s = i.get("pdf-estrazione")
testo = s.per_uso()
check("il corpo c'e' per intero", "Corpo.Corpo" in testo)
check("e il nome in capo", testo.startswith("# Skill: pdf-estrazione"))

print("\n[4] Le prove distinguono una skill generata da una scaricata")
prove = [{"ts": 1700000000, "obiettivo": "Estrarre la tabella ordini",
          "comandi": ["pdftotext -layout f.pdf"], "esito": "43 righe"},
         {"ts": 1700000100, "obiettivo": "Estrarre la tabella clienti",
          "comandi": ["pdftotext -layout g.pdf"], "esito": "12 righe"}]
crea("pdftotext", "Estrae tabelle con pdftotext.", origine="generata",
     prove=prove, categoria="generata")
i = idx()
g = i.get("pdftotext")
check("la generata e' riconosciuta", g and g.origine == "generata", g.origine if g else "?")
check("e porta con se' le prove", g and g.con_prove and len(g.prove) == 2)
check("le prove sono nel testo d'uso",
      g and "pdftotext -layout f.pdf" in g.per_uso())
s = i.get("pdf-estrazione")
check("la scaricata non ha prove", s and not s.con_prove)
riga = g.per_prompt()
check("nel prompt la generata e' segnata", "[2 prove]" in riga, riga[:100])
check("la scaricata non lo e'", "[prove]" not in s.per_prompt())
# Il segno '+': a colpo d'occhio si distingue l'una dall'altra.
check("la generata porta il segno", riga.strip().startswith("+"), riga[:30])

print("\n[5] La soglia decide, e dice perche'")
# Il punto che l'utente ha chiesto: soglia automatica. Il no deve
# avere una ragione, altrimenti "nessuna skill" sembra un bug.
c = sk.Candidato(nome="x", descrizione="d", corpo="c" * 400,
                 prove=[{"ts": 1}, {"ts": 2}])
ok, perche = sk.valuta_candidato(c)
check("sotto soglia non vale", not ok)
check("e dice quante prove mancano", "2/3" in perche, perche)
c2 = sk.Candidato(nome="x", descrizione="d", corpo="c" * 400,
                  prove=[{"ts": 1}, {"ts": 2}, {"ts": 3}])
ok2, perche2 = sk.valuta_candidato(c2)
check("alla soglia vale", ok2, perche2)
c3 = sk.Candidato(nome="x", descrizione="d", corpo="c" * 40,
                  prove=[{"ts": 1}, {"ts": 2}, {"ts": 3}])
ok3, perche3 = sk.valuta_candidato(c3)
check("un corpo troppo corto non vale", not ok3)
check("e lo dice", "troppo corto" in perche3, perche3)
# La soglia si puo' abbassare: su richiesta esplicita non ce n'e'.
ok4, _ = sk.valuta_candidato(c, soglia=1)
check("su richiesta la soglia si abbassa", ok4)

print("\n[6] Salvare una generata")
c4 = sk.Candidato(nome="build-rn", descrizione="Compila APK release RN.",
                  corpo="Procedura lunga. " * 30,
                  prove=[{"ts": 1, "comandi": ["./gradlew assembleRelease"]}] * 3)
i = idx()
p = sk.salva_generata(i, c4)
check("il file esiste", os.path.exists(p), p)
check("va nella cartella giusta", sk.CARTELLA_GENERATE in p, p)
campi, corpo = sk._leggi(p)
check("il frontmatter c'e'", campi.get("nome") == "" or campi.get("name") == "build-rn",
      str(campi)[:120])
check("l'origine e' generata", campi.get("origine") == "generata")
check("le prove sono in un file a parte", os.path.exists(p + ".prove.json"))
check("e si rileggono", len(sk._prove_json(p)) == 3)
i._invalida()
check("l'indice la vede", i.get("build-rn") is not None)

print("\n[7] Un nome non puo' uscire dalla cartella")
# Il nome lo scrive il modello, e un nome di file e' una porta che si
# apre da solo. ".." dentro un nome non sale, ma da solo sì.
i = idx()
for sporco, atteso in [("../../avvia", "avvia"), ("..", "skill"),
                       ("a/b\\c", "a-b-c"), ("", "skill"),
                       ("con spazi", "con-spazi")]:
    p = sk.salva_generata(i, sk.Candidato(
        nome=sporco, descrizione="d", corpo="c" * 400,
        prove=[{"ts": 1}] * 3))
    dentro = os.path.abspath(p).startswith(os.path.abspath(i.radice))
    nome = os.path.basename(os.path.dirname(p))
    check(f"'{sporco}' resta dentro", dentro, p)
    check(f"  e diventa '{nome}'", nome == atteso, nome)

print("\n[8] Importare da uno store")
store = tempfile.mkdtemp(prefix="store-")
os.makedirs(os.path.join(store, "ref-pdf"))
sk._scrivi(os.path.join(store, "ref-pdf", "SKILL.md"),
           {"name": "ref-pdf", "description": "Riferimento PDF."}, "Corpo. " * 50)
# Una skill con file di supporto: senza questi, il documento rimanda a
# roba che non c'e' e l'agente la segue fino all'errore.
os.makedirs(os.path.join(store, "ref-pdf", "references"))
io.open(os.path.join(store, "ref-pdf", "references", "formato.md"),
        "w", encoding="utf-8").write("Il formato del file.")
os.makedirs(os.path.join(store, "ref-pdf", "scripts"))
io.open(os.path.join(store, "ref-pdf", "scripts", "estrai.py"),
        "w", encoding="utf-8").write("print('ciao')\n")
os.makedirs(os.path.join(store, "sotto", "profondo"))
sk._scrivi(os.path.join(store, "sotto", "profondo", "SKILL.md"),
           {"name": "profondo", "description": "Annidata."}, "Corpo. " * 50)

i = idx()
n, nomi = i.importa(store, categoria="estratte")
# Due, non tre: nello store ci sono ref-pdf/ e sotto/profondo/. La
# cartella "sotto" non e' una skill, e' un livello. Il primo test che
# avevo scritto contava tre perche' guardava le cartelle invece che i
# file — e per un attimo ho accusato l'import di perderne una.
check("importa tutte e skill del negozio", n == 2, f"{n}: {nomi}")
check("e restituisce i nomi", len(nomi) == 2, str(nomi))
# La sottocategoria non si perde: senza il parametro, "profondo"
# verrebbe messo sotto "sotto"; col parametro, sotto "estratte/sotto".
# In un archivio con 188 skill, sapere che una e' in devops e non in
# "generale" e' metà del valore.
check("l'annidata conserva la categoria",
      (i.get("profondo") and i.get("profondo").categoria == "estratte/sotto"),
      i.get("profondo").categoria if i.get("profondo") else "?")
dest = os.path.join(i.radice, sk.CARTELLA_SCARICATE, "estratte", "ref-pdf")
check("porta SKILL.md", os.path.exists(os.path.join(dest, "SKILL.md")))
check("porta references/", os.path.exists(os.path.join(dest, "references", "formato.md")))
check("porta scripts/", os.path.exists(os.path.join(dest, "scripts", "estrai.py")))
check("l'origine resta scaricata", i.get("ref-pdf").origine == "scaricata")

print("\n[9] Reimportare non duplica e non porta prove vecchie")
# Le prove di una generata non sopravvivono a un reimport della
# cartella: coprirebbero prove di una procedura che non e' piu' quella.
i2 = idx()
p2 = os.path.join(i2.radice, sk.CARTELLA_SCARICATE, "estratte", "ref-pdf", "SKILL.md")
sk._prove_scrivi(p2, [{"ts": 1, "esito": "falso"}])
i2._invalida()
i2.importa(store, categoria="estratte")
i2._invalida()
check("reimporta ancora 2", True)
check("ma le prove spariscono", not i2.get("ref-pdf").con_prove,
      str(i2.get("ref-pdf").prove)[:60])
check("e resta una sola copia",
      len([s for s in i2.tutte() if s.nome == "ref-pdf"]) == 1)

print("\n[10] La ricerca sceglie per pertinenza")
i = idx()
crea("compila-apk", "Compila un APK Android in release.", "c" * 400, categoria="a")
crea("estrai-pdf", "Estrae testo da un PDF con pdftotext.", "c" * 400, categoria="b")
crea("scrive-una-skill", "Genera una skill nuova.", "c" * 400, categoria="c")
i._invalida()
ris = i.cerca(["compila", "apk"])
check("trova quella giusta", ris and ris[0].nome == "compila-apk",
      str([s.nome for s in ris]))
ris2 = i.cerca(["skill"])
check("e anche l'altra", any(s.nome == "scrive-una-skill" for s in ris2),
      str([s.nome for s in ris2]))
check("una parola troppo corta non cerca",
      i.cerca(["a"]) == [], str(i.cerca(["a"])))
check("una parola che non c'e' non inventa",
      i.cerca(["kubernetes"]) == [], str(i.cerca(["kubernetes"])))

print("\n[11] Il prompt sceglie, e non cresce senza fine")
# Con 200 skill, il prompt non puo' crescere di 200 righe: il posto
# nel messaggio di sistema e' conteso con le istruzioni dell'agente.
i = idx()
for n in range(40):
    crea(f"skill-{n:02d}", f"Fa la cosa numero {n}.", "c" * 400, categoria="massa")
i._invalida()
p = i.prompt("compila apk", limite=10)
righe = [r for r in p.splitlines() if r.strip().startswith(("+", "  -", "-"))]
check("il prompt c'e'", bool(p))
check("non supera il limite", len(righe) <= 12, f"{len(righe)} righe")
nomip = [l.strip() for l in p.splitlines()
          if l.strip().startswith(("+", "-", "  -"))]
# Con 40 skill in piu' nell'indice, il prompt per "compila apk" deve
# contenere UNA riga sola: quella pertinente. Prima ne metteva 24,
# riempiendo con skill generiche che non hanno niente a che fare — e
# l'agente le legge come pertinenti, perche' sono nel prompt insieme
# a quella giusta. Un prompt pieno di rumore peggiora la risposta
# invece di aiutarla: questo e' il punto, e merita un test che lo
# guardi per numero e non per contenuto.
check("una riga sola nel prompt", len(nomip) == 1, f"{len(nomip)}: {nomip}")
check("ed e' quella giusta", "compila-apk" in nomip[0] or "build-rn" in nomip[0],
      str(nomip)[:110])
check("annuncia il totale", f"{len(i.tutte())} in tutto" in p, p[:120])

print("\n[12] La ricerca guarda al contesto, non alla massa")
# Una skill che non c'entra col contesto non deve entrare nel prompt:
# un prompt pieno di cose non pertinenti peggiora la risposta, non la
# migliora.
i = idx()
p = i.prompt("voglio estrarre tabelle da un pdf scansionato")
check("la pertinente c'e'", "estrai-pdf" in p, p[:250])
check("l'irrilevante resta fuori", "compila-apk" not in p, p[:200])

print("\n[13] Un file rotto non rompe l'indice")
# Una skill scritta a mano puo' non avere frontmatter, o averne uno a
# meta'. Non puo' far cadere l'indice delle altre 187.
i = idx()
brutto = os.path.join(RADICE, sk.CARTELLA_SCARICATE, "rotta", "rotta", "SKILL.md")
os.makedirs(os.path.dirname(brutto), exist_ok=True)
io.open(brutto, "w", encoding="utf-8").write("Niente frontmatter, solo testo.")
mezzo = os.path.join(RADICE, sk.CARTELLA_SCARICATE, "rotta2", "mezza", "SKILL.md")
os.makedirs(os.path.dirname(mezzo), exist_ok=True)
io.open(mezzo, "w", encoding="utf-8").write("---\nname: mezza\ndescrizione: troncata\n")
i._invalida()
try:
    tutte = i.tutte()
    check("l'indice regge", len(tutte) > 0, str(len(tutte)))
    check("la skill senza frontmatter ha un nome",
          any(s.nome == "rotta" for s in tutte), str([s.nome for s in tutte][:6]))
    check("e la troncata pure", any(s.nome == "mezza" for s in tutte))
    check("il prompt si genera lo stesso", bool(i.prompt("qualcosa")))
except Exception as e:
    check("l'indice regge", False, f"{type(e).__name__}: {e}")

print("\n[14] Un file non-UTF8 non rompe l'indice")
# Le skill scaricate vengono da repository altrui, e non sono tutte in
# UTF-8. Una con la codifica sbagliata non puo' far cadere le altre.
i = idx()
strano = os.path.join(RADICE, sk.CARTELLA_SCARICATE, "cp1252", "strana", "SKILL.md")
os.makedirs(os.path.dirname(strano), exist_ok=True)
with open(strano, "wb") as f:
    f.write(b"---\nname: strana\ndescription: Con accenti.\n---\n\nCiao \xff\xfe mondo\n")
i._invalida()
try:
    check("l'indice regge", len(i.tutte()) > 0)
    check("e la legge", any(s.nome == "strana" for s in i.tutte()))
except Exception as e:
    check("l'indice regge", False, f"{type(e).__name__}: {e}")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
shutil.rmtree(RADICE, ignore_errors=True)
shutil.rmtree(store, ignore_errors=True)
sys.exit(1 if FAIL else 0)
