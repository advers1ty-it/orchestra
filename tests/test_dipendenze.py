"""Le dipendenze del pannello: una lista sola, letta da requirements.txt.

Il difetto che questo test tiene chiuso: il pannello **Opzioni → Dipendenze**
aveva la sua lista scritta a mano dentro il gestore della rotta (ddgs,
faster-whisper, cloudflared) e non leggeva `requirements.txt`. Nessun altro
lo leggeva: né l'installer, né `orchestra update`. Quindi `Pillow` e `pypdf`,
aggiunti al file, non comparivano nel pannello, non si potevano installare
da lì, e il tool diceva all'utente "installa Pillow" mentre il pannello non
lo nominava.

Il test verifica le tre cose che rendono utile quella lista:

- legge il file vero (e non una seconda copia che può divergere);
- dice lo stato vero, distinguendo un pacchetto che c'è, uno che manca e
  uno il cui modulo non corrisponde al nome (Pillow → PIL);
- il pulsante "Installa" costruisce il comando giusto per ogni voce, senza
  una catena di `if` da aggiornare a mano.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ORCHESTRA_ROOT",
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from orchestra import dipendenze as dep  # noqa: E402
from orchestra.rotte_sistema import RotteSistema  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


print("\n[1] Il file dei requisiti è la lista, e si legge")
voci = dep.requisiti()
nomi = [n.lower() for n, _s in voci]
check("legge requirements.txt", bool(voci), str(voci))
check("c'è ddgs", "ddgs" in nomi, str(nomi))
check("c'è Pillow", "pillow" in nomi, str(nomi))
check("c'è pypdf", "pypdf" in nomi, str(nomi))
check("i commenti non diventano dipendenze",
      not any(n.startswith("#") or n.startswith("-") for n in nomi), str(nomi))
specifiche = {n.lower(): s for n, s in voci}
check("la specifica di versione viene conservata",
      specifiche.get("pillow", "").startswith(">="), str(specifiche))
check("e quella di pypdf", specifiche.get("pypdf", "").startswith(">="),
      str(specifiche))

print("\n[2] Un file con commenti e opzioni si legge lo stesso")
with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, "requirements.txt"), "w", encoding="utf-8") as f:
        f.write("# commento\n"
                "\n"
                "pkg-a>=1.2  # con commento in coda\n"
                "pkg-b[extra]==2.0\n"
                "-r altro.txt\n"
                "pkg-c; sys_platform == 'win32'\n")
    voci2 = dep.requisiti(d)
    check("tre voci vere, non cinque", len(voci2) == 3, str(voci2))
    check("gli extras non rompono il nome", voci2[1][0] == "pkg-b", str(voci2))
    check("il marcatore d'ambiente si scarta", voci2[2][0] == "pkg-c", str(voci2))

    # Senza file (installazione da wheel) il pannello non resta vuoto.
    vuota = dep.requisiti(os.path.join(d, "niente"))
    check("file assente: c'è la lista minima", len(vuota) >= 3, str(vuota))

print("\n[3] Lo stato dice la verità, modulo per modulo")
stato = {d["nome"].lower(): d for d in dep.stato()}
check("ddgs c'è (è installato qui)", stato["ddgs"]["stato"] == "ok",
      str(stato.get("ddgs")))
check("pypdf c'è", stato["pypdf"]["stato"] == "ok", str(stato.get("pypdf")))
check("Pillow c'è", stato["pillow"]["stato"] == "ok", str(stato.get("pillow")))
check("Pillow si cerca come PIL, non come Pillow",
      dep._modulo("Pillow") == "PIL", dep._modulo("Pillow"))
check("la versione è quella vera, non '?'",
      bool(stato["pillow"].get("versione")) and stato["pillow"]["versione"] != "?",
      str(stato["pillow"]))
check("ogni voce dice perché serve", all(d.get("perche") for d in stato.values()),
      str({k: v.get("perche") for k, v in stato.items()}))
check("cloudflared è ancora in elenco, con la sua via",
      stato.get("cloudflared", {}).get("via") == "winget",
      str(stato.get("cloudflared")))
check("le opzionali restano visibili",
      "faster-whisper" in stato, str(sorted(stato)))

print("\n[4] Il comando di installazione è quello giusto")
cmd = dep.comando_installazione("Pillow")
check("Pillow si installa con pip e la sua specifica",
      cmd is not None and "pip" in cmd and any("Pillow>=" in p for p in cmd),
      str(cmd))
check("il comando usa l'interprete in uso",
      cmd is not None and cmd[0] == sys.executable, str(cmd))
check("il nome è indifferente a maiuscole e underscore",
      dep.comando_installazione("pillow") == cmd
      and dep.comando_installazione("PILLOW") == cmd, str(cmd))
check("pypdf ha il suo comando",
      any("pypdf" in p for p in (dep.comando_installazione("pypdf") or [])),
      str(dep.comando_installazione("pypdf")))
cf = dep.comando_installazione("cloudflared")
check("cloudflared passa da winget, non da pip",
      cf is not None and cf[0] == "winget", str(cf))
check("faster-whisper accetta anche il nome col trattino basso",
      dep.comando_installazione("faster_whisper") ==
      dep.comando_installazione("faster-whisper"),
      str(dep.comando_installazione("faster_whisper")))
check("un nome inventato non inventa un comando",
      dep.comando_installazione("pacchetto-inventato") is None)


class FintaRotta:
    """Il minimo per chiamare i gestori senza un server."""

    def __init__(self) -> None:
        self.risposta: tuple | None = None

    def _json(self, dati, code: int = 200) -> None:
        self.risposta = (dati, code)


print("\n[5] Le rotte del pannello usano quella lista, non una loro copia")
# Le rotte sono due (GET e POST) perche' il pannello e' nato chiamando la
# GET e qualcuno ha aggiunto la POST dopo: due copie della stessa risposta,
# e per un po' una delle due e' rimasta indietro con la lista vecchia —
# proprio quella che l'interfaccia chiama. Quindi si provano entrambe.
for etichetta, funzione in (("GET", RotteSistema._r_get_dipendenze_stato),
                            ("POST", RotteSistema._r_post_dipendenze_stato)):
    finta = FintaRotta()
    funzione(finta, "/api/dipendenze/stato", {}, None)
    dati, code = finta.risposta
    nomi_rotta = [d["nome"].lower() for d in dati["deps"]]
    check(f"{etichetta}: la rotta risponde", code == 200, str(code))
    check(f"{etichetta}: contiene Pillow", "pillow" in nomi_rotta, str(nomi_rotta))
    check(f"{etichetta}: contiene pypdf", "pypdf" in nomi_rotta, str(nomi_rotta))
    check(f"{etichetta}: il python in uso è quello giusto",
          dati.get("python", "").startswith(str(sys.version_info[0])),
          str(dati.get("python")))
    check(f"{etichetta}: la lista è quella del modulo",
          nomi_rotta == [d["nome"].lower() for d in dep.stato()], str(nomi_rotta))

finta2 = FintaRotta()
RotteSistema._r_post_dipendenze_installa(finta2, "/api/dipendenze/installa",
                                         {"nome": "inventato"}, None)
dati2, code2 = finta2.risposta
check("un nome sconosciuto: 400 e nessun comando lanciato", code2 == 400, str(code2))
check("e lo dice", "sconosciuta" in (dati2.get("error") or ""), str(dati2))

print("\n" + "=" * 62)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
