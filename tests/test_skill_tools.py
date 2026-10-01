"""I tool delle skill, provati come li usa l'agente.

Un tool che risponde "" sembra funzionare: non tira, non sbaglia, e
il modello conclude che la skill era vuota. Qui si controlla che la
risposta contenga quello che serve, non solo che non sia un'eccezione.
"""

import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestra.skills as sk
import orchestra.skill_tools as st
from orchestra.tools import default_registry

PASS, FAIL = [], []
RADICE = tempfile.mkdtemp(prefix="skilltool-")
sk.RADICE = RADICE
st._INDICE = sk.Indice(RADICE)


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


def chiama(qual_, **kw):
    # "qual_" e non "nome": gli argomenti del tool finiscono in kw, e
    # un tool come skill_leggi ha un campo "nome". Con lo stesso nome
    # il parametro se lo rubava, e l'errore parlava di un valore
    # doppio invece che del tool che stai provando.
    r = default_registry()
    t = r.get(qual_)
    # asyncio.run e non get_event_loop: dalla 3.14 non esiste piu' un
    # loop implicito, e chiederlo solleva un errore che parla di
    # threading e non del codice sotto test — il genere di rumore che
    # fa perdere mezz'ora a cercare il bug nel posto sbagliato.
    return asyncio.run(t.handler(kw))


def crea(nome, descrizione, corpo="Procedura. " * 40,
         categoria="test", origine="scaricata", prove=0):
    cartella = (sk.CARTELLA_SCARICATE if origine == "scaricata"
                else sk.CARTELLA_GENERATE)
    p = os.path.join(RADICE, cartella, categoria, nome, "SKILL.md")
    sk._scrivi(p, {"name": nome, "description": descrizione,
                   "categoria": categoria, "origine": origine}, corpo)
    if prove:
        sk._prove_scrivi(p, [{"ts": 1, "comandi": ["x"], "esito": "ok"}] * prove)
    st._INDICE._invalida()


print("[1] I tool sono nel registro")
r = default_registry()
for n in ("skill_cerca", "skill_leggi", "skill_genera", "skill_importa"):
    check(f"{n} registrato", n in r)
    check(f"  e attivo", r.get(n) is not None and n in [t.name for t in r.active])
# Ogni tool deve dire il suo schema: uno senza 'required' accetta
# chiamate vuote e fallisce con un errore invece di chiedere.
for n in ("skill_cerca", "skill_leggi", "skill_genera", "skill_importa"):
    check(f"{n} dichiara i suoi campi", bool(r.get(n).schema.get("required")),
          str(r.get(n).schema)[:90])

print("\n[2] skill_cerca")
crea("estrai-pdf", "Estrae tabelle da un PDF scansionato con pdftotext.")
out = chiama("skill_cerca", parole="pdf tabelle")
check("risponde qualcosa", bool(out.strip()), repr(out)[:80])
check("e nomina la skill giusta", "estrai-pdf" in out, out[:120])
check("non scarica il corpo", "Procedura. Procedura." not in out, out[:120])
vuoto = chiama("skill_cerca", parole="")
check("senza parole spiega cosa serve", "Esempio" in vuoto, vuoto[:90])
# Una parola sola e troppo corta non produce nulla di utile, e non
# deve fingersi che la ricerca abbia funzionato.
niente = chiama("skill_cerca", parole="kubernetes")
check("una parola che non c'e' lo dice", "Nessuna skill" in niente, niente[:110])
# Su lista: il modello la passa spesso cosi'.
lista = chiama("skill_cerca", parole=["pdf", "tabelle"])
check("accetta anche una lista", "estrai-pdf" in lista, lista[:90])

print("\n[3] skill_leggi porta la procedura")
out = chiama("skill_leggi", nome="estrai-pdf")
check("c'e' il corpo", "Procedura. Procedura." in out, out[:100])
check("e il nome in capo", out.startswith("# Skill: estrai-pdf"), out[:60])
sconosciuta = chiama("skill_leggi", nome="non-esiste")
check("una skill inesistente lo dice", "Nessuna skill" in sconosciuta, sconosciuta[:90])
# Su un errore non si scarica l'indice: 188 nomi in un messaggio
# costano piu' del tentativo.
check("e non elenca tutte le altre", "estrai-pdf" not in sconosciuta, sconosciuta[:90])
vuoto2 = chiama("skill_leggi")
check("senza nome chiede", "esatto" in vuoto2 or "Che skill" in vuoto2, vuoto2[:80])

print("\n[4] skill_leggi segna che e' stata usata")
prima = sk.Indice(RADICE).get("estrai-pdf").volte_usata
chiama("skill_leggi", nome="estrai-pdf")
dopo = sk.Indice(RADICE).get("estrai-pdf").volte_usata
check("il contatore sale", dopo == prima + 1, f"{prima} -> {dopo}")
campi, _ = sk._leggi(os.path.join(RADICE, sk.CARTELLA_SCARICATE, "test",
                                 "estrai-pdf", "SKILL.md"))
check("e resta su disco", campi.get("volte_usata") == str(dopo), str(campi)[:110])

print("\n[5] skill_genera con le prove")
out = chiama("skill_genera", nome="build-rn",
             descrizione="Compila un APK Android in release.",
             procedura="1. Copia le chiavi in android/.\n"
                       "2. Lancia gradlew assembleRelease.\n"
                       "3. Firma con apksigner, verifica con apksigner verify.\n"
                       "4. Copia l'apk dove lo prende la CI.\n"
                       "5. Se il build fallisce, guarda la firma, non il codice.\n"
                       "6. Il primo gradlew scarica tutto: dai tempo.\n"
                       "7. Con --legacy-peer-deps se npm si blocca sui peer.\n"
                       "8. Controlla che l'apk non sia piu' grosso del solito.",
             obiettivo="Generare l'APK firmato",
             comandi=["./gradlew assembleRelease",
                      "apksigner sign --out app.apk app-release-unsigned.apk"],
             esito="APK firmato, 24 MB")
check("davvero salvata, non solo dichiarata",
      out.strip().startswith("Skill salvata"), out[:130])
p = os.path.join(RADICE, sk.CARTELLA_GENERATE, "build-rn", "SKILL.md")
check("il file esiste", os.path.exists(p), p)
s = sk.Indice(RADICE).get("build-rn")
check("l'indice la vede", s is not None)
check("e porta le prove", s and s.con_prove and len(s.prove) == 1, str(s.prove)[:70] if s else "")
check("le prove hanno i comandi",
      s and s.prove[0].get("comandi", [])[:1] == ["./gradlew assembleRelease"],
      str(s.prove[0].get("comandi"))[:80] if s else "")
check("il testo d'uso le mostra", s and "apksigner" in s.per_uso())

print("\n[6] skill_genera senza prove non e' una skill")
# Il punto della soglia: una procedura senza prove e' un'affermazione.
# Salvala e l'agente la ripete perche' "l'ha gia' fatta una volta",
# anche se quella volta e' stata un caso.
out = chiama("skill_genera", nome="senza-prove",
             descrizione="Una cosa.", procedura="fare cosi' " * 30)
check("non la salva", "Non salvata" in out, out[:110])
check("e non dichiara il falso",
      not out.strip().startswith("Skill salvata"), out[:110])
check("spiega perche'", "prove" in out.lower(), out[:130])
check("il file non c'e'",
      not os.path.exists(os.path.join(RADICE, sk.CARTELLA_GENERATE, "senza-prove", "SKILL.md")))

# Una procedura sotto i 200 caratteri non e' una procedura: e' un
# comando. Il rifiuto deve arrivare per un motivo solo e dichiarato,
# altrimenti due motivi si sovrappongono e non sai quale abbia
# fermato la scrittura.
out_corta = chiama("skill_genera", nome="corta",
                   descrizione="Cosa breve.",
                   procedura="leggi il file. " * 6,
                   comandi=["read_file x"], esito="ok")
check("una procedura troppo corta non si salva",
      not out_corta.strip().startswith("Skill salvata"), out_corta[:110])
check("e lo dice per il motivo giusto",
      "troppo corto" in out_corta, out_corta[:130])

print("\n[7] skill_genera senza i campi obbligatori chiede")
mancante = chiama("skill_genera", nome="x")
check("chiede la procedura", "procedura" in mancante.lower(), mancante[:100])
vuoto3 = chiama("skill_genera")
check("senza nome lo dice", "nome" in vuoto3.lower() or "Servono" in vuoto3, vuoto3[:80])

print("\n[8] skill_importa")
store = tempfile.mkdtemp(prefix="store-")
for n, cat in (("typer", "web"), ("rich", "web"), ("pillow", "media")):
    d = os.path.join(store, cat, n)
    os.makedirs(os.path.join(d, "scripts"), exist_ok=True)
    sk._scrivi(os.path.join(d, "SKILL.md"),
               {"name": n, "description": f"Skill {n} di prova."}, "Corpo. " * 40)
    open(os.path.join(d, "scripts", "a.py"), "w").write("x = 1\n")
out = chiama("skill_importa", cartella=store, categoria="estratte")
check("importa", "3 skill" in out, out[:110])
check("e le nomina", "typer" in out and "pillow" in out, out[:110])
check("sono nell'indice",
      sk.Indice(RADICE).get("typer") is not None)
dest = os.path.join(RADICE, sk.CARTELLA_SCARICATE, "estratte", "web", "typer")
check("conserva la sottocategoria dello store", os.path.isdir(dest), dest)
check("e porta gli script", os.path.exists(os.path.join(dest, "scripts", "a.py")))
vuoto4 = chiama("skill_importa", cartella=os.path.join(RADICE, "non-esiste"))
check("una cartella che non c'e' lo dice", "Nessuna skill" in vuoto4, vuoto4[:100])
# Importare non deve far cadere l'indice, ne' far perdere quelle
# gia' presenti.
check("le skill precedenti ci sono ancora",
      sk.Indice(RADICE).get("build-rn") is not None)

print("\n[9] Una skill lunga viene tagliata, e lo dice")
crea("enorme", "Una skill lunghissima.", corpo="parola " * 20000)
out = chiama("skill_leggi", nome="enorme")
check("non riempie il contesto", len(out) < 40000, f"{len(out)} caratteri")
check("e dichiara il taglio", "tagliato" in out, out[-160:])

print("\n[10] Il prompt del sistema")
i = sk.Indice(RADICE)
p = i.prompt("estrai tabelle da un pdf")
check("le skill ci sono nel prompt", "estrai-pdf" in p, p[:150])
check("e i loro tool si spiegano", "skill_leggi" in p, p[:200])
# La generata porta il segno '+' in capo: a colpo d'occhio si
# distingue da una scaricata, e il segno conta perche' una skill
# generata e' un'affermazione dello stesso agente, non una procedura
# scritta da qualcun altro. Il contesto e' quello della generata: con
# un altro, il prompt non la sceglie — ed e' esattamente il motivo per
# cui il prompt si ferma a quello che c'entra.
pg = i.prompt("compila apk android release")
check("la generata entra col suo contesto", "build-rn" in pg, pg[:200])
check("e porta il segno",
      any(l.strip().startswith("+") for l in pg.splitlines()), pg[:250])
check("la scaricata non lo porta",
      not any(l.strip().startswith("+") and "estrai-pdf" in l
              for l in pg.splitlines()), pg[:250])
# Nessuna skill: il prompt sparisce, e non lascia un'istruzione che
# rimanda a un indice vuoto.
vuoto5 = sk.Indice(tempfile.mkdtemp()).prompt("qualcosa")
check("senza skill il prompt e' vuoto", vuoto5 == "", repr(vuoto5)[:60])

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
shutil.rmtree(RADICE, ignore_errors=True)
shutil.rmtree(store, ignore_errors=True)
sys.exit(1 if FAIL else 0)
