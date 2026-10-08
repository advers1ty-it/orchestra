with open('orchestra/routing.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Update the instrada function signature
for i, line in enumerate(lines):
    if 'def instrada(cat: Catalog, richiesta: str, *' in line:
        lines[i] = 'def instrada(cat: Catalog, richiesta: str, *,\n'
        lines.insert(i+1, '             solo_gratis: bool = False,\n')
        lines.insert(i+2, '             escluso: str | None = None,\n')
        lines.insert(i+3, '             provider: str = "openrouter",\n')
        lines.insert(i+4, '             scope: str | None = None) -> Scelta:\n')
        print(f'Updated signature at line {i}')
        break

# Update the docstring
for i, line in enumerate(lines):
    if 'Anche quando non trova niente: una decisione che non c' in line and 'non si' in line:
        lines[i] = '    """Sceglie il modello per questa richiesta. Ritorna sempre una Scelta.\n'
        lines.insert(i+1, '\n')
        lines.insert(i+2, '    Anche quando non trova niente: una decisione che non c\'e\' non si\n')
        lines.insert(i+3, '    distingue da un classifier che non ha girato, e la prima fa\n')
        lines.insert(i+4, '    fallire il turno mentre la seconda passa inosservata.\n')
        lines.insert(i+5, '\n')
        lines.insert(i+6, '    Se `scope` e\' fornito, usa quella categoria invece di dedurla\n')
        lines.insert(i+7, '    dal testo della richiesta.\n')
        lines.insert(i+8, '    """\n')
        print(f'Updated docstring at line {i}')
        break

# Update the category detection to use scope if provided
for i, line in enumerate(lines):
    if 'cat_id = categoria(richiesta)' in line:
        lines[i] = '# Se scope e\' fornito, usa quello come categoria\n'
        lines.insert(i+1, '    if scope and scope in [c[0] for c in CATEGORIE]:\n')
        lines.insert(i+2, '        cat_id = scope\n')
        lines.insert(i+3, '    else:\n')
        lines.insert(i+4, '        cat_id = categoria(richiesta)\n')
        print(f'Updated category logic at line {i}')
        break

with open('orchestra/routing.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Done routing.py')