def unique(items):
    """Return unique elements while preserving original order."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

if __name__ == "__main__":
    print(unique([1, 2, 2, 3, 1]))