@echo off
REM Double-click this to refresh the tool with the latest market data.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" update.py %*
) else (
    python update.py %*
)
echo.
pause
