"""Il matching fra i nomi loro e i nostri id.

Un modulo che scarica 689 modelli e ne tiene 0 non e' un modulo che
fallisce: e' un modulo che funziona e restituisce il vuoto, e il
vuoto e' indistinguibile da "non c'e' niente prior". Per un giorno
intero la chiave era nel .env, il pannello rispondeva 200, e non si
sapeva se il prior esistesse o no.

Qui si verifica il caso che era rotto, con nomi presi dall'API vera:

    "GLM-5.3 (Max)"   -> "z-ai/glm-5.3"
    "GPT-5.4 (Xhigh)" -> "openai/gpt-5.4"

E si verifica che il caso ambiguo NON venga risolto a caso: se due id
finiscono con lo stesso nome, meglio nessun prior che il prior del
modello sbagliato. Un prior attaccato al modello sbagliato è peggio di
nessun prior, perché da lì in poi non si distingue più.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra.prior import (  # noqa: E402
    _match_id, _norm_id, _togli_parentesi,
)

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


CATALOGO = {
    "z-ai/glm-5.3": 1,
    "openai/gpt-5.4": 1,
    "openai/gpt-5.4:high": 1,
    "xiaomi/mimo-v2.6-pro": 1,
    "deepseek/deepseek-v4.1-flash": 1,
    "apodex/apodex-1.1-mini:free": 1,
    "anthropic/claude-opus-5-5": 1,
}

print("[1] I nomi come li manda l'API diventano id del catalogo")
check("GLM-5.3 (Max)", _match_id("GLM-5.3 (Max)", CATALOGO) == "z-ai/glm-5.3",
      str(_match_id("GLM-5.3 (Max)", CATALOGO)))
check("GPT-5.4 (Xhigh)", _match_id("GPT-5.4 (Xhigh)", CATALOGO) == "openai/gpt-5.4",
      str(_match_id("GPT-5.4 (Xhigh)", CATALOGO)))
check("DeepSeek V4.1 Flash (Max)",
      _match_id("DeepSeek V4.1 Flash (Max)", CATALOGO)
      == "deepseek/deepseek-v4.1-flash",
      str(_match_id("DeepSeek V4.1 Flash (Max)", CATALOGO)))
check("MiMo-V2.6-Pro",
      _match_id("MiMo-V2.6-Pro", CATALOGO) == "xiaomi/mimo-v2.6-pro",
      str(_match_id("MiMo-V2.6-Pro", CATALOGO)))

print("\n[2] Le parentesi si tolgono, e non mangiano il nome")
check("toglie la variante", _togli_parentesi("GLM-5.3 (Max)") == "GLM-5.3",
      _togli_parentesi("GLM-5.3 (Max)"))
check("e le parentesi quadre", _togli_parentesi("GPT-5.4 [beta]") == "GPT-5.4",
      _togli_parentesi("GPT-5.4 [beta]"))
check("un nome senza parentesi resta com'e'",
      _togli_parentesi("MiMo-V2.6-Pro") == "MiMo-V2.6-Pro")

print("\n[3] La normalizzazione toglie il suffisso")
check("`:free` non cambia l'identita'",
      _norm_id("apodex/apodex-1.1-mini:free") == "apodex/apodex-1.1-mini",
      _norm_id("apodex/apodex-1.1-mini:free"))
check("`:high` idem",
      _norm_id("openai/gpt-5.4:high") == "openai/gpt-5.4",
      _norm_id("openai/gpt-5.4:high"))
check("maiuscole e spazi non contano",
      _norm_id("  OpenAI/GPT-5.4  ") == "openai/gpt-5.4")

print("\n[4] Il caso ambiguo NON si risolve a caso")
# Due id che finiscono con lo stesso nome. Il prior se lo attacchiamo
# a uno solo dei due e' quello sbagliato nel 50% dei casi, e non lo
# vediamo piu'. Quindi: nessuno.
amb = {"vendor-a/modello-x": 1, "vendor-b/modello-x": 1}
check("su nomi identici resta sul provider",
      _match_id("modello-x", {"vendor-a/modello-x": 1}) == "vendor-a/modello-x",
      str(_match_id("modello-x", {"vendor-a/modello-x": 1})))
check("e con due candidati non sceglie",
      _match_id("modello-x", amb) is None,
      str(_match_id("modello-x", amb)))

print("\n[5] Quello che non c'e', non viene inventato")
check("un nome assente non si aggancia",
      _match_id("Modello-che-non-esiste", CATALOGO) is None,
      str(_match_id("Modello-che-non-esiste", CATALOGO)))
check("una stringa vuota no", _match_id("", CATALOGO) is None)
check("senza catalogo non inventa", _match_id("GLM-5.3 (Max)", None) is None)

print("\n[6] Il caso che era rotto: nomi senza slash")
# Il difetto originale: accettava solo i nomi che contenevano gia' una
# "/", cioe' nessuno di quelli che l'API manda. Con questi nomi deve
# trovare qualcosa.
for nome in ("GLM-5.3 (Max)", "GPT-5.4 (Xhigh)", "MiMo-V2.6-Pro"):
    check(f"'{nome}' si aggancia", _match_id(nome, CATALOGO) is not None,
          str(_match_id(nome, CATALOGO)))

print("\n[7] Il caso reale, non quello che ho scritto io")
# Su un catalogo vero i nomi hanno forme che non mi aspetto: nomi
# lunghi con varianti dentro, e id con punti e trattini.
REALE = {
    "xiaomi/mimo-v2.6-pro": 1, "xiaomi/mimo-v2.6-flash": 1,
    "z-ai/glm-5.3": 1, "z-ai/glm-5.2": 1,
    "deepseek/deepseek-v4.1-flash": 1,
    "openai/gpt-5.4": 1, "openai/gpt-5.5": 1,
    "minimax/minimax-m3": 1,
}
check("MiMo-V2.6-Flash",
      _match_id("MiMo-V2.6-Flash", REALE) == "xiaomi/mimo-v2.6-flash",
      str(_match_id("MiMo-V2.6-Flash", REALE)))
check("GLM-5.2", _match_id("GLM-5.2", REALE) == "z-ai/glm-5.2",
      str(_match_id("GLM-5.2", REALE)))
check("GPT-5.5 (Xhigh)", _match_id("GPT-5.5 (Xhigh)", REALE) == "openai/gpt-5.5",
      str(_match_id("GPT-5.5 (Xhigh)", REALE)))

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)