import io

P = "orchestra/webapp.py"
s = io.open(P, encoding="utf-8").read()

vecchio = '''                             + (f" — {(r.detail or r.error)[:80]}" if not r.passed else ""))'''

nuovo = '''                             + (f" — {perché(r)}" if not r.passed else ""))'''

assert vecchio in s, "la riga del dettaglio non trovata"
s = s.replace(vecchio, nuovo, 1)

m = "def salva_punteggi(cat, summary: dict[str, Any]) -> int:"
funzione = '''def perché(r) -> str:
    """Dice perche' un task e' fallito, e cosa non dice.

    "il file conta.py non esiste" e' il messaggio giusto, ma e'
    ambiguo: non distingue un modello che non ha chiamato nessuno
    strumento da uno che ha provato e non c'e' riuscito. Sono due
    fallimenti diversi, e portano a due correzioni diverse — il primo
    e' il modello, il secondo e' dell'agente o della rete.

    Il benchmark riportava lo stesso testo per i due, e li metteva
    nella stessa riga: il primo modello che ha fallito cosi' sembrava
    la prova che gli strumenti non funzionassero.
    """
    testo = (r.detail or r.error or "senza dettaglio").replace("\\n", " ").strip()
    if r.passed:
        return ""
    if "non esiste" in testo and not getattr(r, "tool_calls", 0):
        return f"{testo} (il modello non ha chiamato nessuno strumento)"
    if "non esiste" in testo and getattr(r, "tool_errors", 0):
        return f"{testo} (strumenti chiamati: {r.tool_calls}, con errore: {r.tool_errors})"
    return testo[:100]


'''
assert m in s
s = s.replace(m, funzione + m, 1)
io.open(P, "w", encoding="utf-8").write(s)
print("  webapp.py: il fallimento dice se il modello ha provato")