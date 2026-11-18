@echo off
cd /d "%~dp0"
echo Starting the Vacancy Tracker in LOCAL TEST MODE...
python -c "import flask" 2>nul
if errorlevel 1 goto install
goto run
:install
echo Installing Flask, one moment...
python -m ensurepip --upgrade >nul 2>nul
python -m pip install --quiet flask
python -c "import flask" 2>nul
if errorlevel 1 goto failed
:run
python run_local.py
pause
exit /b 0
:failed
echo.
echo Could not install Flask. Check that Python is installed and that you are online,
echo then open START-HERE.txt for the manual steps.
pause
exit /b 1
