import os

EST = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff', '.ppm', '.bmp'}
trovate = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', 'skills', 'node_modules')]
    for f in files:
        if os.path.splitext(f)[1].lower() in EST:
            trovate.append(os.path.join(root, f))

print('TROVATE:', len(trovate))
for t in trovate[:60]:
    try:
        print(' ', t, os.path.getsize(t))
    except OSError as e:
        print(' ', t, 'ERR', e)
