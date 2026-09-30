class Contatore:
    def __init__(self):
        self.valore = 0
    
    def incrementa(self, n=1):
        self.valore += n
    
    def get_valore(self):
        return self.valore

# Creazione di un contatore e stampa del valore dopo 3 incrementi
contatore = Contatore()
for _ in range(3):
    contatore.incrementa()
print(contatore.get_valore())
