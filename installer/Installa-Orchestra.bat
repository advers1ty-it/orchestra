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

rem --- 4. Certificati ---
rem  Un Windows appena installato non ha tutte le autorita' di
rem  certificazione: le porta Windows Update, e su una macchina nuova non
rem  e' ancora passato. Orchestra le prende dal trust store di Windows e non
rem  ne ha un elenco suo, quindi se ne manca una il servizio che la usa
rem  risponde "certificato non verificabile" e chi legge pensa alla rete.
rem
rem  Il controllo va fatto adesso, non quando l'utente salva il token del
rem  bot: li' il sintomo e' un messaggio d'errore in mezzo all'app, qui e'
rem  una riga che si sistema subito, con il consenso di chi installa.
rem
rem  Si lancia come FILE e non con -m orchestra: importare il pacchetto fa
rem  la migrazione dei dati e registra l'installazione, e guardare dei
rem  certificati non deve avere effetti collaterali.
echo.
echo  Controllo i certificati...
set "CERT=%DESTDIR%\orchestra\certificati.py"
if not exist "%CERT%" goto :cert_salta
"%PYEXE%" "%CERT%"
if not errorlevel 1 goto :cert_fatto
echo.
echo  Manca almeno una radice: i servizi che la usano diranno "rete non
echo  raggiungibile" pur essendo raggiungibili. Le radici si scaricano da
echo  Windows Update e si importano nello store di sistema: serve il
echo  consenso di amministratore, Windows apre la sua finestra.
set "RIP="
set /p "RIP=Sistemo ora? [S/n] "
if /i "%RIP%"=="n" goto :cert_manuale
echo  Apro la finestra di amministratore...
powershell -NoProfile -Command "Start-Process -FilePath '%PYEXE%' -ArgumentList '%CERT%','--ripara' -Verb RunAs -Wait"
"%PYEXE%" "%CERT%"
if not errorlevel 1 goto :cert_fatto
:cert_manuale
echo.
echo  Per farlo piu' tardi, in PowerShell da amministratore:
echo    certutil -generateSSTFromWU "%%TEMP%%\radici.sst"
echo    certutil -addstore -f root "%%TEMP%%\radici.sst"
echo  (su Windows 11 va bene anche lasciar finire Windows Update)
goto :cert_fatto
:cert_salta
echo  [AVVISO] certificati.py non trovato: salto il controllo.
:cert_fatto

rem --- 5. Dipendenze ---
rem  Orchestra e' stdlib-only e parte anche senza niente di questo. Ma ogni
rem  voce accende una funzione, e senza di essa il tool risponde "installa
rem  X" a chi ha appena finito di installare: il peggior modo di scoprire
rem  che esisteva un'opzione.
rem
rem  Si sceglie, non si impone: chi vuole solo la chat non deve aspettare il
rem  download di un modello di trascrizione. La lista arriva da
rem  orchestra/dipendenze.py, lo stesso modulo del pannello Opzioni, e non
rem  e' riscritta qui: una seconda lista e' quella che resta indietro.
call :dipendenze
echo.

rem --- 6. File .env ---
if not exist "%DESTDIR%\orchestra\.env" (
  copy /y "%DESTDIR%\orchestra\.env.example" "%DESTDIR%\orchestra\.env" >nul
  echo  [OK] Creato orchestra\.env — aprilo e inserisci le chiavi API.
) else (
  echo  [OK] .env esistente conservato.
)

rem --- 7. Collegamento sul Desktop (con icona Orchestra) ---
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); if(-not (Test-Path $d)){ $d=Join-Path $env:USERPROFILE 'Desktop'; New-Item -ItemType Directory -Force -Path $d | Out-Null }; $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Avvia Orchestra.lnk')); $s.TargetPath='%DESTDIR%\Avvia-Orchestra.bat'; $s.WorkingDirectory='%DESTDIR%'; $s.IconLocation='%DESTDIR%\installer\orchestra.ico'; $s.Save(); Write-Host ('  collegamento creato in ' + $d)"
echo  [OK] Collegamento sul Desktop creato.

rem --- 8. Comando 'orchestra' nel PATH (CLI) ---
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

rem ===================================================================
rem  Dipendenze: leggere la lista e installare quello che si sceglie
rem ===================================================================
rem  Sotto il flusso principale e non dentro: cmd esegue le righe in
rem  ordine, e un :label scritto in mezzo al flusso verrebbe attraversato
rem  a piedi, eseguendo un pezzo di codice che nessuno ha chiamato.
:dipendenze
set "DEPFILE=%TEMP%\orchestra-dipendenze.txt"
set "DPY=%DESTDIR%\orchestra\dipendenze.py"
if not exist "%DPY%" goto :dip_salta
"%PYEXE%" "%DPY%" --elenco > "%DEPFILE%" 2>nul
set "DN=0"
for /f "usebackq tokens=1,2,3,4 delims=|" %%a in ("%DEPFILE%") do (
  set /a DN+=1
  set "DEPN_!DN!=%%a"
  set "DEPT_!DN!=%%b"
  set "DEPP_!DN!=%%d"
)
if %DN%==0 goto :dip_salta
echo  Funzioni aggiuntive (Orchestra parte comunque):
for /l %%i in (1,1,%DN%) do call :dip_riga %%i
echo.
echo    0 - nessuna: restano disponibili dopo, in Opzioni, Dipendenze
set "SCELTA="
set /p "SCELTA=Cosa installo? Numeri separati da spazio, Invio = tutte: "
if not defined SCELTA goto :dip_tutte
if "%SCELTA%"=="0" goto :dip_fine
rem  Virgole e punti e virgola si tolgono qui: accettare due separatori costa
rem  una riga, rifiutare tutto l'input per una virgola non lo spiega nessuno.
set "SCELTA=%SCELTA:,=%"
set "SCELTA=%SCELTA:;=%"
for %%n in (%SCELTA%) do call :dip_uno %%n
goto :dip_fine

:dip_tutte
for /l %%i in (1,1,%DN%) do call :dip_uno %%i
goto :dip_fine

:dip_riga
echo    %~1 - !DEPN_%~1!: !DEPP_%~1!
goto :eof

:dip_uno
set "NOME=!DEPN_%~1!"
if not defined NOME goto :dip_ignoto
rem  Anche una dipendenza gia' installata si reinstalla: e' il modo per
rem  rimediare a un'installazione rotta, e dire "ce l'hai gia'" toglierebbe
rem  il rimedio proprio a chi ne ha bisogno. Costa pochi secondi.
echo.
echo  Installo !NOME!...
"%PYEXE%" "%DPY%" --installa "!NOME!"
if errorlevel 1 goto :dip_fallito
echo  [OK] !NOME!
goto :eof
:dip_fallito
echo  [AVVISO] !NOME! non installato: si puo' rifare dopo da
echo  Opzioni, Dipendenze, oppure con pip install !NOME!
goto :eof
:dip_ignoto
echo  [AVVISO] scelta "%~1" non valida: la salto.
goto :eof

:dip_salta
echo  [AVVISO] dipendenze.py non trovato: salto le funzioni aggiuntive.
:dip_fine
del "%DEPFILE%" 2>nul
goto :eof

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
