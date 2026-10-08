with open('orchestra/routing.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update function signature
old_sig = '''def instrada(cat: Catalog, richiesta: str, *,
             solo_gratis: bool = False,
             escluso: str | None = None,
             provider: str = "openrouter") -> Scelta:'''

new_sig = '''def instrada(cat: Catalog, richiesta: str, *,
             solo_gratis: bool = False,
             escluso: str | None = None,
             provider: str = "openrouter",
             scope: str | None = None) -> Scelta:'''

content = content.replace(old_sig, new_sig)

# 2. Update docstring
old_doc = '''    """Sceglie il modello per questa richiesta. Ritorna sempre una Scelta.

    Anche quando non trova niente: una decisione che non c'e' non si
    distingue da un classifier che non ha girato, e la prima fa
    fallire il turno mentre la seconda passa inosservata.
    """'''

new_doc = '''    """Sceglie il modello per questa richiesta. Ritorna sempre una Scelta.

    Anche quando non trova niente: una decisione che non c'e' non si
    distingue da un classifier che non ha girato, e la prima fa
    fallire il turno mentre la seconda passa inosservata.

    Se `scope` e' fornito, usa quella categoria invece di dedurla
    dal testo della richiesta.
    """'''

content = content.replace(old_doc, new_doc)

# 3. Update category detection
old_cat = '    cat_id = categoria(richiesta)'

new_cat = '''    # Se scope e' fornito, usa quello come categoria
    if scope and scope in [c[0] for c in CATEGORIE]:
        cat_id = scope
    else:
        cat_id = categoria(richiesta)'''

content = content.replace(old_cat, new_cat)

with open('orchestra/routing.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')