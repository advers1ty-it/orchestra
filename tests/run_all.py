"""Runner della suite. `python3 tests/run_all.py`

Ordine: offline -> resilienza -> shell -> e2e. I primi tre non chiamano
l'API e devono passare sempre; l'e2e salta da solo se manca la chiave.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _esito import (  # noqa: E402
    OK, FALLITO, NON_PARTITO, CRASH, NON_AVVENUTO, esegui,
)
from _sanita import controlla as controlla_import  # noqa: E402
from _server import avvia as avvia_server  # noqa: E402

# I test NON devono toccare la cronologia dell'utente. Ogni test che
# chiama `Session.send()` fa girare il worker, che salva il turno nello
# storico — e lo storico vero è quello dell'app. Risultato: la cronologia
# dell'utente si riempie di conversazioni di test ("lungo", "a", "lento",
# "primo", "booma"...) da cancellare a mano.
#
# Puntiamo ORCHESTRA_HOME su una cartella di test: `storico()` la legge
# come base del DB, così ogni subprocess qui sotto eredita un DB separato.
# Deve stare nell'ambiente PRIMA di lanciare i test — cambiarlo dopo non
# sposta il singleton già creato.
os.environ.setdefault("ORCHESTRA_HOME", os.path.join(HERE, "_dati_test"))
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)

SUITES = [
    ("offline", "test_offline.py", True),
    ("resilienza", "test_resilience.py", True),
    ("orchestrazione", "test_orchestrazione.py", True),
    ("update", "test_update.py", True),
    ("shell", "test_shell.py", True),
    ("sicurezza", "test_security.py", True),
    ("sessione", "test_session.py", True),
    # Dopo lo stop, l'agente deve poter tornare a lavorare. Il flag di
    # cancel restava acceso e ogni tool veniva annullato prima di partire.
    ("cancel-recupero", "test_cancel_recupero.py", True),
    # Un messaggio role="tool" senza tool_call_id rompe il Nous (e altri
    # proxy): 400 "Missing required parameter: 'tool_call_id'". L'agente
    # costruisce due messaggi di sistema (gira_a_vuoto e nudge) senza id:
    # quando finiscono nel payload, la richiesta va in 400 e il modello
    # non si riprende mai. Copre che OGNI messaggio tool ha un id.
    ("nous-tool-call-id", "test_nous_tool_call_id.py", True),
    # Il nudge anti-bocca-vuota: il modello che annuncia il lavoro e chiude
    # senza farlo. Il vocabolario non riconosceva "Faccio le modifiche vere
    # ora" ne' "Prima indago": sette turni di fila a una iterazione, zero
    # tool, esito "risposta_finale". Per l'utente era "risponde a caso".
    ("annuncio-bocca-vuota", "test_annuncio_bocca_vuota.py", True),
    # La memoria che impara da sola. Era il pezzo mancante: l'estrazione
    # dei fatti esisteva ma nessuno la chiamava, e senza un test che
    # copre il "chiama il provider e mette in memoria" il difetto
    # torna silenzioso — come e' tornato una volta.
    ("memoria", "test_memoria.py", True),
    # I progetti: la cartella in cui si scrive, e il riconoscimento
    # dell'intento. Il test copre anche che il tool scriva DENTRO il
    # progetto e non nella cartella di installazione: e' il difetto
    # che un test solo sulla memoria non vedrebbe.
    ("progetti", "test_progetti.py", True),
    ("webapp", "test_webapp.py", True),
    ("webapp-modelli", "test_webapp_models.py", True),
    # Ogni import deve risolvere su un file tracciato: _guard.py ha
    # dimostrato che un file ignorato rompe solo le installazioni.
    ("file-tracciati", "test_file_tracciati.py", True),
    ("frontend", "test_frontend_split.py", True),
    ("ui", "test_ui.py", True),
    ("traccia-modale", "test_traccia_modale.py", True),
    ("istruzioni", "test_istruzioni.py", True),
    ("servizio", "test_servizio_ui.py", True),
    ("servizio-sync", "test_servizio_sync.py", True),
    ("permessi", "test_permessi.py", True),
    ("permessi-persistenza", "test_permessi_persistenza.py", True),
    ("permesso-shell", "test_permesso_shell.py", True),
    ("eventi-bridge", "test_eventi_bridge.py", True),
    ("eventi-client", "test_eventi_client.py", True),
    ("switch-servizio", "test_switch_servizio.py", True),
    ("prezzi", "test_prezzi.py", True),
    ("categorie", "test_categorie.py", True),
    ("allegati", "test_allegati.py", True),
    ("allegato-e2e", "test_allegato_e2e.py", True),
    ("scrizione", "test_scrizione.py", True),
    ("allegato-giro", "test_allegato_giro.py", True),
    ("benchmark", "test_benchmark.py", True),
    ("task-eseguibili", "test_task_eseguibili.py", True),
    ("salva-punteggi", "test_salva_punteggi.py", True),
    ("punteggio", "test_punteggio.py", True),
    ("runner", "test_runner.py", True),
    ("poll-bench", "test_poll_bench.py", True),
    ("base-campionaria", "test_base_campionaria.py", True),
    ("verifica-codice", "test_verifica_codice.py", True),
    ("curva", "test_curva.py", True),
    ("punteggio-unico", "test_punteggio_unico.py", True),
    ("verifica-js", "test_verifica_js.py", True),
    ("confronto", "test_confronto.py", True),
    ("rate-limit", "test_rate_limit.py", True),
    ("decisions-schema", "test_decisions_schema.py", False),
    ("curva5", "test_curva5.py", True),
    ("skills", "test_skills.py", True),
    ("skill-tools", "test_skill_tools.py", True),
    # Era scritto e non girava: nel runner non c'era, e senza un
    # test che passa sembra che copra quello che copre.
    ("skill-ui", "test_skill_ui.py", True),
    ("bench-fermo", "test_bench_fermo.py", True),
    ("task-leggibili", "test_task_leggibili.py", True),
    ("tool-etichetta", "test_tool_etichetta.py", True),
    ("lista-provider", "test_lista_provider.py", True),
    ("e2e", "test_e2e.py", False),
]

# --------------------------------------------------------------------------
# Controllo di sanità: ogni modulo di test deve poter essere importato.
#
# Non e' la stessa cosa che eseguire i test: qui non si esegue niente, si
# guarda solo che i nomi che il file chiede esistano. Ma e' esattamente il
# controllo che separa "il test e' rosso" da "il test non e' mai partito",
# e senza, una suite che muore all'import si confonde con una che ha
# trovato un difetto.
#
# Prima di tutto questo, ogni test che importa un modulo spostato o
# riscritto viene fuori con ModuleNotFoundError, e la suite viene
# contata come fallita. Il guaio e' che un fallimento in mezzo a ottanta
# suite verdi si guarda e si dimentica: e' successo quattro volte, tutte
# per lo stesso motivo (un modulo spostato, l'import rimasto indietro).
#
# Qui l'import rotto e' un fallimento SUO, detto per nome, prima ancora
# di eseguire un solo test.
# --------------------------------------------------------------------------
print("=" * 66)
print("CONTROLLO DI SANITA': ogni modulo di test deve importare")
print("=" * 66)
rotte = controlla_import(HERE)
if rotte:
    for nome, riga, modulo in rotte:
        print(f"  ROTTO  {nome}:{riga} — '{modulo}' non esiste")
    print(f"\n{len(rotte)} modulo/i di test non importano.")
    print("Sono suite che non girano: il codice che coprono non e' verificato.")
    print("Un test che non parte non e' un test rosso, e' un test ASSENTE.\n")
else:
    print("  OK  tutti i moduli di test importano\n")

results = []
# --------------------------------------------------------------------------
# IL SERVER DI TEST
# --------------------------------------------------------------------------
# Le suite che parlano col server vero hanno bisogno che qualcosa
# risponda. Prima dipendevano dal server di sviluppo che stava gia'
# acceso sulla 8737, e se non c'era fallivano con "connessione rifiutata",
# che sembrava un difetto del codice. Se invece c'era ma con un turno
# aperto, fallivano con 409 — "occupato" — che e' un'altra cosa, e
# sembrava un difetto ancora piu' strano.
#
# Nessuna delle due versioni era giusta, perche' in entrambi i casi il
# test segnalava un difetto che non c'era. Un test che segnala difetti
# inesistenti e' peggio di un test assente: fa perdere tempo a guardarli.
#
# Qui il server parte da solo, su una porta libera, e la porta la dice
# l'ambiente (ORCHESTRA_TEST_PORT). Ogni suite la legge. Se il server non
# parte, lo si dice e le suite HTTP non girano: ma lo si dice PRIMA,
# non sotto forma di un fallback di connettivita' mascherato da test.
# --------------------------------------------------------------------------
server, motivo = avvia_server()
if server is None:
    print(f"  ATTENZIONE: il server di test non e' partito — {motivo}")
    print("  Le suite HTTP non potranno girare: i loro fallimenti "
          "non saranno verdi.\n")
else:
    print(f"  server di test su {server.porta} "
          f"(home: {server.home})\n")

ambiente = dict(os.environ)
if server is not None:
    ambiente["ORCHESTRA_TEST_PORT"] = str(server.porta)

try:
    for name, script, required in SUITES:
        print(f"\n{'='*66}\n>>> {name.upper()}\n{'='*66}")
        esito = esegui(os.path.join(HERE, script), cwd=os.path.dirname(HERE),
                       env=ambiente)
        # L'output del test si rivede: e' la prova, non un riassunto.
        sys.stdout.write(esito.stdout or "")
        if esito.stderr:
            sys.stderr.write(esito.stderr)
        esito.nome = name
        results.append((name, esito, required))
finally:
    # Il server si chiude SEMPRE: anche se una suite e' morta, o se il
    # runner viene fermato. Un server lasciato vivo occupa la porta e
    # fa fallire la corsa successiva per un motivo che non c'entra.
    if server is not None:
        server.chiudi()

print(f"\n{'='*66}\nRIEPILOGO\n{'='*66}")
failed = []
mai_partiti = []
crashati = []
non_avvenuti = []
for name, esito, required in results:
    if esito.stato == OK:
        print(f"  PASS  {name}")
    elif esito.stato == NON_AVVENUTO:
        # La corsa non e' stata possibile: l'API esterna non ha
        # risposto. Non e' un verdetto sul codice, e ne' un difetto:
        # e' la rete. Ma non e' nemmeno un passaggio, e dirlo come
        # PASS sarebbe mentire.
        print(f"  NON AVVENUTO  {name} — {esito.dettaglio}")
        non_avvenuti.append(name)
    elif esito.stato == NON_PARTITO:
        # MAI PARTITO e' un fallimento, ma uno diverso: non c'e' nessun
        # verdetto sul codice, c'e' solo il fatto che il codice non e'
        # stato eseguito. Dillo per nome, cosi' non si confonde con un
        # test che ha trovato un difetto.
        print(f"  MAI PARTITO  {name} — {esito.dettaglio}")
        mai_partiti.append(name)
        failed.append(name)
    elif esito.stato == CRASH:
        print(f"  CRASH  {name} — {esito.dettaglio}")
        crashati.append(name)
        failed.append(name)
    else:
        # Un exit non-zero e' un fallimento, sempre. Prima c'era un
        # ramo che riportava come "SKIP" qualunque errore di una suite
        # marcata come non obbligatoria, e il riepilogo diceva "Tutto
        # verde" con l'e2e partito, fallito, e contato come saltato.
        #
        # Il caso "non posso girare" e' gia' diverso: le suite escono
        # con 0 quando non possono fare il loro lavoro (manca la
        # chiave, per esempio). Quindi l'informazione "opzionale" non
        # serve qui dentro — e tenere un interruttore "i fallimenti non
        # contano" in un runner e' il modo piu' rapido per non accorgersi
        # che qualcosa si e' rotto.
        print(f"  FAIL  {name} (exit {esito.codice})")
        if esito.dettaglio:
            print(f"        {esito.dettaglio}")
        failed.append(name)

if mai_partiti:
    print(f"\n{len(mai_partiti)} suite non sono mai partite: "
          f"{', '.join(mai_partiti)}")
    print("Il codice che coprono NON e' stato eseguito. Non e' un difetto")
    print("del codice testato: e' un test che non esiste.")
if crashati:
    print(f"\n{len(crashati)} suite sono morte con un'eccezione: "
          f"{', '.join(crashati)}")
    print("Non hanno dato nessun verdetto: nessuna asserzione e' arrivata in fondo.")
if non_avvenuti:
    # La concordanza: "una suite non e' potuta avvenire", "due suite non
    # sono potute avvenire". Il numero davanti a "suite" non basta da
    # solo, e un messaggio con l'accordo sbagliato fa sospettare un
    # altro bug in un testo che dovrebbe essere l'ultima riga.
    _n = len(non_avvenuti)
    _verb = "non e' potuta avvenire" if _n == 1 else "non sono potute avvenire"
    print(f"\n{_n} suite {_verb}: {', '.join(non_avvenuti)}")
    print("Parlano con un'API esterna che non ha risposto. Non e' un difetto")
    print("del codice, ma non e' nemmeno una verifica: la copertura di")
    print("quelle zone resta da fare.")
if rotte:
    print(f"\nInoltre {len(rotte)} modulo/i di test non importano (vedi sopra).")

if failed:
    print(f"\n{len(failed)} suite fallite: {', '.join(failed)}")
    sys.exit(1)
if non_avvenuti:
    # Non fallisce il runner: la corsa non e' stata possibile per la
    # rete, e far fallire tutto per quello significa che il rumore
    # impedisce di vedere i difetti veri. Ma non si dice "Tutto verde":
    # non lo e'. Si dice quello che e' vero.
    print("\nNessuna suite e' fallita, ma qualcosa non e' stato verificato.")
    sys.exit(0)
print("\nTutto verde.")
