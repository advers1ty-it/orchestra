"""Lo screenshot deve arrivare al modello come IMMAGINE.

`computer_screenshot` e `browser_screenshot` scrivono un file e dicono
dove. Ma un file non è uno schermo: il modello riceve un percorso e non
ha modo di guardare. Questo test copre il pezzo che chiude il cerchio —
`screenshot_view` — e soprattutto che l'immagine arrivi DENTRO il
messaggio `tool`, non come testo.

Il punto importante non è che il tool legga il file (siamo noi a
scriverlo, sappiamo che c'è). È che il risultato diventi una
`Message.images`: se resta una stringa, il modello non vede nulla e lo
strumento è decorativo.
"""

from __future__ import annotations

import base64
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ORCHESTRA_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestra import Agent, LoopConfig, default_registry  # noqa: E402
from orchestra.tools import _PROFILI  # noqa: E402
from orchestra.types import ToolCall, ToolResult  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


# Un PNG vero, minimo: 1x1 pixel. Serve un file con il magic number
# giusto, perché `allega` guarda i byte e non il nome: un file con
# estensione .png e contenuto di testo viene rifiutato, ed è meglio
# così.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "2mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# La cartella vive per tutto il file: se la chiudessi prima della sezione
# [3], il file sparirebbe lì e il test segnalerebbe un difetto che non
# c'è (l'agente che non trova il file). Si pulisce in fondo.
_d = tempfile.mkdtemp(prefix="orchestra_shot_")
p = os.path.join(_d, "schermo.png")
with open(p, "wb") as f:
    f.write(PNG_1PX)

try:
    print("\n[1] Il tool esiste e fa parte del registro")
    r = default_registry()
    check("screenshot_view registrato", "screenshot_view" in r.all_names(),
          "non c'è nel registro: il modello non lo vede mai")
    check("screenshot_view attivo", r.get("screenshot_view") in r.active,
          "registrato ma non attivo: il modello non lo riceve")
    check("ha una descrizione che spiega quando serve",
          len(r.get("screenshot_view").description) > 40)

    print("\n[2] Leggere uno screenshot vero")
    res = r.get("screenshot_view").handler(nome_file=p)
    check("restituisce un ToolResult", isinstance(res, ToolResult), type(res))
    check("porta una data URL immagine",
          len(res.immagini) == 1
          and res.immagini[0].startswith("data:image/png;base64,"),
          f"immagini={res.immagini[:1]}")
    check("il base64 è quello del file",
          bool(res.immagini)
          and res.immagini[0].split(",", 1)[1]
          == base64.b64encode(PNG_1PX).decode(),
          "il contenuto dell'immagine non corrisponde al file")
    check("il testo dice cosa è",
          "png" in res.text.lower() or "screenshot" in res.text.lower(),
          res.text)

    # Un percorso che non esiste: errore chiaro, mai un crash.
    manca = r.get("screenshot_view").handler(nome_file=os.path.join(_d, "niente.png"))
    check("file assente: messaggio utile",
          isinstance(manca, ToolResult) and "non trovo" in manca.text.lower(),
          manca.text)

    # Un file che non è un'immagine: il magic number decide, non il nome.
    falso = os.path.join(_d, "finto.png")
    with open(falso, "wb") as f:
        f.write(b"questo e' testo, non un png")
    res_falso = r.get("screenshot_view").handler(nome_file=falso)
    check("file non immagine: non mente",
          isinstance(res_falso, ToolResult) and not res_falso.immagini,
          f"ha mandato come immagine qualcosa che non lo è: "
          f"{res_falso.immagini[:1]}")

    # Senza nome: il modello deve capire che gli serve il percorso.
    vuoto = r.get("screenshot_view").handler(nome_file="")
    check("senza nome: dice che serve il percorso",
          "serve" in vuoto.text.lower(), vuoto.text)

    print("\n[3] L'immagine arriva dal tool, non dal testo")
    # Il tool da solo non basta: serve che l'agente la prenda dal
    # risultato. Se la ignorasse, il modello riceverebbe solo il percorso
    # e non vedrebbe nulla — lo strumento esisterebbe ma sarebbe inutile.
    agente = Agent(provider=None, registry=r, system_prompt="sei un agente",
                   config=LoopConfig())
    testo, ok, immagini = agente._execute_tool("screenshot_view", {"nome_file": p})
    check("l'agente prende le immagini dal risultato",
          len(immagini) == 1 and immagini[0].startswith("data:image/"),
          f"immagini={immagini[:1]}")
    check("e il testo resta leggibile (non il base64)",
          "png" in testo.lower() and "base64" not in testo,
          testo)
    check("il tool conta come riuscito", ok is True, str(ok))

    # Un tool che non esiste non deve rompere il contratto a 3 valori.
    t2, ok2, img2 = agente._execute_tool("non_esiste", {})
    check("tool inesistente: tre valori",
          isinstance(t2, str) and ok2 is False and img2 == [],
          f"{type(t2)} {ok2} {img2}")

    print("\n[4] La coppia screenshot + vista è nello stesso profilo")
    check("computer_screenshot nel profilo pieno",
          "computer_screenshot" in _PROFILI.get("pieno", set()),
          "manca: si può catturare ma non leggere")
    check("screenshot_view nel profilo pieno",
          "screenshot_view" in _PROFILI.get("pieno", set()),
          "manca: il modello non lo riceve")

    print("\n[5] Il formato del provider non deve perderla")
    # OpenAI: `Message.to_api` la attacca come parte di contenuto. E' la
    # forma che quasi tutti i gateway capiscono.
    from orchestra.types import Message
    m = Message(role="tool", content="ecco lo screenshot",
                tool_call_id="t1", name="screenshot_view",
                images=["data:image/png;base64,QUJD"])
    api = m.to_api()
    parti = api["content"]
    check("OpenAI: l'immagine e' una parte di contenuto",
          any(p.get("type") == "image_url" and "QUJD" in p["image_url"]["url"]
              for p in parti),
          str(parti))
    check("OpenAI: il testo viene prima dell'immagine",
          parti[0]["type"] == "text" and parti[-1]["type"] == "image_url",
          str(parti))

    # Anthropic: il risultato di un tool e' un `tool_result` dentro un
    # messaggio `user`, e l'immagine deve stare DENTRO quel blocco. Se
    # finisce nel ramo `else` (solo testo), il modello Anthropic non
    # vede nulla.
    from orchestra.providers import AnthropicAdapter, _blocco_immagine
    check("data URL valida -> blocco Anthropic",
          _blocco_immagine("data:image/png;base64,QUJD")["source"]["data"] == "QUJD")
    check("data URL rotta -> None (non un blocco a meta')",
          _blocco_immagine("data:image/png;base64,") is None)
    check("non e' una data URL -> None", _blocco_immagine("schermo.png") is None)

    ad = AnthropicAdapter.__new__(AnthropicAdapter)
    convertito = ad._convert_messages([
        Message(role="user", content="guarda lo schermo"),
        Message(role="assistant", content="",
                tool_calls=[ToolCall(id="t1", name="screenshot_view", arguments="{}")]),
        Message(role="tool", content="ecco lo screenshot", tool_call_id="t1",
                name="screenshot_view", images=["data:image/png;base64,QUJD"]),
    ])
    _, corpo = convertito
    blocco_tool = next(b for b in corpo
                       if isinstance(b.get("content"), list)
                       and b["content"] and b["content"][0].get("type") == "tool_result")
    dentro = blocco_tool["content"][0]["content"]
    check("Anthropic: l'immagine e' dentro tool_result",
          isinstance(dentro, list)
          and any(p.get("type") == "image" and p["source"]["data"] == "QUJD"
                  for p in dentro),
          str(dentro))
    check("Anthropic: il testo accompagna, dopo l'immagine",
          dentro[-1].get("type") == "text" and "screenshot" in dentro[-1]["text"],
          str(dentro))

    print("\n[6] La compaction non lascia un'immagine costosa da sola")
    from orchestra.context import compact_tools
    msgs = [Message(role="system", content="S"), Message(role="user", content="obiettivo")]
    for i in range(10):
        msgs.append(Message(role="tool", content=f"risultato {i}" + "x" * 500,
                            tool_call_id=f"t{i}", name="screenshot_view",
                            images=["data:image/png;base64,QUJD"]))
    n = compact_tools(msgs, keep_recent=2)
    vecchi = [m for m in msgs[:len(msgs) - 2] if m.role == "tool"]
    check("ha potato qualcosa", n > 0, f"pruned={n}")
    check("i vecchi non hanno piu' l'immagine",
          all(not m.images for m in vecchi),
          f"un'immagine e' rimasta: {[len(m.images) for m in vecchi]}")
    check("il testo e' diventato il segnaposto",
          all(m.content.startswith("[potato") for m in vecchi),
          vecchi[0].content[:60])
    check("i recenti conservano immagine e testo",
          msgs[-1].images and msgs[-1].content.startswith("risultato"),
          f"images={bool(msgs[-1].images)} content={msgs[-1].content[:30]}")

finally:
    shutil.rmtree(_d, ignore_errors=True)

print("\n" + "=" * 62)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
