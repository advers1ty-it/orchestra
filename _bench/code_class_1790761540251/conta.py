class Contatore:
    def __init__(self):
        self.valore = 0
    
    def incrementa(self, n=1):
        self.valore += n

# Stampa il valore dopo 3 incrementi partendo da 0
c = Contatore()
c.incrementa()  # primo incremento -> 1
c.incrementa()  # secondo incremento -> 2
c.incrementa()  # terzo incremento -> 3
print(c.valore)
