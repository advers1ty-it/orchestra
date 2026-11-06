@echo off
rem ============================================================
rem  Avvia-Orchestra.bat — il file che c'e' sul Desktop
rem
rem  Fa due sole cose, e non una di piu':
rem   1. si copia in %TEMP% e si riavvia da li', perche' l'aggiornamento
rem      puo' sostituire QUESTO file mentre e' in esecuzione (cmd legge
rem      un .bat riga per riga, e un file che cambia sotto i piedi fa
rem      errori che sembrano del programma);
rem   2. aggiorna, poi passa la mano a Orchestra.cmd.
rem
rem  Avvio, fermata, riavvio, scelta del Python e log vivono in un posto
rem  solo (Orchestra.cmd). Prima erano scritti due volte, con due
rem  implementazioni diverse: una si fidava di `where py` e l'altra no,
rem  e per questo "non parte" succedeva in un launcher e non nell'altro.
rem ============================================================
setlocal

if not defined ORCHESTRA_STABILE (
  set "ORCHESTRA_STABILE=1"
  set "ORCHESTRA_DIR=%~dp0"
  copy /y "%~f0" "%TEMP%\Avvia-Orchestra.stabile.bat" >nul
  call "%TEMP%\Avvia-Orchestra.stabile.bat" %*
  exit /b %errorlevel%
)

cd /d "%ORCHESTRA_DIR%"
title Orchestra

rem  Aggiornamento: lo chiede questo file, non Orchestra.cmd, cosi' chi
rem  lancia `Orchestra.cmd ferma` non aspetta un controllo di rete per
rem  spegnere un server.
set "ORCHESTRA_AGGIORNA=1"
call "%ORCHESTRA_DIR%Orchestra.cmd" %*
exit /b %errorlevel%
