@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw app.py %*
) else (
  start "" python app.py %*
)
timeout /t 3 /nobreak >nul
python ipad_bridge.py
pause
