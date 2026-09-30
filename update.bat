@echo off
REM Double-click this to refresh both variants with the latest market data.
REM
REM The published site does this by itself every Monday, and commits the new
REM figures to the repository, so on a copy that is on GitHub the usual way to
REM get fresh data is git pull. This is for a copy that is not, or for seeing
REM the numbers before Monday.
REM
REM Both files are refreshed, in this order, because the Italian variant takes
REM its growth term from the Shiller data the American refresh downloads, and
REM a test holds the two equal. One refreshed without the other fails it.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" update.py
if errorlevel 1 goto failed

"%PY%" tools\refresh_italy.py --write
if errorlevel 1 goto failed

echo.
echo Both variants refreshed.
goto done

:failed
echo.
echo A refresh did not complete. If one file was already rewritten, the two
echo variants no longer match. To go back to the committed data, run:
echo     git checkout -- variants/

:done
echo.
pause
