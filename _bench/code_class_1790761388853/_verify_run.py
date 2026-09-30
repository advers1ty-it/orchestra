class Contatore:
    def __init__(self):
        self.valore = 0
    
    def incrementa(self, n=1):
        self.valore += n

# Creiamo un contatore e facciamo 3 incrementi
cnt = Contatore()
for _ in range(3):
    cnt.incrementa()
print(cnt.valore)
