def unique(items):
    """Restituisce gli elementi unici mantenendo l'ordine originale."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

# Stampa del risultato
print(unique([1,2,2,3,1]))