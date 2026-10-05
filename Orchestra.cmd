@echo off
rem ===================================================================
rem  Orchestra — avvia / ferma / riavvia il server locale
rem
rem  Tre operazioni in un eseguibile solo, perche' tre icone che fanno
rem  la stessa cosa con parametri diversi sono tre cose che si rompono
rem  in tre modi diversi. Qui c'e' un posto solo dove il numero di porta
rem  e il nome del processo vivono.
rem
rem    Orchestra.cmd avvia
rem    Orchestra.cmd ferma
rem    Orchestra.cmd riavvia
rem
rem  Senza argomento chiede. Un doppio click che non fa niente e'
rem  peggio di uno che chiede: si vede che esiste, e si sceglie.
rem
rem  "ferma" e' verificato, non creduto: prima guarda se qualcosa
rem  ascolta davvero su quella porta, e dice cosa ha trovato. Un
rem  "fermo" dato per scontato e' la peggiore delle risposte, perche'
rem  il server e' ancora li' e tu non lo sai.
rem ===================================================================
setlocal

set "PORTA=8737"
set "ROOT=%~dp0"
set "LOGFILE=%~dp0orchestra.log"
set "LOGERR=%~dp0orchestra.err.log"
set "PY=python"

rem --- quale python? ----------------------------------------------------
rem  `py -3` e' il launcher di Windows e sceglie da solo. Si prova
rem  `python` come seconda scelta.
rem
rem  Niente blocchi if/else qui: dentro un blocco, un `echo` contiene
rem  parentesi che chiudono il blocco, e in cmd quello e' un errore
rem  che si vede solo a meta' esecuzione. Meglio quattro righe piatte.
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if "%PY%"=="" (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if "%PY%"=="" goto :no_python

rem --- l'operazione richiesta -----------------------------------------
rem  Va letta PRIMA del menu: senza questo, `Orchestra.cmd ferma` apre
rem  il menu e aspetta una scelta che l'utente ha gia' fatta. Sembrava
rem  funzionare e non faceva niente.
if /i "%~1"=="avvia"   goto :avvia
if /i "%~1"=="start"   goto :avvia
if /i "%~1"=="ferma"   goto :ferma
if /i "%~1"=="stop"    goto :ferma
if /i "%~1"=="riavvia" goto :riavvia
if /i "%~1"=="restart" goto :riavvia
if /i "%~1"=="log"     goto :vedilog

goto :menu

rem  Python assente: si dice subito e in chiaro, prima di qualsiasi
rem  altra cosa. Un errore a meta' avvio dice molto meno.
:no_python
echo.
echo   Python non trovato.
echo   Installa Python 3 e riprova: senza, Orchestra non parte.
echo.
pause
exit /b 1

rem ===================================================================
rem  Avvia
rem ===================================================================
:avvia
echo.
echo   Avvio di Orchestra su http://127.0.0.1:%PORTA%
echo   Attendere il caricamento del catalogo, puo' durare qualche
echo   secondo: sono centinaia di modelli da scaricare e misurare.
echo.

rem  Il log e' di una sessione sola, non di tutte. Con `>>` il file
rem  cresceva a ogni riavvio, e dopo qualche decina di volte
rem  `Orchestra.cmd log` — il comando che serve quando qualcosa non
rem  va diventava illeggibile proprio quando serve leggerlo.
rem
rem  Perche' non si cancella e basta: azzerandolo, si perde il log del
rem  server che e' MORTO, che e' esattamente quello che si vuole
rem  guardare quando si riviavia per capire perche'. Quindi la
rem  sessione precedente viene conservata in orchestra.log.1, e il
rem  comando log la mostra sotto quella di adesso.
rem
rem  Il file si cancella sempre perche' si arriva qui DOPO che
rem  `riavvia` ha fermato il server: era il server a tenerlo aperto.
rem  Se resta aperto, `del` fallisce in silenzio e il log si
rem  continuerebbe a crescere — quindi l'esito si dice, perche'
rem  altrimenti il file si riempirebbe e nessuno saprebbe perche'.
if exist "%LOGFILE%" (
    move /y "%LOGFILE%" "%LOGFILE%.1" >nul 2>&1
    if exist "%LOGFILE%.1" echo   Il log di prima e' in orchestra.log.1
)
rem  Anche l'errore ruota: su Start-Process stdout e stderr NON possono
rem  andare sullo stesso file ("sono uguali"), quindi sono due. E se
rem  il server non parte, il motivo e' quasi sempre li'.
if exist "%LOGERR%" move /y "%LOGERR%" "%LOGERR%.1" >nul 2>&1
rem  `type nul > file` e non `echo > file`: in cmd, `echo` senza testo
rem  dentro un redirect NON crea il file, e scrive invece "ECHO e'
rem  disattivato" sullo standard output — che finiva nel log con una
rem  parola in mezzo che non significava niente. `type nul` crea un
rem  file vuoto, che e' quello che serve.
type nul > "%LOGFILE%"

rem  Si avvia un processo INDIPENDENTE, che resta vivo anche se
rem  questa finestra si chiude.
rem
rem  `-WindowStyle Hidden` con Start-Process e' la strada giusta, e
rem  prima falliva per una ragione precisa: `%PY%` era "py -3", e
rem  Start-Process leggeva il -3 come argomento posizionale di se
rem  stesso. Si risolve alla fonte: `-FilePath` vuole UN eseguibile,
rem  quindi `-3` glielo si passa in ArgumentList, dove e' un argomento
rem  del launcher e non dello Start-Process.
rem
rem  Perche' non `start /b`: `/b` vuol dire "nessuna finestra NUOVA", e
rem  il processo condivida la console di questa. Chiudendo il cmd,
rem  il server muore con lui — ed e' esattamente il difetto che
rem  avevo creato io quando ho sostituito `/min` con `/b` per togliere
rem  la finestra dalla taskbar. Si puo' nascondere la finestra senza
rem  legare le vite: sono due cose diverse.
rem  %PY1% e' l'eseguibile, %PY2% l'eventuale argomento. Due variabili
rem  e non una sola con dentro "py -3": Start-Process vuole UN nome di
rem  eseguibile in -FilePath, e il resto va in ArgumentList. Con
rem  "py -3" dentro -FilePath, il -3 diventava argomento posizionale di
rem  Start-Process, che si rifiutava di accettarlo.
set "PY1="
set "PY2="
where py >nul 2>&1
if not errorlevel 1 (
    set "PY1=py"
    set "PY2=-3"
)
if "%PY1%"=="" (
    where python >nul 2>&1
    if not errorlevel 1 set "PY1=python"
)
if "%PY1%"=="" goto :no_python

rem  Il redirect lo mette Start-Process: il log continua a funzionare
rem  anche con la finestra nascosta, che e' il punto.
rem
rem  Tutto su UNA riga e senza variabili PowerShell: `$` dentro cmd
rem  viene passato a PowerShell, ma `%` viene espanso dal cmd, e i due
rem  linguaggi sulla stessa riga sbagliano. Senza variabili, niente
rem  da espandere.
powershell -NoProfile -Command "Start-Process -FilePath '%PY1%' -ArgumentList @('%PY2%','-m','orchestra.cli','web','--port','%PORTA%','--no-browser') -WindowStyle Hidden -RedirectStandardOutput '%LOGFILE%' -RedirectStandardError '%LOGERR%'"

rem  Poi si aspetta che la porta risponda davvero, e si apre il
rem  browser solo allora. Aprirlo subito mostrerebbe "connessione
rem  rifiutata" per due secondi, e sembrerebbe che il programma sia
rem  rotto.
call :aspetta %PORTA% 40
if errorlevel 1 (
    echo.
    echo   Il server non ha risposto entro 40 secondi.
    echo   Guarda la finestra di Orchestra per il motivo.
    echo.
    pause
    exit /b 1
)

start "" "http://127.0.0.1:%PORTA%"
echo   Pronto: http://127.0.0.1:%PORTA%
echo.
rem  Pausa breve prima di chiudere la finestra. `timeout /t` sembrava
rem  la scelta ovvia e non funziona: dove c'e' un timeout di GNU/coreutils
rem  nel PATH, `cmd` risolve quello e interpreta `/t` come opzione sua,
rem  dicendo "invalid time interval". `ping` esiste su Windows da
rem  sempre e produce lo stesso ritardo, con un codice di uscita che
rem  qui non interessa.
ping -n 3 127.0.0.1 >nul
exit /b 0


rem ===================================================================
rem  Ferma
rem ===================================================================
:ferma
echo.
call :chi_ha %PORTA%
if errorlevel 1 (
    echo   Non c'e' nessun server su questa porta. Niente da fermare.
    echo.
    pause
    exit /b 0
)

echo   Fermo il server sulla porta %PORTA%...
call :uccidi %PORTA%
if errorlevel 1 (
    echo   Non e' stato possibile fermarlo.
    echo   Aprilo come amministratore e riprova.
) else (
    call :aspetta_libera %PORTA% 10
    echo   Fermato.
)
echo.
pause
exit /b 0


rem ===================================================================
rem  Riavvia
rem ===================================================================
:riavvia
echo.
call :chi_ha %PORTA%
if errorlevel 1 (
    echo   Non era in esecuzione: lo avvio.
    echo.
    goto :avvia
)
echo   Riavvio: fermo quello che c'e' e riparto pulito.
echo   Lo faccio perche' un riavvio a meta' — processo nuovo, vecchio
echo   ancora in ascolto e' il caso peggiore: due server che si
echo   contendono la stessa porta e il primo che arriva risponde.
echo.
call :uccidi %PORTA%
call :aspetta_libera %PORTA% 10
ping -n 2 127.0.0.1 >nul
goto :avvia


rem ===================================================================
rem  Log
rem ===================================================================
:vedilog
rem  Il server gira senza finestra, e una cosa senza voce non serve a
rem  niente quando qualcosa va storto. Il log e' su file e si apre
rem  solo quando lo chiedi.
rem
rem  Piatta, senza blocchi. In cmd una parentesi chiusa dentro un
rem  blocco lo chiude, e quello che segue viene letto come un
rem  comando a caso: l'errore che esce parla d'altro e non del posto
rem  che si era chiuso per sbaglio. Nessuna sequenza di sostituzione
rem  nei commenti per lo stesso motivo: una rem che contiene una
rem  variabile di percorso viene valutata, e se quella variabile non
rem  esiste si ferma tutto.
echo.

if exist "%LOGFILE%" goto :log_ce

echo   Ancora nessun log: il server non e' mai partito da qui,
echo   oppure non ha scritto ancora niente.
echo.
pause
exit /b 0

:log_ce
rem  Dimensione e data le chiede `dir`, che le dà già in una riga
rem  sola. Il tentativo con le variabili di percorso dentro un for
rem  finiva con il testo della variabile non risolto stampato sulla
rem  riga — peggio che non stampare niente, perché sembrava un dato.
dir /-c "%LOGFILE%"
echo.
echo   ---- contenuto del log ----
type "%LOGFILE%"
echo.
echo.
if exist "%LOGFILE%.1" (
    echo   ---- sessione precedente, in orchestra.log.1 ----
    type "%LOGFILE%.1"
    echo.
)
rem  L'errore sta in un file a parte, e viene PRIMO: se il server non
rem  e' partito, la ragione e' li' e non nel log normale. Cercarlo
rem  dopo venti righe di output normale e' come non cercarlo.
if exist "%LOGERR%" (
    echo   ---- errori ----
    type "%LOGERR%"
    echo.
)
if exist "%LOGERR%.1" (
    echo   ---- errori della sessione precedente ----
    type "%LOGERR%.1"
    echo.
)
echo   Il log continua a scrivere. Per guardarlo in un editor apribile,
echo   aspetta che il server sia fermo, oppure apri una copia.
echo.
exit /b 0


rem ===================================================================
rem  Menu
rem ===================================================================
:menu
echo.
echo   ==================  Orchestra  ==================
echo.
echo     1  avvia     apre il browser e avvia il server
echo     2  ferma     chiude il server
echo     3  riavvia   ferma e riapre
echo     4  log       apre il log del server
echo.
set "SCELTA="
set /p "SCELTA=Scegli da 1 a 4 e premi Invio: "

if "%SCELTA%"=="1" goto :avvia
if "%SCELTA%"=="2" goto :ferma
if "%SCELTA%"=="3" goto :riavvia
if "%SCELTA%"=="4" goto :vedilog
if "%SCELTA%"=="" goto :menu

echo.
echo   Non ho capito "%SCELTA%".
ping -n 2 127.0.0.1 >nul
goto :menu


rem ===================================================================
rem  Funzioni
rem ===================================================================

rem  Chi c'e' in ascolto sulla porta. Il PID finisce in _PID.
rem  Errorlevel 1 = nessuno. Il fallback su netstat serve per il caso
rem  (raro) in cui powershell non si riesca a lanciare: meglio una
rem  riga grezza che nessuna risposta.
:chi_ha
set "_PID="
for /f "tokens=5" %%a in ('powershell -NoProfile -Command ^
  "Get-NetTCPConnection -LocalPort %PORTA% -State Listen -EA SilentlyContinue ^| Select-Object -First 1 -ExpandProperty OwningProcess" 2^>nul') do set "_PID=%%a"
if not "%_PID%"=="" exit /b 0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:"LISTENING" ^| findstr /C:":%PORTA%"') do set "_PID=%%a"
if not "%_PID%"=="" exit /b 0
exit /b 1

rem  Chiude quello che ascolta sulla porta.
:uccidi
call :chi_ha
if "%_PID%"=="" exit /b 1
rem  -f: senza conferma. Il server e' nostro e l'utente ha chiesto di
rem  fermarlo; chiedere conferma a chiudere un programma che ha
rem  chiesto di chiudere e' solo un passo in piu' da spiegare.
rem  /T anche: se il server ha avviato un figlio, senza /T il figlio
rem  resta vivo e tiene la porta, e sembra che il fermo non abbia
rem  fatto niente.
taskkill /F /T /PID %_PID% >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0

rem  Aspetta che la porta risponda. Errorlevel 1 = non ha risposto.
:aspetta
set /a _tries=%2
:aspetta_loop
rem  Non basta che la porta sia aperta: deve RISPONDERE. Un socket
rem  in ascolto con dentro un processo che non risponde e' uno stato
rem  possibile, e aprire il browser su quello mostra una pagina vuota
rem  mentre lo script dice "Pronto".
powershell -NoProfile -Command "try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',%PORTA%); $c.Close(); exit 0 }catch{ exit 1 }" >nul 2>&1
if not errorlevel 1 exit /b 0
ping -n 2 127.0.0.1 >nul
set /a _tries-=1
if %_tries% leq 0 exit /b 1
goto :aspetta_loop

rem  Aspetta che la porta si liberi.
:aspetta_libera
set /a _tries=%2
:aspetta_libera_loop
call :chi_ha
if errorlevel 1 exit /b 0
ping -n 2 127.0.0.1 >nul
set /a _tries-=1
if %_tries% leq 0 exit /b 1
goto :aspetta_libera_loop

endlocal