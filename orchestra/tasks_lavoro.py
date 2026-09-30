"""Task per le categorie di lavoro specifiche: js, web, app.

Esistono perche' "code" da solo non basta. Un modello forte in Python
puo' essere mediocre in JavaScript e deludente in React, e il
benchmark deve dire la differenza: e' quello che permette di scegliere
un modello per il lavoro che hai davanti, invece di scegliere "il
migliore in assoluto" e sperare.

Le verifiche sono oggettive come le altre: o il file c'e' con il
contenuto richiesto, o non passa. Nessuna valutazione di stile, nessun
parere. Un modello che scrive JavaScript brutto ma funzionante passa,
che e' il punto: qui si misura se funziona dentro Orchestra.
"""

from .benchmark import Task, v_contains, v_file_lines, v_written, v_all

TASK_LAVORO: list[Task] = [
    # ---------------------------------------------------------------- js
    Task(
        id="js_dedupe", category="js",
        prompt="Crea il file dupe.mjs con una funzione `dupe(arr)` che "
                "torna un nuovo array senza duplicati, mantenendo l'ordine. "
                "In fondo al file esegui la funzione su [1,2,2,3,1] e "
                "stampa il risultato con console.log.",
        verify=v_contains("dupe.mjs", "console.log"),
    ),
    Task(
        id="js_fetch_stato", category="js",
        prompt="Crea stato.mjs con una funzione `descrizione(stato)` che "
                "traduce uno stato in italiano: 'ok' -> 'tutto bene', "
                "'errore' -> 'qualcosa e' andato storto', e per qualsiasi "
                "altro valore 'non so'. Usa uno switch. Aggiungi in fondo "
                "un console.log con il risultato per lo stato 'errore'.",
        verify=v_all(
            v_contains("stato.mjs", "switch"),
            v_contains("stato.mjs", "console.log"),
        ),
    ),
    # --------------------------------------------------------------- web
    Task(
        id="web_pagina", category="web",
        prompt="Crea index.html con una pagina minima e valida: deve "
                "avere il doctype, la meta charset utf-8, un title, e un "
                "h1 con il testo 'Benvenuto'. Collega lo stylesheet con "
                "un <link> verso style.css che crei anch'esso con una "
                "regola che colori il body.",
        verify=v_all(
            v_contains("index.html", "<!DOCTYPE html>"),
            v_contains("index.html", "charset"),
            v_contains("index.html", "<h1"),
            v_contains("index.html", "style.css"),
            v_written(["style.css"]),
        ),
    ),
    Task(
        id="web_layout", category="web",
        prompt="Crea layout.css con un foglio che usa Flexbox: il "
                "contenitore .riga deve mettere i suoi figli in fila, "
                "distribuiti con space-between, e i figli devono avere un "
                "gap di 12px.",
        verify=v_all(
            v_contains("layout.css", "display: flex"),
            v_contains("layout.css", "space-between"),
            v_contains("layout.css", "gap"),
        ),
    ),
    # --------------------------------------------------------------- app
    Task(
        id="app_componente", category="app",
        prompt="Crea Schermata.js con un componente React Native che "
                "esporta una funzione Schermata che usa useState per un "
                "contatore, un TouchableOpacity che lo incrementa e un "
                "Text che mostra il valore. Importa useState da 'react'.",
        verify=v_all(
            v_contains("Schermata.js", "useState"),
            v_contains("Schermata.js", "TouchableOpacity"),
            v_contains("Schermata.js", "<Text"),
        ),
    ),
    Task(
        id="app_useeffect", category="app",
        prompt="Crea Orari.js con un componente che usa useEffect per "
                "aggiornare lo stato con l'ora corrente al mount, e un "
                "useEffect di pulizia che svuota un intervallo. Deve "
                "importare sia useState sia useEffect da 'react'.",
        verify=v_all(
            v_contains("Orari.js", "useEffect"),
            v_contains("Orari.js", "useState"),
            v_contains("Orari.js", "clearInterval"),
        ),
    ),
]
