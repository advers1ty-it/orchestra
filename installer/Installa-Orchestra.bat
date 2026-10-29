@echo off
rem ============================================================
rem  Installa-Orchestra.bat — installazione per non esperti
rem  FILE UNICO: contiene anche lo scaricatore (righe REM-PS:).
rem  Non serve Git, non serve un account GitHub: l'app e' pubblica
rem  e l'installer scarica l'ultima release.
rem ============================================================
setlocal EnableDelayedExpansion
title Installazione Orchestra

echo.
echo  === Installazione Orchestra ===
echo.

rem --- 1. Python ---
set "PYEXE="
for %%P in (python py python3) do (
  if not defined PYEXE %%P --version >nul 2>&1 && set "PYEXE=%%P"
)
if not defined PYEXE (
  for %%D in ("%LOCALAPPDATA%\Programs\Python\Python312" "%LocalAppData%\Programs\Python\Python311" "C:\Python312" "C:\Python311" "C:\Program Files\Python312" "C:\Program Files\Python311") do (
    if not defined PYEXE if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
  )
)
if not defined PYEXE (
  echo  Python non trovato. Provo a installarlo...
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  set "PYEXE=py"
  py -3 --version >nul 2>&1
  if !errorlevel! neq 0 (
    set "PYEXE=python"
    python --version >nul 2>&1
  )
  if defined PYEXE python --version >nul 2>&1 || (
    echo  Winget non ha funzionato; scarico l'installer da python.org...
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile '%TEMP%\python-setup.exe' -UseBasicParsing" 2>nul
    if exist "%TEMP%\python-setup.exe" (
      start /wait "" "%TEMP%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
      del "%TEMP%\python-setup.exe" >nul 2>&1
    )
    set "PYEXE="
    for %%D in ("%LOCALAPPDATA%\Programs\Python\Python312") do if exist "%%~D\python.exe" set "PYEXE=%%~D\python.exe"
  )
)
if not defined PYEXE (
  echo.
  echo  [ERRORE] Installa Python 3.11 o superiore da https://www.python.org/downloads/
  echo  e rilancia questo installer.
  pause
  exit /b 1
)
echo  [OK] Python presente.

rem --- 2. Cartella di installazione ---
set "DESTDIR=%LOCALAPPDATA%\Orchestra"
if not exist "%DESTDIR%" mkdir "%DESTDIR%"
echo  [OK] Cartella: %DESTDIR%

rem --- 3. Download ultima release + estrazione ---
rem Lo script PowerShell e' dentro questo stesso file (righe REM-PS:):
rem lo si estrae in TEMP e lo si esegue, niente altri file da scaricare.
echo  Scarico l'ultima versione da GitHub...
set "PSSCRIPT=%TEMP%\orchestra-scarica.ps1"
powershell -NoProfile -Command "(Get-Content '%~f0' | Where-Object { $_.StartsWith('REM-PS:') } | ForEach-Object { $_.Substring(7) }) | Set-Content '%PSSCRIPT%'"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PSSCRIPT%" -Dest "%DESTDIR%"
set "RC=%errorlevel%"
del "%PSSCRIPT%" 2>nul
if %RC% neq 0 (
  echo.
  echo  [ERRORE] Download fallito. Controlla la connessione e riprova.
  pause
  exit /b 1
)
echo  [OK] App scaricata.

rem --- 4. File .env ---
if not exist "%DESTDIR%\orchestra\.env" (
  copy /y "%DESTDIR%\orchestra\.env.example" "%DESTDIR%\orchestra\.env" >nul
  echo  [OK] Creato orchestra\.env — aprilo e inserisci le chiavi API.
) else (
  echo  [OK] .env esistente conservato.
)

rem --- 5. Collegamento sul Desktop (con icona Orchestra) ---
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); if(-not (Test-Path $d)){ $d=Join-Path $env:USERPROFILE 'Desktop'; New-Item -ItemType Directory -Force -Path $d | Out-Null }; $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Avvia Orchestra.lnk')); $s.TargetPath='%DESTDIR%\Avvia-Orchestra.bat'; $s.WorkingDirectory='%DESTDIR%'; $s.IconLocation='%DESTDIR%\installer\orchestra.ico'; $s.Save(); Write-Host ('  collegamento creato in ' + $d)"
echo  [OK] Collegamento sul Desktop creato.

rem --- 6. Comando 'orchestra' nel PATH (CLI) ---
set "SHIMDIR=%LOCALAPPDATA%\Microsoft\WindowsApps"
if not exist "%SHIMDIR%" mkdir "%SHIMDIR%"
(
  echo @echo off
  echo set "PYTHONPATH=%DESTDIR%;%%PYTHONPATH%%"
  echo python -m orchestra.cli %%*
) > "%SHIMDIR%\orchestra.cmd"
echo  [OK] Comando 'orchestra' registrato (CLI).

echo.
echo  === Fatto! Premi un tasto per avviare Orchestra ===
pause >nul
call "%DESTDIR%\Avvia-Orchestra.bat"
exit /b 0

rem ===== Sotto questa riga solo codice PowerShell (mai eseguito da cmd) =====
REM-PS:param([Parameter(Mandatory = $true)][string]$Dest)
REM-PS:$ErrorActionPreference = 'Stop'
REM-PS:$ProgressPreference = 'SilentlyContinue'
REM-PS:$headers = @{ 'User-Agent' = 'orchestra-installer'; 'Accept' = 'application/vnd.github+json' }
REM-PS:try {
REM-PS:  $rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/advers1ty-it/orchestra/releases/latest' -Headers $headers -TimeoutSec 30
REM-PS:} catch {
REM-PS:  Write-Host '[ERRORE] GitHub non raggiungibile.'
REM-PS:  Write-Host $_.Exception.Message
REM-PS:  exit 1
REM-PS:}
REM-PS:if (-not $rel.zipball_url) { Write-Host '[ERRORE] Nessuna release pubblicata.'; exit 1 }
REM-PS:Write-Host ('  release trovata: ' + $rel.tag_name)
REM-PS:$zip = Join-Path $env:TEMP 'orchestra-release.zip'
REM-PS:Invoke-WebRequest -Uri $rel.zipball_url -Headers $headers -OutFile $zip -TimeoutSec 300
REM-PS:$tmp = Join-Path $env:TEMP ('orchestra-rel-' + [guid]::NewGuid().ToString('N'))
REM-PS:Expand-Archive -Path $zip -DestinationPath $tmp -Force
REM-PS:$root = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
REM-PS:if (-not $root) { Write-Host '[ERRORE] Zip vuoto.'; exit 1 }
REM-PS:$escludi = @('.env', 'token.txt', 'goals.json', 'budget_global.json', 'storico.db', 'memoria_indice.db', '__pycache__', '_ goals_fallback', '_dati_test')
REM-PS:Get-ChildItem -Path $root.FullName -Force | ForEach-Object {
REM-PS:  if ($escludi -contains $_.Name) { return }
REM-PS:  $dst = Join-Path $Dest $_.Name
REM-PS:  if ($_.PSIsContainer) {
REM-PS:    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
REM-PS:    Copy-Item -Recurse -Force $_.FullName $dst
REM-PS:  } else {
REM-PS:    Copy-Item -Force $_.FullName $dst
REM-PS:  }
REM-PS:}
REM-PS:Remove-Item -Recurse -Force $tmp, $zip
REM-PS:Write-Host '  file copiati.'
