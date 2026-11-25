"""I pulsanti di fine turno: le mosse che servono adesso, gia' scritte.

PERCHE' ESISTE

A turno finito si fa quasi sempre una di quattro cose: controllare di non
avere rotto qualcosa, rileggere le proprie modifiche, committare, oppure
decidere cosa fare dopo. Sono frasi che si riscrivono ogni volta, e quella
che servirebbe davvero — "quali test coprono i file che ho appena toccato?"
— viene in mente quando non serve piu'.

Due strade, in quest'ordine.

1. Un modello rilegge l'ultimo scambio e scrive 3-4 proposte su misura:
   la decisione di progetto ancora aperta, le parole giuste per un
   messaggio, il caso che nessuno ha provato. E' il consigliere vero —
   quello che sa cosa state facendo, non cosa si fa di solito.
2. Se il modello non c'e', non risponde in tempo o risponde male, restano
   le proposte ricavate dai fatti del turno: file del riepilogo, test che
   portano il loro nome, git del progetto. Sono meno brillanti ma vere.

Un pulsante che promette "controlla di non avere rotto niente" e poi
incolla un prompt generico sarebbe peggio di nessun pulsante: sembrerebbe
che qualcuno abbia guardato, e non e' vero. Per questo la strada 2 resta,
ma la 1 non deve mai produrre un titolo che varrebbe per qualsiasi
progetto.

Il commit e' l'eccezione: quando ci sono modifiche non committate il suo
pulsante c'e' sempre, accodato dopo i consigli. Non occupa un posto dei
consigli — il modello ne scrive al massimo tre, e il quarto e' suo.

Il prompt si scrive per intero. Premere il pulsante COMPILA il campo, non
manda niente: l'ultima parola resta a chi preme, che puo' correggere prima
di inviare.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from typing import Any, Callable

# Quattro pulsanti: oltre, la scelta non e' piu' una scelta. E quattro file
# nominati per esteso: un prompt che elenca quaranta percorsi non si legge,
# e quindi non si corregge prima di mandarlo.
MASSIMO = 4
NOMINATI = 4
# Quante proposte scrive il modello. Una in meno del massimo visibile:
# l'ultimo posto resta al commit quando c'e' qualcosa da committare, cosi'
# il pulsante non toglie spazio a un consiglio.
MODELLO = 3

# Quanto si aspetta il modello prima di mostrare le proposte fisse. I
# consigli sono un extra: meglio quattro pulsanti onesti fra dodici secondi
# che una casella vuota per un minuto. Il thread continua e mette il
# risultato in cache per chi chiede dopo (la chat del telefono, per esempio).
ATTESA = 12.0

# La cache e' per TURNO, non per chiamante: la finestra e il telefono
# chiedono gli stessi consigli, e senza si pagherebbe due volte la stessa
# domanda ottenendo due liste diverse. Otto voci bastano: oltre, sono
# turni che nessuno sta piu' guardando.
_CACHE: dict[str, list[dict[str, Any]]] = {}
_IN_CORSO: dict[str, threading.Event] = {}
_LOCK = threading.Lock()
_CACHE_MASSIMO = 8


def _file(rie: dict[str, Any]) -> list[dict[str, Any]]:
    """I file del turno, tenendo solo le voci che si possono nominare."""
    return [f for f in (rie or {}).get("file") or []
            if isinstance(f, dict) and f.get("percorso")]


def _elenco(files: list[dict[str, Any]], massimo: int = NOMINATI) -> str:
    """I file con le righe cambiate, e quanti restano fuori."""
    pezzi = []
    for f in files[:massimo]:
        percorso = str(f.get("percorso") or "?")
        aggunte = int(f.get("aggiunte") or 0)
        tolte = int(f.get("tolte") or 0)
        pezzi.append(f"{percorso} (+{aggunte}/-{tolte})"
                     if (aggunte or tolte) else percorso)
    resto = len(files) - len(pezzi)
    if resto > 0:
        pezzi.append(f"e altri {resto}")
    return ", ".join(pezzi)


def test_per(percorso: str, radice: str) -> str:
    """Il comando del test che porta il nome di questo file, se c'e'.

    `orchestra/skills.py` -> `tests/test_skills.py`. Non si indovina oltre
    il nome: un test nominato per sbaglio fa eseguire la suite sbagliata, e
    un pulsante che sembra una verifica ma verifica altro e' peggio di uno
    che non c'e'.
    """
    if not radice:
        return ""
    nome = os.path.basename(str(percorso or "").replace("\\", "/"))
    if not nome.endswith(".py") or len(nome) <= 3:
        return ""
    base = nome[:-3]
    if not base.startswith("test_"):
        base = "test_" + base
    if os.path.isfile(os.path.join(radice, "tests", base + ".py")):
        return f"python tests/{base}.py"
    return ""


def sporchi(radice: str) -> list[str]:
    """I file non committati del progetto, o [] se non e' un repo git.

    Letto, non eseguito: `git status --porcelain` non tocca niente. Se git
    non c'e' o la cartella non e' un repository si torna vuoto, e la
    proposta del commit sparisce — meglio nessun pulsante che uno che
    fallisce quando lo premi.
    """
    if not radice or not os.path.isdir(radice):
        return []
    try:
        esito = subprocess.run(
            ["git", "-C", radice, "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    if esito.returncode != 0:
        return []
    file: list[str] = []
    for riga in (esito.stdout or "").splitlines():
        percorso = riga[3:].strip() if len(riga) > 3 else ""
        # Le rinomine arrivano come "vecchio -> nuovo": quello che conta
        # per un commit e' il nome che ha adesso.
        if " -> " in percorso:
            percorso = percorso.split(" -> ", 1)[1]
        percorso = percorso.strip().strip('"')
        if percorso:
            file.append(percorso)
    return file


def _verifica(rie: dict[str, Any], radice: str) -> dict[str, Any] | None:
    """Cosa puo' essersi rotto: i file del turno e i test che li coprono."""
    file = _file(rie)
    if not file:
        return None
    comandi: list[str] = []
    for f in file[:NOMINATI]:
        comando = test_per(str(f.get("percorso") or ""), radice)
        if comando and comando not in comandi:
            comandi.append(comando)
    if comandi:
        parte = ("I test che portano il loro nome sono "
                 + ", ".join(f"`{c}`" for c in comandi)
                 + ": eseguili, e `python tests/run_all.py` per il giro "
                   "intero. ")
    else:
        parte = ("Per questi file non c'e' un test che ne porta il nome: cerca "
                 "quali test li importano e, se non ce n'e' nessuno, dillo "
                 "invece di scriverne uno nuovo. ")

    esito = str((rie or {}).get("esito_testo") or "").strip()
    errori = int((rie or {}).get("errori") or 0)
    if errori:
        apertura = (f"Il turno si e' chiuso con {errori} errori di tool"
                    f"{' (' + esito + ')' if esito else ''}. ")
    elif esito and esito != "finito":
        apertura = f"Il turno si e' chiuso cosi': {esito}. "
    else:
        apertura = ""

    prompt = (
        f"Il turno appena finito ha toccato {len(file)} file: "
        f"{_elenco(file)}.\n\n"
        f"{apertura}Guardali uno per uno e cerca quello che si rompe senza "
        "fare rumore: chi chiama le funzioni cambiate, i rami nuovi che "
        "nessun test attraversa, i comportamenti cambiati per sbaglio. "
        + parte +
        "Alla fine dimmi cosa hai trovato, con file e riga. Non correggere "
        "niente finche' non te lo dico."
    )
    return {"id": "verifica", "titolo": "Controlla cosa puo' essersi rotto",
            "prompt": prompt}


def _revisione(rie: dict[str, Any], sporchi_: list[str]) -> dict[str, Any] | None:
    """La revisione critica di quello che c'e' sul tavolo."""
    file = _file(rie)
    if file:
        oggetto = f"le modifiche del turno ({_elenco(file)})"
    elif sporchi_:
        oggetto = f"le {len(sporchi_)} modifiche non committate"
    else:
        return None
    prompt = (
        f"Rileggi in modo critico {oggetto} — quelle soltanto, non tutto il "
        "progetto (guarda il diff, non riscrivere da capo). Semplifica: togli "
        "quello che non serve (codice morto, controlli ridondanti, parametri "
        "che nessuno passa, rami che non si verificano mai), accorpa cio' che "
        "dice la stessa cosa, e lascia il comportamento identico. Se qualcosa "
        "e' utile ma scritto male, sistemalo invece di cancellarlo. Alla fine "
        "elencami cosa hai tolto e perche', e cosa hai deciso di NON toccare."
    )
    return {"id": "revisione", "titolo": "Revisione di quello che ho toccato",
            "prompt": prompt}


def _commit(sporchi_: list[str]) -> dict[str, Any] | None:
    """Il commit, se c'e' qualcosa da committare."""
    if not sporchi_:
        return None
    elenco = ", ".join(sporchi_[:8])
    if len(sporchi_) > 8:
        elenco += f" e altri {len(sporchi_) - 8}"
    quanti = "un file" if len(sporchi_) == 1 else f"{len(sporchi_)} file"
    prompt = (
        f"Ci sono {quanti} con modifiche non committate: {elenco}.\n\n"
        "Fai commit di queste modifiche, con un messaggio che spiega perche' "
        "sono state fatte e non solo cosa e' cambiato: una o due frasi, "
        "specifiche, niente elenchi di file. Tieni fuori quello che non "
        "c'entra (archivi, file generati, roba non tracciata). Non pushare."
    )
    return {"id": "commit", "titolo": f"Commit di quello che c'e' ({quanti})",
            "prompt": prompt}


def _seguito(rie: dict[str, Any]) -> dict[str, Any]:
    """Cosa fare dopo: c'e' sempre, ed e' l'unica che non ha prerequisiti."""
    file = _file(rie)
    dopo = (f"dopo aver toccato {_elenco(file, 2)}" if file
            else "dopo questo scambio")
    prompt = (
        f"Cosa resta aperto {dopo}? Rileggi il lavoro fatto e proponi tre "
        "follow-up concreti, ognuno con il perche' e con quanto costa in "
        "tempo. Niente liste generiche: cose che si possono iniziare adesso, "
        "con il file o il modulo da cui partire, e dimmi quale faresti per "
        "prima."
    )
    return {"id": "seguito", "titolo": "Cosa resta aperto", "prompt": prompt}


# -- proposte scritte dal modello -----------------------------------------

# Il prompt e' un contratto: le famiglie di mossa, i divieti che tengono le
# proposte attaccate a QUESTO turno, e il formato JSON. Senza i divieti il
# modello ricade nella lista generica ("cosa resta aperto"), che e' proprio
# quello che queste proposte devono sostituire.
ISTRUZIONI = """Sei l'orchestratore di Orchestra, un assistente di programmazione.
Un turno di lavoro e' appena finito. Il tuo compito non e' riassumerlo: e'
proporre le prossime mosse che aiuterebbero davvero l'utente adesso.

Scegli 3 proposte (non di piu') fra queste famiglie, solo quelle che qui
hanno senso:
- una decisione di progetto ancora aperta: una scelta fra due strade, un
  compromesso, un confine da fissare; di' cosa cambia in ciascuna;
- una scelta di comunicazione o di testo: nomi, messaggi d'errore,
  etichette, tono, copy della UI;
- una verifica mirata su cio' che il turno ha cambiato: il caso che nessuno
  ha provato, non "esegui tutti i test";
- il prossimo passo concreto, se il turno ne ha lasciato uno a meta'.

Regole ferree:
- Ogni proposta nasce da QUESTO scambio: nomina file, funzioni, testi o
  concetti che compaiono davvero nella conversazione. Niente frasi buone
  per qualsiasi progetto.
- Non proporre di rifare, rileggere o ripulire cio' che il turno ha appena
  fatto, se non c'e' un motivo concreto emerso.
- Non allargare il lavoro: puoi proporre una scelta, non una funzione che
  l'utente non ha chiesto.
- Non proporre di fare commit: quando c'e' qualcosa da committare il suo
  pulsante e' gia' li', fuori da questi consigli.
- Il prompt e' quello che l'utente premerebbe e manderebbe: in italiano,
  prima persona, specifico, 2-4 frasi, con le informazioni per partire
  senza rileggere la chat.
- Il titolo e' un imperativo breve (max 45 caratteri), diverso dagli altri.

Rispondi SOLO con JSON valido, senza testo attorno:
{"proposte": [{"titolo": "...", "prompt": "..."}]}
"""


def _prompt_dinamico(rie: dict[str, Any], radice: str,
                     conversazione: str, sporchi_: list[str]) -> str:
    """Le istruzioni, i fatti del turno e l'ultimo scambio."""
    file = _file(rie)
    comandi: list[str] = []
    for f in file[:NOMINATI]:
        comando = test_per(str(f.get("percorso") or ""), radice)
        if comando and comando not in comandi:
            comandi.append(comando)
    righe = [f"Esito del turno: {rie.get('esito_testo') or 'finito'}."]
    righe.append(f"File toccati: {_elenco(file, 6)}." if file
                 else "File toccati: nessuno.")
    righe.append("Test che li coprono: "
                 + (", ".join(f"`{c}`" for c in comandi) + "."
                    if comandi else "nessuno con quel nome."))
    if sporchi_:
        righe.append("Modifiche non committate: "
                     + ", ".join(sporchi_[:6]) + ".")
    righe += ["", "Ultimo scambio:", (conversazione or "").strip()[-5000:]]
    return ISTRUZIONI + "\n" + "\n".join(righe)


def _valida(testo: str) -> list[dict[str, Any]]:
    """Trasforma la risposta del modello in pulsanti, o [] se non e' usabile.

    Una proposta sola non e' una scelta: se il modello ne scrive una, la
    risposta e' probabilmente monca e si ricade sulle fisse. Titoli e
    prompt si ripuliscono qui, non nel chiamante: Telegram tronca a 60
    caratteri e un titolo tagliato a meta' non si capisce.
    """
    t = (testo or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    inizio, fine = t.find("{"), t.rfind("}")
    try:
        dato = (json.loads(t[inizio:fine + 1])
                if 0 <= inizio < fine else None)
    except (ValueError, TypeError):
        dato = None
    grezze = dato.get("proposte") if isinstance(dato, dict) else None
    if not isinstance(grezze, list):
        return []
    fuori: list[dict[str, Any]] = []
    visti: set[str] = set()
    for voce in grezze:
        if not isinstance(voce, dict):
            continue
        titolo = " ".join(str(voce.get("titolo") or "").split())
        titolo = titolo.strip(" .:;-")
        prompt = str(voce.get("prompt") or "").strip()
        if not titolo or len(prompt) < 60 or titolo.lower() in visti:
            continue
        visti.add(titolo.lower())
        fuori.append({"id": f"dinamico-{len(fuori)}",
                      "titolo": titolo[:60], "prompt": prompt[:1500]})
        if len(fuori) >= MODELLO:
            break
    return fuori if len(fuori) >= 2 else []


def _una_volta(chiave: str,
               genera: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Genera una volta per turno, aspettando al massimo `ATTESA`.

    Chi arriva secondo aspetta la generazione gia' in corso invece di
    pagarne una seconda: e' il caso normale, perche' la finestra e il
    telefono chiedono quasi insieme. Chi aspetta e non riceve in tempo usa
    le fisse; se il risultato arriva dopo, resta in cache per la prossima
    richiesta dello stesso turno.
    """
    with _LOCK:
        pronto = _CACHE.get(chiave)
        if pronto:
            return list(pronto)
        evento = _IN_CORSO.get(chiave)
        if evento is None:
            evento = _IN_CORSO[chiave] = threading.Event()

            def lavora() -> None:
                try:
                    lista = genera() or []
                except Exception:  # noqa: BLE001 - un consiglio in meno
                    lista = []
                with _LOCK:
                    if lista:
                        _CACHE[chiave] = list(lista)
                        while len(_CACHE) > _CACHE_MASSIMO:
                            _CACHE.pop(next(iter(_CACHE)))
                    _IN_CORSO.pop(chiave, None)
                evento.set()

            threading.Thread(target=lavora, daemon=True,
                             name="orchestra-suggerimenti").start()
    evento.wait(max(0.0, ATTESA))
    with _LOCK:
        return list(_CACHE.get(chiave) or [])


def proposte(rie: dict[str, Any] | None = None, *,
             radice: str = "",
             stato_git: Callable[[], list[str]] | None = None,
             massimo: int = MASSIMO,
             provider: Any = None,
             conversazione: str = "") -> list[dict[str, Any]]:
    """I pulsanti da mostrare a fine turno, dal piu' urgente al piu' aperto.

    Prima si prova a farli scrivere al modello sul turno vero; se non c'e',
    se e' lento o se risponde male, restano quelli ricavati dai fatti.
    `stato_git` esiste per i test: leggere il git vero renderebbe il test
    dipendente dal repository in cui gira.
    """
    if massimo <= 0:
        return []
    rie = rie or {}
    sporchi_ = list((stato_git or (lambda: sporchi(radice)))() or [])
    # Il commit prenota il suo posto PRIMA del modello: cosi' non viene
    # scartato dal taglio quando i consigli sono gia' al completo. Se il
    # modello non risponde, il commit resta comunque nella lista fissa.
    commit = _commit(sporchi_)
    posti_modello = massimo - (1 if commit else 0)
    dal_modello: list[dict[str, Any]] = []
    if (posti_modello > 0 and (conversazione or "").strip()
            and callable(getattr(provider, "chat", None))):
        ts = rie.get("ts")
        if ts:
            def genera() -> list[dict[str, Any]]:
                from .types import Message

                prompt = _prompt_dinamico(rie, radice, conversazione, sporchi_)
                risposta = provider.chat(
                    [Message(role="user", content=prompt)], tools=None)
                return _valida(getattr(risposta, "content", "") or "")

            dal_modello = _una_volta(
                f"{ts}|{rie.get('traccia_id') or ''}", genera
            )[:posti_modello]
    if dal_modello:
        fuori = list(dal_modello)
        if commit:
            fuori.append(commit)
        return fuori[:massimo]
    tutte = [_verifica(rie, radice),
             _revisione(rie, sporchi_),
             commit,
             _seguito(rie)]
    return [p for p in tutte if p][:massimo]
