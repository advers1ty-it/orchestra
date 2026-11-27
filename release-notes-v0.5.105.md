# v0.5.105 — Istruzioni del progetto in un pannello, tabelle nel markdown, consigli da due in su

_Note costruite dai messaggi dei commit dopo `v0.5.104`: rileggile prima di pubblicarle._

## Istruzioni del progetto in un pannello, tabelle nel markdown, consigli da due in su

**Pannello Progetto — istruzioni persistenti per progetto**
- Nuovo pannello "Progetto" nella sidebar: mostra le istruzioni del progetto attivo e permette di modificarle.
- Le istruzioni sono salvate in `progetti/<nome>/.orchestra/istruzioni.md` e ricaricate automaticamente quando si torna sul progetto.
- Se l'editor ha modifiche non salvate (`istruzioniSporco`), il cambio di progetto chiede conferma prima di scartare le modifiche; annullando si resta sul progetto corrente.
- Test: `tests/test_istruzioni_progetto.py` caso [9] (A con modifiche → cambio a B → resta A).

**Markdown — tabelle**
- Il parser markdown ora supporta le tabelle (pipe syntax) e le rende come `<table>` HTML.
- Nuovo file `tests/test_markdown_tabelle.py` con 24 casi (allineamento, celle vuote, escape, nesting).

**Suggerimenti fine turno — soglia a due proposte**
- Il server accetta e restituisce le proposte del modello se sono **almeno due** (`_valida` in `suggerimenti.py`: `len >= 2`).
- Con una sola proposta si ricade sui pulsanti fissi di fallback; con due o tre si mostrano quelle del modello.
- `core.js` non ha una soglia propria: mostra qualsiasi lista non vuota, quindi l'integrazione è coerente.
- Test: `tests/test_suggerimenti.py` caso «due proposte bastano» (65 PASS totali).

**Nessun breaking change** — le API pubbliche non cambiano; i file di progetto esistenti si leggono come prima.

**Aggiornamento**
- Scarica `orchestra-0.5.105.zip` o `Installa-Orchestra.bat` dalla release.
- L'installer rileva la versione installata e propone l'aggiornamento; lo zip si estrae e sostituisce i file (la cartella `dati/` non viene toccata).