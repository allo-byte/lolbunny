@echo off
setlocal
title Permitir bunnylol en el iPad (firewall)

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Pidiendo permisos de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo ============================================================
echo    Abriendo el puerto 8765 en el Firewall de Windows
echo    para que el iPad pueda entrar al LoL Build Advisor
echo ============================================================
echo.

netsh advfirewall firewall delete rule name="LoL Build Advisor 8765" >nul 2>&1
netsh advfirewall firewall add rule name="LoL Build Advisor 8765" dir=in action=allow protocol=TCP localport=8765 profile=any

echo.
echo Listo. Ya puedes abrir el enlace en el iPad:
echo    http://%COMPUTERNAME%.local:8765/
echo.
pause
endlocal
