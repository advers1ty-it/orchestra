with open('orchestra/webapp.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the indentation
old = """        if path == "/api/allega":
            self._allega(s, body)
        if path == "/api/send":
                    text = (body.get("text") or "").strip()
                    scope = (body.get("scope") or "").strip() or None
                    allegati, problema = self._dal_registro(
                        body.get("allegati") or [])
                    if problema:
                        self._json({"error": problema}, 400)
                        return
                    if not text and not allegati:
                        self._json({"error": "messaggio vuoto"}, 400)
                        return
                    ok = s.send(text, allegati, scope=scope)
            if ok:"""

new = """        if path == "/api/allega":
            self._allega(s, body)
        elif path == "/api/send":
            text = (body.get("text") or "").strip()
            scope = (body.get("scope") or "").strip() or None
            allegati, problema = self._dal_registro(
                body.get("allegati") or [])
            if problema:
                self._json({"error": problema}, 400)
                return
            if not text and not allegati:
                self._json({"error": "messaggio vuoto"}, 400)
                return
            ok = s.send(text, allegati, scope=scope)
            if ok:"""

if old in content:
    content = content.replace(old, new)
    with open('orchestra/webapp.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed')
else:
    print('Not found')