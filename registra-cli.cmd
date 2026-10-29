@echo off
rem Registra il comando `orchestra` per la CLI (Windows).
rem Crea uno shim in %LOCALAPPDATA%\Microsoft\WindowsApps (gia' nel PATH).
setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "SHIMDIR=%LOCALAPPDATA%\Microsoft\WindowsApps"
if not exist "%SHIMDIR%" mkdir "%SHIMDIR%"
set "SHIM=%SHIMDIR%\orchestra.cmd"
(
  echo @echo off
  echo set "PYTHONPATH=%ROOT%;%%PYTHONPATH%%"
  echo python -m orchestra.cli %%*
) > "%SHIM%"
echo Comando 'orchestra' registrato (root: %ROOT%).
echo Prova da un'altra cartella: orchestra --version
pause >nul