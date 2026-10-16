@echo off
rem ============================================================
rem  Avvia-Orchestra.bat — doppio click per usare l'app
rem  - se il server e' spento: aggiorna, lo avvia in background,
rem    apre il browser e chiude subito questa finestra
rem  - se il server e' acceso: chiede Apri / Riavvia / Ferma
rem ============================================================
setlocal EnableDelayedExpansion
rem --- 0. Copia stabile: update puo' sostituire questo file mentre gira.
if not defined ORCHESTRA_STABILE (
  set "ORCHESTRA_STABILE=1"
  set "ORCHESTRA_DIR=%~dp0"
  copy /y "%~f0" "%TEMP%\Avvia-Orchestra.stabile.bat" >nul
  call "%TEMP%\Avvia-Orchestra.stabile.bat"
  exit /b %errorlevel%
)
cd /d "%ORCHESTRA_DIR%"
title Orchestra

set "PORT=8737"
set "URL=http://127.0.0.1:%PORT%"
set "LOG=%CD%\orchestra-server.log"

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

call :porta_aperta
if not errorlevel 1 goto :menu

call :aggiorna
call :avvia_server
exit /b %errorlevel%

:menu
echo.
echo  Orchestra e' gia' in esecuzione su %URL%.
echo  1) Apri interfaccia web
echo  2) Riavvia Orchestra
echo  3) Ferma Orchestra
set "scelta="
set /p scelta="Scelta [1-3]: "
if "%scelta%"=="1" start "" "%URL%" & exit /b 0
if "%scelta%"=="2" goto :riavvia
if "%scelta%"=="3" goto :ferma_scelta
echo  Scelta non valida.
goto :menu

:riavvia
call :aggiorna
call :ferma_server
if errorlevel 1 (
  echo  [ERRORE] Non riesco a fermare il server precedente.
  pause
  exit /b 1
)
call :avvia_server
exit /b %errorlevel%

:ferma_scelta
call :ferma_server
if errorlevel 1 (
  echo  [ERRORE] Non riesco a fermare il server.
  pause
  exit /b 1
)
echo  Orchestra fermata.
timeout /t 2 >nul
exit /b 0

:aggiorna
echo  Controllo aggiornamenti...
"%PYEXE%" -m orchestra.cli update --auto
if errorlevel 1 echo  [AVVISO] Aggiornamento non riuscito, continuo con la versione locale.
exit /b 0

:avvia_server
echo  Avvio Orchestra in background...
powershell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','"%PYEXE%" -m orchestra.cli web --no-browser --port %PORT% > "%LOG%" 2>&1' -WorkingDirectory '%CD%' -WindowStyle Hidden"
call :attendi_server
if errorlevel 1 (
  echo  [ERRORE] Il server non risponde. Vedi %LOG%.
  pause
  exit /b 1
)
start "" "%URL%"
exit /b 0

:ferma_server
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' -or $_.Name -eq 'py.exe') -and $_.CommandLine -match 'orchestra\.cli\s+web' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; exit 0"
call :attendi_stop
exit /b %errorlevel%

:porta_aperta
powershell -NoProfile -Command "try { $c=New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:attendi_server
for /L %%i in (1,1,20) do (
  call :porta_aperta
  if not errorlevel 1 exit /b 0
  timeout /t 1 >nul
)
exit /b 1

:attendi_stop
for /L %%i in (1,1,10) do (
  call :porta_aperta
  if errorlevel 1 exit /b 0
  timeout /t 1 >nul
)
exit /b 1
