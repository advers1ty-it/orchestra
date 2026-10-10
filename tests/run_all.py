"""Runner della suite. `python3 tests/run_all.py`

Ordine: offline -> resilienza -> shell -> e2e. I primi tre non chiamano
l'API e devono passare sempre; l'e2e salta da solo se manca la chiave.
"""

import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))

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
    ("shell", "test_shell.py", True),
    ("sicurezza", "test_security.py", True),
    ("sessione", "test_session.py", True),
    ("webapp", "test_webapp.py", True),
    ("webapp-modelli", "test_webapp_models.py", True),
    ("frontend", "test_frontend_split.py", True),
    ("ui", "test_ui.py", True),
    ("istruzioni", "test_istruzioni.py", True),
    ("servizio", "test_servizio_ui.py", True),
    ("servizio-sync", "test_servizio_sync.py", True),
    ("permessi", "test_permessi.py", True),
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

results = []
for name, script, required in SUITES:
    print(f"\n{'='*66}\n>>> {name.upper()}\n{'='*66}")
    r = subprocess.run([sys.executable, os.path.join(HERE, script)],
                       cwd=os.path.dirname(HERE))
    results.append((name, r.returncode, required))

print(f"\n{'='*66}\nRIEPILOGO\n{'='*66}")
failed = []
for name, code, required in results:
    if code == 0:
        print(f"  PASS  {name}")
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
        print(f"  FAIL  {name} (exit {code})")
        failed.append(name)

if failed:
    print(f"\n{len(failed)} suite fallite: {', '.join(failed)}")
    sys.exit(1)
print("\nTutto verde.")