---
name: skill-authoring
description: Usa quando crei o modifichi una skill di Orchestra. Formato SKILL.md, frontmatter e verifica.
version: 1.0.0
author: Orchestra
categoria: base
origine: scaricata
---

# Scrivere skill di Orchestra

Una skill è un'istruzione che l'agente segue: se è sbagliata,
sbaglia tutto quello che ci costruisce sopra. Scrivila con cura.

## Formato

Una cartella piatta dentro `skills/`, con un solo file:

```
skills/<nome>/
  SKILL.md
```

Lo `SKILL.md` ha un frontmatter e un corpo:

```
---
name: <nome-della-cartella>
description: Quando usarla. Una riga, con il trigger.
categoria: base
origine: scaricata
---

# Titolo

Corpo in markdown: cosa fare, con quali comandi.
```

- `description` è l'unica cosa che l'agente vede sempre
  (due righe nel prompt): deve dire QUANDO usare la skill,
  non cosa contiene.
- Il corpo entra nel contesto solo quando la skill viene
  scelta (`skill_leggi`), e per intero: niente segreti,
  niente chiavi, niente dati personali. Mai.
- `categoria: base` per quelle distribuite con Orchestra.

## Regole di contenuto

- Comandi veri, mai inventati: ogni comando citato deve
  esistere (tool dell'agente o CLI reale), ogni percorso
  deve essere quello vero del progetto.
- Procedure, non saggi: passi numerati, verificabili uno a uno.
- Una skill, un lavoro: se serve un "quando" diverso,
  sono due skill.

## Verifica

Dopo averla scritta, rileggila come un estraneo e aprila
con `skill_leggi <nome>`: deve tornare il testo intero.
Poi `python tests/test_skills.py` deve restare verde.
