"""
`storico_cerca`: cercare nelle conversazioni passate.

PERCHÉ ESISTE

Lo storico su disco c'era già, e conservava. Non faceva ritrovare: per
sapere "quella cosa che avevamo deciso" l'unico modo era aprire le
conversazioni una a una, e l'indice che c'era era per sessione, non per
contenuto.

È lo stesso difetto della memoria, un mese prima: avevo costruito la
persistenza e non il modo di usarla. Con la differenza che qui era già
scritto l'indice FTS5 della memoria, con lo stesso schema — non l'ho
collegato.

COSA TORNA, E PERCHÉ NON LA RIGA NUDA

Un frammento senza sapere di quale conversazione è non si può riaprire, e
ritrovare una cosa che non si può riaprire è un modo raffinato di
perderla. Per questo ogni risultato porta il titolo e l'id della
sessione: con l'id si può aprire, e il titolo dice se è quella giusta.
"""

from __future__ import annotations

from ..storico import storico
from ..types import Tool


def tool_storico_cerca() -> Tool:
    def handler(query: str = "", limite: int = 10) -> str:
        q = (query or "").strip()
        if not q:
            return "Cosa cerco? Serve una parola o una frase."
        try:
            risultati = storico().cerca(q, limite=limite)
        except Exception as e:
            # Un DB illeggibile non deve uccidere il turno: la
            # conversazione di adesso funziona, è lo storico che manca.
            return f"Non riesco a cercare nello storico: {type(e).__name__}: {e}"
        if not risultati:
            return f"Nessuna conversazione passata parla di: {q}"

        # Si contano le SESSIONI, non i messaggi: due risultati dalla stessa
        # chat sono una conversazione, e dire "2 conversazioni" quando è una
        # è il tipo di numero che non torna a chi guarda.
        sessioni = {r["sessione_id"] for r in risultati}
        quante = (f"{len(sessioni)} conversazioni"
                  if len(sessioni) > 1 else "1 conversazione")
        righe = [f"{quante} su «{q}»:", ""]
        for i, r in enumerate(risultati, 1):
            quando = ""
            try:
                import datetime
                quando = datetime.datetime.fromtimestamp(
                    r["creata"]).strftime("%d/%m %H:%M")
            except Exception:
                pass
            righe.append(f"{i}. [{r['titolo'] or '(senza titolo)'}] "
                         f"{r['ruolo']} · {quando}")
            righe.append(f"   {r['frammento']}")
            righe.append(f"   (sessione {r['sessione_id']} — "
                         f"apri con storico/apri)")
            righe.append("")
        return "\n".join(righe).rstrip()

    return Tool(
        name="storico_cerca",
        description=(
            "Cerca nelle conversazioni passate. Usala quando qualcuno "
            "dice «quella cosa di cui avevamo parlato», «come avevamo "
            "fatto», o quando la risposta potrebbe essere in una chat "
            "precedente invece che nel web. Ogni risultato torna con "
            "l'id della sessione, così puoi dire all'utente quale aprire."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Parole da cercare nelle chat passate."},
                "limite": {"type": "integer",
                           "description": "Quanti risultati. Default 10."},
            },
        },
        handler=handler,
    )
