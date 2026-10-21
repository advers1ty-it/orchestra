"""Controllo di sanità: ogni modulo di test deve poter importare.

Non è la stessa cosa che eseguire i test: qui non si esegue niente, si
guarda solo che i nomi che il file chiede esistano. E' esattamente il
controllo che separa "il test è rosso" da "il test non è mai partito".

Prima di tutto questo, ogni test che importa un modulo spostato o
riscritto veniva fuori con ModuleNotFoundError, e la suite veniva
contata come fallita. Il guaio è che un fallimento in mezzo a ottanta
suite verdi si guarda e si dimentica: è successo quattro volte, tutte
per lo stesso motivo (un modulo spostato, l'import rimasto indietro).

Qui l'import rotto è un fallimento SUO, detto per nome, prima ancora di
eseguire un solo test.

PERCHE' IL PARSING E NON L'IMPORT
---------------------------------
L'alternativa sarebbe importare ogni modulo di test in un subprocess e
guardare se muore. Non va bene: alcuni test all'import avviano un server,
scrivono su disco, o parlano con l'esterno. Importarli per controllarli
significa eseguirli — e un controllo che esegue la cosa che dovrebbe
controllare è una fonte di falsi positivi e di effetti collaterali.

Il parsing statico risponde alla domanda giusta: "i nomi che questo
file chiede esistono davvero?". Non esegue niente, non tocca niente, e
non puo' mentire su niente.

LA DISTINZIONE CHE FA LA DIFFERENZA
------------------------------------
"from orchestra import LLMResponse" e "from orchestra import skill_tools"
sono la stessa forma, ma chiedono cose diverse:

  - LLMResponse e' un NOME ESPORTO da orchestra/__init__.py
  - skill_tools e' un MODULO, cioe' orchestra/skill_tools.py

Se si cercano solo un file chiamata come il nome, si sbaglia in due
modi opposti: si segnala come rotto tutto quello che e' un attributo
(LLMResponse, default_registry, LoopConfig — quasi tutti i test), e non
si vede il modulo spostato, che e' il caso vero. Il primo errore
falsifica tutto il controllo: 43 falsi positivi e zero difetti veri.
"""

import ast
import os

# Dove sta il codice importabile. Il progetto sta nella cartella sopra
# i test: i test sono in tests/, il codice in orchestra/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Il pacchetto radice dei moduli controllati.
MODULI = "orchestra"


def _percorso(modulo):
    return os.path.join(ROOT, *modulo.split("."))


def _e_modulo(modulo):
    """Il modulo esiste come file .py?"""
    return os.path.isfile(_percorso(modulo) + ".py")


def _e_pacchetto(modulo):
    """Il modulo esiste come cartella (package o namespace package)?"""
    p = _percorso(modulo)
    if not os.path.isdir(p):
        return False
    if os.path.isfile(os.path.join(p, "__init__.py")):
        return True
    # Namespace package: vale come modulo, se c'e' qualcosa dentro.
    return bool(os.listdir(p))


def _esiste(modulo):
    return _e_modulo(modulo) or _e_pacchetto(modulo)


def _nomi_esportati(modulo):
    """I nomi che un modulo mette a disposizione con "from m import x".

    Si leggono dal sorgente: funzioni, classi, variabili assegnate e
    nomi importati. Non si esegue il modulo — un import può avere
    effetti, e qui non si vuole nessun effetto.

    Un pacchetto espone i nomi del suo __init__.py; un modulo semplice
    espone i propri.
    """
    if _e_pacchetto(modulo):
        init = os.path.join(_percorso(modulo), "__init__.py")
        if not os.path.isfile(init):
            # Namespace package: espone i suoi sottomoduli, nient'altro.
            return None
        return _nomi_del_file(init)
    if _e_modulo(modulo):
        return _nomi_del_file(_percorso(modulo) + ".py")
    return set()


def _nomi_del_file(percorso):
    """I nomi di primo livello definiti in un file Python."""
    nomi = set()
    try:
        with open(percorso, encoding="utf-8") as f:
            albero = ast.parse(f.read(), filename=percorso)
    except (OSError, SyntaxError):
        return nomi
    for nodo in albero.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            nomi.add(nodo.name)
        elif isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if isinstance(t, ast.Name):
                    nomi.add(t.id)
        elif isinstance(nodo, ast.AnnAssign):
            if isinstance(nodo.target, ast.Name):
                nomi.add(nodo.target.id)
        elif isinstance(nodo, ast.Import):
            for alias in nodo.names:
                nomi.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(nodo, ast.ImportFrom):
            for alias in nodo.names:
                nomi.add(alias.asname or alias.name)
    return nomi


def _import_rotto(albero):
    """Gli import di un file che non risolvono, con la riga."""
    rotte = []
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Import):
            # "import orchestra.a.b" vuol dire orchestra/a/b.py (o un
            # pacchetto omonimo). "import orchestra.a" vuol dire il
            # pacchetto orchestra/a/.
            for alias in nodo.names:
                nome = alias.name
                if not nome.startswith(MODULI):
                    continue
                if not _esiste(nome):
                    rotte.append((nodo.lineno, nome))
        elif isinstance(nodo, ast.ImportFrom):
            modulo = nodo.module or ""
            if not modulo.startswith(MODULI):
                continue
            if not _esiste(modulo):
                rotte.append((nodo.lineno, modulo))
                continue
            # "from orchestra import X": X puo' essere un attributo
            # esportato da orchestra/__init__.py, OPPURE un sottomodulo
            # (orchestra/X.py). "from orchestra.tools import skill":
            # skill puo' essere orchestra/tools/skill.py, OPPURE un
            # attributo di orchestra/tools/__init__.py.
            esportati = _nomi_esportati(modulo)
            for alias in nodo.names:
                if alias.name == "*":
                    continue
                nome = alias.name
                # attributo del pacchetto o del modulo?
                if esportati is not None and nome in esportati:
                    continue
                # sottomodulo?
                if _esiste(f"{modulo}.{nome}"):
                    continue
                rotte.append((nodo.lineno, f"{modulo}.{nome}"))
    return rotte


def controlla(tests_dir):
    """Controlla ogni file di test. Ritorna [(file, riga, modulo), ...]."""
    rotte = []
    for nome in sorted(os.listdir(tests_dir)):
        if not (nome.startswith("test_") and nome.endswith(".py")):
            continue
        percorso = os.path.join(tests_dir, nome)
        try:
            with open(percorso, encoding="utf-8") as f:
                albero = ast.parse(f.read(), filename=percorso)
        except SyntaxError as e:
            rotte.append((nome, e.lineno or 0, f"SyntaxError: {e.msg}"))
            continue
        for riga, modulo in _import_rotto(albero):
            rotte.append((nome, riga, modulo))
    return rotte
