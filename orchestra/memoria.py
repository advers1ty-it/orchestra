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

3. ESTRAZIONE DEI FATTI -- a fine turno, un modello rilegge la
   conversazione e ne tira fuori le cose da ricordare. L'unico strato
   che PUO' SBAGLIARE, perche' genera contenuto nuovo. Percio' non
   sovrascrive mai: aggiunge con un timestamp, cosi' un fatto vecchio
   e uno nuovo si distinguono.

   ACCESO, e non piu' spento. Prima le funzioni che lo fanno
   (`estrai_fatti`, `applica_fatti`) esistevano ma nessuno le chiamava:
   la memoria era passiva e ricordava solo quello che l'agente
   registrava a mano. Ora gira a fine turno, in un thread secco — il
   turno non aspetta, e un'estrazione fallita non rovina un turno
   riuscito.

   Ogni fatto porta con se' il PROGETTO da cui e' nato. La memoria
   resta un archivio solo, ma interrogabile per progetto: un fatto
   del sito ristorante e uno della app parrucchieri convivono e si
   distinguono.

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
# L'etichetta del progetto. Sta in una parentesi quadra come `[alta]`,
# e per una ragione precisa: il file e' scritto e letto anche da un
# essere umano, e `[progetto:sito-ristorante]` si capisce guardandolo.
# La fonte resta nella sintassi `_origine_`, che e' gia' li'.
_RE_PROGETTO = re.compile(r"\s*\[progetto:([^\]]*)\]\s*$", re.IGNORECASE)

# Un fatto scritto come REGOLA vale domani come oggi, e deve stare in
# `## Importanti`, che e' la sezione che entra nel prompt. In `## Fatti`
# aspetta che qualcuno lo cerchi, e nessuno lo cerca: il caso vero e'
# "usa solo il calendario di nova gestionale", salvato con un "Salvato in
# memoria" e mai applicato al turno dopo.
#
# La lista e' corta di proposito. Una euristica larga riempirebbe
# `## Importanti`, che ha un tetto di 1.000 caratteri: il fatto
# importante vero uscirebbe dal prompt per fare posto a un fatto
# qualunque. Le formule sono quelle con cui una persona scrive una
# preferenza fissa, non quelle con cui descrive una cosa.
_RE_REGOLA = (
    re.compile(r"\b(?:da|d')\s*ora in poi\b", re.IGNORECASE),
    re.compile(r"\busa(?:re|te)?\s+sempre\b", re.IGNORECASE),
    # "solo" copre gia' "sempre e solo": una regola in piu' per una formula
    # che ne contiene un'altra era solo un caso da mantenere.
    re.compile(r"\b(?:solo|soltanto|unicamente)\b", re.IGNORECASE),
    re.compile(r"\bnon\s+(?:usare|usiamo|fare|facciamo)\s+mai\b",
               re.IGNORECASE),
    re.compile(r"\bpreferisc[oi]\b", re.IGNORECASE),
    re.compile(r"\bregola\s*:", re.IGNORECASE),
)

# Il marcatore che dice "importante per decisione dell'euristica, non
# perche' qualcuno l'ha marcata". Sta in fondo alla riga, dopo il commento
# con la data, e si riconosce ANCORATO alla fine: cosi' un `[auto]` che sta
# dentro il testo di un fatto non viene ne' scambiato per marcatura ne'
# mangiato leggendo. Lo stesso pattern riconosce e toglie.
_RE_AUTO = re.compile(r"\s*\[auto\]\s*$", re.IGNORECASE)


def sembra_regola(fatto: str) -> bool:
    """Vero se il fatto e' scritto come una regola, non come un dato.

    La differenza non e' stilistica: una regola che resta in `## Fatti`
    non entra nel prompt, e il modello la ignora al turno dopo anche se
    l'utente l'ha appena dettata. Il prezzo di promuovere un fatto che
    non era una regola e' una riga in piu' nel prompt; il prezzo di non
    promuoverne una e' una preferenza che non viene mai rispettata.

    La scelta resta reversibile: chi scrive il file a mano puo' spostare
    la riga in `## Fatti`, e `importante=True` continua a funzionare.
    """
    testo = (fatto or "").strip()
    if not testo:
        return False
    return any(r.search(testo) for r in _RE_REGOLA)


def _pulizia_riga(corpo: str) -> tuple[str, str, str]:
    """Toglie la marcatura da una riga di fatto. Torna (testo, fonte, progetto).

    Si toglie tutto, in un ciclo, finche' la riga non cambia piu'. Il
    motivo e' l'ordine: la fonte e la data stanno in coda, e il progetto
    sta in mezzo. Applicare le regex una volta sola, in un ordine solo,
    lascia metà della marcatura dentro il testo quando i marcatori si
    presentano in ordine diverso da quello atteso — e un marcatore
    rimasto dentro il fatto finisce nel prompt, dove il modello lo legge
    come parte della conoscenza.
    """
    testo = corpo
    fonte = ""
    progetto = ""
    for _ in range(6):
        prima = testo
        m = _RE_PROGETTO.search(testo)
        if m:
            progetto = (m.group(1) or "").strip()
            testo = _RE_PROGETTO.sub("", testo)
        testo = _RE_DATA.sub("", testo)
        m2 = _RE_FONTE.search(testo)
        if m2:
            fonte = (m2.group(0) or "").strip().strip("_").strip()
            testo = _RE_FONTE.sub("", testo)
        testo = _RE_ALTA.sub("", testo)
        testo = _RE_AUTO.sub("", testo)
        testo = testo.strip()
        if testo == prima:
            break
    return testo, fonte, progetto


def _marca_auto(riga: str) -> str:
    """Aggiunge `[auto]` in fondo alla riga, se non c'e' gia'.

    In fondo e non in mezzo alla coda: il marcatore si riconosce ancorato
    alla fine, quindi un `[auto]` dentro il testo del fatto resta testo.
    Una riga gia' marcata torna identica: la migrazione deve poter girare
    due volte senza raddoppiare niente.
    """
    corpo = riga.rstrip("\r\n")
    term = riga[len(corpo):]
    if corpo.lower().endswith("[auto]"):
        return riga
    return corpo + "  [auto]" + term


def sposta_regole(testo: str) -> tuple[str, int]:
    """Porta in `## Importanti` le regole rimaste in `## Fatti`.

    Perche' serve un passaggio e non basta `sembra_regola` in
    `aggiungi`: le regole scritte PRIMA che il riconoscimento esistesse
    sono gia' nel file, in `## Fatti`, e li' restano. Nessuno le riscrive
    — e `## Fatti` non entra nel prompt: sono preferenze che l'utente ha
    dettato, ha visto confermate con un "salvato", e che il modello non
    legge mai piu'.

    Si sposta la RIGA INTERA, marcatura compresa: data, fonte e
    `[progetto:...]` sono l'unica traccia di quando e da dove il fatto e'
    arrivato, e ricostruirli qui vorrebbe dire inventarli.

    Se `## Importanti` non c'e' si crea in fondo. Una regola gia'
    presente fra gli Importanti non si duplica.

    Funzione pura (testo dentro, testo fuori) perche' il passaggio si
    possa provare senza toccare un file vero.
    """
    righe = testo.splitlines(keepends=True)

    def corpo(riga: str) -> str:
        r = riga.strip()
        if not r.startswith("-"):
            return ""
        return _pulizia_riga(r.lstrip("-").strip())[0]

    sezione = ""
    gia_importanti: set[str] = set()
    for riga in righe:
        r = riga.strip()
        if r.startswith("## "):
            sezione = r
        elif sezione == "## Importanti":
            c = corpo(riga)
            if c:
                gia_importanti.add(c)

    tenute: list[str] = []
    spostate: list[str] = []
    sezione = ""
    for riga in righe:
        r = riga.strip()
        if r.startswith("## "):
            sezione = r
            tenute.append(riga)
            continue
        if sezione != "## Importanti":
            c = corpo(riga)
            if c and sembra_regola(c) and c not in gia_importanti:
                gia_importanti.add(c)
                spostate.append(_marca_auto(
                    riga if riga.endswith("\n") else riga + "\n"))
                continue
        tenute.append(riga)

    if not spostate:
        return testo, 0

    # L'inserimento va in FONDO alla prima sezione Importanti: spostarle
    # in cima cambierebbe l'ordine dei fatti gia' li', che e' l'ordine in
    # cui sono stati detti.
    fuori: list[str] = []
    sezione = ""
    inserite = False
    i = 0
    while i < len(tenute):
        riga = tenute[i]
        r = riga.strip()
        if r.startswith("## "):
            sezione = r
            fuori.append(riga)
            i += 1
            if sezione == "## Importanti" and not inserite:
                while i < len(tenute) \
                        and not tenute[i].strip().startswith("## "):
                    fuori.append(tenute[i])
                    i += 1
                if fuori and not fuori[-1].endswith("\n"):
                    fuori[-1] = fuori[-1] + "\n"
                fuori.extend(spostate)
                inserite = True
            continue
        fuori.append(riga)
        i += 1

    if not inserite:
        if fuori and not fuori[-1].endswith("\n"):
            fuori[-1] = fuori[-1] + "\n"
        fuori.append("\n## Importanti\n\n" + "".join(spostate))

    return "".join(fuori), len(spostate)


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
        # Guardia della migrazione: `migra_regole` riscrive il file, e la
        # riscrittura non deve far ripartire la migrazione.
        self._migrando = False
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
            # Le regole salvate prima che esistesse `sembra_regola` sono
            # in `## Fatti` e li' restano: `## Fatti` non entra nel
            # prompt. Il passaggio si fa qui e non a ogni `leggi` perche'
            # qui il file e' appena stato riletto — se non e' cambiato
            # non c'e' niente da spostare.
            if self._cache:
                try:
                    self.migra_regole()
                except Exception:  # noqa: BLE001 - la memoria non si perde
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
            # Il file è cambiato: il set anti-duplicato e la cache dei fatti
            # non sono più veri. Senza questo, un fatto appena cancellato
            # resta "già visto" e non si può più riaggiungere.
            self._visti = None
            self._cache_fatti_chiave = None
        # Un file scritto a mano, o incollato dal pannello, puo' portare
        # regole in `## Fatti`: si spostano adesso, o restano fuori dal
        # prompt fino al prossimo riavvio. Il controllo `_migrando` evita
        # che la riscrittura della migrazione ne faccia partire un'altra.
        if not self._migrando:
            try:
                self.migra_regole()
            except Exception:  # noqa: BLE001 - il file e' gia' scritto
                pass

    def migra_regole(self) -> int:
        """Sposta in `## Importanti` le regole rimaste in `## Fatti`.

        Ritorna quante righe ha spostato. Zero e' il caso normale: il file
        e' gia' a posto, o non c'era niente che `sembra_regola` riconoscesse.

        Non solleva verso chi chiama: una migrazione fallita non deve
        impedire di leggere la memoria, che e' il motivo per cui la si sta
        leggendo.
        """
        with self._lock:
            if self._migrando or not self._cache:
                return 0
            nuovo, quante = sposta_regole(self._cache)
            if not quante:
                return 0
            self._migrando = True
            try:
                self.scrivi(nuovo)
            finally:
                self._migrando = False
            return quante

    def aggiungi(self, fatto: str, origine: str = "",
                 importante: bool = False, progetto: str = "") -> bool:
        """Aggiunge un fatto. Mai sovrascrive.

        `importante` lo mette nella sezione `## Importanti`, che è quella
        che finisce nel system prompt. La separazione è per POSIZIONE e non
        per marcatura: una marcatura dentro la riga va pulita, e togliere
        `[alta]` senza mangiare il fatto è un gioco di regex che si perde —
        provato due volte, con il marcatore che finiva dentro il testo o
        veniva mangiato dalla pulizia della fonte.

        `progetto` è l'etichetta che dice DA QUALE progetto viene il
        fatto. Va dentro la riga, non in un campo a parte: il file è la
        verità, e un file di testo con un fatto per riga non ha dove
        tenere un campo. L'etichetta è anche ciò che permette a un
        archivio condiviso di essere interrogato per progetto.

        Ritorna False se il fatto c'era già: duplicare la memoria la fa
        crescere senza che diventi più precisa, e un fatto ripetuto tre
        volte conta il triplo nel contesto senza dire niente di più.
        """
        fatto = " ".join((fatto or "").split()).strip()
        if not fatto:
            return False
        progetto = (progetto or "").strip()
        # Una regola va in `## Importanti` anche se nessuno l'ha marcata:
        # e' l'unica sezione che entra nel prompt, e una preferenza fissa
        # che resta in `## Fatti` non viene letta mai piu'.
        #
        # Chi l'ha decisa resta scritto nella riga: `[auto]` vuol dire
        # "promossa dall'euristica", assente vuol dire "scelta a mano".
        # Serve al taglio del prompt, dove una promozione automatica deve
        # uscire prima di una regola che qualcuno ha scritto apposta.
        regola = sembra_regola(fatto)
        auto = regola and not bool(importante)
        importante = bool(importante) or regola
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
            fatto_pulito = _pulizia_riga(fatto)[0]
            if fatto_pulito in self._visti:
                return False
            self._visti.add(fatto_pulito)
            riga_nuova = f"- {fatto}"
            if progetto:
                riga_nuova += f"  [progetto:{progetto}]"
            if origine:
                riga_nuova += f"  _{origine}_"
            riga_nuova += f"  <!-- {time.strftime('%Y-%m-%d')} -->"
            # In fondo, dopo la data: il marcatore si riconosce ancorato
            # alla fine, così un `[auto]` dentro il testo del fatto non
            # viene mangiato leggendolo.
            if auto:
                riga_nuova += "  [auto]"
            riga_nuova += "\n"

            sezione = "## Importanti" if importante else "## Fatti"
            testo = self.leggi()
            # Append, non riscrittura. Il controllo è su che sezione sta
            # in FONDO: se è quella giusta si appende e basta; se non c'è
            # o è un'altra, si scrive l'intestazione e poi la riga. In
            # Markdown due sezioni con lo stesso nome sono valide, e
            # `importanti_con_origine` le legge tutte, nell'ordine.
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
        """I fatti della sezione `## Importanti`: quelli nel prompt.

        Passa da `importanti_con_origine` invece di rileggere le righe a
        modo suo: due lettori dello stesso file con due regole diverse
        divergono al primo ritocco, e la divergenza si vede come un fatto
        che sta nel prompt in un punto e non nell'altro.
        """
        return [testo for testo, _origine in self.importanti_con_origine()]

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
                    # la coda e' "  [progetto:x]  _origine_  <!-- data -->":
                    # la si stacca dal corpo per riattaccarla al testo
                    # nuovo. Il progetto fa parte della coda perche' e'
                    # un marcatore come gli altri: perderlo significa
                    # che un fatto modificato esce dal suo progetto, e
                    # da lì non e' piu' ritrovabile con gli altri.
                    coda = ""
                    m = re.search(
                        r"(\s*\[progetto:[^\]]*\]\s*"
                        r"\s*_[^_]+_\s*<!--.*?-->\s*"
                        r"|\s*\[progetto:[^\]]*\]\s*_[^_]+_\s*"
                        r"|\s*\[progetto:[^\]]*\]\s*"
                        r"|\s*_[^_]+_\s*<!--.*?-->\s*"
                        r"|\s*<!--.*?-->\s*"
                        r"|\s*_[^_]+_\s*)$", corpo)
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

    def importanti_con_origine(self) -> list[tuple[str, str]]:
        """I fatti di `## Importanti`, con chi li ha messi li'.

        L'origine vale "mano" per un fatto che qualcuno ha marcato come
        importante, "auto" per uno che ci e' finito perche' e' scritto
        come regola (`sembra_regola`). La distinzione non e' curiosita':
        quando lo spazio del prompt finisce, deve uscire una promozione
        automatica, non una preferenza che qualcuno ha scritto e marcato
        apposta.
        """
        with self._lock:
            testo = self.leggi()
        fuori: list[tuple[str, str]] = []
        visti: set[str] = set()
        sezione = ""
        for riga in testo.splitlines():
            r = riga.strip()
            if r.startswith("## "):
                sezione = r
                continue
            if sezione != "## Importanti" or not r.startswith("-"):
                continue
            corpo = _pulizia_riga(r.lstrip("-").strip())[0]
            if not corpo or corpo in visti:
                continue
            visti.add(corpo)
            auto = bool(_RE_AUTO.search(r))
            fuori.append((corpo, "auto" if auto else "mano"))
        return fuori

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
                # toglie il commento HTML con la data, la fonte, la
                # marcatura di priorità e l'etichetta del progetto. La
                # pulizia sta in un posto solo: se ogni lettore si fa
                # le regex per conto proprio le regole divergono, e un
                # marcatore che una riga lascia dentro finisce nel
                # testo del fatto — e da lì nel prompt, dove il modello
                # lo legge come conoscenza.
                corpo = _pulizia_riga(corpo)[0]
                if corpo:
                    fuori.append(corpo)
            self._cache_fatti = fuori
            self._cache_fatti_chiave = chiave
            return fuori

    def fatti_per_progetto(self, progetto: str) -> list[str]:
        """I fatti che vengono da un progetto.

        Il punto di tutto: la memoria e' condivisa, ma non ogni fatto
        serve a ogni progetto. Un archivio unico che risponde " tutto"
        a ogni domanda non e' una memoria, e' un mucchio. Qui si
        restituisce il sottoinsieme che riguarda il progetto chiesto.

        Un progetto vuoto significa "tutti i fatti": e' il modo
        normale di chiedere, e non ha senso che "nessun progetto"
        valga "nessun fatto".
        """
        progetto = (progetto or "").strip().lower()
        if not progetto:
            return self.fatti()
        fuori = []
        with self._lock:
            testo = self.leggi()
        for riga in testo.splitlines():
            r = riga.strip()
            if not r.startswith("-"):
                continue
            corpo = r.lstrip("-").strip()
            testo_fatto, _fonte, prog = _pulizia_riga(corpo)
            if prog.lower() == progetto and testo_fatto:
                fuori.append(testo_fatto)
        return fuori

    def progetti(self) -> list[str]:
        """I progetti di cui la memoria ha qualcosa.

        Vengono dai fatti, non da una tabella: il file e' la verita',
        e un progetto che ha solo un fatto e' un progetto che esiste.
        """
        visti: dict[str, int] = {}
        with self._lock:
            testo = self.leggi()
        for riga in testo.splitlines():
            r = riga.strip()
            if not r.startswith("-"):
                continue
            _t, _f, prog = _pulizia_riga(r.lstrip("-").strip())
            if prog:
                visti[prog] = visti.get(prog, 0) + 1
        return sorted(visti)


    def ottimizza_memoria(self, *args, **kwargs) -> dict:
        """Delega all'ottimizzatore dell'indice FTS5, se disponibile."""
        try:
            from .memoria_indice import ottimizza_memoria as _opt
            return _opt(*args, **kwargs)
        except Exception as e:
            return {"dry_run": kwargs.get("dry_run", True), "errore": str(e),
                    "rimossi": 0, "cancellati": 0, "potati": 0, "uniti": 0,
                    "fusi": 0, "fatti_prima": 0, "fatti_dopo": 0, "candidati": []}

    ottimizza = ottimizza_memoria
    optimize_memory = ottimizza_memoria
    potatura_memoria = ottimizza_memoria
    potatura = ottimizza_memoria


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
    from .types import Message
    try:
        prompt = PROMPT_ESTRAZIONE.format(conversazione=conversazione[-8000:])
        resp = provider.chat(
            [Message(role="user", content=prompt)],
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


def applica_fatti(fatti: list[str], origine: str = "sessione",
                 progetto: str = "") -> int:
    """Mette i fatti in memoria. Ritorna quanti erano nuovi.

    `progetto` va passato a `aggiungi` e non messo nella `origine`: sono
    due cose diverse. L'origine dice DA CHI viene il fatto (sessione,
    agente, mano dell'utente), il progetto dice A QUALE PROGETTO
    appartiene. Se il progetto viaggiasse dentro la fonte, il filtro
    per progetto non avrebbe niente su cui lavorare — e il sintomo
    sarebbe "il progetto e' sparito", che sembra un problema di
    ricerca e invece e' un problema di scrittura.
    """
    m = memoria()
    nuovi = 0
    for f in fatti:
        if m.aggiungi(f, origine=origine, progetto=progetto):
            nuovi += 1
    return nuovi


def estrai_e_ricorda(conversazione: str, provider: Any,
                     progetto: str = "") -> int:
    """Estrae i fatti dalla conversazione e li mette in memoria.

    E' il pezzo che mancava: `estrai_fatti` e `applica_fatti` esistevano
    da sole, ma nessuno le chiamava. La memoria non ricordava niente da
    sola — l'unico modo perché un fatto arrivasse era che l'agente
    chiamasse il tool `memoria` con `azione=aggiungi`, e cioe' che se
    ne ricordasse. Un agente non si ricorda le cose da solo.

    Qui il turno chiama questa funzione e non deve pensarci: estrae,
    scrive, e restituisce quanti fatti nuovi sono entrati. Zero se il
    provider non risponde, se il turno era vuoto, o se non c'era niente
    da ricordare — che sono tre cose diverse, ma per il chiamante
    contano tutte e zero.

    Il `progetto` entra nella riga come etichetta. Non e' un
    requisito per ricordare: e' quello che permette a un archivio
    condiviso di rispondere "cosa serve per IL progetto su cui
    sto lavorando" invece di "tutto quello che Orchestra sa".
    """
    if not (conversazione or "").strip():
        return 0
    try:
        fatti = estrai_fatti(conversazione, provider)
    except Exception:
        return 0
    if not fatti:
        return 0
    try:
        return applica_fatti(fatti, origine="sessione", progetto=progetto)
    except Exception:
        return 0


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


def ottimizza_memoria(*args, **kwargs) -> dict:
    """Potatura della memoria. Delega all'indice FTS5 se disponibile.

    Il backend a file non ha contatori d'uso: senza indice non c'e' niente da
    ottimizzare, e si torna un risultato vuoto invece di un errore.
    """
    try:
        from .memoria_indice import ottimizza_memoria as _opt
        return _opt(*args, **kwargs)
    except Exception as e:
        return {"dry_run": kwargs.get("dry_run", True), "errore": str(e),
                "rimossi": 0, "cancellati": 0, "potati": 0, "uniti": 0,
                "fusi": 0, "fatti_prima": 0, "fatti_dopo": 0, "candidati": []}


ottimizza = ottimizza_memoria
optimize_memory = ottimizza_memoria
potatura_memoria = ottimizza_memoria
potatura = ottimizza_memoria

