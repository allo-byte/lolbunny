@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title bunnylol
set "PORT=8765"

set "PYW=pythonw"
set "PY=python"
where pythonw >nul 2>&1 || set "PYW="
where python  >nul 2>&1 || set "PY="
if "%PYW%"=="" if "%PY%"=="" (
  echo.
  echo  NO ENCONTRE PYTHON EN ESTE PC.
  echo  Instala Python 3.11 desde python.org y vuelve a abrir esto.
  echo.
  pause
  exit /b 1
)

set "UP="
for /f "delims=" %%s in ('powershell -NoProfile -Command "try{(Invoke-WebRequest http://127.0.0.1:%PORT%/api/meta -UseBasicParsing -TimeoutSec 3).StatusCode}catch{}"') do set "UP=%%s"
if "%UP%"=="200" (
  echo  Ya estaba abierto. No abro una segunda copia.
  timeout /t 2 >nul
  exit /b 0
)

echo  Abriendo bunnylol...
if not "%PYW%"=="" (
  start "bunnylol" "%PYW%" app.py
) else (
  start "bunnylol" "%PY%" app.py
)

set "UP="
for /l %%n in (1,1,30) do (
  for /f "delims=" %%s in ('powershell -NoProfile -Command "try{(Invoke-WebRequest http://127.0.0.1:%PORT%/api/meta -UseBasicParsing -TimeoutSec 2).StatusCode}catch{}"') do set "UP=%%s"
  if "%%s"=="200" goto ready
  timeout /t 1 >nul
)

:ready
if not "%UP%"=="200" (
  cls
  echo ============================================================
  echo    NO PUDE ABRIR EL PROGRAMA
  echo ============================================================
  echo.
  echo  Ultimas lineas del registro de errores:
  echo.
  powershell -NoProfile -Command "if (Test-Path 'cache\app.log') { Get-Content 'cache\app.log' -Tail 15 } else { '  (no hay registro)' }"
  echo.
  echo  Prueba a ejecutar a mano en esta carpeta:  python app.py
  echo.
  pause
  exit /b 1
)

echo.
echo  LISTO. El overlay esta en este PC.
echo  Para el iPad, abre  iPad.bat  (te dice la direccion).
echo.
timeout /t 3 >nul
endlocal
