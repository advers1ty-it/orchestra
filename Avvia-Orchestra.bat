@echo off
rem ============================================================
rem  Avvia-Orchestra.bat — doppio click per usare l'app
rem  1. controlla aggiornamenti da GitHub (silenzioso)
rem  2. avvia il server e apre il browser
rem ============================================================
setlocal
cd /d "%~dp0"
title Orchestra

py -3 -m orchestra.cli update --auto 2>nul || python -m orchestra.cli update --auto 2>nul

echo  Avvio Orchestra...
py -3 -m orchestra.cli web 2>nul || python -m orchestra.cli web
pause
