"""Generazione immagini: scelta del provider, risposte, salvataggio, tool.

Nessuna rete: le risposte dei provider sono finte, con la stessa forma di
quelle vere. Il punto non e' testare OpenAI o Google (non possiamo), ma che
cosa fa Orchestra quando la risposta e' quella forma — e che cosa dice
quando manca una chiave o il modello non restituisce un'immagine.
"""

import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from orchestra import Agent, LoopConfig  # noqa: E402
from orchestra import attachments as att  # noqa: E402
from orchestra import image_gen as ig  # noqa: E402
from orchestra.tools import applica_profilo, default_registry  # noqa: E402
from orchestra.types import LLMResponse, ToolCall, ToolResult  # noqa: E402
from orchestra.attachments import Attachment  # noqa: E402

PASS, FAIL = [], []


def check(nome, cond, dettaglio=""):
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


# Un PNG vero di un pixel: serve per verificare che i byte salvati siano
# davvero l'immagine e non una stringa che somiglia a base64.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
    "hKmMIQAAAABJRU5ErkJggg=="
)
B64_PNG = base64.b64encode(PNG_1PX).decode("ascii")


def _senza_marcatura(dati: bytes) -> bytes:
    """I byte del provider, senza il chunk che Orchestra aggiunge.

    Da quando un'immagine generata porta dentro la sua dichiarazione (art.
    50(2) AI Act) i byte salvati non sono piu' identici a quelli arrivati:
    c'e' un `tEXt` in piu' prima di `IEND`. Il controllo qui sotto vuole
    dire "sono davvero quei pixel", non "sono gli stessi byte", quindi la
    marcatura si toglie invece di far fallire il test a ogni rilascio.
    """
    if not dati.startswith(b"\x89PNG\r\n\x1a\n"):
        return dati
    fuori = dati[:8]
    i = 8
    while i + 12 <= len(dati):
        lunghezza = int.from_bytes(dati[i:i + 4], "big")
        tipo = dati[i + 4:i + 8]
        fine = i + 12 + lunghezza
        if tipo != b"tEXt":
            fuori += dati[i:fine]
        i = fine
        if tipo == b"IEND":
            break
    return fuori

TMP = tempfile.mkdtemp(prefix="orchestra-img-")

# Le chiavi: questi test non devono dipendere ne' dal `.env` della macchina
# ne' da quello che prepara la CI. In CI il file di ambiente finto contiene
# una OPENROUTER_API_KEY e nessuna OPENAI: il tool sceglieva OpenRouter
# mentre il finto rispondeva come Google, e sei controlli diventavano rossi
# per un motivo che non e' il codice. Si finge qui un ambiente completo.
CHIAVI_FINTE = {"ORCHESTRA_IMAGE_PROVIDER": "", "OPENAI_API_KEY": "sk-test",
                "GEMINI_API_KEY": "goog", "OPENROUTER_API_KEY": "or-key"}
ig.ambiente = lambda: dict(CHIAVI_FINTE)


def env(**valori):
    """Un ambiente finto: solo le chiavi che il test dichiara."""
    base = {"ORCHESTRA_IMAGE_PROVIDER": ""}
    base.update(valori)
    return base


print("\n[1] Quale provider usare, senza indovinare")
check("senza chiavi non ce n'e' nessuno",
      ig.provider_disponibile("", env()) == "", ig.provider_disponibile("", env()))
check("con OPENAI_API_KEY si usa OpenAI",
      ig.provider_disponibile("", env(OPENAI_API_KEY="sk-test")) == "openai")
check("con GEMINI_API_KEY si usa Google",
      ig.provider_disponibile("", env(GEMINI_API_KEY="goog")) == "google")
check("OpenAI vince quando ci sono entrambe",
      ig.provider_disponibile("", env(OPENAI_API_KEY="sk", GEMINI_API_KEY="g"))
      == "openai")
check("il provider chiesto vince su tutto",
      ig.provider_disponibile("google", env(OPENAI_API_KEY="sk")) == "google")
check("'gemini' e' un alias di google",
      ig.provider_disponibile("gemini", env()) == "google")
check("ORCHESTRA_IMAGE_PROVIDER vale come scelta",
      ig.provider_disponibile("", env(ORCHESTRA_IMAGE_PROVIDER="google")) == "google")
# La chiave richiesta esplicitamente non deve essere sostituita in silenzio
# da un altro provider: sarebbe una spesa che l'utente non ha autorizzato.
check("un provider esplicito resta quello anche senza chiave",
      ig.provider_disponibile("openai", env(GEMINI_API_KEY="g")) == "openai")
# OpenRouter: una chiave sola per la chat e per le immagini, cosi' chi lo usa
# non deve comprare anche una chiave OpenAI o Google.
check("con OPENROUTER_API_KEY si usa OpenRouter",
      ig.provider_disponibile("", env(OPENROUTER_API_KEY="or-key")) == "openrouter")
check("'router' e 'or' sono alias di openrouter",
      ig.provider_disponibile("router", env()) == "openrouter"
      and ig.provider_disponibile("or", env()) == "openrouter")
check("chi parla via OpenRouter genera via OpenRouter",
      ig.provider_disponibile("", env(OPENROUTER_API_KEY="or-key",
                                     ORCHESTRA_PROVIDER="openrouter"))
      == "openrouter")
check("OpenRouter non scavalca un provider esplicito",
      ig.provider_disponibile("google", env(OPENROUTER_API_KEY="or-key",
                                            GEMINI_API_KEY="g")) == "google")

print("\n[2] Nessuna chiave: l'errore dice come risolvere")
try:
    ig.genera("un gatto", cartella=TMP, env=env())
    check("senza chiave solleva", False)
except ig.ImageGenError as e:
    testo = str(e).lower()
    check("senza chiave solleva", True)
    check("dice quale chiave serve",
          "openai_api_key" in testo and "gemini_api_key" in testo, testo)
    check("propone l'alternativa locale", "invokeai" in testo, testo)

print("\n[3] OpenAI: la risposta b64 diventa un file")
originale = ig._post_json
chiamate = []


def finto_openai(url, corpo, testa, provider):
    chiamate.append((url, corpo, testa, provider))
    return {"created": 1, "data": [{"b64_json": B64_PNG}]}


ig._post_json = finto_openai
try:
    img = ig.genera("un gatto arancione", cartella=TMP,
                    env=env(OPENAI_API_KEY="sk-test"), dimensione="1024x1024")
    check("usa l'endpoint di generazione",
          chiamate and chiamate[0][0] == ig.ENDPOINT["openai"], str(chiamate[:1]))
    check("manda il modello predefinito",
          chiamate and chiamate[0][1].get("model") == ig.MODELLI["openai"])
    check("manda la dimensione richiesta",
          chiamate and chiamate[0][1].get("size") == "1024x1024")
    check("l'autorizzazione e' Bearer",
          chiamate and chiamate[0][2].get("Authorization") == "Bearer sk-test")
    check("i byte sono quelli restituiti", _senza_marcatura(img.dati) == PNG_1PX)
    check("il mime e' png", img.mime == "image/png")
    check("il file esiste", img.percorso.exists(), str(img.percorso))
    check("sta nella cartella immagini",
          img.percorso.parent.name == "immagini", str(img.percorso))
    check("il nome viene dal prompt",
          img.percorso.name.startswith("un-gatto-arancione"), img.percorso.name)
    check("la data url e' la forma degli allegati",
          img.data_url().startswith("data:image/png;base64,"))
    prima = img.percorso

    img2 = ig.genera("un gatto arancione", cartella=TMP,
                     env=env(OPENAI_API_KEY="sk-test"))
    check("non sovrascrive l'immagine precedente", img2.percorso != prima,
          f"{prima.name} / {img2.percorso.name}")
    check("aggiunge un suffisso", img2.percorso.name.startswith("un-gatto-arancione-"),
          img2.percorso.name)

    print("\n[4] Google: l'immagine sta nelle parti della risposta")

    url_google = []

    def finto_google(url, corpo, testa, provider):
        url_google.append(url)
        assert testa.get("x-goog-api-key") == "goog", testa
        return {"candidates": [{"content": {"parts": [
            {"text": "ecco"},
            {"inlineData": {"mimeType": "image/png", "data": B64_PNG}},
        ]}, "finishReason": "STOP"}]}

    ig._post_json = finto_google
    img3 = ig.genera("un cane", provider="google", cartella=TMP,
                     env=env(GEMINI_API_KEY="goog"), dimensione="16:9")
    check("il modello predefinito sta nel percorso",
          bool(url_google) and ig.MODELLI["google"] in url_google[0],
          str(url_google[:1]))
    check("salva i byte dell'immagine", _senza_marcatura(img3.dati) == PNG_1PX)
    check("riconosce il provider", img3.provider == "google")
    check("il file e' un png", img3.percorso.suffix == ".png", img3.percorso.name)

    # /v1/ puo' rispondere 404 su un progetto abilitato solo su /v1beta/:
    # si riprova, invece di dire che il modello non esiste.
    prove = []

    def finto_google_beta(url, corpo, testa, provider):
        prove.append(url)
        if len(prove) == 1:
            raise ig.ImageGenError("Google: HTTP 404.", status=404)
        return {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": B64_PNG}}]}}]}

    ig._post_json = finto_google_beta
    img4 = ig.genera("un gatto", provider="google", cartella=TMP,
                     env=env(GEMINI_API_KEY="goog"))
    check("404 su /v1 ritenta su /v1beta", len(prove) == 2, str(prove))
    check("il secondo tentativo usa v1beta",
          len(prove) == 2 and "/v1beta/" in prove[1], str(prove[:2]))
    check("e l'immagine arriva", _senza_marcatura(img4.dati) == PNG_1PX)

    # Il modello si puo' forzare dall'ambiente, senza toccare il codice.
    ig._post_json = finto_google
    img5 = ig.genera("un gatto", provider="google", cartella=TMP,
                     env=env(GEMINI_API_KEY="goog",
                             ORCHESTRA_IMAGE_MODEL="gemini-3.1-flash-image"))
    check("ORCHESTRA_IMAGE_MODEL sceglie il modello",
          img5.modello == "gemini-3.1-flash-image", img5.modello)
    check("e finisce nell'URL, non nel corpo",
          bool(url_google) and "gemini-3.1-flash-image" in url_google[-1],
          str(url_google[-1:]))

    print("\n[5] Google senza immagine: si dice perche'")
    ig._post_json = lambda *a, **k: {"candidates": [{
        "content": {"parts": [{"text": "non posso generare questa immagine"}]},
        "finishReason": "SAFETY"}]}
    try:
        ig.genera("qualcosa", provider="google", cartella=TMP,
                  env=env(GEMINI_API_KEY="goog"))
        check("senza immagine solleva", False)
    except ig.ImageGenError as e:
        check("senza immagine solleva", True)
        check("riporta il motivo del modello",
              "non posso generare" in str(e) or "SAFETY" in str(e), str(e))

    print("\n[6] Gli errori HTTP dicono cosa fare")
    e401 = ig._errore_http("openai", 401, "invalid api key")
    check("401 parla della chiave", "chiave" in str(e401).lower(), str(e401))
    e429 = ig._errore_http("google", 429, "quota")
    check("429 parla di quota", "quota" in str(e429).lower(), str(e429))
    check("il dettaglio del provider resta",
          "invalid api key" in str(e401), str(e401))

    print("\n[7] Un prompt vuoto o troppo lungo non parte")
    try:
        ig.genera("   ", cartella=TMP, env=env(OPENAI_API_KEY="sk"))
        check("prompt vuoto rifiutato", False)
    except ig.ImageGenError:
        check("prompt vuoto rifiutato", True)
    try:
        ig.genera("x" * (ig.MAX_PROMPT + 1), cartella=TMP,
                  env=env(OPENAI_API_KEY="sk"))
        check("prompt troppo lungo rifiutato", False)
    except ig.ImageGenError as e:
        check("prompt troppo lungo rifiutato", True)
        check("dice il limite", str(ig.MAX_PROMPT) in str(e), str(e))

    print("\n[8] Dimensioni: si manda solo quello che l'API accetta")
    check("1024x1024 passa", ig._dimensione_openai("1024x1024") == "1024x1024")
    check("'square' diventa 1024x1024",
          ig._dimensione_openai("square") == "1024x1024")
    check("'portrait' diventa verticale",
          ig._dimensione_openai("portrait") == "1024x1536")
    check("una dimensione inventata viene omessa",
          ig._dimensione_openai("enorme") == "")

    print("\n[9] Il tool: anteprima per la UI, nessuna immagine al modello")
    from orchestra.tools import image_gen as tool_mod

    tool_mod._root_progetto = lambda: Path(TMP)
    tool = tool_mod.tool_image_gen()
    ig._post_json = finto_openai
    # Il tool legge le chiavi dall'ambiente del processo: qui si mette solo
    # quella finta, e si toglie subito dopo.
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        res = tool.handler(prompt="una montagna al tramonto")
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
    check("restituisce un ToolResult", isinstance(res, ToolResult), type(res))
    check("il testo dice dove sta il file", "immagini" in res.text, res.text)
    check("ha un'anteprima per la UI", len(res.anteprime) == 1,
          str(len(res.anteprime)))
    check("l'anteprima e' una data URL",
          res.anteprime and res.anteprime[0].startswith("data:image/png;base64,"))
    # L'immagine non torna al modello: costa token e non tutti i provider
    # la accettano dentro un messaggio `tool`.
    check("nessuna immagine per il modello", res.immagini == [],
          str(res.immagini[:1]))

    print("\n[10] Modifica: il riferimento diventa multipart (OpenAI)")
    # La modifica OpenAI non e' JSON: e' multipart. Un errore qui non si
    # vede finche' il provider non risponde 400, quindi si controlla il
    # corpo della richiesta vera, non solo che la funzione sia stata
    # chiamata.
    catturato = {}

    class FintaRisposta:
        def __init__(self, corpo):
            self._corpo = corpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._corpo

    def finto_urlopen(req, timeout=0):
        catturato["url"] = req.full_url
        catturato["headers"] = dict(req.headers)
        catturato["data"] = req.data
        return FintaRisposta(json.dumps(
            {"data": [{"b64_json": B64_PNG}]}).encode())

    urlopen_originale = ig.urllib.request.urlopen
    ig.urllib.request.urlopen = finto_urlopen
    try:
        img_edit = ig.genera(
            "rendilo blu", env=env(OPENAI_API_KEY="sk-test"),
            cartella=TMP, riferimento=(PNG_1PX, "image/png"))
    finally:
        ig.urllib.request.urlopen = urlopen_originale
    corpo = catturato.get("data") or b""
    check("la modifica usa /images/edits",
          catturato.get("url") == ig.ENDPOINT_EDITS, str(catturato.get("url")))
    check("l'header dichiara multipart",
          "multipart/form-data" in str(catturato.get("headers")),
          str(catturato.get("headers")))
    check("c'e' il campo model", b'name="model"' in corpo)
    check("c'e' il campo prompt", b'name="prompt"' in corpo)
    check("c'e' il file chiamato image",
          b'name="image"; filename=' in corpo)
    check("il file dichiara il mime", b"Content-Type: image/png" in corpo)
    check("i byte dell'immagine sono nel corpo", PNG_1PX in corpo)
    check("il confine chiude il corpo", corpo.rstrip().endswith(b"--"))
    check("e l'immagine torna", _senza_marcatura(img_edit.dati) == PNG_1PX)

    print("\n[11] Modifica: Google manda l'immagine fra le parti")
    corpi_google = []

    def finto_google_edit(url, corpo_, testa, provider):
        corpi_google.append(corpo_)
        return {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": B64_PNG}}]}}]}

    ig._post_json = finto_google_edit
    img_edit_g = ig.genera(
        "rendilo blu", provider="google", env=env(GEMINI_API_KEY="goog"),
        cartella=TMP, riferimento=(PNG_1PX, "image/png"))
    parti = ((corpi_google[0].get("contents") or [{}])[0].get("parts") or [])
    check("la richiesta ha due parti", len(parti) == 2, str(parti)[:120])
    check("la prima e' il prompt", parti and parti[0].get("text") == "rendilo blu")
    check("la seconda e' l'immagine",
          len(parti) > 1
          and parti[1].get("inlineData", {}).get("data") == B64_PNG)
    check("e l'immagine torna", _senza_marcatura(img_edit_g.dati) == PNG_1PX)

    print("\n[12] Riferimento: data URL, ultimo allegato, percorso")
    ig._post_multipart = finto_multipart = lambda *a, **k: {
        "data": [{"b64_json": B64_PNG}]}
    # Il tool legge le chiavi dall'ambiente: qui basta che ce ne sia una,
    # perche' il provider e' finto.
    os.environ["OPENAI_API_KEY"] = "sk-test"
    data_url = "data:image/png;base64," + B64_PNG
    res_data = tool.handler(prompt="aggiungi un cappello", riferimento=data_url)
    check("una data URL e' un riferimento valido",
          res_data.anteprime and "modificata" in res_data.text,
          res_data.text)
    att.registra_immagini([data_url])
    res_ultimo = tool.handler(prompt="aggiungi un cappello", riferimento="ultimo")
    check("'ultimo' usa l'immagine appena allegata",
          res_ultimo.anteprime and "modificata" in res_ultimo.text,
          res_ultimo.text)
    att._ultime_immagini = []
    res_niente = tool.handler(prompt="x", riferimento="ultimo")
    check("senza allegati 'ultimo' lo dice",
          "nessuna immagine allegata" in res_niente.text, res_niente.text)
    # Rimetterla per il test end-to-end che segue.
    att.registra_immagini([data_url])
    png_su_disco = Path(TMP) / "da-modificare.png"
    png_su_disco.write_bytes(PNG_1PX)
    import orchestra.tools._guard as guard
    guard_originale = guard._safe_path
    guard._safe_path = lambda v: png_su_disco
    try:
        res_path = tool.handler(prompt="cambia sfondo",
                                riferimento="da-modificare.png")
    finally:
        guard._safe_path = guard_originale
    check("un percorso del progetto e' un riferimento valido",
          res_path.anteprime and "modificata" in res_path.text, res_path.text)
    res_non_img = Path(TMP) / "non-immagine.png"
    res_non_img.write_text("testo, non png", encoding="utf-8")
    guard._safe_path = lambda v: res_non_img
    try:
        res_falso = tool.handler(prompt="x", riferimento="non-immagine.png")
    finally:
        guard._safe_path = guard_originale
    check("un file che non e' un'immagine viene rifiutato",
          "non e' un'immagine" in res_falso.text, res_falso.text)
    os.environ.pop("OPENAI_API_KEY", None)

    print("\n[13] Nel loop vero: l'evento porta l'anteprima, il modello no")
    # Il pezzo che manca ai test del tool: cosa arriva davvero alla UI e
    # cosa arriva al modello. Se l'anteprima restasse nel ToolResult e
    # nessuno la mettesse nell'evento, la chat mostrerebbe solo il percorso.
    eventi = []

    class ProviderFinto:
        def __init__(self):
            self.i = 0
            self.name = "finto"
            self.model = "finto-1"

        def chat(self, messages, tools=None, **kw):
            self.i += 1
            if self.i == 1:
                # La modifica della foto allegata: e' il caso che il ponte
                # `ultimo` esiste per rendere possibile.
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCall(
                        id="call_gen", name="image_gen",
                        arguments='{"prompt":"rendila notturna",'
                                  ' "riferimento":"ultimo"}')],
                    model="finto-1")
            return LLMResponse(content="Ecco l'immagine.", model="finto-1")

    agente = Agent(
        ProviderFinto(), default_registry(), "sei un agente",
        LoopConfig(max_iterations=4),
        on_event=lambda kind, data: eventi.append((kind, data)))
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        agente.run("rendi notturna la foto che ti ho allegato", allegati=[
            Attachment(nome="foto.png", kind="image", mime="image/png",
                       immagini=[data_url])])
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
    check("l'agente ricorda l'immagine allegata",
          att.ultima_immagine() == data_url, str(att.ultima_immagine())[:40])
    fini = [d for k, d in eventi if k == "tool_end" and d.get("name") == "image_gen"]
    check("l'evento tool_end c'e'", len(fini) == 1, str(len(fini)))
    check("l'evento porta l'anteprima",
          bool(fini) and len(fini[0].get("images") or []) == 1,
          str(fini[:1])[:200])
    check("l'anteprima e' una data URL",
          bool(fini) and str((fini[0].get("images") or [""])[0]).startswith(
              "data:image/png;base64,"))
    # Il messaggio mandato al modello non contiene l'immagine: il tool ha
    # gia' descritto il risultato, e un'immagine in role="tool" non e'
    # accettata da tutti i provider compatibili.
    msg_tool = [m for m in agente.state.messages if m.role == "tool"]
    check("il messaggio tool non porta immagini",
          bool(msg_tool) and all(not m.images for m in msg_tool),
          str([len(m.images) for m in msg_tool]))

    check("il testo dice che e' una modifica",
          bool(fini) and "modificata" in str(fini[0].get("result")),
          str(fini[:1])[:200])

    print("\n[14] OpenRouter: una API sola, molti modelli")
    corpi_or = []

    def finto_openrouter(url, corpo_, testa, provider):
        corpi_or.append((url, corpo_, testa, provider))
        return {"created": 1,
                "data": [{"b64_json": B64_PNG, "media_type": "image/png"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 4175,
                          "total_tokens": 4175, "cost": 0.04}}

    ig._post_json = finto_openrouter
    img_or = ig.genera("una volpe nel bosco", provider="openrouter",
                       cartella=TMP, env=env(OPENROUTER_API_KEY="or-key"),
                       dimensione="1536x1024")
    url_or, corpo_or, testa_or, prov_or = corpi_or[0]
    check("usa /api/v1/images", url_or == ig.ENDPOINT["openrouter"], url_or)
    check("il provider e' openrouter", prov_or == "openrouter", prov_or)
    check("manda lo slug del modello",
          corpo_or.get("model") == ig.MODELLI["openrouter"], str(corpo_or))
    check("manda un'immagine sola", corpo_or.get("n") == 1, str(corpo_or))
    check("l'autorizzazione e' Bearer",
          testa_or.get("Authorization") == "Bearer or-key", str(testa_or))
    check("dichiara la provenienza a OpenRouter",
          bool(testa_or.get("HTTP-Referer"))
          and bool(testa_or.get("X-OpenRouter-Title")),
          str(testa_or))
    # La taglia standard diventa un rapporto: i modelli xAI rifiutano i pixel.
    check("1536x1024 diventa 3:2", corpo_or.get("aspect_ratio") == "3:2",
          str(corpo_or))
    check("e non manda anche i pixel", "size" not in corpo_or, str(corpo_or))
    check("i byte sono quelli restituiti",
          _senza_marcatura(img_or.dati) == PNG_1PX)
    check("il provider risulta openrouter", img_or.provider == "openrouter")
    check("il modello risulta quello scelto",
          img_or.modello == ig.MODELLI["openrouter"], img_or.modello)
    check("il file esiste", img_or.percorso.exists(), str(img_or.percorso))

    check("1:1 resta 1:1", ig._forma_openrouter("1:1") == {"aspect_ratio": "1:1"})
    check("una proporzione estesa passa",
          ig._forma_openrouter("9:21") == {"aspect_ratio": "9:21"})
    check("una dimensione inventata viene omessa",
          ig._forma_openrouter("enorme") == {})
    check("'auto' non manda niente", ig._forma_openrouter("auto") == {})
    # I pixel espliciti non si mandano: il rapporto si ricava, perche'
    # `size` lo rifiutano quasi tutti i modelli del catalogo.
    check("2048x2048 diventa 1:1",
          ig._forma_openrouter("2048x2048") == {"aspect_ratio": "1:1"})
    check("800x1200 diventa 2:3",
          ig._forma_openrouter("800x1200") == {"aspect_ratio": "2:3"})
    check("un rapporto estremo resta al provider",
          ig._forma_openrouter("3700x100") == {})
    check("un tier di risoluzione non diventa un pixel fasullo",
          ig._forma_openrouter("2K") == {})

    # Modifica: OpenRouter vuole un URL (http o data URL) dentro
    # `input_references`, non un file multipart.
    ig.genera("rendila invernale", provider="openrouter", cartella=TMP,
              env=env(OPENROUTER_API_KEY="or-key"),
              riferimento=(PNG_1PX, "image/png"))
    corpo_rif = corpi_or[-1][1]
    rif = corpo_rif.get("input_references") or []
    check("il riferimento sta in input_references", len(rif) == 1, str(rif)[:120])
    check("il riferimento e' di tipo image_url",
          bool(rif) and rif[0].get("type") == "image_url", str(rif)[:120])
    url_rif = ((rif[0].get("image_url") or {}).get("url") if rif else "") or ""
    check("il riferimento e' una data URL coi byte veri",
          url_rif.startswith("data:image/png;base64,") and B64_PNG in url_rif,
          url_rif[:40])

    # Piu' immagini insieme. Il caso vero e' il poster con dentro il logo e
    # la foto del prodotto: con un riferimento solo l'unica strada e'
    # incollare, e si vede. L'ordine e' l'unico modo che il prompt ha per
    # dire "la prima e' la base, la seconda e' il logo".
    tre = [(PNG_1PX, "image/png"),
           (PNG_1PX + b"uno", "image/png"),
           (PNG_1PX + b"due", "image/jpeg")]
    ig.genera("metti il logo della seconda nel poster della prima",
              provider="openrouter", cartella=TMP,
              env=env(OPENROUTER_API_KEY="or-key"), riferimento=tre)
    rif_tre = (corpi_or[-1][1].get("input_references") or [])

    def _url_di(voce):
        return ((voce.get("image_url") or {}).get("url") or "")

    check("tre riferimenti partono tutti e tre", len(rif_tre) == 3,
          str(rif_tre)[:120])
    check("restano nell'ordine dato",
          len(rif_tre) == 3
          and _url_di(rif_tre[0]).endswith(B64_PNG)
          and _url_di(rif_tre[1]).endswith(
              base64.b64encode(tre[1][0]).decode("ascii")),
          str([_url_di(v)[-16:] for v in rif_tre]))
    check("ognuno porta il suo mime, non quello del primo",
          len(rif_tre) == 3 and _url_di(rif_tre[2]).startswith(
              "data:image/jpeg;base64,"),
          _url_di(rif_tre[2])[:30] if len(rif_tre) == 3 else "")

    # La forma vecchia resta valida: e' quella che chiama chi c'era prima.
    check("un riferimento singolo resta una lista di uno",
          ig._lista_riferimenti((PNG_1PX, "image/png"))
          == [(PNG_1PX, "image/png")])
    check("un elenco resta un elenco", len(ig._lista_riferimenti(tre)) == 3)
    check("senza riferimento non c'e' lista",
          ig._lista_riferimenti(None) == [] and ig._lista_riferimenti("") == [])

    # Il tetto e' del modello, ma oltre il massimo del catalogo si ferma
    # prima di spendere: nessuna richiesta parte.
    prima_del_tetto = len(corpi_or)
    try:
        ig.genera("troppe", provider="openrouter", cartella=TMP,
                  env=env(OPENROUTER_API_KEY="or-key"),
                  riferimento=[(PNG_1PX, "image/png")] * 15)
        check("quindici riferimenti sono un errore", False, "nessun errore")
    except ig.ImageGenError as e:
        check("quindici riferimenti sono un errore", "14" in str(e), str(e)[:120])
    check("e non parte nessuna richiesta", len(corpi_or) == prima_del_tetto)

    # Gli altri due provider: Google mette le immagini fra le parti,
    # OpenAI ripete il campo `image[]` nel multipart.
    _pj, _pm = ig._post_json, ig._post_multipart
    presi_g = {}

    def finto_google_tre(url, corpo_, testa, provider):
        presi_g["corpo"] = corpo_
        return {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": B64_PNG}}]}}]}

    ig._post_json = finto_google_tre
    ig.genera("uniscile", provider="google", cartella=TMP,
              env=env(GEMINI_API_KEY="goog"), riferimento=tre)
    parti_g = ((presi_g.get("corpo") or {}).get("contents") or [{}])[0]
    parti_g = parti_g.get("parts") or []
    inline = [p for p in parti_g if isinstance(p, dict) and p.get("inlineData")]
    check("Google manda tre immagini fra le parti", len(inline) == 3,
          str(len(parti_g)))
    check("e il prompt resta la prima parte",
          bool(parti_g) and parti_g[0].get("text") == "uniscile",
          str(parti_g[:1])[:120])

    presi_o = {}

    def finto_multipart_tre(url, campi, allegati, testa, provider):
        presi_o["allegati"] = list(allegati)
        presi_o["url"] = url
        return {"data": [{"b64_json": B64_PNG}]}

    ig._post_multipart = finto_multipart_tre
    ig.genera("uniscile", provider="openai", cartella=TMP,
              env=env(OPENAI_API_KEY="sk-test"), riferimento=tre)
    campi_usati = [a[0] for a in presi_o.get("allegati") or []]
    nomi_rif = [a[1] for a in presi_o.get("allegati") or []]
    check("OpenAI va su /images/edits",
          presi_o.get("url") == ig.ENDPOINT_EDITS, str(presi_o.get("url")))
    check("ripete il campo image[] per ogni file",
          campi_usati.count("image[]") == 3, str(campi_usati))
    check("con un nome per file, nell'ordine",
          nomi_rif == ["riferimento-1.png", "riferimento-2.png",
                       "riferimento-3.jpg"], str(nomi_rif))

    # Il tool: `riferimenti` deve arrivare fino alla richiesta. E' la parte
    # che l'agente usa davvero, e un parametro raccolto e poi perso e' il
    # difetto piu' silenzioso di tutti.
    os.environ["OPENROUTER_API_KEY"] = "or-key"
    ig._post_json = finto_openrouter
    try:
        res_tre = tool.handler(prompt="uniscile", provider="openrouter",
                              riferimenti=[data_url, data_url, data_url])
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)
    rif_tool = (corpi_or[-1][1].get("input_references") or [])
    check("il tool manda tutti i riferimenti", len(rif_tool) == 3,
          str(len(rif_tool)))
    check("e lo dice nel risultato",
          "3 immagini di riferimento" in res_tre.text, res_tre.text[:140])

    # Tre foto a piena risoluzione in base64 sono peso che il modello non
    # usa e che si paga in token: prima di partire si accorcia il lato lungo.
    try:
        from PIL import Image as _Image
    except ImportError:  # pragma: no cover
        _Image = None
    if _Image is not None:
        import io as _io
        grande = _io.BytesIO()
        _Image.new("RGB", (2400, 1600), (200, 30, 10)).save(
            grande, "JPEG", quality=95)
        pesante = grande.getvalue()
        limite_vero = ig.LIMITE_BYTES_RIFERIMENTI
        ig.LIMITE_BYTES_RIFERIMENTI = 1000
        try:
            ridotti = ig._riduci_riferimenti([(pesante, "image/jpeg")])
        finally:
            ig.LIMITE_BYTES_RIFERIMENTI = limite_vero
        with _Image.open(_io.BytesIO(ridotti[0][0])) as im:
            misura = max(im.size)
        check("un riferimento troppo pesante viene ridotto",
              misura == ig.LATO_RIFERIMENTO, str(misura))
        check("e resta un JPEG", ridotti[0][1] == "image/jpeg",
              ridotti[0][1])
        check("sotto il limite non si tocca",
              ig._riduci_riferimenti([(PNG_1PX, "image/png")])
              == [(PNG_1PX, "image/png")])
    ig._post_json, ig._post_multipart = _pj, _pm

    # `media_type` puo' arrivare con un parametro dopo il `;`: il nome del
    # file non deve diventare `x.png; charset=...`.
    ig._post_json = lambda *a, **k: {"data": [
        {"b64_json": B64_PNG, "media_type": "image/png; charset=binary"}]}
    img_param = ig.genera("un gatto", provider="openrouter", cartella=TMP,
                          env=env(OPENROUTER_API_KEY="or-key"))
    check("il parametro del mime non sporca l'estensione",
          img_param.percorso.suffix == ".png" and img_param.mime == "image/png",
          img_param.percorso.name)

    # I modelli vettoriali (Recraft) restituiscono SVG: salvarlo come .png
    # produrrebbe un file che nessun programma apre.
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>'
    ig._post_json = lambda *a, **k: {"data": [{
        "b64_json": base64.b64encode(svg).decode("ascii"),
        "media_type": "image/svg+xml"}]}
    img_svg = ig.genera("un'icona tonda", provider="openrouter", cartella=TMP,
                        env=env(OPENROUTER_API_KEY="or-key"))
    check("l'SVG si salva come .svg", img_svg.percorso.suffix == ".svg",
          img_svg.percorso.name)
    check("e dichiara il mime giusto", img_svg.mime == "image/svg+xml", img_svg.mime)
    check("l'anteprima e' un'immagine vettoriale",
          img_svg.data_url().startswith("data:image/svg+xml;base64,"))
    check("i byte sono l'SVG", img_svg.dati == svg)

    # Un formato che non sappiamo mostrare non diventa un file .png a caso.
    ig._post_json = lambda *a, **k: {"data": [
        {"b64_json": B64_PNG, "media_type": "image/gif"}]}
    try:
        ig.genera("una gif", provider="openrouter", cartella=TMP,
                  env=env(OPENROUTER_API_KEY="or-key"))
        check("un formato sconosciuto viene rifiutato", False)
    except ig.ImageGenError as e:
        check("un formato sconosciuto viene rifiutato", True)
        check("e dice quale formato era", "image/gif" in str(e), str(e))

    # 402: e' il codice che OpenRouter usa per il saldo, e va distinto da una
    # chiave sbagliata (401), perche' l'azione e' un'altra.
    e402 = ig._errore_http("openrouter", 402, "insufficient credits")
    check("402 parla di saldo, non di chiave",
          "credito" in str(e402).lower() and "saldo" in str(e402).lower(), str(e402))
    check("402 dice come ricaricare", "credits" in str(e402), str(e402))

    print("\n[15] Il catalogo: scegliere uno slug invece di indovinarlo")
    letto = {}

    def finto_get(url, testa, provider):
        letto["url"] = url
        letto["auth"] = testa.get("Authorization")
        return {"data": [
            {"id": "google/gemini-3.1-flash-image",
             "name": "Gemini 3.1 Flash Image",
             "architecture": {"input_modalities": ["text", "image"],
                              "output_modalities": ["image"]},
             "supported_parameters": {"aspect_ratio": {"type": "enum"},
                                      "resolution": {"type": "enum"}}},
            {"id": "x-ai/grok-image", "name": "Grok Image",
             "architecture": {"input_modalities": ["text"]}},
            {"name": "senza id"},
        ]}

    get_originale = ig._get_json
    ig._get_json = finto_get
    try:
        voci = ig.modelli_immagine(env(OPENROUTER_API_KEY="or-key"))
        check("legge /api/v1/images/models", letto.get("url") == ig.ENDPOINT_MODELLI,
              str(letto.get("url")))
        check("manda la chiave se c'e'",
              letto.get("auth") == "Bearer or-key", str(letto.get("auth")))
        check("scarta le voci senza id", len(voci) == 2, str([v["id"] for v in voci]))
        check("sa quali accettano un riferimento",
              voci[0]["riferimento"] is True and voci[1]["riferimento"] is False,
              str([v["riferimento"] for v in voci]))
        check("porta i parametri supportati",
              voci[0]["parametri"] == ["aspect_ratio", "resolution"],
              str(voci[0]["parametri"]))
        check("la voce senza parametri resta vuota",
              voci[1]["parametri"] == [], str(voci[1]["parametri"]))

        res_elenco = tool.handler(elenco_modelli=True)
        check("il tool elenca i modelli",
              "google/gemini-3.1-flash-image" in res_elenco.text, res_elenco.text)
        check("segnala chi accetta riferimenti",
              "immagini di riferimento" in res_elenco.text, res_elenco.text)
        check("e dice come usarne uno",
              'provider="openrouter"' in res_elenco.text, res_elenco.text)
        check("l'elenco non genera immagini", res_elenco.anteprime == [],
              str(res_elenco.anteprime[:1]))
    finally:
        ig._get_json = get_originale

    print("\n[16] Il tool e' nel registro e in tutti i profili")
    reg = default_registry()
    check("image_gen registrato", "image_gen" in reg, str(reg.all_names())[:200])
    for profilo in ("base", "ricerca", "skill", "pieno"):
        reg2 = default_registry()
        applica_profilo(reg2, profilo)
        check(f"attivo nel profilo {profilo}", "image_gen" in reg2.nomi_attivi(),
              str(reg2.nomi_attivi()))
finally:
    ig._post_json = originale

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if FAIL else 0)
