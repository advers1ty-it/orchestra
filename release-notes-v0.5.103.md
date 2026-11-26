# v0.5.103 — La memoria e le istruzioni seguono il progetto

## I fatti senza progetto tornano insieme a quelli del progetto attivo

Il filtro per progetto escludeva i fatti salvati senza etichetta, e il
tool `memoria` passa sempre il progetto attivo: quei fatti diventavano
invisibili proprio mentre si lavorava a un progetto. Ora tornano in
entrambi i percorsi, la lettura del file e la ricerca FTS5.

## Le istruzioni del repository arrivano quando servono

`AGENTS.md`, `CLAUDE.md` e gli altri file di istruzioni erano letti alla
creazione della sessione e cuciti nel prefisso stabile: attivare un
progetto dopo non li portava, e cambiandolo restavano quelli vecchi. Ora
si risolvono dal progetto attivo nel blocco volatile, si rileggono a
ogni turno (quindi valgono anche le modifiche fatte a mano) e il
prefisso stabile non viene mai ricalcolato.

## Il blocco progetto ricorda dove si è già lavorato

Accanto ai fatti, il prompt del progetto elenca gli ultimi file toccati:
percorsi relativi alla cartella, senza duplicati, al massimo otto e
dentro un tetto di caratteri. Un agente che riapre un progetto non
riparte più da zero.

## Correzioni della memoria, ciascuna con la sua suite

- `elimina` e `modifica` confrontano il fatto esatto (non una
  sottostringa), rispettano il progetto e conservano la coda della riga;
  dopo una cancellazione o una modifica l'indice si riallinea dal file.
- La potatura conserva `creata`, `usi`, origine e scadenza, e il
  `dry_run` non scrive niente.
- `appendi` aggiunge il newline mancante: due fatti non finiscono più
  sulla stessa riga.
- Lo stato e il pannello mostrano i fatti interi, non i chunk
  dell'indice, e il percorso di `memory.md`.
- L'estrazione automatica legge solo i messaggi dell'utente e valida
  ogni fatto (lunghezza, markup, etichette, marcatori).

## Interfaccia

I controlli che erano solo un'icona ora hanno un nome, le select e i
dialoghi hanno etichette e ruoli ARIA, e il testo usa virgole e due
punti invece delle linee lunghe. Restyling di `app.css` e degli script
dei pannelli, con il digest della cache del service worker aggiornato.
