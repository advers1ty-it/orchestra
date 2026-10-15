@echo off
rem ============================================================
rem  Avvia-Orchestra.bat — doppio click per usare l'app
rem  1. controlla aggiornamenti da GitHub (silenzioso)
rem  2. avvia il server e apre il browser
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Orchestra

rem --- 1. Trova l'interprete Python (anche se il PATH e' vecchio) ---
set "PYEXE="
for %%P in (py python python3) do (
  if not defined PYEXE %%P --version >nul 2>&1 && set "PYEXE=%%P"
)
if not defined PYEXE (
  for %%D in ("%LOCALAPPDATA%\Programs\Python\Python312" "%LocalAppData%\Programs\Python\Python311" "C:\Python312" "C:\Python311" "C:\Program Files\Python312" "C:\Program Files\Python311") do (
    if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
  )
)
if not defined PYEXE (
  echo.
  echo  [ERRORE] Python non trovato. Esegui prima Installa-Orchestra.bat.
  pause
  exit /b 1
)

rem --- 2. Aggiornamenti ---
%PYEXE% -m orchestra.cli update --auto >nul 2>&1

echo  Avvio Orchestra...
%PYEXE% -m orchestra.cli web
pause
