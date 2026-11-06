"""L'avvio automatico: la voce deve nominare un programma che esiste.

Il caso che ha motivato questo file, il 6/11/2026: la voce nella chiave Run
c'era, il pannello diceva "attivo", e al login Windows rispondeva "Unable to
create process using 'D:\\orchestra\\tests\\_probe5\\Python\\pythoncore-3.15-64\\
python.exe'". Il comando registrato invocava `py -3`, e su quella macchina il
launcher `py` puntava a un Python sparito. Uno stato che dice "attivo" mentre
l'avvio non parte e' peggio di nessuno stato: chi legge crede di aver finito.

Qui si verifica la forma del comando, non Windows: i controlli sul registro
girano solo dove la chiave esiste davvero.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestra.autostart as as_mod

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


print("\n[1] il comando nomina l'interprete che sta eseguendo Orchestra")
cmd = as_mod._comando()
check("c'e' un -FilePath", "-FilePath" in cmd, cmd[:120])
check("e' sys.executable", as_mod._interprete_registrato(cmd) == sys.executable,
      as_mod._interprete_registrato(cmd) + " vs " + sys.executable)
check("non passa dal launcher py",
      "FilePath 'py'" not in cmd and "-3" not in cmd, cmd[:120])
check("porta con se' la cartella di Orchestra", "-WorkingDirectory" in cmd,
      cmd[:200])
radice = os.path.dirname(os.path.dirname(os.path.abspath(as_mod.__file__)))
check("la cartella e' quella dell'installazione", radice in cmd, radice)
check("avvia il server senza aprire il browser",
      "'--no-browser'" in cmd and "'web'" in cmd, cmd[:200])
check("scrive su un log e su un log d'errore",
      "orchestra.log" in cmd and "orchestra.err.log" in cmd, cmd[:200])

print("\n[2] il percorso si estrae da solo, e un percorso sparito si vede")
finto = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "_probe_autostart", "python.exe")
comando_morto = ("powershell -NoProfile -Command \"Start-Process -FilePath '%s' "
                 "-ArgumentList @('-m','orchestra.cli') -WorkingDirectory '%s'\""
                 % (finto, radice))
check("estrazione del -FilePath",
      as_mod._interprete_registrato(comando_morto) == finto,
      as_mod._interprete_registrato(comando_morto))
check("senza -FilePath non si inventa un percorso",
      as_mod._interprete_registrato("powershell -Command \"niente\"") == "")

# `info()` legge il registro, e il registro qui non si puo' pilotare: la
# regola che decide se una voce e' utilizzabile invece e' pura, e il test
# chiama quella che gira davvero.
def _problema_di(comando):
    return as_mod.problema_del_comando(comando)


check("un interprete sparito e' un problema dichiarato",
      _problema_di(comando_morto).startswith("il programma registrato non esiste piu'"),
      _problema_di(comando_morto))
comando_senza_cartella = ("powershell -Command \"Start-Process -FilePath '%s' "
                          "-ArgumentList @('-m','orchestra.cli')\"" % sys.executable)
check("una voce senza cartella di lavoro e' un problema dichiarato",
      "cartella" in _problema_di(comando_senza_cartella),
      _problema_di(comando_senza_cartella))
check("il comando appena scritto non ha problemi", _problema_di(cmd) == "",
      _problema_di(cmd))

print("\n[3] percorsi con spazi e apostrofi, e cartelle non scrivibili")
# PowerShell chiude le stringhe con l'apice singolo: dentro un percorso
# l'apice va raddoppiato, altrimenti il comando finisce li' e il resto
# diventa spazzatura. Verificato a mano il 6/11/2026 su un percorso vero
# ("Temp\\prova avvio\\o'brien"): senza raddoppio PowerShell risponde
# "Carattere di terminazione mancante", con il raddoppio il file di log
# viene creato e il processo parte.
check("l'apice singolo si raddoppia",
      as_mod._citato(r"C:\una cartella\o'brien") == r"'C:\una cartella\o''brien'",
      as_mod._citato(r"C:\una cartella\o'brien"))
check("gli spazi restano dentro gli apici",
      as_mod._citato(r"C:\una cartella") == r"'C:\una cartella'",
      as_mod._citato(r"C:\una cartella"))
import tempfile
prova = tempfile.mkdtemp()
check("una cartella scrivibile si riconosce", as_mod._scrivibile(prova) is True)
check("una cartella che non esiste non si dichiara scrivibile",
      as_mod._scrivibile(os.path.join(prova, "manca")) is False)
check("la prova non lascia file in giro", os.listdir(prova) == [], str(os.listdir(prova)))
import shutil
shutil.rmtree(prova, ignore_errors=True)
cartella_cmd = as_mod._cartella_lavoro()
check("la cartella di lavoro esiste", os.path.isdir(cartella_cmd), cartella_cmd)
check("e' quella da cui `-m orchestra.cli` trova il pacchetto",
      os.path.isdir(os.path.join(cartella_cmd, "orchestra")), cartella_cmd)
cartella_log = as_mod._cartella_log()
check("la cartella dei log si puo' scrivere", as_mod._scrivibile(cartella_log),
      cartella_log)

print("\n[4] lo stato dice anche perche', e su un altro sistema non mente")
info = as_mod.info()
for campo in ("disponibile", "attivo", "comando", "problema"):
    check("info() ha il campo " + campo, campo in info, str(info))
if as_mod.disponibile():
    check("su Windows la chiave Run e' leggibile",
          isinstance(info["attivo"], bool), str(info))
else:
    check("altrove non e' disponibile", info["disponibile"] is False, str(info))
    check("e non risulta attivo", info["attivo"] is False, str(info))

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
