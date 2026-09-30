def unique(items):
    """Restituisce gli elementi unici mantenendo l'ordine originale."""
    return list(dict.fromkeys(items))

if __name__ == "__main__":
    result = unique([1, 2, 2, 3, 1])
    print(result)
