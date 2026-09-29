def fib(n):
    """Restituisce il n-esimo numero di Fibonacci (F0 = 0, F1 = 1)."""
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError("n deve essere un intero")
    if n < 0:
        raise ValueError("n deve essere non negativo")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


if __name__ == "__main__":
    print(fib(10))
