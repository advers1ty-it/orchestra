"""Le skill dell'agente: due origini, una sola cosa da sapere quando servono.

Una skill e' un SKILL.md con un frontmatter:

    ---
    name: nome-della-skill
    description: Quando usarla. Una riga.
    ---

    # corpo in markdown: cosa fare, con quali comandi.

Il corpo non finisce MAI nel prompt di sistema. Va' nel contesto solo
quando la skill e' stata scelta, e per intero. Il prompt porta i nomi
e le descrizioni — due righe per skill — e nient'altro. Con decine di
skill, il prompt pieno costerebbe migliaia di token a ogni
messaggio, e la gran parte di quelle skill non servirebbe a nulla.

LE DUE ORIGINI, E PERCHE' SONO DIVERSE

    scaricate/  — copiate da uno store esterno. Contengono istruzioni
                 scritte da altri, e non sono state verificate qui.
    generate/  — scritte dall'agente dopo aver eseguito qualcosa che
                 ha funzionato. Portano con se' le prove.

Le skill dentro skills/ senza sottocartelle sono la base
distribuita con Orchestra. Portano `origine: base` invece di
`scaricata`: stesso trattamento tecnico, ma dicono di essere
state riviste dagli sviluppatori invece che copiate da uno
store esterno. La categoria si dichiara nel frontmatter
(`categoria: base`).

La distinzione non e' cosmetica ed e' percio' nel formato: `origine` e
`prove` stanno nel frontmatter, e chi le legge deve poter dire quanto
vale cid' che sta leggendo. Una skill scaricata dice "questa e' la
metodo di qualcun altro". Una generata dice "questo e' l'ho appena
fatto, e guarda".

SOGLIA

Una skill generata nasce solo se la procedura e' riuscita piu' volte
(SOGLIA_RIPETIZIONI) e non e' banale. Il motivo e' che l'agente puo'
ripetere un comando identico cento volte senza che ne debba uscire una
skill: e' rumore, e rumore nel prompt costa token e influenza la
risposta. Su richiesta esplicita non c'e' soglia: se chiedi, si
scrive.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

HERE = os.path.dirname(os.path.abspath(__file__))
RADICE = os.environ.get("ORCHESTRA_SKILLS") or os.path.join(
    os.path.dirname(HERE), "skills")
CARTELLA_SCARICATE = "scaricate"
CARTELLA_GENERATE = "generate"

# Quante volte una procedura deve riuscire prima di meritare una skill.
# Una volta e' un caso: puo' essere stato un colpo di fortuna, o un
# comando che ha funzionato perche' la cartiga era vuota. Tre volte
# e' una procedura.
SOGLIA_RIPETIZIONI = 3

# Una skill che serve a una riga ("leggi il file") non vale una skill.
# Il corpo sotto questa lunghezza e' rumore con un nome.
#
# La soglia e' bassa perche' una procedura vera sta fra le 300 e le
# 800 parole, e 200 caratteri sono cinque righe: la soglia non deve
# fermare una procedura corta ma vera, solo i comandi isolati. Un
# numero piu' alto faceva rifiutare cose giuste — e il rifiuto
# arrivava con una spiegazione che sembrava un errore di chi ha
# scritto, non di chi ha scritto bene.
LUNGHEZZA_MINIMA = 120

# Quante skill entrano nel prompt. oltre, si sceglie per pertinenza.
MAX_NEL_PROMPT = 24

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_CAMPO = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", re.M)


# ------------------------------------------------------------------------
# Il modello
# ------------------------------------------------------------------------


@dataclass
class Skill:
    """Una skill, letta da disco."""

    nome: str
    descrizione: str
    corpo: str
    percorso: str
    categoria: str = ""
    origine: str = "scaricata"      # "scaricata" | "generata"
    prove: list[dict[str, Any]] = field(default_factory=list)
    usata_il: float = 0.0
    volte_usata: int = 0

    @property
    def con_prove(self) -> bool:
        """Una skill generata senza prove non vale una scritta a mano.

        Il punto e' che "questo funziona" e' un'affermazione. Le prove
        sono i comandi veri, l'output, il file. Chi le legge puo'
        ricontrollare in trenta secondi se la skill regge, e se il
        modello se l'e' inventata si vede subito.
        """
        return bool(self.prove)

    def per_prompt(self) -> str:
        """Le due righe che vanno nel prompt di sistema.

        Niente corpo. E' la differenza fra 20.000 token e 900.
        """
        segno = "+" if self.origine == "generata" else " "
        riga = f"  {segno} {self.nome}: {self.descrizione}"
        if self.origine == "generata":
            n = len(self.prove)
            riga += f" [{n} prove] se vuoi i dettagli chiedi: skill_leggi {self.nome}"
        return riga

    def per_uso(self) -> str:
        """Il testo che entra nel contesto quando la skill e' stata scelta.

        Include il corpo per intero e, se ci sono, le prove. Una
        procedura senza le prove che l'hanno generata e' un'affermazione;
        con, e' qualcosa che l'ha appena funzionato.
        """
        parti = [f"# Skill: {self.nome}", "", self.corpo]
        if self.prove:
            parti += ["", "## Prove che questa procedura ha funzionato", ""]
            for i, p in enumerate(self.prove, 1):
                quando = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(p.get("ts", 0)))
                parti.append(f"### Prova {i} — {quando}")
                if p.get("obiettivo"):
                    parti.append(f"Obiettivo: {p['obiettivo']}")
                if p.get("comandi"):
                    parti.append("Comandi usati:")
                    parti.append("```")
                    for c in p["comandi"]:
                        parti.append(str(c))
                    parti.append("```")
                if p.get("esito"):
                    parti.append(f"Esito: {p['esito']}")
                parti.append("")
        return "\n".join(parti)


# ------------------------------------------------------------------------
# Lettura e scrittura
# ------------------------------------------------------------------------


def _leggi(path: str) -> tuple[dict[str, str], str]:
    try:
        testo = io.open(path, encoding="utf-8").read()
    except UnicodeDecodeError:
        # Non tutto cid' che si scarica e' in UTF-8. Una skill in
        # cp1252 — che capita, e capita spesso nelle skill vecchie —
        # non puo' far cadere l'indice delle altre 187: l'agente deve
        # poter leggere una descrizione con due caratteri strani.
        #
        # errors="replace" e' la scelta giusta perche' il
        # frontmatter conta piu' del corpo, e un nome con un
        # carattere sbagliato e' comunque piu' utile di niente.
        try:
            testo = io.open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            return {}, ""
    except OSError:
        return {}, ""
    m = _FRONT.match(testo)
    if not m:
        return {}, testo.strip()
    campi: dict[str, str] = {}
    for k, v in _CAMPO.findall(m.group(1)):
        campi[k.strip().lower()] = v.strip().strip('"').strip("'")
    return campi, testo[m.end():].strip()


def _scrivi(path: str, campi: dict[str, str], corpo: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in campi.items())
    tmp = path + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(
        f"---\n{fm}\n---\n\n{corpo}\n")
    os.replace(tmp, path)


def _prove_json(path: str) -> list[dict[str, Any]]:
    j = path + ".prove.json"
    if not os.path.exists(j):
        return []
    try:
        d = json.loads(io.open(j, encoding="utf-8").read())
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _prove_scrivi(path: str, prove: list[dict[str, Any]]) -> None:
    io.open(path + ".prove.json", "w", encoding="utf-8").write(
        json.dumps(prove, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------------
# L'indice
# ------------------------------------------------------------------------


class Indice:
    """Tutte le skill sul disco, indicizzate per nome.

    L'indice si ricostruisce a ogni uso invece di essere tenuto in
    memoria. Il motivo e' che puo' cambiare fuori dal processo: una
    skill scaricata dalla UI, una generata dall'agente in un altro
    turno, una cancellata a mano. Un indice in memoria direbbe cose
    che non sono piu' vere, e la cosa peggiore che puo' fare un indice
    e' mentire su cid' che contiene.
    """

    def __init__(self, radice: str | None = None) -> None:
        self.radice = radice or RADICE
        # L'indice appena creato non ha mai letto niente, e non
        # deve rimandare la prima lettura: si puo' costruire, scrivere
        # una skill e chiedere subito — ed e' esattamente cio' che fa
        # l'agente quando genera. Con la cache armata all'inizio,
        # quello che tornava era un indice vuoto, e il sintomo era
        # "la skill non esiste" invece di "non l'ho ancora cercata".
        self._cache: dict[str, Skill] = {}
        self._leggibile = 0.0

    # -- lettura ---------------------------------------------------------

    def _skill_da_file(self, p: str, dirpath: str, base_categoria: str,
                       origine_default: str) -> tuple[str, Skill]:
        """Costruisce una Skill da uno SKILL.md."""
        campi, corpo = _leggi(p)
        nome = campi.get("name") or os.path.basename(dirpath)
        prove = _prove_json(p)
        if not prove and campi.get("prove"):
            prove = _prove_da_campo(campi["prove"])
        return nome, Skill(
            nome=nome,
            descrizione=campi.get("description", "").strip(),
            corpo=corpo,
            percorso=p,
            # La categoria e' il percorso RELATIVO alla radice
            # delle scaricate, cioe' tutto tranne il nome della
            # skill. Prendere solo il nome della cartella padre
            # perdeva i livelli: uno store con tante skill in tante
            # categorie, e dentro ognuna altre sottocategorie,
            # finiva tutto sotto una sola voce — e allora due
            # skill con lo stesso nome in posti diversi erano
            # indistinguibili. E il nome e' la chiave.
            categoria=campi.get("categoria")
            or os.path.relpath(
                os.path.dirname(dirpath), base_categoria
            ).replace(os.sep, "/"),
            origine=campi.get("origine") or origine_default,
            prove=prove,
            volte_usata=int(campi.get("volte_usata", 0) or 0),
        )

    def _scorri(self) -> None:
        # 5 secondi: abbastanza per non rileggere 188 file a ogni
        # messaggio, poco perche' una skill scaricata durante la
        # sessione successiva la vedi subito.
        if self._cache and (time.time() - self._leggibile) < 5.0:
            return
        trovate: dict[str, Skill] = {}
        for cartella, origine in ((CARTELLA_SCARICATE, "scaricata"),
                                  (CARTELLA_GENERATE, "generata")):
            radice = os.path.join(self.radice, cartella)
            if not os.path.isdir(radice):
                continue
            for dirpath, dirs, files in os.walk(radice):
                # Stessa regola dell'import: una cartella che
                # comincia per un punto non entra. Se qualcuno
                # rimette a mano una skill in .archive, deve sapere
                # che non la vedra' nel prompt — e lo deve sapere
                # dall'indice, non accorgersene.
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                if "SKILL.md" not in files:
                    continue
                p = os.path.join(dirpath, "SKILL.md")
                nome, skill = self._skill_da_file(
                    p, dirpath, os.path.join(self.radice, cartella),
                    origine)
                trovate[nome] = skill
        # Skill di base: dentro skills/ senza sottocartelle. Stessa
        # regola dei punti, e si saltano le cartelle gestite
        # (scaricate/generate) per non indicizzare due volte.
        try:
            voci = sorted(os.listdir(self.radice))
        except OSError:
            voci = []
        for voce in voci:
            if voce.startswith(".") or voce in (CARTELLA_SCARICATE,
                                                CARTELLA_GENERATE):
                continue
            p = os.path.join(self.radice, voce, "SKILL.md")
            if not os.path.isfile(p):
                continue
            nome, skill = self._skill_da_file(
                p, os.path.join(self.radice, voce), self.radice,
                "scaricata")
            trovate[nome] = skill
        self._cache = trovate
        self._leggibile = time.time()

    def _invalida(self) -> None:
        self._leggibile = 0.0

    # -- interrogazioni --------------------------------------------------

    def tutte(self) -> list[Skill]:
        self._scorri()
        return sorted(self._cache.values(), key=lambda s: s.nome)

    def per_origine(self, origine: str) -> list[Skill]:
        return [s for s in self.tutte() if s.origine == origine]

    def get(self, nome: str) -> Skill | None:
        self._scorri()
        return self._cache.get(nome)

    def nomi(self) -> list[str]:
        return [s.nome for s in self.tutte()]

    def cerca(self, parole: Iterable[str], limite: int = 6) -> list[Skill]:
        """Per pertinenza, sul nome e sulla descrizione.

        Deliberatamente povera: nessun embedding, nessun vettore. Un
        indice lessicale con 200 skill non ha bisogno di altro, e una
        ricerca semantica che sbaglia di poco e' peggio di una che
        sbaglia in modo leggibile — perche' non sai quando fidarti.
        """
        parole = [p.lower() for p in parole if p and len(p) > 2]
        if not parole:
            return []
        punteggi: list[tuple[int, Skill]] = []
        for s in self.tutte():
            testo = (s.nome + " " + s.descrizione).lower()
            p = 0
            for w in parole:
                if w in s.nome.lower():
                    p += 3          # il nome e' il segnale piu' forte
                elif w in testo:
                    p += 1
            if p:
                punteggi.append((p, s))
        punteggi.sort(key=lambda x: (-x[0], x[1].nome))
        return [s for _p, s in punteggi[:limite]]

    # -- prompt ----------------------------------------------------------

    def prompt(self, contesto: str = "", limite: int = MAX_NEL_PROMPT) -> str:
        """Le due righe per skill, scelte per pertinenza.

        Il prompt completo e' quello che finisce nel messaggio di
        sistema, e li' il posto e' conteso: se le skill lo riempiono,
        le istruzioni dell'agente passano in secondo ordine. Per
        questo il limite e' uno e non si alza.
        """
        if not self.tutte():
            return ""
        scelte = self.cerca(contesto.split(), limite=limite) if contesto else []
        if len(scelte) < limite and not contesto:
            # Solo SENZA contesto si completa con quante sono. Con un
            # contesto, completare con le prime rimaste e' il contrario
            # di cio' che serve: 40 skill "skill-NN" entrerebbero tutte,
            # perche' non hanno parole in comune col compito, e
            # finirebbero nel prompt accanto a quella che serve davvero.
            # L'agente le vede, le legge come pertinenti, e chiede
            # perche' gli serve un estrattore PDF e gli viene
            # risposto "compila apk".
            gia = {s.nome for s in scelte}
            for s in self.tutte():
                if s.nome not in gia:
                    scelte.append(s)
                    gia.add(s.nome)
                if len(scelte) >= limite:
                    break
        righe = [s.per_prompt() for s in scelte[:limite]]
        return (
            f"\n## Skill disponibili ({len(self.tutte())} in tutto, "
            f"quelle sotto sono le piu' vicine a cio' che ti hanno chiesto)\n"
            "Una skill e' una procedura gia' scritta. Se il tuo compito e' "
            "vicino a una, leggila PRIMA di improvvisare:\n"
            "  skill_leggi <nome>  porta la procedura nel contesto\n"
            "  skill_cerca <parole> cerca fra tutte\n"
            "Chiedere costa un messaggio. Improvvisare costa un intervento "
            "sbagliato che devi disfare.\n"
            + "\n".join(righe)
        )

    # -- uso -------------------------------------------------------------

    def segna_usata(self, nome: str) -> None:
        s = self.get(nome)
        if not s:
            return
        s.volte_usata += 1
        s.usata_il = time.time()
        campi, corpo = _leggi(s.percorso)
        campi["name"] = s.nome
        campi["description"] = s.descrizione
        campi["volte_usata"] = str(s.volte_usata)
        _scrivi(s.percorso, campi, corpo)
        self._invalida()

    # -- import ----------------------------------------------------------

    def importa(self, sorgente: str, categoria: str = "",
                origine: str = "scaricata") -> tuple[int, list[str]]:
        """Porta skill da uno store esterno (cartella locale o URL git).

        Se `sorgente` e' un URL (http/https/git@), clona il repository
        in una cartella temporanea, importa da li', e rimuove il clone.
        Restituisce (quante, nomi). In caso di errore di clone,
        restituisce (0, [messaggio]).
        """
        temp: str | None = None
        if _e_url(sorgente):
            temp = tempfile.mkdtemp(prefix="skill-store-")
            ok, msg = _clona_repo(sorgente, temp)
            if not ok:
                shutil.rmtree(temp, ignore_errors=True)
                return 0, [msg]
            sorgente = temp
        try:
            return self._importa_cartella(sorgente, categoria, origine)
        finally:
            if temp:
                shutil.rmtree(temp, ignore_errors=True)

    def _importa_cartella(self, sorgente: str, categoria: str = "",
                          origine: str = "scaricata") -> tuple[int, list[str]]:
        """Porta skill da una cartella locale (implementazione).

        Copia la cartella intera, non solo SKILL.md.
        """
        if not os.path.isdir(sorgente):
            return 0, []
        dentro: list[str] = []
        n = 0
        scartate: list[str] = []
        for dirpath, dirs, files in os.walk(sorgente):
            # Una cartella che inizia per un punto e' nascosta per
            # convenzione, e in uno store ".archive" significa
            # "messo via apposta". Importarlo comunque porta dentro
            # roba che qualcuno ha deciso di non usare piu' — e da
            # tante skill, con meta' del prompt speso su nomi che
            # nessuno aprira'.
            #
            # Non e' una deduplica e' una distinzione: una skill
            # archiviata puo' essere proprio quella giusta, e in quel
            # caso la cerchi tu. Quello che non si fa e' metterla nel
            # prompt senza che nessuno l'abbia chiesta.
            nascoste = [d for d in dirs if d.startswith(".")]
            for h in nascoste:
                scartate.append(h)
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if any(part.startswith(".") for part in
                   os.path.relpath(dirpath, sorgente).split(os.sep)):
                continue
            if "SKILL.md" not in files:
                continue
            nome = os.path.basename(dirpath)
            # La categoria e' il PRIMO livello dentro lo store, non il
            # nome della cartella che contiene lo store. Con una
            # sottocategoria annidata, il parametro `categoria` deve
            # comunque andare davanti: se lo store e' gia' diviso in
            # categorie (creative/, devops/), rigenerarle dal nome
            # della singola cartella perdeva quell'informazione e
            # battezzava tutto "estratte".
            sottocat = os.path.relpath(dirpath, sorgente)
            parti = [p for p in sottocat.split(os.sep)[:-1] if p not in (".",)]
            if categoria:
                parti.insert(0, categoria)
            elif not parti:
                parti = ["generale"]
            dest = os.path.join(self.radice, CARTELLA_SCARICATE, *parti, nome)
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(dirpath, dest, dirs_exist_ok=True)
            # Le prove non sopravvivono a un reimport: quelle
            # scaricate non ne hanno mai avute, e coprire un file
            # .prove.json dalla versione precedente lascerebbe prove
            # di una procedura che non e' piu' quella.
            for extra in os.listdir(dest):
                if extra.endswith(".prove.json"):
                    os.remove(os.path.join(dest, extra))
            # Il frontmatter ricorda la categoria. Senza, rimettere una
            # skill dal cestino la piazzava sotto "generale": la copia
            # nel cestino ha la stessa posizione della copia attiva, e
            # la categoria si ricava dal percorso — ma in .cestino quel
            # percorso e' fatto di timestamp e non dice piu' nulla.
            p_copia = os.path.join(dest, "SKILL.md")
            campi, corpo = _leggi(p_copia)
            campi["name"] = nome
            if not campi.get("categoria"):
                campi["categoria"] = "/".join(parti)
            campi.setdefault("origine", "scaricata")
            _scrivi(p_copia, campi, corpo)
            n += 1
            dentro.append(nome)
        if n:
            self._invalida()
        return n, dentro


def _prove_da_campo(testo: str) -> list[dict[str, Any]]:
    """Prove nel corpo del frontmatter.

    Il JSON inline serve a chi scrive a mano. Con 188 skill importate
    e poi modificate, pero', finisce in una riga sola e illeggibile.
    Per questo accetta entrambe: un file accanto, che e' il modo
    normale, o il campo nel frontmatter, che e' per l'uso singolo.
    """
    try:
        d = json.loads(testo)
        return d if isinstance(d, list) else []
    except (ValueError, TypeError):
        return []


# ------------------------------------------------------------------------
# Generazione
# ------------------------------------------------------------------------


@dataclass
class Candidato:
    """Una procedura che potrebbe diventare skill, e perche' forse no."""

    nome: str
    descrizione: str
    corpo: str
    prove: list[dict[str, Any]] = field(default_factory=list)
    motivo_rifiuto: str = ""

    @property
    def vale(self) -> bool:
        if len(self.prove) < SOGLIA_RIPETIZIONI:
            return False
        if len(self.corpo) < LUNGHEZZA_MINIMA:
            return False
        return bool(self.nome.strip())


def valuta_candidato(c: Candidato, soglia: int = SOGLIA_RIPETIZIONI) -> tuple[bool, str]:
    """Il giudizio, e la ragione.

    La ragione serve perche' "no" senza spiegazione e' indistinguibile
    da un bug: se il 90% delle procedure non genera skill, l'utente
    pensa che il meccanismo sia rotto invece che severo.
    """
    if len(c.prove) < soglia:
        return False, (f"{len(c.prove)}/{soglia} prove: si aspetta che "
                       f"riunisca prima")
    if len(c.corpo) < LUNGHEZZA_MINIMA:
        return False, (f"corpo troppo corto ({len(c.corpo)} caratteri, "
                       f"minimo {LUNGHEZZA_MINIMA}): e' un comando, "
                       f"non una procedura")
    if not c.nome.strip():
        return False, "senza nome"
    return True, f"{len(c.prove)} prove"


def salva_generata(indice: Indice, c: Candidato) -> str:
    """Scrive la skill generata e il suo file di prove.

    Il nome viene ripulito: un nome di file che siamo noi a scrivere
    e' una porta che siamo noi ad aprire. Una skill il cui nome e'
    "../avvia" potrebbe uscire dalla cartella al primo shutil.
    """
    nome = _nome_sicuro(c.nome)
    p = os.path.join(indice.radice, CARTELLA_GENERATE, nome, "SKILL.md")
    _scrivi(p, {
        "name": nome,
        "description": c.descrizione.strip() or "Procedura appresa.",
        "categoria": "generata",
        "origine": "generata",
        "generata_il": time.strftime("%Y-%m-%d %H:%M"),
        "prove": str(len(c.prove)),
    }, c.corpo)
    _prove_scrivi(p, c.prove)
    indice._invalida()
    return p


_NOME_SPORCO = re.compile(r"[^A-Za-z0-9._-]+")


def _e_url(sorgente: str) -> bool:
    s = (sorgente or "").strip().lower()
    return (s.startswith("http://") or s.startswith("https://")
            or s.startswith("git@") or s.startswith("ssh://"))


def _clona_repo(url: str, dest: str) -> tuple[bool, str]:
    """Clona un repository git in `dest`. Shallow, senza prompt.

    Restituisce (ok, messaggio). `git` deve essere nel PATH: se non
    c'e', l'errore viene riportato invece di far cadere l'import.
    """
    try:
        r = subprocess.run(
            ["git", "clone", "--depth", "1", url.strip(), dest],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        return False, "git non trovato nel PATH"
    except subprocess.TimeoutExpired:
        return False, "clone scaduto (timeout 120s)"
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        return False, f"clone fallito: {err[:300]}"
    return True, "ok"


def _nome_sicuro(nome: str) -> str:
    """Un nome che puo' stare in una cartella, e nient'altro."""
    s = _NOME_SPORCO.sub("-", (nome or "").strip()).strip("-._")
    s = s[:80]
    # ".." dentro un nome non puo' salire, ma ".." da solo e' la
    # cartella sopra: si toglie, perche' il costo e' zero.
    while ".." in s:
        s = s.replace("..", ".")
    return s or "skill"
