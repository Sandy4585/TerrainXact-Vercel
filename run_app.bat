@echo off
setlocal

REM Define paths
set MINICONDA_PATH=%~dp0Miniconda3
set ENV_PATH=%~dp0env
set LOG_FILE=%~dp0setup_log.txt

REM Redirect all output to log file
echo Logging to %LOG_FILE%
echo. > %LOG_FILE%
call :Log > %LOG_FILE% 2>&1
type %LOG_FILE%
pause
exit /b

:Log
REM Check if Miniconda is installed
if not exist "%MINICONDA_PATH%" (
    echo Installing Miniconda...
    start /wait "" "%~dp0Miniconda3-latest-Windows-x86_64.exe" /InstallationType=JustMe /RegisterPython=0 /S /D=%MINICONDA_PATH%
)

REM Initialize Conda
call "%MINICONDA_PATH%\Scripts\activate.bat" base

REM Check if the environment exists and create it if it doesn't
if not exist "%ENV_PATH%" (
    echo Creating Conda environment...
    conda env create -f "%~dp0environment.yaml" -p "%ENV_PATH%"
)

REM Activate the environment
echo Activating the environment...
call conda activate "%ENV_PATH%"
if errorlevel 1 (
    echo Failed to activate the environment.
    exit /b 1
)

REM Set the Flask application environment variable
set FLASK_APP=app.py
set FLASK_ENV=development

REM Run the Flask application
echo Running the Flask application...
start "" "http://127.0.0.1:5000"
python -m flask run
if errorlevel 1 (
    echo Failed to run the Flask application.
    exit /b 1
)
exit /b
