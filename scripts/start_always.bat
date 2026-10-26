@echo off
echo Starting AI Job Agent and Telegram Bot in 24/7 background mode...
cd /d "D:\project upload to github\Job_Automation"

:: Stop existing instances first to avoid conflict
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

:: Start background process invisibly
powershell -Command "Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList 'main.py --watch --interval 60 --sites all' -WorkingDirectory 'D:\project upload to github\Job_Automation' -WindowStyle Hidden"

timeout /t 3 /nobreak >nul
echo.
echo ========================================================
echo  Agent is now running 24/7 in the background!
echo  Open your Telegram and send /status or /pending!
echo ========================================================
pause
