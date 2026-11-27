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
radice = os.path.dirname(os.path.dirname(os.path.abspath(as_mod.__file__)))
if as_mod.LINUX:
    check("c'e' il launcher o il modulo",
          "Avvia-Orchestra.sh" in cmd or "orchestra.cli" in cmd, cmd[:160])
    check("non passa da PowerShell", "-FilePath" not in cmd, cmd[:120])
    check("non apre il browser al login", "--no-browser" in cmd, cmd[:160])
    check("la cartella e' quella dell'installazione", radice in cmd, cmd[:160])
    check("estrae il programma dal comando Linux",
          as_mod._programma_linux(cmd) != "", cmd[:160])
else:
    check("c'e' un -FilePath", "-FilePath" in cmd, cmd[:120])
    check("e' sys.executable", as_mod._interprete_registrato(cmd) == sys.executable,
          as_mod._interprete_registrato(cmd) + " vs " + sys.executable)
    check("non passa dal launcher py",
          "FilePath 'py'" not in cmd and "-3" not in cmd, cmd[:120])
    check("porta con se' la cartella di Orchestra", "-WorkingDirectory" in cmd,
          cmd[:200])
    check("la cartella e' quella dell'installazione", radice in cmd, radice)
    check("avvia il server senza aprire il browser",
          "'--no-browser'" in cmd and "'web'" in cmd, cmd[:200])
    check("scrive su un log e su un log d'errore",
          "orchestra.log" in cmd and "orchestra.err.log" in cmd, cmd[:200])

print("\n[2] il percorso si estrae da solo, e un percorso sparito si vede")
def _problema_di(comando):
    return as_mod.problema_del_comando(comando)

if as_mod.WINDOWS:
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
    check("un interprete sparito e' un problema dichiarato",
          _problema_di(comando_morto).startswith("il programma registrato non esiste piu'"),
          _problema_di(comando_morto))
    comando_senza_cartella = ("powershell -Command \"Start-Process -FilePath '%s' "
                              "-ArgumentList @('-m','orchestra.cli')\"" % sys.executable)
    check("una voce senza cartella di lavoro e' un problema dichiarato",
          "cartella" in _problema_di(comando_senza_cartella),
          _problema_di(comando_senza_cartella))
else:
    check("estrae il programma dal comando Linux",
          bool(as_mod._programma_linux(cmd)), cmd[:160])
    check("un programma sparito e' un problema dichiarato",
          _problema_di('env "%s" -m orchestra.cli web' % os.path.join(radice, "sparito")).startswith("il programma registrato non esiste piu'"),
          _problema_di('env "%s" -m orchestra.cli web' % os.path.join(radice, "sparito")))

check("il comando appena scritto non ha problemi", _problema_di(cmd) == "",
      _problema_di(cmd))

print("\n[3] percorsi con spazi e apostrofi, e cartelle non scrivibili")
if as_mod.WINDOWS:
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
if as_mod.WINDOWS:
    check("su Windows la chiave Run e' leggibile",
          isinstance(info["attivo"], bool), str(info))
elif as_mod.LINUX:
    check("su Linux l'avvio automatico e' disponibile",
          info["disponibile"] is True, str(info))
    # Si prova la scrittura su una configurazione temporanea: il test non
    # deve lasciare un autostart vero nella home di chi lo esegue.
    vecchio_xdg = os.environ.get("XDG_CONFIG_HOME")
    tmp_xdg = tempfile.mkdtemp(prefix="orch_autostart_")
    os.environ["XDG_CONFIG_HOME"] = tmp_xdg
    try:
        check("abilita scrive il file .desktop", as_mod.abilita() is True)
        check("il file esiste", os.path.isfile(as_mod._linux_file()),
              as_mod._linux_file())
        acceso = as_mod.info()
        check("risulta attivo", acceso["attivo"] is True, str(acceso))
        check("e non ha problemi", acceso["problema"] == "", str(acceso))
        check("disabilita lo rimuove", as_mod.disabilita() is True)
        check("non risulta piu' attivo", as_mod.info()["attivo"] is False)
    finally:
        if vecchio_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = vecchio_xdg
        shutil.rmtree(tmp_xdg, ignore_errors=True)
else:
    check("altrove non e' disponibile", info["disponibile"] is False, str(info))
    check("e non risulta attivo", info["attivo"] is False, str(info))

print("\n" + "=" * 60)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
