"""I tool delle skill: leggere, cercare, generare, importare.

Sono quattro, e non di piu'. Ogni tool in piu' nel prompt e' un
disturbo: il modello sceglie male quando ha troppe opzioni, e sceglie
male anche quando sono tutte giuste.

    skill_cerca   parole       -> nomi e descrizioni, niente di piu'
    skill_leggi   nome         -> la procedura per intero
    skill_genera  ...          -> scrive una skill da cid' che hai fatto
    skill_importa  cartella    -> porta dentro uno store esterno

La separazione fra cerca e leggi e' deliberata: il prompt di sistema
porta gia' i nomi e le descrizioni delle piu' vicine, quindi cercare
e' quasi sempre inutile. Ma "quasi sempre" non e' "sempre", e senza
cerca una skill giusta ma non in cima e' invisibile — che e' il modo
migliore per non trovarla mai.
"""

from __future__ import annotations

import os
from typing import Any

import orchestra.skills as sk
from ..types import Tool


def _indice() -> sk.Indice:
    """L'indice condiviso.

    Uno solo per processo, non uno per chiamata: rileggere 188 file
    a ogni `skill_cerca` costerebbe qualche secondo, e l'agente ne fa
    tre o quattro per turno. La cache dentro l'indice fa gia' il suo
    lavoro, quindi qui basta non crearne uno nuovo ogni volta.

    Se ORCHESTRA_SKILLS cambia, l'indice viene rifatto. Il motivo e'
    che la radice si legge una volta sola: un test (o un utente che
    cambia la variabile per un'operazione) si ritroverebbe a scrivere
    dove non sta guardando, e la skill finirebbe in una cartella
    invisibile a ogni altro.
    """
    global _INDICE
    if _INDICE is not None and _INDICE.radice == sk.RADICE:
        return _INDICE
    _INDICE = sk.Indice(sk.RADICE)
    return _INDICE


_INDICE: sk.Indice | None = None


def _testo(testo: str, *, limite: int = 30000) -> str:
    """Taglia e dice che ha tagliato.

    Una procedura lunga che entra per intero puo' mangiare il contesto
    — e il contesto serve a cid' che stai facendo, non alla skill che
    hai aperto per sbaglio. Il taglio e' dichiarato perche' un testo
    che finisce di punto sembra completo, e l'agente agisce su un
    documento che non ha letto tutto.
    """
    if len(testo) <= limite:
        return testo
    return (testo[:limite]
            + f"\n\n... [tagliato: {len(testo) - limite} caratteri. "
              f"Il resto e' in {sk.RADICE}]")


# --------------------------------------------------------------------------


def tool_skill_cerca() -> Tool:
    # La firma è a keyword, non un dict: l'agent chiama `handler(**args)`,
    # e con `args: dict` ogni chiamata moriva con "unexpected keyword
    # argument". Tutti e quattro i tool di questo file avevano lo stesso
    # difetto.
    async def handler(parole: str = "", limite: int = 8) -> str:
        if isinstance(parole, list):
            parole = " ".join(str(p) for p in parole)
        parole = str(parole).strip()
        if not parole:
            return ("Che parole? Esempio: {\"parole\": \"estratto pdf tabelle\"}. "
                    "Usa parole che compaiono nel tuo compito, non parole generiche.")
        i = _indice()
        if not i.tutte():
            return ("Non c'e' nessuna skill. Importane una con skill_importa, "
                    "oppure fai il compito e poi usa skill_genera.")
        try:
            limite = max(1, min(int(limite or 8), 50))
        except (TypeError, ValueError):
            limite = 8
        trovate = i.cerca(parole.split(), limite=limite)
        if not trovate:
            return (f"Nessuna skill su {len(i.tutte())} parla di {parole!r}. "
                    f"Procedi senza, e se il tuo metodo funziona valuta "
                    f"skill_genera.")
        righe = []
        for s in trovate:
            segno = "+" if s.origine == "generata" else " "
            extra = f"  [generata, {len(s.prove)} prove]" if s.con_prove else ""
            righe.append(f"  {segno} {s.nome}: {s.descrizione}{extra}")
        return (f"{len(trovate)} su {len(i.tutte())} skill. "
                f"Con skill_leggi porti nel contesto quella che ti serve.\n"
                + "\n".join(righe))

    return Tool(
        name="skill_cerca",
        description=("Searches the skills by keyword. Returns names and "
                     "descriptions. Use it when the prompt does not show what "
                     "you need: it may not, there the prompt only lists the "
                     "closest ones."),
        schema={
            "type": "object",
            "properties": {
                "parole": {"type": "string",
                           "description": "Keywords separated by spaces."},
                "limite": {"type": "integer",
                           "description": "How many results (default 8)."},
            },
            "required": ["parole"],
        },
        handler=handler,
    )


def tool_skill_leggi() -> Tool:
    async def handler(nome: str = "") -> str:
        nome = str(nome or "").strip()
        if not nome:
            return "Che skill? Passa il nome esatto."
        i = _indice()
        s = i.get(nome)
        if not s:
            # Non elencare tutto qui: 188 nomi in un messaggio di errore
            # costano piu' del tentativo che li ha prodotti. Si dice come
            # cercarli, e si lascia che l'agente lo faccia.
            vicine = [x.nome for x in i.cerca(nome.split(), limite=5)]
            aiuto = (" Nelle vicine: " + ", ".join(vicine)) if vicine else ""
            return (f"Nessuna skill chiamata {nome!r}."
                    f"Cerca con skill_cerca, parola per parola.{aiuto}")
        if s.proposta:
            # Una proposta non e' ancora una procedura: leggerla qui la
            # farebbe sembrare approvata, e l'agente la seguirebbe senza
            # che nessuno abbia deciso. Si dice cosa manca e chi decide.
            return (f"{nome} e' una proposta: non e' ancora stata accettata, "
                    f"quindi non fa parte delle procedure disponibili. "
                    f"Si accetta dal pannello Opzioni \u2192 Skill.")
        i.segna_usata(nome)
        return _testo(s.per_uso())

    return Tool(
        name="skill_leggi",
        description=("Brings the procedure of a skill into the context, whole. "
                     "Use it when your task is close to a skill shown in the "
                     "prompt: following a written procedure beats improvising, "
                     "and improvising has to be undone."),
        schema={
            "type": "object",
            "properties": {
                "nome": {"type": "string",
                         "description": "Exact skill name."},
            },
            "required": ["nome"],
        },
        handler=handler,
    )


def tool_skill_genera() -> Tool:
    async def handler(nome: str = "", descrizione: str = "",
                      procedura: str = "", obiettivo: str = "", **args) -> str:
        nome = str(nome or "").strip()
        descrizione = str(descrizione or "").strip()
        corpo = str(procedura or "").strip()
        obiettivo = str(obiettivo or "").strip()
        if not nome or not corpo:
            return ("Servono nome e procedura. La procedura e' cosa hai fatto, "
                    "passo passo, con i comandi esatti: non un riassunto, un "
                    "elenco di azioni che qualcun altro puo' ripetere.")
        prove = list(args.get("prove") or [])
        if args.get("comandi"):
            prove.append({
                "ts": __import__("time").time(),
                "obiettivo": obiettivo or "Sessione corrente",
                "comandi": [str(c) for c in args["comandi"]],
                "esito": str(args.get("esito") or "riuscita"),
            })
        c = sk.Candidato(nome=nome, descrizione=descrizione, corpo=corpo,
                         prove=prove)
        if not prove:
            c.motivo_rifiuto = "nessuna prova: una procedura senza prove e' " \
                               "un'affermazione"
        ok, perche = sk.valuta_candidato(c, soglia=1)
        if not ok:
            return ("Non salvata: " + perche + ".\n"
                    "Una skill serve a ripetere qualcosa che ha funzionato, "
                    "non a registrare un tentativo. Se il metodo funziona, "
                    "metti il campo 'prove' con i comandi e l'esito, e riprova.")
        p = sk.salva_generata(_indice(), c)
        return (f"Skill salvata: {c.nome}\n  {p}\n"
                f"  prove allegate: {len(prove)}\n"
                f"Da ora in poi entra nel prompt quando il compito le somiglia.")

    return Tool(
        name="skill_genera",
        description=("Saves a procedure you have just carried out successfully, "
                     "so it can be repeated later. Write it ONLY when the "
                     "method worked: a skill describing a failed attempt makes "
                     "the error repeat. Include the evidence, so anyone can "
                     "see it really works."),
        schema={
            "type": "object",
            "properties": {
                "nome": {"type": "string",
                         "description": "Short name, no spaces."},
                "descrizione": {"type": "string",
                                "description": ("When to use it. One line, "
                                                "with words that show up "
                                                "in the task.")},
                "procedura": {"type": "string",
                              "description": ("The steps, with the exact "
                                              "commands. Write for someone "
                                              "else.")},
                "obiettivo": {"type": "string",
                              "description": "What you were doing."},
                "comandi": {"type": "array", "items": {"type": "string"},
                            "description": ("The commands you ran, in "
                                            "order.")},
                "esito": {"type": "string",
                          "description": "What happened."},
            },
            "required": ["nome", "procedura"],
        },
        handler=handler,
    )


def tool_skill_importa() -> Tool:
    async def handler(cartella: str = "", categoria: str = "") -> str:
        sorgente = str(cartella or "").strip()
        if not sorgente:
            return "Che cartella? Il percorso di uno store con dentro le cartelle delle skill, oppure un URL git (https://... o git@...)."
        i = _indice()
        n, nomi = i.importa(sorgente, categoria=str(categoria or "").strip())
        if not n:
            return (f"Nessuna skill importata da {sorgente}: dentro non ci sono "
                    f"cartelle con un SKILL.md.")
        prime = ", ".join(nomi[:12])
        piu = f" (+{len(nomi) - 12} altre)" if len(nomi) > 12 else ""
        return (f"{n} skill importate in {sorgente}{piu}\n  {prime}\n"
                f"Ora sono nel prompt quando il compito le somiglia.")

    return Tool(
        name="skill_importa",
        description=("Imports a skill store: a directory holding other "
                     "directories, each with a SKILL.md. It also copies the "
                     "scripts and references kept inside them."),
        schema={
            "type": "object",
            "properties": {
                "cartella": {"type": "string",
                             "description": ("Path of the store, or a git URL "
                                             "(https://... or git@...).")},
                "categoria": {"type": "string",
                              "description": ("Category to file them "
                                              "under.")},
            },
            "required": ["cartella"],
        },
        handler=handler,
    )


def registra(r) -> None:
    for t in (tool_skill_cerca(), tool_skill_leggi(),
              tool_skill_genera(), tool_skill_importa()):
        r.register(t)
