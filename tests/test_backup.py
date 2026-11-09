"""Backup e ripristino: un archivio che si puo' davvero riaprire.

La parte che conta non e' "lo zip esiste": e' che il database dentro lo
zip contenga le ultime scritture, e che il ripristino rimetta i file
senza lasciare mezzi dati. Per questo il test apre il .db ripristinato e
ci legge una riga, invece di controllare solo i nomi.
"""

import os
import sqlite3
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import orchestra.backup as bkp  # noqa: E402

_conta = 0
_falliti: list[str] = []


def check(nome: str, cond: bool, extra: str = "") -> None:
    global _conta
    if cond:
        _conta += 1
        print(f"  OK  {nome}")
    else:
        _falliti.append(nome)
        print(f"  FAIL  {nome}" + (f" — {extra}" if extra else ""))


def casa_nuova() -> str:
    casa = tempfile.mkdtemp(prefix="orch-backup-")
    os.environ["ORCHESTRA_HOME"] = casa
    bkp.ENV_PATH = os.path.join(casa, ".env")
    return casa


def _db_con_riga(percorso: str) -> str | None:
    con = sqlite3.connect(percorso)
    try:
        riga = con.execute("SELECT testo FROM turni LIMIT 1").fetchone()
        return riga[0] if riga else None
    finally:
        con.close()


def _prepara(casa: str) -> None:
    with open(os.path.join(casa, "memory.md"), "w", encoding="utf-8") as f:
        f.write("# memoria\nricordo questo\n")
    con = sqlite3.connect(os.path.join(casa, "storico.db"))
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE turni (testo TEXT)")
        con.execute("INSERT INTO turni VALUES ('una risposta che deve sopravvivere')")
        con.commit()
        # La connessione resta aperta: le ultime scritture sono nel WAL,
        # non ancora nel .db. E' il caso che una copia con shutil perde.
    finally:
        con.close()


print("[1] crea: lo zip contiene i dati, e il database e' completo")
casa = casa_nuova()
_prepara(casa)
esito = bkp.crea("", con_chiavi=False)
archivio = esito["percorso"]
check("lo zip esiste", os.path.isfile(archivio), archivio)
check("sta nella cartella backup della home",
      os.path.dirname(archivio) == os.path.join(casa, "backup"), archivio)
with zipfile.ZipFile(archivio) as z:
    nomi = z.namelist()
    check("c'e' il manifesto", "MANIFEST.json" in nomi)
    check("c'e' la memoria", "dati/memory.md" in nomi)
    check("c'e' lo storico", "dati/storico.db" in nomi)
    check("niente journal -wal nello zip",
          not any(n.endswith("-wal") for n in nomi), str(nomi))
    with tempfile.TemporaryDirectory() as tmp:
        z.extract("dati/storico.db", tmp)
        letto = _db_con_riga(os.path.join(tmp, "dati", "storico.db"))
    check("la riga scritta prima del backup c'e' ancora",
          letto == "una risposta che deve sopravvivere", repr(letto))
    check("il manifesto dichiara la versione",
          b'"versione"' in z.read("MANIFEST.json"))

print("[2] elenco: dice cosa salva, e non elenca i journal")
voci = {v["nome"] for v in bkp.elenco(con_chiavi=False)}
check("memory.md nell'elenco", "memory.md" in voci, str(voci))
check("nessun -wal nell'elenco", not any(v.endswith("-wal") for v in voci), str(voci))

print("[3] ripristina: i file tornano in una home vuota")
prima = archivio
casa2 = casa_nuova()
# Un dato vecchio: il ripristino deve salvarlo prima di sovrascrivere.
with open(os.path.join(casa2, "vecchio.txt"), "w", encoding="utf-8") as f:
    f.write("questo c'era prima")
esito2 = bkp.ripristina(prima, con_chiavi=False)
check("ha scritto i file", esito2["ripristinati"] >= 2, str(esito2))
check("memory.md ripristinata",
      os.path.isfile(os.path.join(casa2, "memory.md")))
check("storico.db ripristinato e leggibile",
      _db_con_riga(os.path.join(casa2, "storico.db")) ==
      "una risposta che deve sopravvivere")
check("la sicurezza esiste prima del ripristino",
      os.path.isfile(esito2["sicurezza"]), esito2["sicurezza"])

print("[4] ripristina: rifiuta un archivio che non e' un backup")
straniero = os.path.join(casa2, "straniero.zip")
with zipfile.ZipFile(straniero, "w") as z:
    z.writestr("x.txt", "ciao")
try:
    bkp.ripristina(straniero, con_chiavi=False)
    check("archivio estraneo rifiutato", False, "nessuna eccezione")
except RuntimeError as e:
    check("archivio estraneo rifiutato", "MANIFEST" in str(e), str(e))
check("nessun file estraneo scritto",
      not os.path.exists(os.path.join(casa2, "x.txt")))

print("[5] ripristina: non esce dalla cartella dati")
cattivo = os.path.join(casa2, "cattivo.zip")
with zipfile.ZipFile(cattivo, "w") as z:
    z.writestr("MANIFEST.json", '{"formato": 1, "versione": "x", "file": []}')
    z.writestr("dati/../fuggito.txt", "non doveva finire qui")
try:
    bkp.ripristina(cattivo, con_chiavi=False)
    check("archivio con percorso che esce rifiutato", False, "nessuna eccezione")
except RuntimeError as e:
    check("archivio con percorso che esce rifiutato", "non contiene dati" in str(e), str(e))
check("il file fuori posto non e' stato scritto",
      not os.path.exists(os.path.join(casa2, "fuggito.txt")))

print("[6] ripristina: archivio inesistente e formato sconosciuto")
try:
    bkp.ripristina(os.path.join(casa2, "non-c-e.zip"), con_chiavi=False)
    check("archivio inesistente segnalato", False)
except RuntimeError as e:
    check("archivio inesistente segnalato", "non trovato" in str(e), str(e))
futuro = os.path.join(casa2, "futuro.zip")
with zipfile.ZipFile(futuro, "w") as z:
    z.writestr("MANIFEST.json", '{"formato": 99}')
    z.writestr("dati/memory.md", "x")
try:
    bkp.ripristina(futuro, con_chiavi=False)
    check("formato sconosciuto rifiutato", False)
except RuntimeError as e:
    check("formato sconosciuto rifiutato", "formato" in str(e), str(e))

print("[7] chiavi: il .env entra nell'archivio solo se richiesto")
casa3 = casa_nuova()
with open(bkp.ENV_PATH, "w", encoding="utf-8") as f:
    f.write("ORCHESTRA_PROVIDER=nous\n")
with open(os.path.join(casa3, "memory.md"), "w", encoding="utf-8") as f:
    f.write("memoria\n")
senza = bkp.crea("", con_chiavi=False)
with zipfile.ZipFile(senza["percorso"]) as z:
    check("senza --con-chiavi non c'e' il .env",
          "config/.env" not in z.namelist())
    check("il manifesto lo dice", b'"con_chiavi": false' in z.read("MANIFEST.json"))
con = bkp.crea("", con_chiavi=True)
with zipfile.ZipFile(con["percorso"]) as z:
    check("con le chiavi c'e' config/.env", "config/.env" in z.namelist())
casa4 = casa_nuova()
ripristino = bkp.ripristina(con["percorso"], con_chiavi=True)
check("le chiavi sono tornate", ripristino["chiavi"])
with open(bkp.ENV_PATH, "r", encoding="utf-8") as f:
    check("il contenuto e' quello salvato",
          "ORCHESTRA_PROVIDER=nous" in f.read())

print("[8] crea: una home vuota non produce un archivio vuoto")
casa5 = casa_nuova()
try:
    bkp.crea("", con_chiavi=False)
    check("home vuota segnalata", False)
except RuntimeError as e:
    check("home vuota segnalata", "niente da salvare" in str(e), str(e))

print("[9] piu' installazioni: elenco per percorso, e scelta quale salvare")
import json  # noqa: E402
import orchestra.dati as dati_mod  # noqa: E402

base = tempfile.mkdtemp(prefix="orch-base-")
prima_inst = os.path.join(base, "aaaa1111")
seconda_inst = os.path.join(base, "bbbb2222")
os.makedirs(prima_inst)
os.makedirs(seconda_inst)
for cartella, percorso in ((prima_inst, r"C:\prova\a"),
                           (seconda_inst, r"D:\orchestra")):
    with open(os.path.join(cartella, "memory.md"), "w", encoding="utf-8") as f:
        f.write("memoria di " + percorso + "\n")
    with open(os.path.join(cartella, dati_mod.SEGNAPOSTO), "w", encoding="utf-8") as f:
        json.dump({"percorso": percorso, "versione": "0.5.90",
                   "creato": "2026-11-01T10:00:00"}, f)

# Rumore accanto alle installazioni: succede davvero. Sotto
# %LOCALAPPDATA%\orchestra ci finiscono una copia del codice, i test e un
# Python — e "Salva tutti" non deve prenderli per installazioni.
rumore_codice = os.path.join(base, "orchestra")
rumore_moduli = os.path.join(base, "node_modules")
os.makedirs(rumore_codice)
os.makedirs(rumore_moduli)
with open(os.path.join(rumore_codice, "budget_global.json"), "w", encoding="utf-8") as f:
    f.write("{}")
with open(os.path.join(rumore_moduli, "x.js"), "w", encoding="utf-8") as f:
    f.write("// nulla")

# Un'installazione vecchia, senza segnaposto: si riconosce dal nome
# esadecimale e dai file di dati.
vecchia_inst = os.path.join(base, "cccc33334444")
os.makedirs(vecchia_inst)
with open(os.path.join(vecchia_inst, "memory.md"), "w", encoding="utf-8") as f:
    f.write("memoria vecchia\n")

# Si sostituiscono le funzioni che scelgono la cartella dati: il test non
# deve poter guardare (e meno che mai scrivere) i dati veri dell'utente.
vecchi = (dati_mod.base_dati, dati_mod.cartella_dati,
          bkp.cartella_dati, bkp.installazioni)
# ORCHESTRA_HOME dice "questa e' l'unica installazione": finche' resta
# impostata (le sezioni precedenti la usano) l'elenco non guarda le
# cartelle sorelle, ed e' giusto cosi'.
home_prima = os.environ.pop("ORCHESTRA_HOME", None)
dati_mod.base_dati = lambda: base
dati_mod.cartella_dati = lambda: seconda_inst
bkp.cartella_dati = dati_mod.cartella_dati
bkp.installazioni = dati_mod.installazioni
try:
    voci = dati_mod.installazioni()
    check("il codice accanto non e' un'installazione",
          all(v["id"] not in ("orchestra", "node_modules") for v in voci),
          str([v["id"] for v in voci]))
    check("un'installazione vecchia senza segnaposto viene riconosciuta",
          any(v["id"] == "cccc33334444" for v in voci),
          str([v["id"] for v in voci]))
    check("la corrente viene per prima",
          voci[0]["corrente"] and voci[0]["dati"] == seconda_inst, str(voci[0]))
    check("trova tre installazioni", len(voci) == 3, str(len(voci)))
    check("il percorso si legge dal segnaposto",
          voci[0]["percorso"] == r"D:\orchestra", voci[0]["percorso"])
    check("l'altra non e' segnata come corrente", not voci[1]["corrente"])
    check("l'elenco misura i dati", voci[0]["file"] >= 1 and voci[0]["byte"] > 0,
          str(voci[0]))

    scelta = bkp.crea("", con_chiavi=False, installazione=r"C:\prova\a")
    check("si sceglie per percorso", scelta["dati"] == prima_inst, scelta["dati"])
    check("l'archivio sta nella cartella di quella installazione",
          scelta["percorso"].startswith(os.path.join(prima_inst, "backup")),
          scelta["percorso"])

    esiti = bkp.crea_tutte(con_chiavi=False)
    check("un archivio per installazione, e nessuna in piu'",
          len(esiti) == 3 and all(e["esito"] == "ok" for e in esiti), str(esiti))

    elenco_archivi = bkp.archivi()
    check("gli archivi si elencano per profilo",
          len(elenco_archivi) >= 4
          and any("D:\\orchestra" in (a.get("profilo") or "")
                  for a in elenco_archivi),
          str([a.get("profilo") for a in elenco_archivi]))

    os.remove(os.path.join(prima_inst, "memory.md"))
    ripristino = bkp.ripristina(scelta["percorso"], con_chiavi=False,
                                installazione=r"C:\prova\a")
    check("si ripristina nell'installazione indicata",
          ripristino["dati"] == prima_inst
          and os.path.isfile(os.path.join(prima_inst, "memory.md")),
          str(ripristino))
    check("il ripristino dice da dove viene l'archivio",
          "prova" in (ripristino.get("da") or ""), ripristino.get("da"))

    try:
        bkp.crea("", con_chiavi=False, installazione="non-esiste")
        check("profilo sconosciuto segnalato", False)
    except bkp.InstallazioneSconosciuta as e:
        check("profilo sconosciuto segnalato", "--elenco" in str(e), str(e))
finally:
    (dati_mod.base_dati, dati_mod.cartella_dati,
     bkp.cartella_dati, bkp.installazioni) = vecchi
    if home_prima is not None:
        os.environ["ORCHESTRA_HOME"] = home_prima

print(f"\n{_conta} check, {len(_falliti)} falliti")
if _falliti:
    print("FALLITI: " + ", ".join(_falliti))
    sys.exit(1)
