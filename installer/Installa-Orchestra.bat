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

rem --- 1. Python 3.14: quello che installiamo noi, con il percorso intero ---
rem  Due guasti in uno, e vanno risolti insieme.
rem
rem  Il primo: `py` e `python` non sono un interprete, sono un selettore.
rem  `py -3 --version` puo' rispondere di si' e poi `py` da solo scegliere
rem  la versione predefinita, che su una macchina con un runtime portabile
rem  registrato e' quella sbagliata: il controllo passa, l'installazione
rem  muore dopo con "Unable to create process". E' successo davvero, ed e'
rem  il "l'ha trovato e poi non lo trova piu'".
rem
rem  Il secondo: un Python che c'e' non e' un Python che funziona. Un 3.15
rem  senza pip si lascia intervistare (versione, import) e poi non installa
rem  niente. Quindi la versione non si indovina: la installiamo noi e la
rem  usiamo con il percorso completo, che non dipende dal PATH.
rem
rem  Perche' 3.14 e non 3.15: sul 3.15 manca la ruota di onnxruntime (serve
rem  alla trascrizione) e i runtime "portatili" li abbiamo gia' visti
rem  rotti. Il 3.14 e' stato provato: import del pacchetto, webapp, CLI,
rem  pip presente.
set "PYEXE="
call :cerca_python
if defined PYEXE goto :python_ok
echo  Python 3.14 non trovato. Provo a installarlo...
winget install -e --id Python.Python.3.14 --silent --accept-package-agreements --accept-source-agreements
call :cerca_python
if defined PYEXE goto :python_ok
echo  Winget non ha funzionato; scarico l'installer da python.org...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe' -OutFile '%TEMP%\python-setup.exe' -UseBasicParsing" 2>nul
if exist "%TEMP%\python-setup.exe" (
  echo  Installo Python 3.14 (qualche minuto)...
  start /wait "" "%TEMP%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
  del "%TEMP%\python-setup.exe" >nul 2>&1
)
call :cerca_python
if defined PYEXE goto :python_ok
rem  Ultima risorsa: un interprete qualunque, ma con il percorso RISOLTO.
rem  Meglio un'Orchestra che parte con un Python che non e' il nostro, che
rem  un installer che si chiude a meta'.
for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE for /f "delims=" %%P in ('python3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE goto :python_mancante
echo  [AVVISO] uso un Python diverso da quello previsto: %PYEXE%
goto :python_ok
:python_mancante
echo.
echo  [ERRORE] Python 3.14 non installato e nessun altro Python utilizzabile.
echo  Installa Python 3.14 da https://www.python.org/downloads/ e rilancia.
pause
exit /b 1
:python_ok
echo  [OK] Python: %PYEXE%

rem --- 2. Cartella di installazione ---
set "DESTDIR=%LOCALAPPDATA%\Orchestra"
if not exist "%DESTDIR%" mkdir "%DESTDIR%"
echo  [OK] Cartella: %DESTDIR%

rem --- 3. Download ultima release + estrazione ---
rem Lo script PowerShell e' dentro questo stesso file (righe REM-PS:):
rem lo si estrae in TEMP e lo si esegue, niente altri file da scaricare.
rem  Prima del download: si riesce a fare un TLS verso GitHub? Il download
rem  lo fa PowerShell, che spesso si salva da solo (recupera i certificati
rem  che gli mancano via AIA, con una cache sua); Python no. Quindi si prova
rem  con lo stesso Python che servira' poi: se e' lui a non fidarsi, il
rem  passo 4 arriverebbe dopo un "Download fallito" che non spiega niente.
rem
rem  La sonda e' generica di proposito: chiede "questo TLS regge?", non
rem  "c'e' la radice di Telegram". L'elenco delle radici che servono
rem  all'app sta in orchestra/certificati.py, e li' resta: una seconda lista
rem  scritta qui sarebbe la copia che invecchia.
echo  Verifico la connessione sicura a GitHub...
set "TLSPROBE=%TEMP%\orchestra-tls.txt"
"%PYEXE%" -c "import ssl,socket;s=ssl.create_default_context().wrap_socket(socket.create_connection(('api.github.com',443),timeout=8),server_hostname='api.github.com');s.close()" >nul 2>"%TLSPROBE%"
if not errorlevel 1 goto :tls_download
rem  Solo l'errore di certificato merita questo discorso: se manca la rete,
rem  il download fallira' e lo dira' lui.
findstr /C:"CERTIFICATE_VERIFY_FAILED" "%TLSPROBE%" >nul 2>&1
if errorlevel 1 goto :tls_download
echo.
echo  Python non si fida di github.com: i certificati di Windows sono
echo  incompleti, ed e' il caso di un Windows appena installato. Le radici
echo  si scaricano da Windows Update e si importano nello store di sistema:
echo  serve il consenso di amministratore, Windows apre la sua finestra.
set "RIP="
set /p "RIP=Sistemo ora? [S/n] "
if /i "%RIP%"=="n" goto :tls_download
call :ripara_radici
"%PYEXE%" -c "import ssl,socket;s=ssl.create_default_context().wrap_socket(socket.create_connection(('api.github.com',443),timeout=8),server_hostname='api.github.com');s.close()" >nul 2>"%TLSPROBE%"
if not errorlevel 1 echo  [OK] certificati a posto.
if errorlevel 1 echo  [AVVISO] ancora niente: provo lo stesso il download.
:tls_download
del "%TLSPROBE%" 2>nul
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
call :ripara_radici
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
rem  Trova il Python 3.14 che installiamo noi, per percorso assoluto.
rem  Non basta che risponda alla versione: un 3.15 senza pip passa questo
rem  controllo e fallisce dopo, quando deve installare qualcosa. Quindi si
rem  prova anche che `ssl` si importi, che e' l'unica cosa senza cui
rem  Orchestra non parla con nessun provider.
:cerca_python
set "PYEXE="
for %%D in ("%LOCALAPPDATA%\Programs\Python\Python314" "C:\Python314" "%PROGRAMFILES%\Python314") do (
  if not defined PYEXE call :prova_python "%%~D\python.exe"
)
goto :eof

:prova_python
if not exist "%~1" goto :eof
"%~1" -c "import sys,ssl;raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
set "PYEXE=%~1"
goto :eof

rem  La riparazione dei certificati sta in un posto solo: la usano la sonda
rem  prima del download e il controllo dopo l'estrazione. Due copie degli
rem  stessi due comandi sono due punti che possono divergere.
rem
rem  La prima meta' scrive solo un file e non chiede permessi; la seconda
rem  tocca lo store di sistema e senza amministratore risponde "accesso
rem  negato". Quindi si eleva solo la seconda.
:ripara_radici
set "SST=%TEMP%\orchestra-radici.sst"
certutil -generateSSTFromWU "%SST%" >nul 2>&1
powershell -NoProfile -Command "Start-Process -FilePath 'certutil' -ArgumentList '-addstore','-f','root','%SST%' -Verb RunAs -Wait"
del "%SST%" 2>nul
goto :eof

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
REM-PS:$escludiNomi = @('.env', 'token.txt', 'goals.json', 'budget_global.json',
REM-PS:                  'storico.db', 'memoria_indice.db', 'permessi.json',
REM-PS:                  'nous_auth.json', '.remote_state.json')
REM-PS:$escludiEst = @('.db', '.db-wal', '.db-shm')
REM-PS:$escludiCart = @('__pycache__', 'node_modules', 'sessions', 'tmp', 'plans',
REM-PS:                 '.orchestra', '.git', '.freebuff', '_dati_test',
REM-PS:                 '_dati_test_server', '_bench', '_prova', '_probe',
REM-PS:                 '.cloud-attachments')
REM-PS:$copiati = 0
REM-PS:$saltati = 0
REM-PS:#  Copia a unione: si sovrascrive il codice, non si cancella MAI una
REM-PS:#  cartella, e i dati locali non si toccano a nessun livello.
REM-PS:#  La regola vecchia guardava solo i nomi nella radice dell'archivio:
REM-PS:#  `.env` sta dentro orchestra\, quindi la cartella veniva cancellata e
REM-PS:#  con lei le chiavi. Rilanciare l'installer su un'installazione
REM-PS:#  esistente deve aggiornare il codice, non azzerare il lavoro.
REM-PS:foreach ($f in (Get-ChildItem -Path $root.FullName -Recurse -Force -File)) {
REM-PS:  $rel = $f.FullName.Substring($root.FullName.Length).TrimStart('\')
REM-PS:  $salta = $false
REM-PS:  foreach ($parte in ($rel -split '\\')) {
REM-PS:    if ($escludiCart -contains $parte) { $salta = $true }
REM-PS:  }
REM-PS:  if ($escludiNomi -contains $f.Name) { $salta = $true }
REM-PS:  foreach ($est in $escludiEst) {
REM-PS:    if ($f.Name.ToLower().EndsWith($est)) { $salta = $true }
REM-PS:  }
REM-PS:  if ($salta) { $saltati++; continue }
REM-PS:  $dstFile = Join-Path $Dest $rel
REM-PS:  $cartella = Split-Path $dstFile -Parent
REM-PS:  if (-not (Test-Path $cartella)) { New-Item -ItemType Directory -Path $cartella -Force | Out-Null }
REM-PS:  Copy-Item -Force $f.FullName $dstFile
REM-PS:  $copiati++
REM-PS:}
REM-PS:Write-Host ('  ' + $copiati + ' file aggiornati, ' + $saltati + ' lasciati come erano')
REM-PS:Remove-Item -Recurse -Force $tmp, $zip
REM-PS:Write-Host '  file copiati.'
