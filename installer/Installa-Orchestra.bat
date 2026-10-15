@echo off
rem ============================================================
rem  Installa-Orchestra.bat — installazione per non esperti
rem  Non serve Git, non serve un account GitHub.
rem  Scarica l'ultima release dal repo privato usando token.txt
rem  (il file token.txt deve stare accanto a questo installer:
rem  ce lo mette chi prepara il pacchetto, NON sta su GitHub).
rem ============================================================
setlocal EnableDelayedExpansion
title Installazione Orchestra

echo.
echo  === Installazione Orchestra ===
echo.

rem --- 1. Python ---
py -3 --version >nul 2>&1
if %errorlevel% neq 0 python --version >nul 2>&1
if %errorlevel% neq 0 (
  echo  Python non trovato. Provo a installarlo...
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  py -3 --version >nul 2>&1
  if !errorlevel! neq 0 python --version >nul 2>&1
  if !errorlevel! neq 0 (
    echo.
    echo  [ERRORE] Installa Python 3.11 o superiore da https://www.python.org/downloads/
    echo  e rilancia questo installer.
    pause
    exit /b 1
  )
)
echo  [OK] Python presente.

rem --- 2. Token read-only ---
set "TOKENFILE=%~dp0token.txt"
if not exist "%TOKENFILE%" (
  echo.
  echo  [ERRORE] Manca token.txt accanto a questo installer.
  echo  Chiedi a chi ti ha mandato il pacchetto il file mancante.
  pause
  exit /b 1
)

rem --- 3. Cartella di installazione ---
set "DESTDIR=%LOCALAPPDATA%\Orchestra"
if not exist "%DESTDIR%" mkdir "%DESTDIR%"
copy /y "%TOKENFILE%" "%DESTDIR%\token.txt" >nul
echo  [OK] Cartella: %DESTDIR%

rem --- 4. Download ultima release + estrazione ---
echo  Scarico l'ultima versione da GitHub...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scarica-release.ps1" -TokenFile "%DESTDIR%\token.txt" -Dest "%DESTDIR%"
if %errorlevel% neq 0 (
  echo.
  echo  [ERRORE] Download fallito. Controlla la connessione e riprova.
  pause
  exit /b 1
)
echo  [OK] App scaricata.

rem --- 5. File .env ---
if not exist "%DESTDIR%\orchestra\.env" (
  copy /y "%DESTDIR%\orchestra\.env.example" "%DESTDIR%\orchestra\.env" >nul
  echo  [OK] Creato orchestra\.env — aprilo e inserisci le chiavi API.
) else (
  echo  [OK] .env esistente conservato.
)

rem --- 6. Collegamento sul Desktop ---
set "SHORTCUT=%USERPROFILE%\Desktop\Avvia Orchestra.lnk"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%'); $s.TargetPath='%DESTDIR%\Avvia-Orchestra.bat'; $s.WorkingDirectory='%DESTDIR%'; $s.Save()"
echo  [OK] Collegamento sul Desktop creato.

echo.
echo  === Fatto! Premi un tasto per avviare Orchestra ===
pause >nul
call "%DESTDIR%\Avvia-Orchestra.bat"
