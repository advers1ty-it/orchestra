"""Scrittura sicura del .env.

Il menu Opzioni scrive le chiavi da solo, e questa e' la parte piu'
sensibile dell'applicazione: il server sta su 127.0.0.1 senza
autenticazione, quindi chiunque riesca a raggiungere la porta locale
potrebbe leggere e scrivere le chiavi. Le protezioni qui dentro non sono
decorative, sono il motivo per cui si puo' esporre un editor.

Le regole:

1. **Mai restituire il valore.** Solo "configurata" o no, e gli ultimi
   4 caratteri. Una chiave che torna in una risposta JSON finisce nei
   log, nella cronologia e in qualunque schermata.
2. **Whitelist.** Si puo' scrivere solo una chiave che corrisponde a un
   provider noto o a un'impostazione dichiarata. Senza, un POST
   scriverebbe `PATH=/usr/bin` o riga vuota e avremmo dato a chiunque
   una scrittura arbitraria su disco.
3. **Niente newline.** Un valore con dentro un a capo finirebbe su due
   righe e il .env diventerebbe un file diverso da quello che credevamo.
4. **Sovrascritura atomica.** Si scrive in un temporaneo e poi si
   rinomina: un crash a meta' non lascia il .env a meta'.
5. **Non toccare le altre righe.** Commenti, spazi, ordine: tutto com'era.
   Una persona ci mette dentro roba sua e non deve perderla.
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Any

# Chiavi scrivibili dal menu. Ogni voce e' un provider che Orchestra sa
# usare, o un'impostazione che il programma legge davvero. Nient'altro:
# se una chiave non e' in questa lista, non e' scritta.
# Scrivibili ma NON mostrate fra le chiavi: sono configurazione, e il
# pannello le espone come menu a tendina. Se comparissero anche nella
# lista delle chiavi, ci sarebbero due modi per cambiarle e divergerebbero
# senza che nessuno se ne accorga.
SOLO_SCRIVIBILI = ("ORCHESTRA_PROVIDER", "ORCHESTRA_MODEL", "ORCHESTRA_REASONING", "ORCHESTRA_BUDGET", "ORCHESTRA_MAX_ITERS", "ORCHESTRA_CONTEXT_LIMIT")

WRITABLE: dict[str, str] = {
    # Ordine di visualizzazione: prima il predefinito, poi le chiavi
    # con piano gratis, poi il resto. Scritte per nome, mai per
    # posizione: riordinare non rompe niente.
    "OPENROUTER_API_KEY": "OpenRouter",
    "GROQ_API_KEY": "Groq",
    "CEREBRAS_API_KEY": "Cerebras",
    "MISTRAL_API_KEY": "Mistral",
    "NVIDIA_API_KEY": "NVIDIA NIM",
    "TOGETHER_API_KEY": "Together",
    "GEMINI_API_KEY": "Google AI Studio",
    "HF_TOKEN": "Hugging Face",
    "OPENAI_API_KEY": "OpenAI",
    "ARTIFICIAL_ANALYSIS_KEY": "Artificial Analysis",
    "NOUS_API_KEY": "Nous Research (token manuale)",
    "ORCHESTRA_PROVIDER": "Provider predefinito",
    "ORCHESTRA_MODEL": "Modello predefinito",
    "ORCHESTRA_REASONING": "Livello reasoning",
    "ORCHESTRA_BUDGET": "Budget (JSON)",
    "ORCHESTRA_MAX_ITERS": "Max iterazioni loop",
    "ORCHESTRA_CONTEXT_LIMIT": "Limite contesto (token)",
    "ORCHESTRA_OLLAMA_URL": "Indirizzo Ollama",
    "ORCHESTRA_LMSTUDIO_URL": "Indirizzo LM Studio",
}

# Servizi che danno accesso gratis, con cosa offrono davvero. I numeri
# vengono da quello che dicono loro, e sono l'unica parte di questo file
# che invecchia: per questo la data e' esplicita e va aggiornata.
FREE_SERVICES: list[dict[str, Any]] = [
    # ---- senza chiave, funzionano subito ----
    {
        "id": "ollama",
        "gruppo": "Sul tuo computer",
        "nome": "Ollama",
        "costo": "gratis, sul tuo computer",
        "chiave": False,
        "cosa": "Modelli locali. Nessuna richiesta esce dal computer e nessun costo: il limite e' la tua GPU.",
        "requisiti": "Ollama installato e un modello scaricato.",
        "come": " ollama.com",
    },
    {
        "id": "lmstudio",
        "gruppo": "Sul tuo computer",
        "nome": "LM Studio",
        "costo": "gratis, sul tuo computer",
        "chiave": False,
        "cosa": "Come Ollama ma con un'interfaccia grafica: modelli sul tuo computer, nessun costo, niente rete.",
        "requisiti": "LM Studio installato.",
        "come": " lmstudio.ai",
    },

    # ---- con chiave, e un piano gratis ----
    #
    # Qui sotto la lista era scritta a mano e non coincideva piu' con
    # quella vera: consigliava Google e Hugging Face, che Orchestra NON
    # supporta — la chiave che mettevi non sarebbe mai stata usata —
    # e non citava NVIDIA e Together, che sono due dei servizi che
    # funzionano. Nove provider supportati, sette citati, due inventati.
    #
    # Un servizio consigliato che Orchestra non supporta e' la peggiore
    # delle due direzioni: si fa una chiave, la si mette, e non capita
    # niente, senza che nessuno dica perche'.
    {
        "id": "openrouter",
        "gruppo": "Gratis con chiave",
        "nome": "OpenRouter",
        "costo": "quasi tutto gratis",
        "chiave": True,
        "cosa": "Scelta enorme di modelli, con molte varianti gratis. I piani gratis hanno limiti giornalieri: per un uso intenso serve una chiave con credito.",
        "requisiti": "Account. Serve una chiave.",
        "come": " openrouter.ai/keys",
        "avvertenza": "I modelli gratis sono limitati a 20 richieste al minuto e 50 al giorno senza accredito; 1000 al giorno dopo 10 dollari di credito.",
    },
    {
        "id": "nvidia",
        "gruppo": "Gratis con chiave",
        "nome": "NVIDIA Build",
        "costo": "gratis con chiave",
        "chiave": True,
        "cosa": "Il piano gratis piu' ampio per numero di modelli, con modelli recenti di punta.",
        "requisiti": "Account NVIDIA Developer. Serve una chiave.",
        "come": " build.nvidia.com",
        "avvertenza": "Alcuni modelli elencati sono ritirati e rispondono 404 o 410: e' il catalogo, non un errore di Orchestra.",
    },
    {
        "id": "together",
        "gruppo": "Gratis con chiave",
        "nome": "Together AI",
        "costo": "gratis con chiave, con limiti",
        "chiave": True,
        "cosa": "Buona selezione di modelli open, con un piano gratis limitato per la ricerca.",
        "requisiti": "Account. Serve una chiave.",
        "come": " api.together.ai/settings/api-keys",
    },
    {
        "id": "groq",
        "gruppo": "Gratis con chiave",
        "nome": "Groq",
        "costo": "gratis con limiti",
        "chiave": True,
        "cosa": "I piu' veloci in assoluto sui modelli supportati. Quelli senza supporto agli strumenti non compaiono in Orchestra.",
        "requisiti": "Account. Serve una chiave.",
        "come": " console.groq.com/keys",
    },
    {
        "id": "cerebras",
        "gruppo": "Gratis con chiave",
        "nome": "Cerebras",
        "costo": "gratis con limiti",
        "chiave": True,
        "cosa": "Molto veloce, catalogo piccolo e mirato.",
        "requisiti": "Account. Serve una chiave.",
        "come": " cloud.cerebras.ai",
    },
    {
        "id": "mistral",
        "gruppo": "Gratis con chiave",
        "nome": "Mistral",
        "costo": "gratis con limiti",
        "chiave": True,
        "cosa": "I modelli del produttore stesso, con un piano gratis limitato.",
        "requisiti": "Account. Serve una chiave.",
        "come": " console.mistral.ai",
    },
    {
        "id": "huggingface",
        "gruppo": "Gratis con chiave",
        "nome": "Hugging Face",
        "costo": "gratis con token, con limiti",
        "chiave": True,
        "cosa": "Inferenza su migliaia di modelli open, con un piano gratis fra i piu' ampi per numero di richieste.",
        "requisiti": "Account Hugging Face. Serve un token.",
        "come": " huggingface.co/settings/tokens",
        "avvertenza": "L'API e' condivisa: quando e' molto usata risponde che i modelli sono sovraccarichi. Riprova dopo qualche minuto.",
    },
    {
        "id": "google",
        "gruppo": "Gratis con chiave",
        "nome": "Google AI Studio",
        "costo": "gratis con chiave, con limiti",
        "chiave": True,
        "cosa": "Gemini. Il piano gratis con quota giornaliera, senza carta.",
        "requisiti": "Account Google. Serve una chiave.",
        "come": " aistudio.google.com/apikey",
        "avvertenza": "Vale solo per AI Studio. Vertex AI e' un altro servizio e chiede progetto e carta.",
    },
    {
        "id": "nous",
        "gruppo": "Collegamento diretto",
        "nome": "Nous Research",
        "costo": "gratis con collegamento Orchestra, con limiti",
        "chiave": False,
        "cosa": "Accesso diretto all'inference API di Nous (Pareto, LFM, Gemini, ecc.), con il modello free nous/welcome e, su account, ai modelli a pagamento.",
        "requisiti": "Si collega da solo con il pulsante qui sotto, oppure con un token manuale messo in Servizi.",
        "come": " premi «Collega Nous» qui sotto",
    },
{
        "id": "anthropic",
        "gruppo": "A pagamento",
        "nome": "Anthropic",
        "costo": "a pagamento",
        "chiave": True,
        "cosa": "I modelli Claude diretti dal produttore.",
        "requisiti": "Account Anthropic con carta. Serve una chiave.",
        "come": " console.anthropic.com/settings/keys",
    },
    {
        "id": "openai",
        "gruppo": "A pagamento",
        "nome": "OpenAI",
        "costo": "a pagamento",
        "chiave": True,
        "cosa": "Il riferimento a pagamento, utile per confrontare quanto costano gli altri.",
        "requisiti": "Account con carta. Serve una chiave.",
        "come": " platform.openai.com/api-keys",
    },
]


NOTA_FREE = ("I piani gratis cambiano spesso: se un limite non torna, "
             "ricontrolla la pagina del servizio. 'Gratis' vuol dire "
             "'un piano gratis con limiti': fuori Ollama e LM Studio, "
             "tutti gli altri chiedono una chiave, e alcuni una carta.")


def _leggi_righe(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def stato(path: str, valori: dict[str, str]) -> list[dict[str, Any]]:
    """Cosa c'e' nel .env, senza mai restituirne i valori.

    Restituisce solo: presente si'/no, e gli ultimi 4 caratteri come
    indizio. Il resto del valore non esce di qui — non in un log, non
    in una risposta, non nella cronologia del browser.
    """
    out = []
    for chiave, etichetta in WRITABLE.items():
        if chiave in SOLO_SCRIVIBILI:
            continue  # non e' una credenziale: sta nei menu in alto
        v = (valori or {}).get(chiave, "")
        if chiave == "NOUS_API_KEY" and not str(v).strip():
            try:
                from . import nous_auth
                tok, _ = nous_auth.get_nous_credentials(valori)
                if tok:
                    v = tok
            except Exception:
                pass
        v = v.strip()
        out.append({
            "chiave": chiave,
            "etichetta": etichetta,
            "presente": bool(v),
            # solo 4 caratteri: serve a distinguere due chiavi, non a
            # usarne una
            "indizio": ("..." + v[-4:]) if len(v) > 8 else ("*" * len(v) if v else ""),
            "lunghezza": len(v),
            "writable": True,
        })
    return out


def scrivi(path: str, chiave: str, valore: str) -> tuple[bool, str]:
    """Scrive o cancella una chiave. Restituisce (ok, messaggio).

    Non solleva: dalla UI un errore deve essere una riga leggibile, non
    una traccia.
    """
    if chiave not in WRITABLE:
        return False, f"chiave non scrivibile: {chiave}"
    valore = (valore or "").strip()
    # un a capo o un '=' nel valore cambierebbe la struttura del file
    if "\n" in valore or "\r" in valore:
        return False, "il valore non puo' contenere a capo"
    if len(valore) > 500:
        return False, "valore troppo lungo (max 500 caratteri)"

    righe = _leggi_righe(path)
    nuovo: list[str] = []
    trovata = False
    for riga in righe:
        m = re.match(r"^(\s*)(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)(\s*)=(.*)$", riga)
        if m and m.group(2) == chiave:
            trovata = True
            if valore:
                nuovo.append(f"{chiave}={valore}")
            # se vuoto: la riga sparisce invece di restare VUOTA
            continue
        nuovo.append(riga)
    if valore and not trovata:
        # in fondo, con un commento che spiega cosa ci sta facendo
        nuovo.append("")
        nuovo.append(f"# {WRITABLE[chiave]} — inserito dal menu Opzioni")
        nuovo.append(f"{chiave}={valore}")

    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".env")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(nuovo).rstrip() + "\n")
        os.replace(tmp, path)
        # su Windows il .env puo' contenere una chiave: restringerlo
        # impedisce che altri account della macchina la leggano
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as e:
        return False, f"scrittura fallita: {e}"
    return True, (f"{chiave} salvata" if valore else f"{chiave} rimossa")
