import re

with open('orchestra/webapp.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix /api/chiavi to include reasoning
old_chiavi = '''            self._json({
                "chiavi": keys_mod.stato(ENV_PATH, self.app.env),
                "servizi_gratis": keys_mod.FREE_SERVICES,
                "nota_gratis": keys_mod.NOTA_FREE,
                "catalogo": {
                    "modelli": len(cat_.models) if cat_ is not None else 0,
                    "gratuiti": len(cat_.free()) if cat_ is not None else 0,
                },
                "motori": sorted(NO_KEY_PROVIDERS),
                "provider": self.app.env.get("ORCHESTRA_PROVIDER", ""),
            })'''

new_chiavi = '''            self._json({
                "chiavi": keys_mod.stato(ENV_PATH, self.app.env),
                "servizi_gratis": keys_mod.FREE_SERVICES,
                "nota_gratis": keys_mod.NOTA_FREE,
                "catalogo": {
                    "modelli": len(cat_.models) if cat_ is not None else 0,
                    "gratuiti": len(cat_.free()) if cat_ is not None else 0,
                },
                "motori": sorted(NO_KEY_PROVIDERS),
                "provider": self.app.env.get("ORCHESTRA_PROVIDER", ""),
                "reasoning": self.app.env.get("ORCHESTRA_REASONING", ""),
            })'''

if old_chiavi in content:
    content = content.replace(old_chiavi, new_chiavi)
    print('Fixed /api/chiavi')
else:
    print('NOT FOUND: /api/chiavi')

# 2. Fix /api/reasoning endpoint
old_reasoning = '''        elif path == "/api/reasoning":
            r = (body.get("reasoning") or "").strip()
            valid = {"none", "minimal", "low", "medium", "high", "xhigh", "max", ""}
            if r not in valid:
                self._json({"error": f"livello reasoning non valido: {r}"}, 400)
                return
            if self.app.session.busy:
                self._json({"error": "l'agente sta lavorando: attendi o annulla prima"}, 409)
                return
            from . import keys as keys_mod
            self.app.env["ORCHESTRA_REASONING"] = r
            keys_mod.scrivi(ENV_PATH, "ORCHESTRA_REASONING", r)
            # ricrea la sessione col nuovo livello
            self.app.session = self.app._make_session(
                self.app.env.get("ORCHESTRA_PROVIDER", "openrouter"),
                self.app.env.get("ORCHESTRA_MODEL", ""),
            )
            self._json({"ok": True, "reasoning": r})
        elif path == "/api/chiavi":'''

new_reasoning = '''        elif path == "/api/reasoning":
            r = (body.get("reasoning") or "").strip()
            valid = {"none", "minimal", "low", "medium", "high", "xhigh", "max", ""}
            if r not in valid:
                self._json({"error": f"livello reasoning non valido: {r}"}, 400)
                return
            if self.app.session.busy:
                self._json({"error": "l'agente sta lavorando: attendi o annulla prima"}, 409)
                return
            from . import keys as keys_mod
            self.app.env["ORCHESTRA_REASONING"] = r
            keys_mod.scrivi(ENV_PATH, "ORCHESTRA_REASONING", r)
            # ricrea la sessione col nuovo livello
            self.app.session = self.app._make_session(
                self.app.env.get("ORCHESTRA_PROVIDER", "openrouter"),
                self.app.env.get("ORCHESTRA_MODEL", ""),
            )
            self._json({"ok": True, "reasoning": r})
        elif path == "/api/chiavi":'''

if old_reasoning in content:
    content = content.replace(old_reasoning, new_reasoning)
    print('Fixed /api/reasoning')
else:
    print('NOT FOUND: /api/reasoning')
    # Debug: find what's there
    idx = content.find('api/reasoning')
    if idx >= 0:
        print(repr(content[idx:idx+500]))

with open('orchestra/webapp.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')