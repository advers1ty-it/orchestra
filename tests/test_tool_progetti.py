"""Il tool `progetti`: elenco, scheda dell'attivo, nota.

Il confine da verificare e' quello che il tool NON fa: non cambia il
progetto attivo. Il progetto e' la cartella in cui i tool scrivono, e
spostarla e' una decisione dell'utente (UI) o del riconoscimento
deterministico dell'intento, non del modello.

Il resto e' informazione che prima l'agente non aveva: quali progetti
esistono, con che percorso e nota, quando sono stati usati l'ultima
volta, e cosa c'e' scritto su quello attivo.

Niente rete, niente dati veri: tutto in una cartella temporanea.
"""

from __future__ import annotations

import os
import sys
import tempfile

# ORCHESTRA_HOME prima degli import: progetti legge l'ambiente all'import.
_TMP = tempfile.mkdtemp(prefix="orchestra_tool_progetti_")
os.environ["ORCHESTRA_HOME"] = os.path.join(_TMP, "dati")
os.makedirs(os.environ["ORCHESTRA_HOME"], exist_ok=True)
os.environ["ORCHESTRA_ROOT"] = os.path.join(_TMP, "radice")

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

from orchestra import progetti as pr                       # noqa: E402
from orchestra.tools.progetti import tool_progetti          # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


def chiama(**kwargs) -> str:
    return tool_progetti().handler(**kwargs)


P1 = os.path.join(_TMP, "lavori", "sito-ristorante")
P2 = os.path.join(_TMP, "lavori", "app-parrucchieri")
P3 = os.path.join(_TMP, "lavori", "archivio")
for percorso in (P1, P2, P3):
    os.makedirs(percorso, exist_ok=True)

pr.registra("Sito Ristorante", P1,
            note="Cliente: Trattoria da Gino.\nConsegna: venerdi'.",
            alias="restaurant site, menu")
pr.registra("App Parrucchieri", P2, note="Solo iOS per ora.",
            alias="salon")
pr.registra("Archivio", P3, note="")
pr.tocca("Sito Ristorante")
check("un progetto mai usato non mostra una data finta",
      not any("1970" in r for r in chiama(azione="elenca").splitlines()),
      chiama(azione="elenca")[:400])
pr.registra_file("Sito Ristorante", os.path.join(P1, "menu.json"))

print("\n[1] L'elenco mostra percorso, nota e ultimo uso")

# Un progetto attivo simulato: il tool legge il nome dal thread, come in
# produzione (Session._prepara_root lo imposta nel thread del turno).
pr._set_root_sessione(P1, "Sito Ristorante")
elenco = chiama(azione="elenca")
check("ci sono tutti e tre", all(n in elenco for n in
      ("Sito Ristorante", "App Parrucchieri", "Archivio")), elenco[:400])
check("il percorso c'e'", os.path.abspath(P1) in elenco, elenco[:400])
check("la nota c'e', su una riga", "Trattoria da Gino" in elenco
      and "\nConsegna" not in elenco, elenco[:400])
check("l'ultimo uso c'e'", "ultimo uso:" in elenco, elenco[:400])
check("il progetto attivo e' segnato", "(attivo)" in elenco, elenco[:400])
check("i file toccati si contano", "1 file toccato" in elenco, elenco[:400])

print("\n[2] Il limite taglia, e lo dice")

corto = chiama(azione="elenca", limite=2)
check("due righe di progetto", sum(1 for r in corto.splitlines()
                                   if r.startswith("- ")) == 2, corto)
check("il taglio e' dichiarato", "altri progetti non mostrati: 1" in corto,
      corto)

print("\n[3] La scheda dell'attivo")

stato = chiama(azione="stato")
check("dice il nome", "Progetto attivo: Sito Ristorante" in stato, stato)
check("dice la cartella", os.path.abspath(P1) in stato, stato)
check("dice la nota", "Trattoria da Gino" in stato, stato)
check("dice gli alias", "Chiamato anche:" in stato
      and "restaurant site" in stato, stato)
check("dice i file toccati", "menu.json" in stato, stato)
check("dichiara che non sposta il progetto", "non sposta la cartella" in stato,
      stato)

print("\n[4] La nota si aggiorna, e solo la nota")

prima = pr.per_nome("Sito Ristorante")
esito = chiama(azione="nota", testo="Cliente: Gino.\nConsegna: lunedi'.")
dopo = pr.per_nome("Sito Ristorante")
check("il tool conferma", "Nota del progetto" in esito
      and "aggiornata" in esito, esito)
check("la nota e' cambiata", "Consegna: lunedi'." in (dopo.get("note") or ""),
      str(dopo.get("note")))
check("il percorso non e' cambiato",
      dopo.get("percorso") == prima.get("percorso"),
      f"{prima.get('percorso')} -> {dopo.get('percorso')}")
check("gli alias non sono cambiati",
      dopo.get("alias") == prima.get("alias"),
      f"{prima.get('alias')} -> {dopo.get('alias')}")
check("il progetto attivo non e' cambiato",
      pr._root_progetto() == "Sito Ristorante", pr._root_progetto())
check("la nuova nota si legge con stato",
      "Consegna: lunedi'." in chiama(azione="stato"))

svuota = chiama(azione="nota", testo="")
check("la nota vuota svuota", "svuotata" in svuota
      and not (pr.per_nome("Sito Ristorante").get("note") or "").strip(),
      svuota)

print("\n[5] Senza progetto attivo si dice, non si indovina")

pr._set_root_sessione("", "")
note_prima = {p.get("nome"): p.get("note") for p in pr.tutti()}
senza = chiama(azione="stato")
check("stato spiega che non c'e' un attivo", "Nessun progetto attivo" in senza,
      senza)
rifiuto = chiama(azione="nota", testo="qualcosa")
check("la nota senza progetto si rifiuta", "Nessun progetto attivo" in rifiuto,
      rifiuto)
note_dopo = {p.get("nome"): p.get("note") for p in pr.tutti()}
check("e non ha scritto niente su nessun progetto",
      note_dopo == note_prima, str(note_dopo))

print("\n[6] Azione sconosciuta, errore leggibile")

sbagliata = chiama(azione="cancella")
check("elenca le azioni vere", "elenca, stato, nota" in sbagliata, sbagliata)

print(f"\n{len(PASS)} passati, {len(FAIL)} falliti")
if FAIL:
    print("FALLITI: " + ", ".join(FAIL))
    sys.exit(1)
