import io

P = "orchestra/webapp.py"
s = io.open(P, encoding="utf-8").read()

# Estraggo il blocco. Stava dentro il handler POST del benchmark,
# a hundred righe dal begin, e nessun test lo poteva raggiungere: la
# variabile `cat` del ciclo copriva il catalogo, e niente se n'e'
# accorto perche' il codice non e' mai stato eseguito in un test.
#
# Un blocco che nessun test puo' chiamare e' un blocco che non viene
# eseguito finche' qualcuno lo esegue a mano — e l'unico che lo fa e'
# l'utente, con un modello vero, dopo tre minuti di benchmark.
vecchio = '''                summary = summarize(results)
                # by_category[cat] e' un dizionario — score, passati,
                # quanti — non un numero. Qui era rimasto il confronto
                # col vecchio formato, e il benchmark si interrompeva
                # con "TypeError: '>' not supported between instances of
                # 'dict' and 'int'" DOPO aver eseguito tutti i task:
                # le misurazioni erano fatte, il punteggio no, e la
                # lista restava quella di prima. Un errore che arriva
                # alla fine di un lavoro di tre minuti e butta via tutto.
                for mid, data in summary["per_model"].items():
                    prof = cat.models.get(mid)
                    if not prof:
                        continue
                    prof.scores = {}
                    prof.frazioni = {}
                    prof.task_per_cat = {}
                    # "categoria", non "cat": in questa funzione `cat`
                    # e' il catalogo dei modelli, e dichiarare una
                    # variabile locale con lo stesso nome la rende
                    # locale per TUTTO il corpo — anche per le righe
                    # precedenti. Il risultato era
                    # "UnboundLocalError: cannot access local variable
                    # 'cat'" su `cat.models`, che e' la prima riga di
                    # questo blocco.
                    #
                    # Il nome diceva gia' due cose diverse: un
                    # catalogo di modelli e una categoria di task. Due
                    # cose con un nome solo e' la definizione di un
                    # bug che aspetta.
                    for categoria, d in (data.get("by_category") or {}).items():
                        v = d.get("score", 0) if isinstance(d, dict) else d
                        if v > 0:
                            prof.scores[categoria] = v
                        if isinstance(d, dict):
                            prof.frazioni[categoria] = d.get("passati", 0)
                            prof.task_per_cat[categoria] = d.get("quanti", 0)
                    prof.last_measured = time.time()
                try:''')

nuovo = '''                summary = summarize(results)
                # salvatug() scrive i punteggi sul catalogo. Sta in
                # una funzione perche' qui dentro non era
                # raggiungibile da nessun test: e' il posto dove due
                # bug hanno vissuto senza essere visti.
                salva_punteggi(cat, summary)
                try:'''

assert vecchio in s, "il blocco da estrarre non trovato"
s = s.replace(vecchio, nuovo, 1)

# la funzione, a livello di modulo
m = '''def _skill_elenco(indice) -> dict[str, Any]:'''
nuova_f = '''def salva_punteggi(cat, summary: dict[str, Any]) -> int:
    """Scrive i punteggi misurati sul catalogo. Ritorna quanti modelli.

    `by_category[categoria]` e' un dizionario — score, passati, quanti —
    e non un numero. Prima del campo della frazione era un numero, e
    due posti si erano messi a fare `v > 0` su un dizionario: il primo
    crashava il benchmark DOPO tutti i task, il secondo lasciava
    `cat` — che e' il catalogo — sovrascritto dalla categoria del
    ciclo, e il terzo turno lanciava
    "UnboundLocalError: cannot access local variable 'cat'".

    Tre sintomi diversi, una causa sola: il formato e' cambiato e non
    si e' cercato chi lo leggeva.
    """
    if cat is None:
        return 0
    n = 0
    for mid, data in (summary.get("per_model") or {}).items():
        prof = cat.models.get(mid)
        if not prof:
            continue
        prof.scores = {}
        prof.frazioni = {}
        prof.task_per_cat = {}
        for categoria, d in (data.get("by_category") or {}).items():
            v = d.get("score", 0) if isinstance(d, dict) else d
            if v > 0:
                prof.scores[categoria] = v
            if isinstance(d, dict):
                prof.frazioni[categoria] = d.get("passati", 0)
                prof.task_per_cat[categoria] = d.get("quanti", 0)
        prof.last_measured = time.time()
        n += 1
    return n


def _skill_elenco(indice) -> dict[str, Any]:'''

assert m in s, "punto di inserimento non trovato"
s = s.replace(m, nuova_f, 1)

io.open(P, "w", encoding="utf-8").write(s)
print("  webapp.py: il blocco e' ora una funzione chiamabile")