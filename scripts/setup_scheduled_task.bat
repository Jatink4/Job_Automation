@echo off
:: scripts/setup_scheduled_task.bat — Configure Daily Windows Task Scheduler Job
:: Runs daily discovery in Review-Before-Submit dry-run mode.

setlocal enabledelayedexpansion
set "TASK_NAME=AI_Job_Bot_Daily_Discovery"
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "MAIN_SCRIPT=%PROJECT_DIR%\main.py"

echo ==============================================================
echo       AI Job Agent — Windows Daily Task Scheduler Setup
echo ==============================================================
echo.
echo Project Directory: %PROJECT_DIR%
echo Python Path:       %PYTHON_EXE%
echo Main Script:       %MAIN_SCRIPT%
echo.

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment python.exe not found!
    echo Please create the virtual environment first:
    echo   python -m venv .venv
    pause
    exit /b 1
)

echo Configuring daily automated discovery at 09:00 AM...
echo (Discovered jobs are vetted and saved to job_bot.db for your dashboard review)
echo.

:: Create task in Task Scheduler using schtasks
schtasks /create /tn "%TASK_NAME%" /tr "\"%PYTHON_EXE%\" \"%MAIN_SCRIPT%\" --profile all --dry-run" /sc daily /st 09:00 /f

if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUCCESS] Daily task '%TASK_NAME%' scheduled successfully!
    echo It will run automatically every day at 09:00 AM.
    echo.
    echo You can check or run it manually at any time with:
    echo   schtasks /run /tn "%TASK_NAME%"
    echo.
    echo To remove this task later:
    echo   schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo.
    echo [WARNING] schtasks returned an error code.
    echo If prompted for administrative privileges, run this batch script as Administrator.
)

echo.
pause
