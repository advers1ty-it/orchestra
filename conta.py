class Contatore:
    def __init__(self):
        self._valore = 0

    def incrementa(self, n=1):
        self._valore += n

    @property
    def valore(self):
        return self._valore


c = Contatore()
c.incrementa()
c.incrementa()
c.incrementa()
print(c.valore)
