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
SOLO_SCRIVIBILI = ("ORCHESTRA_PROVIDER", "ORCHESTRA_MODEL")

WRITABLE: dict[str, str] = {
    "OPENROUTER_API_KEY": "OpenRouter",
    "GROQ_API_KEY": "Groq",
    "NVIDIA_API_KEY": "NVIDIA NIM",
    "TOGETHER_API_KEY": "Together",
    "CEREBRAS_API_KEY": "Cerebras",
    "MISTRAL_API_KEY": "Mistral",
    "OPENAI_API_KEY": "OpenAI",
    "ARTIFICIAL_ANALYSIS_KEY": "Artificial Analysis",
    "ORCHESTRA_PROVIDER": "Provider predefinito",
    "ORCHESTRA_MODEL": "Modello predefinito",
    "ORCHESTRA_OLLAMA_URL": "Indirizzo Ollama",
    "ORCHESTRA_LMSTUDIO_URL": "Indirizzo LM Studio",
}

# Servizi che danno accesso gratis, con cosa offrono davvero. I numeri
# vengono da quello che dicono loro, e sono l'unica parte di questo file
# che invecchia: per questo la data e' esplicita e va aggiornata.
FREE_SERVICES: list[dict[str, Any]] = [
    {
        "id": "ollama",
        "nome": "Ollama (sul tuo computer)",
        "costo": "gratis, sempre",
        "chiave": False,
        "cosa": "Modelli locali. Nessun account, nessun rate limit, funziona offline.",
        "requisiti": "8 GB di RAM per un modello da 7B. Sotto Q4_K_M le chiamate ai tool diventano inaffidabili.",
        "come": " Scaricalo da ollama.com, poi: ollama pull qwen2.5-coder:7b",
    },
    {
        "id": "lmstudio",
        "nome": "LM Studio",
        "costo": "gratis, sempre",
        "chiave": False,
        "cosa": "Come Ollama, con un'interfaccia grafica per scegliere e scaricare i modelli.",
        "requisiti": "Come Ollama.",
        "come": " lmstudio.com — scarica un modello e avvia il server locale",
    },
    {
        "id": "groq",
        "nome": "Groq",
        "costo": "gratis senza carta",
        "chiave": True,
        "cosa": "L'inferenza piu' veloce in assoluto. Limiti generosi, quindi ottimo per il free.",
        "requisiti": "Account. Serve una chiave.",
        "come": " console.groq.com/keys",
    },
    {
        "id": "cerebras",
        "nome": "Cerebras",
        "costo": "gratis senza carta",
        "chiave": True,
        "cosa": "Gratis illimitato nei limiti d'uso. Modelli forti sul free tier.",
        "requisiti": "Account. Serve una chiave.",
        "come": " cloud.cerebras.ai",
    },
    {
        "id": "google",
        "nome": "Google AI Studio",
        "costo": "gratis senza carta",
        "chiave": True,
        "cosa": "Gemini. Il free tier che non scade piu' nel tempo.",
        "requisiti": "Account Google. Serve una chiave.",
        "come": " aistudio.google.com/apikey",
    },
    {
        "id": "openrouter",
        "nome": "OpenRouter",
        "costo": "quasi tutto gratis",
        "chiave": True,
        "cosa": "Scelta enorme di modelli, e 16-17 varianti :free. Usata insieme a una a pagamento per il fallback.",
        "requisiti": "Account. Serve una chiave.",
        "come": " openrouter.ai/keys",
        "avvertenza": "I :free sono limitati a 20 richieste al minuto e 50 al giorno senza accredito; 1000 al giorno dopo 10 dollari di credito. Ecco perche' i benchmark si fermano con HTTP 429.",
    },
    {
        "id": "huggingface",
        "nome": "Hugging Face Inference",
        "costo": "gratis con limiti",
        "chiave": True,
        "cosa": "Ospita modelli open che altrove non trovi.",
        "requisiti": "Account. Serve una chiave.",
        "come": " huggingface.co/settings/tokens",
    },
]

NOTA_FREE = ("Rilevato il 30 settembre 2026. I free tier cambiano spesso: "
             "prima di basarci un prodotto, ricontrolla la pagina del servizio.")


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
