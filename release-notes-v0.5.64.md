## v0.5.64 — Lavori durevoli e checkout isolati

### Lavori durevoli
- La coda dei compiti in background dei bot vive in `lavori.db`, non in memoria: un riavvio non la svuota.
- All'avvio i lavori `in_attesa` ripartono; quelli trovati `in_corso` diventano `interrotto` invece di essere rieseguiti alla cieca, perché un turno a metà può aver già scritto file o speso token.
- Dal pannello Bot puoi riprovare un lavoro fallito/interrotto o annullare quello in corso. Annullare non ferma la chat dell'utente.
- API: `GET /api/lavori`, `POST /api/lavori/riprova`, `POST /api/lavori/annulla`.

### Checkout isolati
- Se il progetto del bot è un repository git con almeno un commit, ogni lavoro parte in un worktree separato nella cartella dati, sul ramo `orchestra/lavoro-<id>`.
- La cartella che hai aperta non viene toccata: due lavori sullo stesso progetto non si sovrappongono. Il checkout parte da `HEAD`, quindi le modifiche non committate non vengono copiate.
- Progetti non git continuano nella cartella normale. Un repository git senza commit, o un checkout che non si crea, fa fallire il lavoro invece di ripiegare sulla cartella dell'utente.
- Il pannello mostra ramo e percorso; **Scarta checkout** elimina il worktree e il ramo. `ORCHESTRA_WORKTREE=0` spegne l'isolamento.
- Eliminare un bot scarta i suoi checkout non ancora scartati.

### Proposta di merge
- Dopo aver eseguito le verifiche, il bot può chiamare `proponi_merge` con riepilogo e verifica: committa le modifiche sul ramo isolato e registra una proposta.
- Il pannello mostra **pronto per il merge** con la verifica dichiarata e il pulsante **Unisci**. Il merge resta una decisione dell'utente.
- **Unisci** rifiuta un progetto con modifiche non committate, controlla che il ramo non sia cambiato dopo la proposta e annulla il merge in caso di conflitto.
- La verifica è quella dichiarata dal bot: non viene rieseguita automaticamente prima del merge.

### API
- Nuove rotte: `POST /api/lavori/scarta`, `POST /api/lavori/unisci`.

Per aggiornare: riavvia Orchestra (`Avvia-Orchestra.bat` → opzione 2).
