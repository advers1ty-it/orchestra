# v0.5.102 — I consigli di fine turno arrivano davvero dal modello

## I consigli di fine turno ora sono quelli del modello

A fine turno Orchestra propone tre o quattro mosse già scritte. Il
generatore che le fa scrivere al modello c'era, ma non si vedeva mai: il
modello, con il ragionamento al massimo, impiegava circa 15 secondi
contro i 12 di attesa, e il server ricadeva sulle proposte standard
("Controlla cosa può essersi rotto", "Cosa resta aperto"). La finestra
chiedeva una volta sola, quindi restavano quelle.

Adesso:

- i consigli chiedono poco ragionamento: la stessa risposta arriva in
  circa 6 secondi invece di 15, e le proposte restano specifiche;
- la finestra mostra subito le proposte ricavate dal turno (i file
  toccati, i test che li coprono, il commit) e le sostituisce appena il
  modello ha finito, senza aspettare a casella vuota;
- un modello che non risponde non viene più interrogato a ogni
  richiesta: il turno chiuso resta chiuso.

## Test dei processi più stabili

Due commit rendono più affidabile il test del tool `processo`: aspetta
il lettore di stdin anche sui runner lenti, e distingue un dato perso da
un avvio lento invece di confonderli.
