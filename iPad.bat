@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title bunnylol - Iniciar y ver en el iPad
set "PORT=8765"

echo ============================================================
echo     BUNNYLOL
echo ============================================================
echo.

set "UP="
for /f "delims=" %%s in ('powershell -NoProfile -Command "try{(Invoke-WebRequest http://127.0.0.1:%PORT%/api/meta -UseBasicParsing -TimeoutSec 3).StatusCode}catch{}"') do set "UP=%%s"

if "%UP%"=="200" (
  echo  El programa ya estaba abierto. Trayendo la ventana al frente...
) else (
  echo  Abriendo el programa...
)

where pythonw >nul 2>&1
if errorlevel 1 (
  start "bunnylol" python app.py
) else (
  start "bunnylol" pythonw app.py
)

if not "%UP%"=="200" (
  for /l %%n in (1,1,40) do (
    for /f "delims=" %%s in ('powershell -NoProfile -Command "try{(Invoke-WebRequest http://127.0.0.1:%PORT%/api/meta -UseBasicParsing -TimeoutSec 2).StatusCode}catch{}"') do set "UP=%%s"
    if "%%s"=="200" goto ready
    timeout /t 1 >nul
  )
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
  echo  Prueba a ejecutar a mano:  python app.py
  echo.
  pause
  exit /b
)

REM --- Firewall: asegura que el iPad pueda entrar ---
netsh advfirewall firewall show rule name="LoL Build Advisor 8765" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Primera vez: abriendo el puerto %PORT% en el Firewall de Windows...
  echo  ACEPTA el aviso de permisos de administrador que va a aparecer.
  echo.
  call "%~dp0Permitir-en-iPad.bat"
)

REM --- Leer el enlace unico (nombre del PC) y la IP real ---
set "HOST=%COMPUTERNAME%"
set "MDNS=http://%HOST%.local:%PORT%"
set "NETBIOS=http://%HOST%:%PORT%"
set "IP="
set "i=0"
for /f "delims=" %%a in ('powershell -NoProfile -Command "try{$a=(Invoke-RestMethod http://127.0.0.1:%PORT%/api/meta -TimeoutSec 4).access; $a.mdns; $a.netbios; $a.ip; $a.hostname}catch{}"') do (
  set /a i+=1
  if !i!==1 set "MDNS=%%a"
  if !i!==2 set "NETBIOS=%%a"
  if !i!==3 set "IP=%%a"
  if !i!==4 set "HOST=%%a"
)
echo !MDNS!/| clip

echo.
echo ============================================================
echo     YA ESTA LISTO  -  ABRE ESTO EN EL IPAD
echo ============================================================
echo.
echo    Este PC:  !HOST!
echo.
echo    En Safari del iPad escribe:
echo.
echo         !IP!/
echo.
echo    (Tambien vale:  !MDNS!/  -  es fija, no cambia)
echo    - Ya esta copiada al portapapeles.
echo.
echo ============================================================
echo    Si el iPad no abre NINGUNA:
echo      - iPad y PC tienen que estar en la MISMA WiFi.
echo      - En el iPad: Ajustes ^> WiFi ^> (i) ^> Direccion IP.
echo        Debe empezar por  192.168.0.
echo      - Desactiva "aislamiento de clientes" en el router.
echo ============================================================
echo.
echo    (La ventana del overlay esta en el PC. Puedes cerrar
echo     ESTA ventana; el programa sigue funcionando.)
echo.
pause
endlocal
