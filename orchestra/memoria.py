"""
Memoria: quello che Orchestra sa di te e non deve chiederti due volte.

Perche' esiste: ogni sessione ripartiva da zero. Il system prompt era
vuoto, e la compattazione del contesto gettava il riepilogo invece di
tenerlo. Orchestra dimenticava a ogni riavvio, e dentro una sessione
lunga dimenticava in silenzio.

TRE STRATI, in ordine di costo e di danno se sbagliano:

1. MEMORIA.MD -- un file di testo, leggibile e modificabile a mano. Chi
   lo scrive sa cosa c'è dentro, perche' puo' aprirlo con un editor.
   E' il livello piu' importante: tutto il resto e' automatismo sopra.

2. COMPATTAZIONE SALVATA -- il riepilogo che `fit_context` produce viene
   messo da parte invece di buttarlo. Recupero, non invenzione: quelle
   parole il modello le ha gia' dette.

3. ESTRAZIONE DEI FATTI -- a fine sessione, un modello rilegge la
   conversazione e ne tira fuori le cose da ricordare. L'unico strato
   che PUO' SBAGLIARE, perche' genera contenuto nuovo. Percio':
   spento di default, e mai sovrascrive -- aggiunge con un timestamp,
   cosi' un fatto vecchio e uno nuovo si distinguono.

REGISTRO DEI PROVIDER

`memory.md` e' il backend incluso, non l'unico possibile. Un backend e'
una classe con `leggi()`, `scrivi()`, `elimina()`. Installarne un altro
vuol dire registrarlo qui: il resto del codice non sa quale sta usando.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any
from .dati import percorso

def _percorso_memoria() -> str:
    """Dove sta il file di memoria.

    Nella cartella dati di Orchestra (vedi dati.py): un file che l'agente
    modifica da solo non deve vivere dentro il repo sorgente, dove un
    `git status` lo vede come modifica e un `git checkout` lo cancella.
    Se il file c'e' gia' accanto al modulo (installazioni vecchie), si
    legge da li' una volta e poi si scrive nel nuovo posto.
    """
    return percorso("memory.md")


PERCORSO_MEMORIA = _percorso_memoria()

# Quanto può essere lunga la memoria prima di essere tagliata. Non è un
# limite artistico: sopra una certa dimensione la memoria ruba spazio al
# contesto della conversazione, e un contesto pieno di ricordi risponde
# peggio di uno con i ricordi giusti.
TETTO_CARATTERI = 20_000

# Entro quanti secondi una memoria su disco si rilegge. Il file si può
# modificare a mano mentre il server gira: senza, l'utente corregge un
# fatto, riavvia, e non capisce perché la correzione non è comparsa.
FINESTRA_RELOAD = 10.0


# Regex precompilate: `fatti()` le applica a ogni riga del file, e viene
# chiamata a ogni `aggiungi`. Con pattern stringa `re.sub` ricompila
# ogni volta.
_RE_DATA = re.compile(r"\s*<!--.*?-->\s*$")
_RE_FONTE = re.compile(r"\s*_[^_]+_\s*$")
_RE_ALTA = re.compile(r"\s*\[alta\]\s*$", re.IGNORECASE)


class Memoria:
    """Backend su file di testo.

    Il formato è Markdown con una sezione per argomento, perché è quello
    che un essere umano apre e capisce. Un JSON sarebbe più comodo per il
    codice e illeggibile per chi deve correggere uno sbaglio.
    """

    def __init__(self, percorso: str | None = None) -> None:
        self.percorso = percorso or PERCORSO_MEMORIA
        self._lock = threading.RLock()
        self._ultima_lettura = 0.0
        self._cache = ""
        # Insieme dei fatti già visti, per il controllo anti-duplicato.
        # Popolato la prima volta da `fatti()`, poi tenuto aggiornato da
        # `appendi`: senza, `aggiungi` dovrebbe rifare il parse completo
        # a ogni fatto, che è il costo che questo insieme evita.
        self._visti: set[str] | None = None
        self._cache_fatti_chiave = None
        self._ultimo_mtime = 0.0
        if not os.path.exists(self.percorso):
            self.scrivi_intestazione()

    def scrivi_intestazione(self) -> None:
        """Crea il file con l'intestazione, se non c'è.

        Il file lo crea Orchestra, non l'utente: scoprire che "la memoria"
        vuol dire "crea tu un file con il nome giusto" è il modo per non
        usarla mai.
        """
        with self._lock:
            with open(self.percorso, "w", encoding="utf-8") as f:
                f.write(
                    "# Memoria di Orchestra\n\n"
                    "Quello che Orchestra sa di te e non deve chiederti due volte.\n"
                    "Puoi modificare questo file a mano: viene riletto da solo.\n\n"
                    "## Fatti\n\n")

    def _rileggi_se_cambiato(self) -> None:
        con_il_lock = self._lock
        with con_il_lock:
            try:
                mtime = os.path.getmtime(self.percorso)
            except OSError:
                return
            adesso = time.time()
            if (mtime != self._ultimo_mtime
                    or adesso - self._ultima_lettura > FINESTRA_RELOAD):
                try:
                    with open(self.percorso, "r", encoding="utf-8") as f:
                        self._cache = f.read()
                    self._ultimo_mtime = mtime
                    self._ultima_lettura = adesso
                    # il file è cambiato fuori da noi (a mano): il set
                    # dei fatti visti non è più vero, e senza invalidarlo
                    # `aggiungi` riscriverebbe un fatto che qualcuno ha
                    # già scritto nel file.
                    self._visti = None
                    self._cache_fatti_chiave = None
                except OSError:
                    pass

    def leggi(self) -> str:
        self._rileggi_se_cambiato()
        with self._lock:
            testo = self._cache
        if len(testo) > TETTO_CARATTERI:
            # NON si taglia in silenzio. Il taglio silenzioso è il difetto
            # peggiore che questa memoria abbia avuto: con 20.000 fatti il
            # file si fermava a 272, la ricerca girava su quelli, e non
            # c'era un errore da nessuna parte — solo fatti che non
            # esistevano più.
            #
            # Adesso si alza il tetto e si tiene TUTTO. Il tetto basso
            # serviva a non iniettare la memoria intera nel prompt, ma
            # quello non si fa più: nel prompt finiscono solo gli
            # Importanti, e il resto lo cerca l'indice FTS5.
            TETTO_LETTURA = 2_000_000      # 2 MB: nessuno arriva qui a mano
            if len(testo) > TETTO_LETTURA:
                testo = (testo[:TETTO_LETTURA]
                         + f"\n\n[...memoria oltre {TETTO_LETTURA:,} caratteri:"
                           f" il file è {len(testo):,}. Questa è un'emergenza,"
                           f" non un limite di progetto — separa i fatti in"
                           f" più file o usa l'indice.]")
            return testo
        return testo

    def appendi(self, riga: str) -> None:
        """Aggiunge in FONDO al file, senza riscriverlo.

        `aggiungi` faceva split/join su tutto il testo a ogni fatto: con
        5000 fatti erano 125 secondi, perché il costo è quadratico — ogni
        scrittura ricopia tutto quello che c'è già. L'append è O(1).

        La cache si aggiorna per concatenato, NON rileggendo il file:
        leggere l'intero file per aggiornare una riga è lo stesso costo
        della scrittura completa, solo spostato. `_rileggi_se_cambiato`
        se ne accorgerà da solo se il file cambia fuori da qui (a mano),
        perché confronta l'mtime.
        """
        with self._lock:
            with open(self.percorso, "a", encoding="utf-8") as f:
                f.write(riga)
            self._cache = (self._cache or "") + riga
            # la cache dei fatti va invalidata a mano: la sua chiave è
            # l'hash del testo, e ricalcolarlo su 300 KB per sapere che
            # una riga è cambiata è il costo che la cache serve a evitare.
            self._cache_fatti_chiave = None
            self._ultima_lettura = time.time()
            # si lascia `_ultimo_mtime` indietro di proposito: se qualcuno
            # scrive a mano, `_rileggi_se_cambiato` deve accorgersene.
            try:
                self._ultimo_mtime = os.path.getmtime(self.percorso)
            except OSError:
                pass

    def scrivi(self, testo: str) -> None:
        with self._lock:
            with open(self.percorso, "w", encoding="utf-8") as f:
                f.write(testo)
            self._cache = testo
            self._ultimo_mtime = os.path.getmtime(self.percorso)
            self._ultima_lettura = time.time()

    def aggiungi(self, fatto: str, origine: str = "",
                 importante: bool = False) -> bool:
        """Aggiunge un fatto. Mai sovrascrive.

        `importante` lo mette nella sezione `## Importanti`, che è quella
        che finisce nel system prompt. La separazione è per POSIZIONE e non
        per marcatura: una marcatura dentro la riga va pulita, e togliere
        `[alta]` senza mangiare il fatto è un gioco di regex che si perde —
        provato due volte, con il marcatore che finiva dentro il testo o
        veniva mangiato dalla pulizia della fonte.

        Ritorna False se il fatto c'era già: duplicare la memoria la fa
        crescere senza che diventi più precisa, e un fatto ripetuto tre
        volte conta il triplo nel contesto senza dire niente di più.
        """
        fatto = " ".join((fatto or "").split()).strip()
        if not fatto:
            return False
        with self._lock:
            # Il confronto va fatto sui fatti PULITI, non sulle righe
            # grezze: una riga scritta da `aggiungi` porta dietro la data
            # e l'origine, quindi confrontarla col fatto nudo non
            # corrispondeva mai — e il "nuovo" che tornava era vero solo
            # perché il duplicato veniva scritto lo stesso.
            # Il confronto anti-duplicato usa un SET incrementale, non
            # `fatti()`. Rifare il parse di 5000 righe a ogni fatto è
            # 27 ms; su 5000 fatti fa 140 secondi, e il profiler dice che
            # l'86% del tempo sta lì — 2,6 milioni di chiamate a re.sub.
            if self._visti is None:
                self._visti = set(self.fatti())
            fatto_pulito = _RE_DATA.sub("", _RE_FONTE.sub("", _RE_ALTA.sub("", fatto)))
            fatto_pulito = fatto_pulito.strip()
            if fatto_pulito in self._visti:
                return False
            self._visti.add(fatto_pulito)
            riga_nuova = f"- {fatto}"
            if origine:
                riga_nuova += f"  _{origine}_"
            riga_nuova += f"  <!-- {time.strftime('%Y-%m-%d')} -->\n"

            sezione = "## Importanti" if importante else "## Fatti"
            testo = self.leggi()
            # Append, non riscrittura. Il controllo è su che sezione sta
            # in FONDO: se è quella giusta si appende e basta; se non c'è
            # o è un'altra, si scrive l'intestazione e poi la riga. In
            # Markdown due sezioni con lo stesso nome sono valide, e
            # `_fatti_della` le concatena nell'ordine.
            ultima_sezione = ""
            for riga_testo in reversed(testo.splitlines()):
                if riga_testo.strip().startswith("## "):
                    ultima_sezione = riga_testo.strip()
                    break
            if ultima_sezione == sezione:
                self.appendi(riga_nuova)
            else:
                self.appendi(f"\n{sezione}\n\n{riga_nuova}")
            return True

    def importanti(self) -> list[str]:
        """I fatti della sezione `## Importanti`: quelli nel prompt."""
        return self._fatti_della("## Importanti")

    def _fatti_della(self, sezione: str) -> list[str]:
        """I fatti di UNA sezione, senza la marcatura."""
        with self._lock:
            testo = self.leggi()
        if sezione not in testo:
            return []
        parti = testo.split(sezione, 1)[1]
        # la sezione finisce alla prossima intestazione di livello 2
        for altra in ("\n## ",):
            i = parti.find(altra)
            if i >= 0:
                parti = parti[:i]
        fuori = []
        for riga in parti.splitlines():
            r = riga.strip()
            if not r.startswith("-"):
                continue
            corpo = r.lstrip("-").strip()
            corpo = re.sub(r"\s*<!--.*?-->\s*$", "", corpo)
            corpo = re.sub(r"\s*_[^_]+_\s*$", "", corpo)
            if corpo:
                fuori.append(corpo)
        return fuori

    def elimina(self, fatto: str) -> bool:
        with self._lock:
            testo = self.leggi()
            righe = testo.splitlines(keepends=True)
            fuori, tolto = [], False
            for riga in righe:
                corpo = riga.strip().lstrip("-*").strip()
                if corpo == fatto.strip() or fatto.strip() in corpo:
                    tolto = True
                    continue
                fuori.append(riga)
            if tolto:
                self.scrivi("".join(fuori))
            return tolto

    def modifica(self, vecchio: str, nuovo: str) -> bool:
        """Sostituisce il testo di un fatto, tenendo origine e data.

        `elimina` + `aggiungi` perderebbe la data (quella nuova sarebbe
        oggi) e l'origine, che sono l'unica traccia di quando e da dove
        il fatto e' arrivato. Qui si riscrive solo la parte di testo e si
        lasciano intatti i marcatori in coda.

        Ritorna False se il fatto non c'e', o se il nuovo testo e' vuoto.
        """
        nuovo = " ".join((nuovo or "").split()).strip()
        vecchio = (vecchio or "").strip()
        if not nuovo or not vecchio:
            return False
        with self._lock:
            testo = self.leggi()
            righe = testo.splitlines(keepends=True)
            fuori, fatto = [], False
            for riga in righe:
                corpo = riga.strip().lstrip("-*").strip()
                if not fatto and (corpo == vecchio or vecchio in corpo):
                    # la coda e' "  _origine_  <!-- data -->": la si stacca
                    # dal corpo per riattaccarla al testo nuovo.
                    coda = ""
                    m = re.search(r"(\s*_[^_]+_\s*<!--.*?-->\s*|\s*<!--.*?-->\s*|\s*_[^_]+_\s*)$", corpo)
                    if m:
                        coda = m.group(1)
                    indent = riga[:len(riga) - len(riga.lstrip())]
                    # il terminatore di riga vive in `riga`, non in
                    # `corpo` (che e' strippato): va riattaccato a mano,
                    # o il fatto modificato si incolla al successivo.
                    term = riga[len(riga.rstrip("\r\n")):]
                    fuori.append(f"{indent}- {nuovo}{coda}{term}")
                    fatto = True
                    continue
                fuori.append(riga)
            if fatto:
                self.scrivi("".join(fuori))
                # il set anti-duplicato ha in cache il testo vecchio:
                # va buttato o il fatto modificato resta "gia' visto".
                self._visti = None
            return fatto

    def fatti(self) -> list[str]:
        """I fatti uno per uno, senza la marcatura.

        Serve alla UI: mostrare il file grezzo è un editor di testo,
        mostrare i fatti è una lista che si può correggere.

        Il risultato è in cache per (testo, lunghezza): `aggiungi` lo
        chiama a OGNI fatto per il controllo anti-duplicato, e su 5000
        fatti rifare il parse completo ogni volta costa 27 ms per fatto —
        140 secondi in tutto. La cache si butta da sé se il testo
        cambia, perché la chiave è il testo stesso.
        """
        with self._lock:
            testo = self.leggi()
            chiave = (len(testo), hash(testo))
            if getattr(self, "_cache_fatti_chiave", None) == chiave:
                return self._cache_fatti
            fuori = []
            for riga in testo.splitlines():
                r = riga.strip()
                if not r.startswith("-"):
                    continue
                corpo = r.lstrip("-").strip()
                # toglie il commento HTML con la data e la fonte
                corpo = _RE_DATA.sub("", corpo)
                corpo = _RE_FONTE.sub("", corpo)
                # e la marcatura di priorità. Se resta qui finisce dentro
                # il testo del fatto: il confronto anti-duplicato di
                # `aggiungi` non trova corrispondenza e il duplicato viene
                # scritto lo stesso — provato, "Ricordato".
                corpo = _RE_ALTA.sub("", corpo)
                if corpo:
                    fuori.append(corpo)
            self._cache_fatti = fuori
            self._cache_fatti_chiave = chiave
            return fuori


# -- registro dei backend --------------------------------------------------

_BACKEND: dict[str, type[Memoria]] = {"file": Memoria}
_ATTIVO: str = "file"
_istanza: Memoria | None = None
_lock_classe = threading.Lock()


def registra_backend(nome: str, classe: type[Memoria]) -> None:
    """Aggiunge un backend. Il resto del codice non cambia."""
    with _lock_classe:
        _BACKEND[nome] = classe


def backend_disponibili() -> list[str]:
    return sorted(_BACKEND.keys())


def imposta_backend(nome: str) -> bool:
    global _istanza, _ATTIVO
    if nome not in _BACKEND:
        return False
    with _lock_classe:
        _ATTIVO = nome
        _istanza = None       # ricreata al prossimo uso
    return True


def memoria() -> Memoria:
    """Il backend attivo. Se cambia, l'istanza si rifà da sola."""
    global _istanza
    with _lock_classe:
        if _istanza is None:
            _istanza = _BACKEND[_ATTIVO]()
        return _istanza


# -- estrazione dei fatti --------------------------------------------------

# Il prompt che estrae. Scritto per essere controllabile: si chiede una
# riga per fatto, senza commenti, così il parsing non può fallire in
# mezzo a una frase.
PROMPT_ESTRAZIONE = """Rileggi la conversazione e tira fuori solo le cose che
servono nelle conversazioni di DOMANI: preferenze, fatti sul progetto,
decisioni prese, vincoli. Non citare la conversazione, non fare
introduzioni, non riassumere quello che è stato fatto.

Una riga per fatto, senza numeri, senza trattini, senza commenti.
Massimo 10 righe. Se non c'è niente da ricordare, rispondi NIENTE.

Conversazione:
{conversazione}"""


def estrai_fatti(conversazione: str, provider: Any) -> list[str]:
    """Chiede a un modello quali fatti meritano di essere ricordati.

    L'unico punto in cui Orchestra AGGUNGE contenuto nuovo alla memoria,
    quindi l'unico che può sbagliare. Chi la chiama sa che il risultato
    va visto prima di fidarsi: per questo `applica_fatti` è una funzione
    separata, e non lo fa da sola.
    """
    from .providers import LLMResponse  # noqa: F401  (per il tipo)
    try:
        prompt = PROMPT_ESTRAZIONE.format(conversazione=conversazione[-8000:])
        resp = provider.chat(
            [{"role": "user", "content": prompt}],
            tools=None,
        )
        testo = (getattr(resp, "content", "") or "").strip()
    except Exception:
        return []

    if not testo or testo.upper().startswith("NIENTE"):
        return []

    fatti = []
    for riga in testo.splitlines():
        r = riga.strip()
        r = re.sub(r"^[\-\*\d\.\)\s]+", "", r)
        if r and len(r) > 8:
            fatti.append(r)
    return fatti[:10]


def applica_fatti(fatti: list[str], origine: str = "sessione") -> int:
    """Mette i fatti in memoria. Ritorna quanti erano nuovi."""
    m = memoria()
    nuovi = 0
    for f in fatti:
        if m.aggiungi(f, origine=origine):
            nuovi += 1
    return nuovi


def contesto_memoria() -> str:
    """Il pezzo di memoria da iniettare nel system prompt.

    Vuoto se non c'è niente: iniettare "Memoria: (vuota)" insegna al
    modello a parlare della memoria invece di usarla.
    """
    try:
        # Si guardano i FATTI, non il testo: un file appena creato ha
        # l'intestazione e basta, ed è lungo abbastanza da passare una
        # soglia sui caratteri. Iniettare "Memoria di Orchestra" senza
        # un solo fatto insegna al modello a parlare della memoria
        # invece di usarla.
        if not memoria().fatti():
            return ""
        testo = memoria().leggi().strip()
    except Exception:
        return ""
    if len(testo) < 40:
        return ""
    return testo


def stato() -> dict[str, Any]:
    """Per la UI: quale backend, quanti fatti, quanto è lunga."""
    try:
        m = memoria()
        fatti = m.fatti()
        return {
            "backend": _ATTIVO,
            "disponibili": backend_disponibili(),
            "percorso": getattr(m, "percorso", ""),
            "n_fatti": len(fatti),
            "caratteri": len(m.leggi()),
            "tetto": TETTO_CARATTERI,
            "fatti": fatti,
        }
    except Exception as e:
        return {"backend": _ATTIVO, "errore": str(e), "fatti": [], "n_fatti": 0}


def salva_config(percorso: str | None = None) -> None:
    """Quale backend è attivo, così sopravvive al riavvio."""
    p = percorso or os.path.join(os.path.dirname(__file__), "memoria_config.json")
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"backend": _ATTIVO}, f)
    except OSError:
        pass


def carica_config(percorso: str | None = None) -> None:
    p = percorso or os.path.join(os.path.dirname(__file__), "memoria_config.json")
    try:
        with open(p, encoding="utf-8") as f:
            nome = (json.load(f) or {}).get("backend", "file")
        if nome in _BACKEND:
            imposta_backend(nome)
    except (OSError, ValueError):
        pass