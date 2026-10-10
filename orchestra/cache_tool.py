"""Cache dei risultati dei tool, sui soli tool PURI.

Il problema: se l'agente chiede due volte la stessa cosa nello stesso
turno (o in turni vicini), la rifà da capo — una `calculate`, una
`read_file` di un file che non è cambiato. Costo e tempo spesi per un
risultato identico.

Il rischio, ed è grosso: cacheare un tool il cui risultato dipende dal
MONDO esterno dà roba vecchia spacciata per nuova. Se `read_file(path)`
torna il contenuto cachato e il file è cambiato, l'agente legge un
fantasma. Se `web_cerca` torna risultati vecchi, l'agente risponde con
notizie di ieri. Peggio che lento: sbagliato.

Quindi la regola è una sola: si cachea SOLO ciò che è PURO — il cui
risultato dipende solo dagli argomenti, deterministico, indipendente da
qualsiasi stato esterno. `calculate("2+2")` è sempre 4. Tutto il resto
no. Un tool entra in cache se lo dichiara lui, non per indovinare: la
lista è esplicita, e un tool non elencato NON si cachea, punto.

TTL breve (5 minuti) anche sui puri: non costano niente a ricalcolare, e
un TTL lungo su una cache in memoria che muore col processo è
un'ottimizzazione che non ottimizza niente.

La cache è in memoria e per-processo: non sopravvive al riavvio, ed è
voluto. Una cache persistente dei tool è un modo sottile per servire
roba vecchia dopo un aggiornamento.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Callable

# I tool il cui risultato è PURO: dipende solo dagli argomenti, sempre
# uguale, indipendente dal mondo. Questa lista è l'unica autorità: un
# tool non elencato qui non si cachea, qualunque cosa faccia.
# `calculate`: aritmetica, 2+2 fa 4 oggi e domani.
# `skill_cerca`/`skill_leggi`: cercano fra le skill, che cambiano solo se
#   l'utente le modifica — e anche allora un TTL di 5 minuti è accettabile
#   perché il danno è leggere un indice di skill leggermente stantio, non
#   un dato di lavoro sbagliato.
# `list_dir` NON c'è di proposito: il contenuto di una cartella cambia, ed
#   è esattamente il tool su cui un fantasma farebbe più danno.
TOOL_PURI = frozenset({"calculate", "skill_cerca", "skill_leggi"})

TTL_S = 300.0  # 5 minuti: breve, perché i puri costano poco a ricalcolare


class CacheTool:
    """Cache in memoria, thread-safe, con scadenza.

    Thread-safe perché l'agent gira in un thread e la UI può ispezionare
    dall'altro; una dict nuda condivisa è una race. Il lock è grossolano
    ma la sezione critica è un acceso a dict: la contesa è irrilevante.
    """

    def __init__(self, ttl: float = TTL_S) -> None:
        self._ttl = ttl
        self._dati: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self.hit = 0
        self.miss = 0

    @staticmethod
    def _chiave(nome: str, args: dict[str, Any]) -> str:
        # Chiave stabile dai soli argomenti rilevanti: l'ordine delle
        # chiavi del dict non deve cambiare la cache. sha1 dei dati
        # canonici — breve e senza collisioni pratiche.
        grezzo = repr(sorted((k, repr(v)) for k, v in (args or {}).items()))
        return f"{nome}|{hashlib.sha1(grezzo.encode()).hexdigest()[:16]}"

    def cachevole(self, nome: str) -> bool:
        return nome in TOOL_PURI

    def prendi(self, nome: str, args: dict[str, Any]) -> str | None:
        if not self.cachevole(nome):
            return None
        chiave = self._chiave(nome, args)
        with self._lock:
            voce = self._dati.get(chiave)
            if voce is None:
                self.miss += 1
                return None
            ts, valore = voce
            if time.time() - ts > self._ttl:
                # scaduto: si cancella e si conta come miss, non come hit
                del self._dati[chiave]
                self.miss += 1
                return None
            self.hit += 1
            return valore

    def metti(self, nome: str, args: dict[str, Any], valore: str) -> None:
        if not self.cachevole(nome):
            return
        with self._lock:
            self._dati[self._chiave(nome, args)] = (time.time(), valore)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"hit": self.hit, "miss": self.miss,
                    "voci": len(self._dati),
                    "tool_cachevoli": sorted(TOOL_PURI)}

    def svuota(self) -> None:
        with self._lock:
            self._dati.clear()


# Una cache per processo: l'agent la trova senza passarla a mano, e più
# agent non devono dividersi una cache che ha senso solo per processo.
_cache: CacheTool | None = None


def cache_tool() -> CacheTool:
    global _cache
    if _cache is None:
        _cache = CacheTool()
    return _cache
