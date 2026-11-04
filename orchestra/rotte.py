"""La tabella delle rotte HTTP.

Una rotta era un ramo di una catena `elif path == "..."` dentro `do_POST`,
lunghi fino a millenovecento righe. Il difetto non era la lunghezza: era che
il metodo e il percorso erano due cose diverse nello stesso `if`. Un ramo
scritto solo sotto GET faceva rispondere 404 a un POST che esisteva, e chi
lo chiamava leggeva "non trovato" invece di "questo non si fa in GET". E'
successo due volte, su `/api/skill` e su `/api/skill/file`, e ogni volta la
cura e' stata un secondo ramo copiato sotto l'altro metodo.

Qui la rotta e' un dato: metodo, percorso, gestore, dichiarati una volta
accanto al codice che la serve con `@rotta("GET", "/api/state")`. Il
dispatch e' uno solo, e allora "metodo sbagliato" e' una risposta che si
puo' dare sempre (405 con `Allow`), non un caso che ogni ramo deve
ricordarsi di distinguere.

TRE REGOLE

1. Il percorso esatto vince sul modello. `/api/tracce/oggi` non deve
   finire in `/api/tracce/{id}` solo perche' il modello e' stato
   registrato prima: la rotta scritta per quel percorso e' quella che
   qualcuno ha pensato, e non deve dipendere dall'ordine degli import.

2. Un doppione e' un errore all'import, non un comportamento. Due gestori
   sullo stesso metodo e percorso farebbero vincere il primo registrato —
   cioe' l'ordine degli import deciderebbe quale codice gira. Meglio non
   partire.

3. I parametri sono segmenti, non espressioni regolari. `{id}` prende un
   segmento non vuoto; tutto il resto e' confronto letterale. Non serve
   altro, e una regex permetterebbe a una rotta di nasconderne un'altra
   senza che si veda leggendo la tabella.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

METODI = ("GET", "POST", "PUT", "PATCH", "DELETE")


class ErroreRotte(RuntimeError):
    """La tabella e' configurata male. Non e' una richiesta sbagliata."""


@dataclass(frozen=True)
class Rotta:
    metodo: str
    percorso: str
    gestore: Callable[..., Any]
    parti: tuple[str, ...]
    parametri: tuple[str, ...]

    @property
    def modello(self) -> bool:
        """Vero se il percorso contiene almeno un `{nome}`."""
        return bool(self.parametri)

    def combacia(self, parti: tuple[str, ...]) -> dict[str, str] | None:
        """I parametri estratti, oppure None se il percorso non e' questo."""
        if len(parti) != len(self.parti):
            return None
        fuori: dict[str, str] = {}
        for atteso, trovato in zip(self.parti, parti):
            if atteso.startswith("{") and atteso.endswith("}"):
                if not trovato:
                    return None
                fuori[atteso[1:-1]] = trovato
            elif atteso != trovato:
                return None
        return fuori


def _spezza(percorso: str) -> tuple[str, ...]:
    # split e non split + filtro: la differenza tra "/api/x" e "/api/x/" e'
    # un segmento vuoto in fondo, e il server non normalizza i percorsi.
    return tuple(percorso.split("/"))


def _forma(parti: tuple[str, ...]) -> tuple[str, ...]:
    """Le parti con i nomi dei parametri azzerati, per trovare i doppioni."""
    return tuple("{}" if p.startswith("{") and p.endswith("}") else p
                 for p in parti)


class Tabella:
    def __init__(self) -> None:
        self._esatte: dict[tuple[str, str], Rotta] = {}
        self._modelli: list[Rotta] = []

    def registra(self, metodo: str, percorso: str,
                 gestore: Callable[..., Any]) -> Rotta:
        metodo = (metodo or "").upper()
        if metodo not in METODI:
            raise ErroreRotte(f"metodo sconosciuto: {metodo!r}")
        if not percorso.startswith("/"):
            raise ErroreRotte(f"percorso senza / iniziale: {percorso!r}")
        if not callable(gestore):
            raise ErroreRotte(f"gestore non chiamabile per {metodo} {percorso}")

        parti = _spezza(percorso)
        parametri = tuple(p[1:-1] for p in parti
                          if p.startswith("{") and p.endswith("}"))
        for nome in parametri:
            if not nome.isidentifier():
                raise ErroreRotte(
                    f"parametro non valido {{{nome}}} in {metodo} {percorso}")
        if len(set(parametri)) != len(parametri):
            raise ErroreRotte(f"parametro ripetuto in {metodo} {percorso}")

        # Il doppione si cerca sulla forma, non sul testo: `/a/{x}` e
        # `/a/{y}` sono la stessa rotta, e il secondo nome non crea una
        # rotta nuova — crea due gestori che nessuno puo' distinguere.
        for gia in self.tutte():
            if gia.metodo != metodo:
                continue
            if gia.parti == parti or _forma(gia.parti) == _forma(parti):
                raise ErroreRotte(
                    f"rotta ripetuta: {metodo} {percorso} "
                    f"(gia' registrata come {gia.percorso})")

        rotta_ = Rotta(metodo=metodo, percorso=percorso, gestore=gestore,
                       parti=parti, parametri=parametri)
        if rotta_.modello:
            self._modelli.append(rotta_)
        else:
            self._esatte[(metodo, percorso)] = rotta_
        return rotta_

    def cerca(self, metodo: str, percorso: str
              ) -> tuple[Rotta, dict[str, str]] | None:
        """La rotta che serve questa richiesta, o None.

        None vuol dire una di due cose, e chi chiama le distingue con
        `metodi()`: percorso sconosciuto (404) o metodo sbagliato (405).
        """
        metodo = (metodo or "").upper()
        esatta = self._esatte.get((metodo, percorso))
        if esatta is not None:
            return esatta, {}
        parti = _spezza(percorso)
        for modello in self._modelli:
            if modello.metodo != metodo:
                continue
            parametri = modello.combacia(parti)
            if parametri is not None:
                return modello, parametri
        return None

    def metodi(self, percorso: str) -> set[str]:
        """I metodi che accettano questo percorso, per l'header `Allow`."""
        ammessi: set[str] = set()
        for (metodo, scritto) in self._esatte:
            if scritto == percorso:
                ammessi.add(metodo)
        parti = _spezza(percorso)
        for modello in self._modelli:
            if len(modello.parti) == len(parti) and modello.combacia(parti) is not None:
                ammessi.add(modello.metodo)
        return ammessi

    def tutte(self) -> list[Rotta]:
        """Tutte le rotte, esatte e modelli, in ordine stabile."""
        elenco = list(self._esatte.values()) + list(self._modelli)
        return sorted(elenco, key=lambda r: (r.percorso, r.metodo))

    def per_metodo(self, metodo: str) -> list[Rotta]:
        return [r for r in self.tutte() if r.metodo == metodo.upper()]

    def verifica(self) -> list[str]:
        """I problemi che si possono vedere solo guardando l'insieme.

        Non lancia: un test vuole l'elenco, e una diagnostica vuole
        mostrarlo invece di morire. Le registrazioni singole invece
        falliscono subito, perche' li' il contesto e' ancora quello giusto
        per dire quale riga ha sbagliato.
        """
        problemi: list[str] = []
        visti: dict[tuple[str, tuple[str, ...]], str] = {}
        for r in self.tutte():
            chiave = (r.metodo, _forma(r.parti))
            if chiave in visti:
                problemi.append(
                    f"{r.metodo} {r.percorso} ripete {visti[chiave]}")
                continue
            visti[chiave] = r.percorso
            if not r.gestore.__name__:
                problemi.append(f"{r.metodo} {r.percorso} senza nome")
        return problemi


# La tabella del server. E' un singleton di modulo, e non un attributo
# della classe, perche' le rotte si registrano mentre il corpo della classe
# viene eseguito: a quel punto `Handler` non esiste ancora.
ROTTE = Tabella()


def rotta(metodo: str, percorso: str):
    """Dichiara una rotta sopra il metodo che la serve.

        @rotta("GET", "/api/state")
        def _r_get_state(self, path, body, s): ...

    Il decoratore restituisce la funzione com'era: il metodo resta un metodo
    normale, chiamabile (e testabile) anche senza passare dal server.
    """
    def registra(gestore: Callable[..., Any]) -> Callable[..., Any]:
        ROTTE.registra(metodo, percorso, gestore)
        return gestore
    return registra
