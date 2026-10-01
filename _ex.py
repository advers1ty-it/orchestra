import io

P = "orchestra/benchmark.py"
s = io.open(P, encoding="utf-8").read()

# 1) extract_campi: il prompt non dice cosa mettere nel campo
#    "preventivo". Il modello ci ha messo "Preventivo n. 2026/1847",
#    il verificatore pretendeva "2026/1847". Entrambe sono letture
#    ragionevoli di "estrai il preventivo", e il compito non ne
#    scelueva nessuna: il benchmark non misurava la capacita' di
#    estrarre, ma se il modello aveva indovinato la convenzione che
#    non era scritta da nessuna parte.
vecchio = '''        prompt="Leggi il file listino.txt nella cartella di lavoro e tira fuori i dati in un file preventivi.json.
Deve essere un JSON valido con questi campi: cliente (stringa), codice (stringa), preventivo (stringa), data (stringa in formato AAAA-MM-GG), totale (numero).
La data e' quella dentro 'Preventivo n. 2026/1847 del 14 giugno 2026'. Il totale e' la somma dei tre importi elencati dopo 'Servizi'.
Scrivi solo il file JSON, senza spiegazioni.",'''

nuovo = '''        prompt="""Leggi il file listino.txt nella cartella di lavoro e tira fuori i dati in un file preventivi.json.
Deve essere un JSON valido con questi campi: cliente (stringa), codice (stringa), preventivo (stringa), data (stringa in formato AAAA-MM-GG), totale (numero).
Nella riga 'Preventivo n. 2026/1847 del 14 giugno 2026' ci sono tre cose, e ognuna va in un campo diverso:
  - preventivo: SOLO '2026/1847', senza la parola 'Preventivo' e senza 'n.'
  - data: '2026-06-14', ricavata dal 14 giugno 2026
Il totale e' la somma dei tre importi elencati dopo 'Servizi'.
Scrivi solo il file JSON, senza spiegazioni.""",'''
assert vecchio in s, "il prompt di extract_campi non trovato"
s = s.replace(vecchio, nuovo, 1)

io.open(P, "w", encoding="utf-8").write(s)
print("  extract_campi: il prompt dice cosa mettere in ogni campo")