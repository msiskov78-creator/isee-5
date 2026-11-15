@echo off
setlocal
cd /d "%~dp0"
set "GESTURE_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%GESTURE_PYTHON%" set "GESTURE_PYTHON=%~dp0gitignor\.venv\Scripts\python.exe"
if not exist "%GESTURE_PYTHON%" (
    echo Python environment not found. Expected .venv or gitignor\.venv.
    exit /b 1
)
"%GESTURE_PYTHON%" -B "%~dp0main.py" %*
exit /b %errorlevel%
