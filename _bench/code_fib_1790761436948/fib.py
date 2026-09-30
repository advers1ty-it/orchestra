def fib(n):
    """Restituisce il n-esimo numero di Fibonacci (con F(0)=0, F(1)=1)."""
    if n < 0:
        raise ValueError("n deve essere non negativo")
    if n == 0:
        return 0
    if n == 1:
        return 1
    # Calcolo iterativo per evitare ricorsione profonda
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

if __name__ == "__main__":
    print(fib(10))
