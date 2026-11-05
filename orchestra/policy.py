"""La policy di un bot: quali tool, e quale shell.

CHE COSA E' QUESTO, E CHE COSA NON E'

Questa e' una policy IN-PROCESS. Non e' una sandbox del sistema
operativo: il bot gira nello stesso processo di Orchestra, con le stesse
chiavi e gli stessi permessi dell'utente. Quello che cambia e' cosa il
modello puo' CHIEDERE: un registro di tool ristretto, e un elenco di
comandi shell ammessi.

Non ferma un processo che l'utente ha gia' autorizzato, non isola la
memoria, non toglie le variabili d'ambiente. Se serve un confine vero
servono processi separati (o un container), ed e' un altro lavoro.
Dirlo qui evita la fiducia sbagliata: una policy che sembra una
sandbox e' peggio di nessuna policy.

QUATTRO LISTE, NON UNA

- `tools`: i tool che il bot puo' usare. Vuota = decide il profilo.
  Se c'e', e' un limite: si parte dal profilo e si toglie tutto il
  resto. Non allarga mai: un tool fuori dal profilo resta fuori anche
  se compare qui.
- `nega_tools`: i tool da spegnere comunque. Vince su `tools`.
- `shell`: i comandi che `run_shell` puo' eseguire, per nome del
  programma (`git`, `npm`, `python`). Vuota = tutti quelli che il
  profilo consente.
- `nega_shell`: sottostringhe che bloccano il comando intero, sempre.
  Vince su `shell`, e serve anche quando la shell non e' in allowlist:
  e' il caso "lascia la shell, ma non `rm -rf`".

PERCHE' LA SHELL NON E' UN PARSER

`shell` confronta il PRIMO comando di ogni sezione (`;`, `&&`, `||`,
`|`, newline). Non e' un parser completo della shell: un programma
ammesso puo' fare quello che vuole — `git` puo' invocare un hook,
`python` puo' eseguire codice arbitrario. L'allowlist serve a togliere
i comandi che non c'entrano, non a trasformare un interprete in un
giocattolo. Chi da' `python` a un bot gli sta dando tutto, e la policy
non lo nasconde.

Per questo, quando l'allowlist e' attiva, si rifiutano anche le
sostituzioni di comando (`$(...)`, backtick, `<(…)`, `>(…)`): sono un
modo per eseguire un programma che non e' il primo della riga. Le
virgolette singole le rendono testo e passano; le doppie NO, perche'
la shell esegue `$(...)` e i backtick anche dentro le doppie.
"""

from __future__ import annotations

import json
import re
import shlex
import threading
from typing import Any

# Le liste non hanno un motivo per essere lunghe: una policy con 200
# tool e' un profilo scritto a mano, non una policy. Il tetto evita che
# un JSON sbagliato porti in giro una lista enorme dentro ogni turno.
MAX_VOCI = 100
MAX_VOCE = 200

_CHIAVI = ("tools", "nega_tools", "shell", "nega_shell")

_LOCALE = threading.local()


def _testo(valore: Any) -> str:
    return str(valore or "").strip()[:MAX_VOCE]


def _lista(valore: Any) -> list[str]:
    """Una lista di stringhe, da lista o da stringa separata da virgole.

    Il formato a virgole esiste perche' e' quello che si scrive in una
    casella di testo: chiedere un array JSON all'utente e' un errore di
    sintassi in attesa di accadere.
    """
    if valore is None:
        return []
    if isinstance(valore, str):
        # Un JSON incollato per sbaglio e' meglio accettarlo che
        # trasformarlo in una voce sola con dentro le parentesi.
        testo = valore.strip()
        if testo.startswith("["):
            try:
                valore = json.loads(testo)
            except (ValueError, TypeError):
                valore = testo.split(",")
        else:
            valore = testo.split(",")
    if not isinstance(valore, (list, tuple, set)):
        return []
    out: list[str] = []
    for voce in valore:
        v = _testo(voce)
        if not v:
            continue
        if v.lower() not in [o.lower() for o in out]:
            out.append(v)
        if len(out) >= MAX_VOCI:
            break
    return out


def _norm_tool(nome: str) -> str:
    return _testo(nome).lower()


def normalizza(policy: Any) -> dict[str, list[str]]:
    """La policy come la si salva: quattro liste, niente altro.

    Una policy illeggibile non deve diventare una policy vuota in
    silenzio: quella si' che sarebbe pericolosa, perche' "vuota"
    significa "nessun limite". Un valore che non e' un oggetto viene
    letto come policy vuota, ma solo perche' non c'e' niente da
    interpretare; le chiavi sconosciute si ignorano.
    """
    if isinstance(policy, str):
        try:
            policy = json.loads(policy)
        except (ValueError, TypeError):
            policy = {}
    if not isinstance(policy, dict):
        return {k: [] for k in _CHIAVI}
    out = {k: _lista(policy.get(k)) for k in _CHIAVI}
    out["tools"] = [_norm_tool(v) for v in out["tools"]]
    out["nega_tools"] = [_norm_tool(v) for v in out["nega_tools"]]
    return out


def vuota(policy: Any) -> bool:
    """Vero se la policy non limita niente.

    Non basta che il dizionario sia vuoto: `{"tools": []}` e' la stessa
    cosa di niente, e chi la legge lo deve poter capire senza guardare
    dentro ogni chiave.
    """
    return not any(normalizza(policy).values())


def attivi(registro: Any) -> list[Any]:
    """I tool attivi, dai due registri che l'app usa.

    `tools.ToolRegistry` ha `elenco_attivi`/`disattiva` (API italiana),
    `types.ToolRegistry` ha `active`/`deactivate` (API inglese). La
    sessione puo' ricevere l'uno o l'altro — i test usano il secondo —
    e una policy che funziona solo con uno dei due e' una policy che
    spegne tutto o niente a seconda di chi la chiama.
    """
    if hasattr(registro, "elenco_attivi"):
        return list(registro.elenco_attivi())
    return list(getattr(registro, "active", []) or [])


def spegni(registro: Any, nome: str) -> None:
    if hasattr(registro, "disattiva"):
        registro.disattiva(nome)
    else:
        registro.deactivate(nome)


def applica_al_registro(registro: Any, policy: Any) -> dict[str, list[str]]:
    """Toglie dal registro i tool che la policy non consente.

    Si applica DOPO il profilo: la policy restringe, non allarga. Un
    tool che il profilo ha spento non torna acceso perche' compare
    nella lista `tools`; un tool che il profilo ha acceso e la policy
    non nomina viene spento se `tools` non e' vuota.
    """
    p = normalizza(policy)
    consentiti = set(p["tools"])
    vietati = set(p["nega_tools"])
    for tool in attivi(registro):
        nome = str(getattr(tool, "name", "")).lower()
        if nome in vietati or (consentiti and nome not in consentiti):
            spegni(registro, nome)
    return p


# ---------------------------------------------------------------------------
# Policy del turno in corso
# ---------------------------------------------------------------------------

# Il registro e' per sessione, ma `run_shell` non lo riceve: e' un
# handler con la firma `(command, timeout)`, e passargli la sessione
# vorrebbe dire cambiare la firma di tutti i tool. Il turno gira in un
# thread suo, quindi la policy del turno sta nel thread. Chi non ha
# attivato niente (CLI, benchmark) non ha limiti: e' il comportamento
# di prima, e non si cambia per gli altri.
def attiva(policy: Any) -> dict[str, list[str]]:
    p = normalizza(policy)
    _LOCALE.policy = p
    return p


def disattiva() -> None:
    _LOCALE.policy = None


def corrente() -> dict[str, list[str]]:
    p = getattr(_LOCALE, "policy", None)
    return normalizza(p) if p is not None else {k: [] for k in _CHIAVI}


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------

def _sezioni(command: str) -> list[str]:
    """Spezza il comando sui separatori che ESEGUONO un altro comando.

    Rispetta le virgolette: `echo "a; b"` e' una sezione sola. Non
    rispetta le sostituzioni (che sono un'altra cosa, e si controllano
    prima), ne' i separatori dentro `$(...)`; per questo le
    sostituzioni vengono rifiutate quando l'allowlist e' attiva.
    """
    fuori: list[str] = []
    buf: list[str] = []
    quote = ""
    escape = False
    for ch in command:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\" and quote != "'":
            buf.append(ch)
            escape = True
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            continue
        if ch in ";|&\n":
            fuori.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    fuori.append("".join(buf))
    return fuori


def _sostituzione(command: str) -> bool:
    """Vero se il comando esegue una sostituzione.

    Solo le virgolette SINGOLE rendono la sostituzione testo. Le
    doppie no: `echo "$(whoami)"` esegue `whoami`, ed e' il caso che
    conta. Trattare le doppie come le singole sarebbe un buco nella
    regola, non una semplificazione.
    """
    quote = ""
    escape = False
    for i, ch in enumerate(command):
        if escape:
            escape = False
            continue
        if ch == "\\" and quote != "'":
            escape = True
            continue
        if ch == "'":
            quote = "" if quote == "'" else ("'" if not quote else quote)
            continue
        if ch == '"':
            quote = "" if quote == '"' else ('"' if not quote else quote)
            continue
        if quote == "'":
            continue
        if ch == "`":
            return True
        if ch in "$<>" and command[i + 1:i + 2] == "(":
            return True
    return False


def _primo_comando(sezione: str) -> str:
    """Il nome del programma che la sezione esegue per prima.

    Salta le assegnazioni d'ambiente (`FOO=bar git status`), che non
    sono il programma. Senza, un comando con una variabile davanti
    verrebbe confrontato con `FOO=bar` e rifiutato anche se `git` era
    consentito.
    """
    s = sezione.strip()
    if not s:
        return ""
    try:
        parti = shlex.split(s, posix=False)
    except ValueError:
        parti = s.split()
    for parte in parti:
        p = parte.strip().strip("\"'")
        if not p:
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", p):
            continue
        return p
    return ""


def _nome_programma(command: str) -> str:
    nome = _primo_comando(command).replace("\\", "/").rsplit("/", 1)[-1]
    if nome.lower().endswith(".exe"):
        nome = nome[:-4]
    return nome.lower()


def _consentito(command: str, consentiti: list[str]) -> bool:
    if not consentiti:
        return True
    ammessi = set()
    for c in consentiti:
        n = c.replace("\\", "/").rsplit("/", 1)[-1].lower()
        ammessi.add(n[:-4] if n.endswith(".exe") else n)
    for sezione in _sezioni(command):
        nome = _nome_programma(sezione)
        if nome and nome not in ammessi:
            return False
    # Un comando fatto solo di assegnazioni non esegue niente: non c'e'
    # un programma da confrontare, e bloccarlo sarebbe un falso positivo.
    return True


# Comandi che distruggono la macchina e non hanno un uso legittimo dentro
# un progetto. Non sono la policy del bot: valgono SEMPRE, anche senza
# policy. "Nessuna policy" vuol dire "nessun limite sui tool del bot",
# non "puoi formattare il disco": un agente che sbaglia una variabile non
# deve poter cancellare la radice, e l'utente non ha modo di fermarlo
# mentre il comando gira.
#
# La lista e' volutamente corta e specifica. Bloccare "tutto cio' che e'
# distruttivo" non e' possibile (ogni `rm` lo e' per qualcuno), e una
# regola troppo larga verrebbe aggirata o disattivata. Questi sono i casi
# in cui il danno e' irreversibile e il beneficio e' nullo.
_RADICI = r"(?:/|/\*|~/?|\$home|%userprofile%|%systemdrive%|[a-z]:[\\/]?\*?)"

_DISTRUTTIVI: tuple[tuple[str, str], ...] = (
    (r"\brm\s+(?:-{1,2}[a-z-]+\s+)*" + _RADICI + r"(?=\s|$|;|&|\|)",
     "cancellazione ricorsiva di una radice (rm -rf /)"),
    (r"\brm\s+(?:-[a-z]*[rf][a-z]*\s+)+\./?(?=\s|$)",
     "cancellazione dell'intera cartella di lavoro (rm -rf .)"),
    (r"\brm\s+(?:-[a-z]*[rf][a-z]*\s+)+\*(?=\s|$)",
     "cancellazione di tutto il contenuto della cartella (rm -rf *)"),
    (r"\b(del|erase)\s+[^\n|;&]*(?:/[fsq]\b[^\n|;&]*){1,4}[a-z]:[\\/]?(?:\*|\\|\s|$)",
     "cancellazione di un intero disco (del /f /s /q)"),
    (r"\b(rd|rmdir)\s+(?:/[sq]\s+)*[a-z]:[\\/]?(?:\*|\s|$)",
     "cancellazione di un intero disco (rd /s /q)"),
    (r"\bformat\s+[a-z]:", "formattazione di un disco (format)"),
    (r"\bmkfs(?:\.\w+)?\b", "formattazione di un filesystem (mkfs)"),
    (r"\bdd\b[^\n]*\bof\s*=\s*/dev/",
     "scrittura diretta su un device (dd of=/dev/...)"),
    (r"\bdiskpart\b", "partizionamento del disco (diskpart)"),
    (r"\bbcdedit\b", "modifica del boot loader (bcdedit)"),
    (r"\bvssadmin\s+delete\b", "cancellazione delle shadow copy (vssadmin)"),
    (r"\bcipher\s+/w\b", "cancellazione sicura del disco (cipher /w)"),
    (r"\b(clear-disk|initialize-disk|format-volume)\b",
     "inizializzazione di un disco (PowerShell)"),
    (r"\breg\s+delete\s+(hklm|hkey_local_machine)\b",
     "cancellazione del registro di sistema"),
    (r"\bshutdown\s+(/s|/r|-h|-p)\b", "spegnimento o riavvio della macchina"),
    (r"\b(stop-computer|restart-computer)\b",
     "spegnimento o riavvio della macchina"),
    (r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bchmod\s+-R\s+777\s+/\s*$", "permessi aperti su tutto il filesystem"),
)


def _distruttivo(testo: str) -> str | None:
    """Il motivo per cui il comando e' catastrofico, o None.

    Si normalizzano gli spazi prima di cercare: `rm   -rf   /` e
    `rm -rf /` sono lo stesso comando, e la prima forma e' quella che
    basta per non far scattare un controllo scritto con un solo spazio.
    """
    low = re.sub(r"\s+", " ", str(testo or "").lower()).strip()
    for schema, motivo in _DISTRUTTIVI:
        if re.search(schema, low):
            return motivo
    return None


# Comandi che dentro il progetto fanno danni veri ma recuperabili. Non si
# bloccano come quelli sopra: `rm -rf build/` e' normale, e un agente che
# non puo' pulire una cartella di lavoro e' un agente che si arrende. Si
# CHIEDONO, perche' quello che manca non e' il permesso di cancellare: e'
# il momento in cui qualcuno guarda cosa sta per sparire. Il checkpoint
# copre i file modificati, non quelli cancellati.
_RISCHIOSI: tuple[tuple[str, str], ...] = (
    (r"\brm\s+(?:-{1,2}[\w-]+\s+)*-?[\w]*[rf][\w]*\b",
     "cancellazione con rm (-r o -f)"),
    (r"\b(rd|rmdir)\s+/s\b", "cancellazione ricorsiva di una cartella (rd /s)"),
    (r"\b(del|erase)\s+[^|;&]*/s\b", "cancellazione ricorsiva (del /s)"),
    (r"\bremove-item\b[^|;&]*-recurse\b",
     "cancellazione ricorsiva (Remove-Item -Recurse)"),
    (r"\bgit\s+reset\s+--hard\b",
     "git reset --hard: butta le modifiche non committate"),
    (r"\bgit\s+clean\s+-[a-z]*f",
     "git clean -f: cancella i file non tracciati"),
    (r"\bgit\s+(?:checkout|restore)\s+(?:--\s+)?\.",
     "git checkout/restore sui file: riporta indietro il lavoro"),
    (r"\bgit\s+stash\s+(?:drop|clear)\b",
     "git stash drop/clear: butta le modifiche messe da parte"),
    (r"\btruncate\s+-s\s*0\b", "svuotamento di un file (truncate -s 0)"),
)


def rischio_operativo(command: str) -> str | None:
    """Il motivo per cui il comando va confermato, o None.

    Diverso da `_distruttivo`: quelli non si eseguono mai, questi si
    eseguono se l'utente dice di si'. La distinzione e' il punto — un
    `rm -rf` dentro il progetto e' un comando di lavoro, un `rm -rf /`
    non lo e'.
    """
    low = re.sub(r"\s+", " ", str(command or "").lower()).strip()
    for schema, motivo in _RISCHIOSI:
        if re.search(schema, low):
            return motivo
    return None


def motivo_blocco(command: str) -> str | None:
    """Perche' questo comando non si puo' eseguire, o None.

    Il messaggio dice la regola, non solo "no": un modello che riceve
    un divieto senza motivo riprova uguale, e un umano che legge il log
    non sa quale lista cambiare.
    """
    p = corrente()
    testo = str(command or "")
    minuscolo = testo.lower()

    # Prima di tutto: i comandi che distruggono la macchina. Non dipendono
    # dalla policy del bot, e non c'e' una scelta dell'utente che li
    # renda accettabili.
    catastrofico = _distruttivo(testo)
    if catastrofico:
        return f"comando distruttivo bloccato: {catastrofico}"

    for vietato in p["nega_shell"]:
        if vietato.lower() in minuscolo:
            return (f"la policy vieta i comandi che contengono "
                    f"{vietato!r} (nega_shell)")
    consentiti = p["shell"]
    if not consentiti:
        return None
    if _sostituzione(testo):
        return ("la policy consente solo comandi espliciti, e questo usa "
                "una sostituzione di comando ($(...), backtick o <(...))")
    if not _consentito(testo, consentiti):
        primo = _nome_programma(testo) or "?"
        return (f"la policy consente solo: {', '.join(consentiti)} "
                f"(questo comando usa {primo!r})")
    return None
