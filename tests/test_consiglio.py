"""Il consiglio: chi siede al tavolo deve vedere la domanda.

Perche' questo file esiste: il consiglio girava con seat che ricevevano la
decisione e le chiavi delle opzioni («A», «B», «C») ma non le etichette, e
il prompt diceva «Read the brief: .../brief.md» a un agente con un registro
di tool vuoto. Il risultato era un dibattito fluente, con citazioni vere,
che punteggiava alternative che non sapeva nominare — e il difetto non si
vede nel verdetto, perche' il verdetto e' scritto dal Chair, che il brief
lo conosceva.

Qui si controlla la cosa che conta e che nessuno vede: **cosa arriva
davvero nel prompt di un seat**. Il provider e' finto (nessuna rete,
nessuna chiave) e tiene in memoria ogni prompt, cosi' il test puo'
legge­rli. La seconda meta' del file verifica la matematica del verdetto:
pesi, band, cap per il rischio di rovina, conteggio dei voti.

Nota: `run_council` scrive in `sessions/` sotto `base_dir`; ogni prova usa
una cartella temporanea, cosi' le sessioni vere dell'utente restano intatte.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Come gli altri test: accenti veri su console Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DATI = tempfile.mkdtemp(prefix="orchestra_consiglio_dati_")
os.environ.setdefault("ORCHESTRA_HOME", DATI)
os.environ.setdefault("ORCHESTRA_ROOT",
                      tempfile.mkdtemp(prefix="orchestra_consiglio_lav_"))

from orchestra import council  # noqa: E402
from orchestra.types import LLMResponse  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


DECISIONE = ("Gestisco un coaching da 30k al mese con 15 clienti a 2.000. "
             "Alzo a 3.500 per tutti, alzo solo ai nuovi, o tengo 2.000?")
ETICHETTA_A = "Alzare a 3.500 per tutti"
ETICHETTA_B = "Tenere 2.000 e alzare solo ai nuovi clienti"
ASSUNZIONE = "Tasso di chiusura attuale sconosciuto: assunto al 50 per cento"
SEAT = ["bezos", "hormozi", "buffett"]

# Quanto ogni seat da' all'opzione A nel round del voto. Scelti per avere
# una media pesata (pesi 2, 3, 2) di 53/7 = 7,57: sopra la soglia del GO.
PUNTI_A = {"Bezos": 7, "Hormozi": 9, "Buffett": 6}
# Il final score e' un voto sulla risoluzione, non sull'opzione: Buffett
# dissente e da' 4. Se i due numeri fossero identici, il test non
# distinguerebbe il supporto alla risoluzione dalla media delle opzioni.
FINALE = {"Bezos": 7, "Hormozi": 9, "Buffett": 4}


def _nome_seat(testo: str) -> str:
    """Quale seat parla in questo prompt.

    Non basta cercare «You hold the ... seat»: il system prompt di ogni
    agente comincia con «You hold the **Strategy and decisions** seat on the
    Roast Room council». Il nome corto arriva solo dal prompt del round, e
    ha una lista chiusa: si cerca quello.
    """
    for nome in PUNTI_A:
        if f"You hold the {nome} seat" in testo:
            return nome
    return ""


class ProviderFinto:
    """Risponde in modo deterministico, e ricorda ogni prompt ricevuto."""

    name = "finto"
    model = "finto-1"

    def __init__(self, ruin_seat: str = ""):
        self.chiamate: list[str] = []
        self.ruin_seat = ruin_seat

    # -- le cinque risposte che il consiglio chiede -----------------------

    def _chair0(self) -> str:
        return json.dumps({
            "options": [{"id": "A", "label": ETICHETTA_A},
                        {"id": "B", "label": ETICHETTA_B}],
            "weights": {
                "bezos": {"weight": 2, "reason": "decisione poco reversibile"},
                "hormozi": {"weight": 3, "reason": "e' un prezzo"},
                "buffett": {"weight": 2, "reason": "tocca il cash"},
            },
            "assumptions": [ASSUNZIONE],
            "brief": ("Coach da 30k al mese, 15 clienti a 2.000; il founder "
                      "valuta un aumento di prezzo."),
        }, ensure_ascii=False)

    def _consiglia(self) -> str:
        return json.dumps({
            "seats": [
                {"key": "bezos", "why": "la reversibilita' della scelta"},
                {"key": "hormozi", "why": "e' un prezzo"},
                {"key": "buffett", "why": "guarda il downside"},
            ],
            "note": "Manca un seat sul prodotto.",
        }, ensure_ascii=False)

    def _cruxes(self) -> str:
        return json.dumps({
            "cruxes": [{
                "question": "Il prezzo alza i ricavi o fa perdere i clienti?",
                "sides": [
                    {"position": "alza", "seats": ["hormozi"]},
                    {"position": "protegge la base", "seats": ["buffett"]},
                ],
            }],
            "unanimous": False,
            "note": "Si combatte sul tasso di chiusura.",
        }, ensure_ascii=False)

    def _draft(self) -> str:
        return json.dumps({
            "option": "A",
            "label": "GO WITH CONDITIONS",
            "recommendation": "Alzare a 3.500, ma solo dopo un test su cinque clienti.",
            "conditions": ["Almeno 4 rinnovi su 5 al prezzo nuovo"],
            "next_steps": ["Chiamare cinque clienti questa settimana"],
            "cheapest_test": "Cinque chiamate, un prezzo, zero sconti.",
            "kill_criteria": "Meno di 2 rinnovi su 5 entro il 30 novembre.",
        }, ensure_ascii=False)

    def _verdict(self) -> str:
        return (
            "# Roast Room: alzare i prezzi\n\n"
            "## Verdict: GO\n\n"
            "**The call:** Alzare a 3.500 per tutti, con il test delle cinque chiamate.\n\n"
            "## Scorecard\n| Seat | Weight | Final stance |\n| --- | --- | --- |\n"
            "| Hormozi | 3 | Endorse |\n\n"
            "## Why the council landed here\n- Hormozi (Value Equation, S115)\n\n"
            "## Glossario\n- CAC: quanto costa acquisire un cliente.\n"
        )

    def _card(self, round_n: int, seat: str) -> str:
        a = PUNTI_A[seat]
        b = 6 if seat == "Buffett" else (4 if seat == "Hormozi" else 5)
        ruin = "likely" if (self.ruin_seat == seat and round_n == 3) else "none"
        if round_n == 1:
            return (
                f"SEAT: {seat}\nSTANCE: Yes\nOPTION SCORES: A 8 · B 5\n"
                f"PILLAR SCORE: 8/10\nCONFIDENCE: 4/5\nRUIN RISK: none\n"
                f"DOOR: two-way\n\nTHE CALL: A, con condizioni.\n"
                f"WHY:\n1. il prezzo e' la leva\n2. il cash\n3. la velocita'\n"
                f"THE RISK I SEE: churn.\nWHAT WOULD CHANGE MY MIND: un test.\n"
                f"WHAT I'D DO THIS WEEK: cinque chiamate.\n"
                f"QUESTION FOR THE FOUNDER: quanto vale un cliente?"
            )
        if round_n == 2:
            # Una citazione vera dal cervello di Bezos e una inventata: il
            # controllo deve trovare la prima e fermare la seconda.
            citazioni = ""
            if seat == "Bezos":
                citazioni = (
                    '\n"Type 2 decisions can and should be made quickly by '
                    'high judgment individuals or small groups." (S063)'
                    '\n"Il prezzo giusto e\' quello che il cliente non '
                    'dimentica." (S999)\n'
                )
            return (
                f"SEAT: {seat}\nI DISAGREE MOST WITH: Buffett.\n"
                f"{citazioni}"
                f"I CONCEDE: il rischio di churn.\nON THE CRUXES: alza, ma testa.\n"
                f"STANCE: Conditional yes\nOPTION SCORES: A 8 · B 5\n"
                f"PILLAR SCORE: 8/10\nCONFIDENCE: 4/5\nRUIN RISK: none\n"
                f"MOVED: yes, from B to A, because il test costa poco\n"
                f"MY CONDITIONS FOR YES: 4 rinnovi su 5."
            )
        voto = {"Buffett": "Dissent", "Hormozi": "Endorse with amendment"}.get(
            seat, "Endorse")
        return (
            f"SEAT: {seat}\nVOTE: {voto}\nOPTION SCORES: A {a} · B {b}\n"
            f"FINAL SCORE: {FINALE[seat]}/10\nFINAL PILLAR SCORE: 8/10\n"
            f"RUIN RISK: {ruin}\n"
            f"AMENDMENT OR DISSENT: {'il test va fatto prima' if voto != 'Endorse' else ''}\n"
            f"ONE LINE FOR THE FOUNDER: alza, ma prima prova."
        )

    def chat(self, messages, tools=None, **kwargs):  # noqa: ANN001
        testo = "\n".join(getattr(m, "content", "") or "" for m in messages)
        self.chiamate.append(testo)
        # L'ordine conta: il prompt del verdict contiene la draft (e quindi
        # "cheapest_test"), quindi il verdict va riconosciuto prima.
        if "CONSIGLIA IL TAVOLO" in testo:
            corpo = self._consiglia()
        elif "ROUND 1 OF" in testo:
            corpo = self._card(1, _nome_seat(testo))
        elif "ROUND 2 OF" in testo:
            corpo = self._card(2, _nome_seat(testo))
        elif "ROUND 3 OF" in testo:
            corpo = self._card(3, _nome_seat(testo))
        elif '"options"' in testo and "Seat al tavolo" in testo:
            corpo = self._chair0()
        elif '"cruxes"' in testo:
            corpo = self._cruxes()
        elif "Scrivi il verdict.md completo" in testo:
            corpo = self._verdict()
        elif '"cheapest_test"' in testo:
            corpo = self._draft()
        else:
            corpo = self._verdict()
        return LLMResponse(content=corpo, model=self.model)


def esegui(base: str, ruin_seat: str = ""):
    prov = ProviderFinto(ruin_seat=ruin_seat)
    esito = council.run_council(DECISIONE, seats=list(SEAT), rounds=3,
                                provider=prov, base_dir=base)
    return prov, esito


print("\n[1] al seat arrivano le opzioni, non solo le chiavi")
base1 = tempfile.mkdtemp(prefix="orchestra_consiglio_1_")
prov1, esito1 = esegui(base1)
r1 = [c for c in prov1.chiamate if "ROUND 1 OF" in c]
check("il round 1 chiede un parere a ogni seat", len(r1) == len(SEAT),
      f"{len(r1)} prompt")
check("ogni prompt nomina l'opzione A per esteso",
      all(ETICHETTA_A in c for c in r1), r1[0][:300] if r1 else "")
check("e anche l'opzione B", all(ETICHETTA_B in c for c in r1),
      r1[0][:300] if r1 else "")
check("con le assunzioni del Chair sui numeri mancanti",
      all(ASSUNZIONE in c for c in r1), r1[0][-400:] if r1 else "")
check("e la decisione originale del founder",
      all("15 clienti a 2.000" in c for c in r1), r1[0][:300] if r1 else "")

print("\n[2] nessuno ordina piu' di leggere file che non puo' aprire")
tutti = "\n".join(prov1.chiamate)
check("niente «Read the brief» nei prompt", "Read the brief" not in tutti)
check("e nessun prompt manda il seat a leggere brief.md o round-1.md",
      "brief.md" not in tutti and "round-1.md" not in tutti)
check("niente percorsi del progetto originale",
      ".claude/skills" not in tutti and "REPO ROOT" not in tutti)
sys_bezos = council.advisor_system_prompt("bezos")
check("il system prompt non dice di leggere `_hot.md`",
      "Read `_hot.md`" not in sys_bezos, sys_bezos[:200])
check("ma il cervello c'e' dentro", "HOT SHEET" in sys_bezos
      and "FRAMEWORKS" in sys_bezos)
check("e la sezione riscritta dice che non ci sono tool",
      "You have no tools" in sys_bezos, sys_bezos[:400])
check("il resto dell'agente resta intatto (lente e voce)",
      "## Your lens" in sys_bezos and "## How you talk" in sys_bezos)

print("\n[3] round 2 e 3 portano il contesto che serve")
r2 = [c for c in prov1.chiamate if "ROUND 2 OF" in c]
r3 = [c for c in prov1.chiamate if "ROUND 3 OF" in c]
check("il round 2 contiene i card del round 1",
      r2 and all("THE CALL: A, con condizioni." in c for c in r2), str(len(r2)))
check("e i cruxes del Chair",
      r2 and all("Il prezzo alza i ricavi" in c for c in r2))
check("il round 3 contiene la draft resolution",
      r3 and all("Alzare a 3.500, ma solo dopo un test" in c for c in r3))
check("e le opzioni anche nel voto",
      r3 and all(ETICHETTA_A in c for c in r3))

print("\n[4] la matematica del verdetto")
sc = esito1["scoring"]
# (2*7 + 3*9 + 2*6) / 7 = 53/7 = 7,571...
check("media pesata delle opzioni", sc["option_weighted"]["A"] == 7.6,
      str(sc["option_weighted"]))
check("l'opzione raccomandata e' quella con la media piu' alta",
      sc["recommended"] == "A", sc["recommended"])
check("band GO sopra la soglia di 7,5", sc["band"] == "GO", sc["band"])
check("spread 9-6", sc["spread"] == 3, str(sc["spread"]))
# Il round del voto non chiede CONFIDENCE: se la confidenza non torna
# indietro dal round 2, il consiglio direbbe sempre 10/10.
check("la confidenza viene dal round 2 quando il voto non la chiede",
      sc["confidence"] == 8, str(sc["confidence"]))
check("supporto alla risoluzione pesato sui final score",
      sc["resolution_support"] == 7.0, str(sc["resolution_support"]))

print("\n[5] voti e minority report")
check("un endorse, un emendamento, un dissenso",
      sc["votes"] == {"endorse": 1, "amend": 1, "dissent": 1}, str(sc["votes"]))
verdetto = json.load(open(os.path.join(esito1["session_dir"], "verdict.json"),
                          encoding="utf-8"))
check("la minority e' chi ha dissentito", verdetto["minority"]["seat"] == "Buffett",
      str(verdetto["minority"]))
check("solo chi ha scritto un emendamento compare in elenco",
      [a["seat"] for a in verdetto["amendments"]] == ["Hormozi", "Buffett"],
      str(verdetto["amendments"]))

print("\n[6] il cap per il rischio di rovina abbassa il verdetto")
base2 = tempfile.mkdtemp(prefix="orchestra_consiglio_2_")
prov2, esito2 = esegui(base2, ruin_seat="Buffett")
sc2 = esito2["scoring"]
check("senza il cap la band sarebbe GO",
      sc2["option_weighted"]["A"] == 7.6, str(sc2["option_weighted"]))
check("con un seat in ruin likely la band scende a RESHAPE",
      sc2["band"] == "RESHAPE", sc2["band"])
check("e il verdetto lo dice", "Ruin cap" in sc2["override_note"],
      sc2["override_note"])

print("\n[7] la sessione resta completa su disco")
cartella = esito1["session_dir"]
for nome in ("brief.md", "round-1.md", "round-2.md", "round-3.md",
             "cruxes.json", "draft.json", "draft-resolution.md",
             "verdict.md", "verdict.json", "citazioni.json", "provider.json"):
    check(f"c'e' {nome}", os.path.exists(os.path.join(cartella, nome)))
brief = open(os.path.join(cartella, "brief.md"), encoding="utf-8").read()
check("il brief su disco elenca le etichette", ETICHETTA_A in brief, brief[:300])
check("e le assunzioni", ASSUNZIONE in brief, brief[:300])
testo_verdetto = open(os.path.join(cartella, "verdict.md"), encoding="utf-8").read()
check("il verdetto e' markdown con la band", "## Verdict: GO" in testo_verdetto,
      testo_verdetto[:200])
check("e ha il glossario richiesto dal template", "## Glossario" in testo_verdetto)

print("\n[8] nessun seat e' finito in errore")
check("nessuna card e' un messaggio d'errore",
      "[errore:" not in json.dumps(esito1["seat_data"], ensure_ascii=False))

print("\n[9] ogni seat ha tutto il suo cervello")
mancanti = []
for s in council.load_roster():
    sp = council.advisor_system_prompt(s["key"])
    if ("## PRINCIPLES" not in sp or "## FRAMEWORKS" not in sp
            or "## VOICE" not in sp or "[sezione troncata" in sp):
        mancanti.append(s["key"])
check("tutti e dodici i cervelli entrano interi (principi, framework, voce)",
      not mancanti, str(mancanti))
sp_musk = council.advisor_system_prompt("musk")
check("il cervello piu' grande supera gli 85.000 caratteri",
      len(sp_musk) > 85_000, str(len(sp_musk)))
check("e non e' un troncamento mascherato",
      "[sezione troncata" not in sp_musk)

print("\n[10] il tavolo lo propone il Chair, e non sono tutti")
check("il tavolo abituale ha sette nomi", len(council.tavolo_default()) == 7,
      str(council.tavolo_default()))
check("la modalita' del roster e' «ask»", council.modalita_tavolo() == "ask",
      council.modalita_tavolo())
cons = council.consiglia_tavolo(DECISIONE, provider=ProviderFinto())
check("la proposta non supera sette seat", len(cons["seats"]) <= 7, str(cons["seats"]))
check("e tiene il seat del downside", "buffett" in cons["seats"], str(cons["seats"]))
check("con il perche' per ogni scelto",
      all(cons["why"].get(k) for k in cons["seats"]), str(cons["why"]))
base3 = tempfile.mkdtemp(prefix="orchestra_consiglio_3_")
esito3 = council.run_council(DECISIONE, seats=None, rounds=1,
                             provider=ProviderFinto(), base_dir=base3)
check("senza seats espliciti siede il tavolo proposto",
      esito3["seats"] == cons["seats"], f'{esito3["seats"]} vs {cons["seats"]}')
check("e non tutti e dodici", len(esito3["seats"]) < len(council.load_roster()),
      str(esito3["seats"]))

print("\n[11] le citazioni si controllano col cervello")
cit = esito1["citazioni"]
check("due citazioni con fonte nei card di Bezos", cit["controllate"] == 2,
      str(cit["controllate"]))
check("una e' verbatim, una e' inventata", cit["non_trovate"] == 1,
      str(cit["non_trovate"]))
inventata = [c for c in cit["voci"] if not c["trovata"]]
check("e la fonte inventata e' S999",
      bool(inventata) and inventata[0]["fonte"] == "S999",
      str(inventata[:1]))
verdetto_cit = open(os.path.join(cartella, "verdict.md"), encoding="utf-8").read()
check("il verdetto dichiara il controllo",
      "## Citazioni verificate" in verdetto_cit)
check("e nomina la citazione non trovata", "S999" in verdetto_cit)

print("\n[12] il consiglio usa il provider che gli e' stato dato")
check("il provider finto e' registrato nel risultato",
      esito1["provider"] == "finto", esito1["provider"])
prov_file = json.load(open(os.path.join(cartella, "provider.json"),
                           encoding="utf-8"))
check("e scritto accanto alla sessione, col modello",
      prov_file.get("provider") == "finto" and prov_file.get("model") == "finto-1",
      str(prov_file))

print("\n" + "=" * 62)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
sys.exit(1 if FAIL else 0)
