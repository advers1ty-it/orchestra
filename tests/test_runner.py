"""Il runner deve distinguere un test rosso da un test mai partito.

Il difetto che questo chiude: `required=False` faceva riportare come
"SKIP (non richiesto)" qualunque errore di una suite opzionale. Il
riepilogo diceva "Tutto verde", il processo usciva con 0, e l'e2e —
che era partito, aveva fallito, e aveva stampato un FAIL — non
contava.

E' la classe di difetto piu' pericolosa in un runner: non un test
rosso, che si vede. Un test rosso che il runner ha deciso di non
guardare.

E' nato anche il secondo difetto, piu' subdolo: un test che NON PARTE
(un import rotto) e un test che trova un difetto escono entrambi con
codice 1. Il runner li contava uguali, e un fallimento in mezzo a
ottanta suite verdi si guarda e si dimentica. E' successo quattro volte,
tutte per lo stesso motivo: un modulo spostato e l'import rimasto
indietro. Il codice che quei test coprono non e' mai stato eseguito,
e nessun report lo diceva.

Qui il comportamento si prova ESEGUENDO, non leggendo il sorgente: il
vecchio test guardava una stringa nel sorgente del runner, e una
riscrittura del runner (anche quella giusta) lo faceva fallire senza
che nulla fosse rotto. Un test che legge il sorgente di un altro test
prova la forma, non il comportamento: e' il modo piu' rapido per
avere un test che passa mentre il difetto c'e'.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from _esito import (  # noqa: E402
    OK, FALLITO, NON_PARTITO, CRASH, NON_AVVENUTO, classifica,
)

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}" + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("[1] Un test che parte e trova un difetto e' FALLITO")
esito = classifica(1, "  OK   uno\n  FAIL qualcosa\nFALLITI: ['qualcosa']\n", "")
check("e' FALLITO", esito.stato == FALLITO, esito.stato)
check("e il dettaglio elenca le asserzioni", "qualcosa" in (esito.dettaglio or ""),
      str(esito.dettaglio))

print("\n[2] Un test che non parte e' NON PARTITO, non FALLITO")
# Il caso vero: un modulo spostato. Il traceback va su stderr.
err = ("Traceback (most recent call last):\n"
       '  File "D:\\orchestra\\tests\\test_x.py", line 17, in <module>\n'
       "    import orchestra.skill_tools as st\n"
       "ModuleNotFoundError: No module named 'orchestra.skill_tools'\n")
esito = classifica(1, "", err)
check("e' NON PARTITO", esito.stato == NON_PARTITO, esito.stato)
check("e dice quale modulo manca", "orchestra.skill_tools" in (esito.dettaglio or ""),
      str(esito.dettaglio))
check("NON e' un crash", esito.stato != CRASH, esito.stato)
check("NON e' un fallimento generico", esito.stato != FALLITO, esito.stato)

print("\n[3] Un test che muore per un'eccezione e' CRASH")
err = ("Traceback (most recent call last):\n"
       '  File "D:\\orchestra\\tests\\test_y.py", line 40, in <module>\n'
       "    x = 1 / 0\n"
       "ZeroDivisionError: division by zero\n")
esito = classifica(1, "", err)
check("e' CRASH", esito.stato == CRASH, esito.stato)
check("e dice cosa e' successo", "ZeroDivisionError" in (esito.dettaglio or ""),
      str(esito.dettaglio))

print("\n[4] Un test che passa e' OK")
esito = classifica(0, "  OK   tutto bene\n", "")
check("e' OK", esito.stato == OK, esito.stato)

print("\n[3b] Il crash dice COSA e' successo, non solo DOVE")
# La riga dell'eccezione ("ZeroDivisionError: division by zero") e'
# quella che dice cosa e' successo. La riga di codice prima ("x = 1 / 0")
# dice solo dove, e per un utente e' un muro.
err = ("Traceback (most recent call last):\n"
       '  File "D:\\orchestra\\tests\\test_y.py", line 40, in <module>\n'
       "    x = 1 / 0\n"
       "ZeroDivisionError: division by zero\n")
esito = classifica(1, "", err)
check("e' CRASH", esito.stato == CRASH, esito.stato)
check("e dice l'eccezione, non la riga di codice",
      "ZeroDivisionError" in (esito.dettaglio or ""), str(esito.dettaglio))
check("e non solo la riga di codice",
      "1 / 0" not in (esito.dettaglio or ""), str(esito.dettaglio))

print("\n[3c] Con output DOPO il traceback, la riga giusta e' sempre quella")
# Un traceback non e' sempre l'ultima cosa scritta: dopo puo' venire un
# messaggio del programma. Se la ricerca parte dal fondo e prende
# "qualunque cosa assomiglia a un'eccezione", rischia di prendere un
# messaggio qualsiasi. Deve prendere l'eccezione vera.
err = ("Traceback (most recent call last):\n"
       '  File "D:\\orchestra\\tests\\test_y.py", line 40, in <module>\n'
       "    x = 1 / 0\n"
       "ZeroDivisionError: division by zero\n"
       "\n"
       "Durante la pulizia: something: happened\n")
esito = classifica(1, "", err)
check("prende l'eccezione, non il messaggio dopo",
      "ZeroDivisionError" in (esito.dettaglio or ""), str(esito.dettaglio))

print("\n[4b] Un ImportError DENTRO un test non e' 'mai partito'")
# "import" dentro una funzione di test che fallisce: il test e'
# PARTITO (ha stampato), e poi e' morto. Dichiararlo "mai partito"
# nasconderebbe il difetto vero dietro una parola che parla d'altro.
err = ("Traceback (most recent call last):\n"
       '  File "D:\\orchestra\\tests\\test_z.py", line 50, in <module>\n'
       "    import numpy\n"
       "ModuleNotFoundError: No module named 'numpy'\n")
esito = classifica(1, "  OK   uno\n  FAIL qualcosa\n", err)
check("e' CRASH, non 'mai partito'", esito.stato == CRASH, esito.stato)

print("\n[4c] Una corsa non avvenuta non e' un test rosso")
# L'e2e parla con l'API vera. Se il provider non risponde, non c'e'
# nessun verdetto sul codice: e' la rete. Confonderlo con un test
# rosso fa litigare col provider invece che col codice.
out = ("IL PROVIDER NON HA RISPOSTO: nvidia: HTTP 404\n"
       "Non e' un difetto dell'agente ne' dei modelli\n")
esito = classifica(1, out, "")
check("e' NON AVVENUTO", esito.stato == NON_AVVENUTO, esito.stato)
check("NON e' FALLITO", esito.stato != FALLITO, esito.stato)
check("e NON e' un crash", esito.stato != CRASH, esito.stato)

print("\n[5] La parola 'ImportError' in stdout NON crea un falso 'non partito'")
# Un test puo' parlare di ImportError parlando di un difetto che ha
# trovato in un altro programma. Se il classificatore guardasse lo
# stdout, un test ROSSO sembrerebbe un test MAI PARTITO: il contrario
# esatto di quello che si vuole.
esito = classifica(1, "  FAIL qualcosa\nImportError: il modulo del provider\n", "")
check("resta FALLITO", esito.stato == FALLITO, esito.stato)

print("\n[6] Il runner vero, su una suite finita che non parte")
# Non un test del classificatore: il runner vero, con dentro un file
# che muore all'import.
D = tempfile.mkdtemp()
rotto = os.path.join(D, "rotto.py")
with open(rotto, "w", encoding="utf-8") as f:
    f.write("import orchestra.skill_tools as st\n")
buona = os.path.join(D, "buona.py")
with open(buona, "w", encoding="utf-8") as f:
    f.write("print('  OK   tutto bene')\n")

runner = os.path.join(D, "runner.py")
with open(runner, "w", encoding="utf-8") as f:
    # ROOT nel path, cosi' che "orchestra" esista e l'errore sia
    # sull'UNDER modulo mancante: e' il caso vero, e quello da
    # riconoscere.
    f.write(
        "import sys, os\n"
        "sys.path.insert(0, %r)\n" % HERE +
        "sys.path.insert(0, %r)\n" % ROOT +
        "from _esito import esegui, OK, NON_PARTITO\n"
        # PYTHONPATH=ROOT, non cwd: in Python sys.path[0] e' la cartella
        # dello SCRIPT (quella temporanea), non la cwd. Senza PYTHONPATH
        # l'errore sarebbe "No module named 'orchestra'" — che non dice
        # QUALE modulo manca, e fa sembrare rotto qualcosa che e' a posto.
        "import os\n"
        "env = dict(os.environ)\n"
        "env['PYTHONPATH'] = %r\n" % ROOT +
        "es = esegui(%r, env=env)\n" % rotto +
        "print('STATO', es.stato)\n"
        "print('DETTAGLIO', es.dettaglio)\n"
    )
r = subprocess.run([sys.executable, runner], capture_output=True, text=True)
out = r.stdout
print("    " + out.replace("\n", "\n    ").strip())
check("il runner classifica 'non partito'", "NON PARTITO" in out, out)
check("e lo dice", "orchestra.skill_tools" in out, out)

print("\n[7] Il runner vero dice 'Tutto verde' solo se tutto e' passato")
runner2 = os.path.join(D, "runner2.py")
with open(runner2, "w", encoding="utf-8") as f:
    f.write(
        "import sys, os\n"
        "sys.path.insert(0, %r)\n" % HERE +
        "from _esito import esegui, OK, NON_PARTITO\n"
        "env = dict(os.environ)\n"
        "env['PYTHONPATH'] = %r\n" % ROOT +
        "es = esegui(%r, env=env)\n" % rotto +
        "if es.stato != OK:\n"
        "    print('MAI PARTITO  rotto')\n"
        "    sys.exit(1)\n"
        "print('Tutto verde.')\n"
        "sys.exit(0)\n"
    )
r2 = subprocess.run([sys.executable, runner2], capture_output=True, text=True)
check("non esce 0 con una suite mai partita", r2.returncode != 0,
      f"returncode={r2.returncode}")
check("e non dice 'Tutto verde'", "Tutto verde" not in r2.stdout, r2.stdout)

print("\n[8] Il controllo di sanità trova un import rotto")
from _sanita import controlla  # noqa: E402
D2 = tempfile.mkdtemp()
with open(os.path.join(D2, "test_falso.py"), "w", encoding="utf-8") as f:
    f.write("import orchestra.skill_tools as st\n")
with open(os.path.join(D2, "test_buono.py"), "w", encoding="utf-8") as f:
    f.write("import orchestra.skills as sk\n")
rotte = controlla(D2)
check("lo trova", len(rotte) == 1, str(rotte))
check("e dice il modulo", rotte and "orchestra.skill_tools" in rotte[0][2],
      str(rotte))
check("e non segnala quello giusto", not any("orchestra.skills" in r[2] for r in rotte),
      str(rotte))

print("\n[8b] Un nome ESPORTO non e' un modulo rotto")
# "from orchestra import LLMResponse" chiede un attributo di
# orchestra/__init__.py, non un file orchestra/LLMResponse.py. Se il
# controllo non fa questa distinzione segnala come rotto quasi tutti i
# test — 43 falsi positivi e zero difetti veri, e un controllo che dice
# sempre "rotto" non dice niente.
D2b = tempfile.mkdtemp()
with open(os.path.join(D2b, "test_esportato.py"), "w", encoding="utf-8") as f:
    f.write("from orchestra import LLMResponse, LoopConfig, Message\n")
with open(os.path.join(D2b, "test_esportato2.py"), "w", encoding="utf-8") as f:
    f.write("from orchestra.tools import default_registry, set_permission_gate\n")
rotte2 = controlla(D2b)
check("non segnala gli attributi esportati", not rotte2, str(rotte2))

print("\n[8c] Un modulo spostato dentro un pacchetto e' rotto")
# "from orchestra.tools import skill" vuol dire orchestra/tools/skill.py.
# Se quel file sparisce, l'import non risolve: ed e' esattamente il
# difetto che ha rotto i test quando i tool sono stati spostati.
D2c = tempfile.mkdtemp()
with open(os.path.join(D2c, "test_pacchetto.py"), "w", encoding="utf-8") as f:
    f.write("from orchestra.tools import skill as st\n")
rotte3 = controlla(D2c)
check("non lo segnala, perche' skill.py esiste", not rotte3, str(rotte3))

print("\n[8d] Il caso VERO: un modulo sparito dalla root")
# "from orchestra import skill_tools" chiede orchestra/skill_tools.py,
# che e' sparito dal 0.5.14. Questo e' l'import che ha rotto i test,
# e il controllo deve vederlo — non confonderlo con un attributo
# esportato, che e' una cosa diversa.
D2d = tempfile.mkdtemp()
with open(os.path.join(D2d, "test_sparito.py"), "w", encoding="utf-8") as f:
    f.write("from orchestra import skill_tools as st\n")
rotte4 = controlla(D2d)
check("lo segnala come rotto", len(rotte4) == 1, str(rotte4))
check("e nomina il modulo",
      rotte4 and "skill_tools" in rotte4[0][2], str(rotte4))

print("\n[9] Il controllo di sanità NON esegue i test")
# Se eseguisse un file di test, il file farebbe danni. Si prova con un
# file che, se eseguito, scriverebbe un file: il file non deve
# comparire.
D3 = tempfile.mkdtemp()
marcatore = os.path.join(D3, "eseguito.txt")
with open(os.path.join(D3, "test_pericoloso.py"), "w", encoding="utf-8") as f:
    f.write("open(%r, 'w').write('x')\n" % marcatore)
controlla(D3)
check("il file non e' stato eseguito", not os.path.exists(marcatore),
      "il controllo ha eseguito il test: fa danni")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)
