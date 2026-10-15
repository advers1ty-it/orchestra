"""La delega: un agente che chiede a un altro agente.

CHE COSA È, E PERCHÉ ESISTE

Un agente lungo si riempie. Va e torna fra la richiesta iniziale, i
file che ha letto, i tentativi che sono falliti, e il risultato che
alla fine voleva. Dopo venti passi la metà di quello che ha in testa
sono cose che ha già scoperto e che non gli servono più.

La delega serve a questo: il padre tiene la domanda e passa a un
figlio un compito stretto. Il figlio parte con una finestra vuota,
fa il suo lavoro, e indietro torna **solo la risposta** — non il
trascorso. Il padre non ha mai visto i venti passi, quindi non ne
porta il costo.

IL FILO, E LA RAGIONE DEL FILO

Un figlio che può delegare a sua volta è un regresso infinito: A
delega a B, B delega a C, C delega a D, e ogni generazione costa
token finché finisce il credito o finisce la pazienza. Non è un
rischio teorico — è quello che fanno i sistemi che si auto-pianificano
senza un tetto.

Quindi il figlio NON delega. Non è una scelta che si lascia al
modello: è che il tool non esiste nel registro che il figlio riceve.
Un tetto che si può disattivare non è un tetto, e un tetto messo
solo nelle istruzioni è un tetto che un modello può dimenticare al
quarto passo.

IL CONTESTO VIENE DA CHI DELEGA

Il padre scrive il contesto, e lo scrive per il figlio: che cosa deve
sapere e che cosa può ignorare. Non gli passiamo la conversazione.
È proprio il punto della delega.

LA SCELTA DEL MODELLO

Il figlio non eredita il modello del padre per default. Ne sceglie
uno proprio, con lo stesso instradamento del padre ma sulla sua
domanda: un compito stretto e meccanico spesso è meglio su un modello
piccolo, e spendere il modello forte per fare il lavoro di uno piccolo
è il modo più comune di buttare via un orchestratore.
"""

PROFONDITA_MAX = 1

from typing import Any, Callable


class Figlio:
    """Il risultato di un compito delegato, visto dal padre.

    Non e' una stringa perche' il padre deve poter distinguere tre
    cose che sembrano uguali guardando il testo: che il figlio ha
    risposto, che il figlio ha esaurito i passi, e che il figlio e'
    andato in errore. Sono tre esiti diversi e portano a tre decisioni
    diverse — accettare, rivedere, cambiare approccio — e un errore
    presentato come risposta e' il peggiore dei tre, perche' il padre
    non ha modo di accorgersene.
    """

    def __init__(self, esito: str, testo: str, *, passi: int = 0,
                 modello: str = "", motivo: str = "",
                 costo: float | None = None):
        self.esito = esito        # "risposto" | "esaurito" | "errore"
        self.testo = testo
        self.passi = passi
        self.modello = modello
        self.motivo = motivo
        self.costo = costo

    @property
    def ok(self) -> bool:
        return self.esito == "risposto"

    def per_il_padre(self) -> str:
        """Cosa il padre legge: la risposta e come' e' finita.

        L'esito va PRIMO e in chiaro, perche' se arriva dopo un
        testo lungo e fallito il padre lo legge come un risultato.
        """
        if self.esito == "risposto":
            return self.testo
        if self.esito == "esaurito":
            # `self.passi` è il numero VERO di passi di questo figlio,
            # non un numero fisso: il figlio eredita i passi dal padre,
            # quindi il messaggio deve riportare il valore effettivo
            # raggiunto, non una costante.
            return (f"[il figlio ha finito i {self.passi} passi senza "
                    f"rispondere — non e' un risultato]\n{self.testo}")
        return (f"[il figlio e' andato in errore: {self.motivo} — "
                f"non e' un risultato]\n{self.testo}")

    def __repr__(self) -> str:
        return f"<Figlio {self.esito} su {self.passi} passi>"


def _risposta_finale(stato: Any) -> str:
    """L'ultima cosa che ha detto il figlio, come testo.

    `Agent.run()` restituisce un `AgentState`, e in quello NON c'e' un
    campo `finale`: la risposta e' l'ultimo messaggio dell'assistente.
    Me ne ero accorto perche' ho scritto `finale` qui e il figlio
    tornava sempre con `passi=0` e testo vuoto — sembrava un modello
    muto, ed era un campo che non esiste.

    Un campo inventato e' il difetto peggiore di questo modulo:
    funziona, non alza niente, e restituisce il vuoto. Il vuoto viene
    poi letto come «il modello non ha risposto», che e' una diagnosi
    che si propaga e che nessuno controlla piu'.
    """
    messaggi = getattr(stato, "messages", None) or []
    for m in reversed(messaggi):
        if getattr(m, "role", "") == "assistant":
            return (getattr(m, "content", "") or "").strip()
    return ""


def _ultimo_progresso(stato: Any) -> str:
    """L'ultimo pezzo di lavoro concreto, quando non c'e' risposta finale.

    Un figlio che esaurisce i passi spesso ha COMUNQUE fatto qualcosa di
    utile: eseguito un tool, letto un file, tentato un comando. Tornare
    vuoto butta quel lavoro e non dice perche' si e' fermato. Qui si
    prende l'ultimo tool eseguito e il suo esito, in una riga: il padre
    (e l'utente) vede DOVE il figlio si e' incagliato invece di un muto
    "non ha risposto".
    """
    messaggi = getattr(stato, "messages", None) or []
    ultimo_tool = ""
    for m in reversed(messaggi):
        ruolo = getattr(m, "role", "")
        if ruolo == "tool":
            nome = getattr(m, "name", "") or "tool"
            contenuto = (getattr(m, "content", "") or "").strip()
            # tagliato: un risultato da 3000 righe in una riga di
            # diagnosi è rumore, non informazione
            if len(contenuto) > 200:
                contenuto = contenuto[:200] + "…"
            esito = "errore" if contenuto.startswith("ERRORE") else "ok"
            ultimo_tool = f"ultimo tool `{nome}` ({esito}): {contenuto}"
            break
        if ruolo == "assistant":
            # un assistente con contenuto parziale è già qualcosa
            testo = (getattr(m, "content", "") or "").strip()
            if testo:
                ultimo_tool = f"ultimo messaggio prima di fermarsi: {testo[:200]}"
                break
    if not ultimo_tool:
        return ""
    return f"[il figlio si è fermato senza chiudere — {ultimo_tool}]"


def _costo(stato: Any, tariffa: Any = None) -> float | None:
    """Quanto ha costato il figlio. None se non lo si sa.

    `AgentState` non ha un campo `costo`: ha `total_tokens`, e i token
    non distinti fra input e output. La tariffa la sa il catalogo —
    `ModelInfo.estimate_cost` — quindi serve passarla dentro, e quando
    non c'e' il risultato e' None, NON zero.

    La differenza non e' accademica: `0.0000 USD` nel resoconto dice
    "questa delega e' stata gratis", e una delega gratuita che non lo
    e' stata si scopre dal conto, non dal log. Un numero falso in un
    posto che si presume sia misurato e' peggio di un campo vuoto,
    perche' il campo vuoto si nota.

    Il tariffario riceve i soli `total_tokens` e li tratta tutti come
    input: e' un'approssimazione in eccesso (l'output costa di piu' su
    quasi tutti i modelli), e la si dichiara invece di nasconderla.
    """
    if tariffa is None:
        return None
    try:
        return float(tariffa(int(getattr(stato, "total_tokens", 0) or 0)))
    except Exception:  # noqa: BLE001
        return None


class Delegatore:
    """Costruisce i figli e tiene conto di quanto costano.

    Un oggetto e non una funzione, perche' la delega ha due costi che
    una funzione non porta con se': quanto costa (token), e quanto
    spesso (i figli che si sono rivelati inutili). Il secondo e' il
    dato che dice se il padre merita di delegare la prossima volta —
    e senza averlo, la delega e' una scelta cieca.
    """

    def __init__(self, fabbrica: Callable[[str], Any],
                 *, scegli_modello: Callable[[str], Any] | None = None,
                 tariffa: Callable[[int], float] | None = None,
                 profondita: int = 0, max_figli: int = 6,
                 on_modello_usato: Callable[[str], None] | None = None):
        self._fabbrica = fabbrica          # obiettivo -> Agent
        self._scegli_modello = scegli_modello
        self._tariffa = tariffa
        self.on_modello_usato = on_modello_usato
        self.profondita = profondita
        self.max_figli = max_figli
        self.n_figli = 0
        self.costo_totale: float | None = None
        self.storia: list[dict[str, Any]] = []

    def puo_delegare(self) -> tuple[bool, str]:
        """Se si puo' ancora delegare, e perchè no quando non si puo'.

        Anche il perche', perche' un "no" senza spiegazione nel mezzo
        di un ragionamento e' indistinguibile da un crash.
        """
        if self.profondita >= PROFONDITA_MAX:
            return False, (f"profondità massima ({PROFONDITA_MAX}): "
                           f"un figlio non delega a sua volta")
        if self.n_figli >= self.max_figli:
            return False, (f"troppi figli già ({self.n_figli}): il tetto "
                           f"serve a fermare un piano che non finisce")
        return True, ""

    def delega(self, obiettivo: str, contesto: str = "") -> Figlio:
        """Affida un compito. Non solleva mai: torna sempre un Figlio.

        Sollevare qui sarebbe l'errore piu' ovvio: un figlio che
        crasha deve togliere un pezzo al padre, non fermarlo. Il padre
        legge "errore" e decide da li' — ed e' l'unica cosa che puo'
        decidere lui, perche' lui e' l'unico che sa cosa stava
        cercando.
        """
        puo, perche_no = self.puo_delegare()
        if not puo:
            f = Figlio("errore", "", motivo=perche_no)
            self._registra(obiettivo, f)
            return f

        self.n_figli += 1
        testo = (contesto.strip() + "\n\n" if contesto else "") + obiettivo.strip()

        modello = ""
        if self._scegli_modello is not None:
            try:
                modello = self._scegli_modello(obiettivo) or ""
            except Exception:  # noqa: BLE001
                # La scelta del modello che fallisce non ferma il
                # lavoro: si delega senza sapere il modello, e si
                # dichiara che non si sa. Il contrario — non delegare
                # perche' non si e' potuti scegliere il modello —
                # punirebbe il padre per un problema che non e' suo.
                modello = ""

        try:
            figlio = self._fabbrica(testo)
            stato = figlio.run(testo)
        except Exception as e:  # noqa: BLE001
            f = Figlio("errore", "", modello=modello, motivo=str(e))
            self._registra(obiettivo, f)
            return f

        testo_out = _risposta_finale(stato)
        passi = int(getattr(stato, "iterations", 0) or 0)
        costo = _costo(stato, self._tariffa)

        # Se il figlio ha esaurito i passi senza chiudere col testo, non
        # si torna vuoto: vuoto non dice DOVE si è incagliato. Si estrae
        # l'ultimo progresso utile — l'ultimo tool che ha eseguito e cosa
        # è tornato — così il padre vede "ha provato run_shell, è tornato
        # errore" invece di "non ha risposto". È la differenza fra un
        # fallimento diagnosticabile e uno muto.
        progresso = ""
        if not testo_out:
            progresso = _ultimo_progresso(stato)
            if progresso:
                testo_out = progresso

        esito = "risposto"
        motivo = ""
        # `stopped_because` dice PERCHE' l'agente si e' fermato, e la
        # ragione e' quella che va data al padre. Senza, un figlio che
        # si e' fermato perche' ha finito i passi e uno che si e'
        # fermato perche' il provider e' andato via si presentano
        # uguali.
        ragione_fermo = getattr(stato, "stopped_because", "") or ""
        # L'esito "esaurito" dipende da come si è fermato, non dal fatto
        # che io abbia recuperato un progresso: se ha esaurito i passi, è
        # esaurito ANCHE se ho trovato un ultimo tool utile da mostrare. Il
        # testo recuperato sta DENTRO il messaggio, non lo trasforma in un
        # successo — sarebbe dire al padre "risposto" per un figlio che non
        # ha chiuso.
        if ragione_fermo and ragione_fermo != "risposta_finale":
            esito = "esaurito"
            motivo = f"fermato: {ragione_fermo} (dopo {passi} passi)"
        elif not testo_out:
            esito, motivo = "errore", "nessuna risposta finale"

        # Il modello usato serve al tariffario: il prezzo che conta
        # e' quello del modello che ha fatto il lavoro, non quello
        # previsto al momento della scelta.
        if modello and self.on_modello_usato is not None:
            try:
                self.on_modello_usato(modello)
            except Exception:  # noqa: BLE001
                pass

        f = Figlio(esito, testo_out, passi=passi, modello=modello,
                   motivo=motivo, costo=costo)
        self._registra(obiettivo, f)
        return f

    def _registra(self, obiettivo: str, f: Figlio) -> None:
        if f.costo is not None:
            self.costo_totale = (self.costo_totale or 0.0) + f.costo
        self.storia.append({
            "obiettivo": obiettivo[:120],
            "esito": f.esito,
            "passi": f.passi,
            "modello": f.modello,
            "costo": f.costo,
        })

    def resoconto(self) -> str:
        """Quanto sono costati i figli, in una riga.

        Serve al padre per capire se la delega ha reso. Una delega che
        costa piu' di fare il lavoro direttamente e' una delega da non
        fare, e senza questo numero non lo si scopre che dopo.
        """
        utili = sum(1 for s in self.storia if s["esito"] == "risposto")
        soldi = ("costo non noto" if self.costo_totale is None
                 else f"{self.costo_totale:.4f} USD")
        return f"{len(self.storia)} deleghe, {utili} utili, {soldi}"
