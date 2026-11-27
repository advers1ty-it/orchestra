# v0.5.106 — Interfaccia: menu Strumenti e niente obiettivi manuali

**Header più leggero, azioni rare in un menu**
- Opzioni, Cron, MCP, Cosa fai?, Docs e Consiglio non stanno più in fila nell'header: sono raggruppati in **Strumenti**, per Lavoro, Automazioni, Aiuto e Sistema.
- Il menu si chiude con un clic fuori, con Escape o dopo la scelta. Sul telefono scegliere una voce chiude anche l'header esteso e riporta alla pagina.
- L'altezza dell'header scende e i controlli che si usano durante il lavoro restano in primo piano.

**Avviso di scope richiudibile**
- L'avviso sul routing e sullo scope è un popover sotto l'header, con il pulsante **i** per riaprirlo.
- Si chiude da solo dopo dieci secondi; il conto alla rovescia si ferma mentre il puntatore o il focus sono sopra l'avviso.
- Il testo non allarga più l'header né manda a capo il selettore del modello.

**Pannelli laterali a schede**
- Storia, Progetti, Memoria, Capacità e Tracce sono schede nella sidebar, con la rotaia delle icone quando il pannello è ridotto.
- La vista attiva resta una sola e il cambio è annunciato; la cronologia continua a mostrare il progetto di ogni conversazione.

**Obiettivi e compiti in background: fuori dalla UI manuale**
- Rimosso il pulsante **Obiettivo** dal menu e tutta la barra del pannello goal.
- Rimosso il modulo **Compito in background** da Opzioni → Bot, con i pulsanti di avvio e aggiornamento stato.
- **Cosa fai?** non crea più un goal: prepara un normale messaggio nel campo in basso e lo lascia pronto da inviare con **Scrivi in chat**.
- Il backend dei goal, lo scheduler, i cron job e le API restano disponibili per l'agente e per le automazioni; non cambiano i dati già salvati.

**Piccole correzioni e documentazione**
- Il pannello Bot carica subito lo stato di Telegram quando si apre, senza aspettare il clic sul QR.
- La guida descrive il menu Strumenti e non promette più pulsanti che non esistono.
- Aggiornati i test di integrità HTML, del frontend, della UI e dei bot.

**Nessun breaking change** — i file di progetto e i dati esistenti si leggono come prima.

**Aggiornamento**
- Scarica `orchestra-0.5.106.zip` o `Installa-Orchestra.bat` dalla release.
- L'installer rileva la versione installata e propone l'aggiornamento; lo zip si estrae e sostituisce i file (la cartella `dati/` non viene toccata).
