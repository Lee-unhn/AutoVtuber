@echo off
REM AutoVtuber convenience launcher
REM Usage: double-click run.bat, or `run.bat` from cmd

setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found. Run setup first:
    echo     C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe -m venv venv
    echo     venv\Scripts\activate
    echo     pip install -r requirements.txt
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python -m autovtuber %*
endlocal
