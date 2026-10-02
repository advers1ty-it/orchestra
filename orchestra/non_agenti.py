"""Un modello che non parla non è un agente.

IL BUCO

Groq mescola nel suo catalogo tre cose che non hanno niente a che
vedere fra loro: i modelli che parlano, i modelli che ascoltano
(`whisper-large-v3` prende audio e restituisce testo), e i
classificatori (`llama-prompt-guard-2-22m` non genera: classifica se
un prompt e' un attacco injection).

Tutti e tre rispondono su `/chat/completions`, quindi il filtro del
tool-calling non li distingue: nessuno dichiara `supports_tools:
false`, e `with_tools()` li lascia passare tutti.

Il risultato e' stato questo: l'instradamento ha assegnato a un
figlio `llama-prompt-guard-2-22m`, un classificatore da 22 milioni di
parametri, che risponde `safe`/`unsafe` invece di contare le righe di
un file. Non e' un errore di punteggio: e' un modello sbagliato nella
stessa categoria, scelto legittimamente.

PERCHE' UN ELENCO DI NOMI, E NON UNA REGOLA GENERALE

Perche' non c'e' un campo "modale" affidabile: `whisper` su OpenRouter
ha architettura diverse da `whisper` su Groq e le liste di modelli non
portano informazione sui formati. Un tentativo di dedurlo dalla
struttura del nome escluderebbe anche modelli buoni che hanno un
trattino nel nome — e un modello escluso per sbaglio e' un modello che
non ti serve, e non lo vedi.

Quindi: nomi noti, esclusi per nome, e la lista e' dichiarata e
leggibile. Il rischio residuo — un modello non-linguistico con un
nome che non conosciamo — resta, ed e' il motivo per cui la delega
dichiara il modello che ha usato: un nome sbagliato si vede alla
prima risposta.
"""

# Modelli che NON generano testo. Se un giorno un provider li espone
# in un formato diverso, la lista va accorciata — e il fatto che sia
# una lista vuol dire che si puo' accorgersene.
NON_AGENTI = (
    "whisper",            # trascrizione audio
    "prompt-guard",       # classificatore di injection
    "tts-",               # sintesi vocale
    "text-moderation",
    "embed",              # vettori: non parlano
    "orpheus-arabic",     # solo arabo: di una lingua sola
)
# Nota su quello che ho tolto: c'era anche `guard-2`, per coprire i
# nomi abbreviati. Ma `guard-2` e' dentro `gpt-oss-safeguard-20b`, che
# e' un modello vero: e' stato escluso per tre caratteri di nome. Un
# filtro che Butta via un modello buono e' peggio di un filtro che
# lascia passare uno strano — il primo non lo vedi, il secondo lo
# vedi dalla risposta. Meglio la lista corta.


def e_agent(mid: str) -> bool:
    """Questo id e' un modello che puo' fare il lavoro di Orchestra?"""
    m = (mid or "").lower()
    return not any(k in m for k in NON_AGENTI)


def spiegazione_esclusione(mid: str) -> str:
    """Perche' un id e' stato escluso. Vuota se non e' escluso."""
    m = (mid or "").lower()
    for k in NON_AGENTI:
        if k in m:
            return k
    return ""