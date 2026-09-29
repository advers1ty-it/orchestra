class Contatore:
    """Contatore semplice con valore intero."""

    def __init__(self, valore=0):
        self._valore = valore

    def incrementa(self, n=1):
        """Aumenta il valore di n e restituisce il nuovo valore."""
        self._valore += n
        return self._valore

    @property
    def valore(self):
        return self._valore

    @valore.setter
    def valore(self, nuovo_valore):
        self._valore = nuovo_valore

    def __repr__(self):
        return f"Contatore(valore={self._valore})"


if __name__ == "__main__":
    c = Contatore()
    c.incrementa()
    c.incrementa()
    c.incrementa()
    print(c.valore)
