@echo off
echo Checking background AI Job Agent status...
powershell -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' }; if ($p) { Write-Host ('🟢 Agent is RUNNING (PID: ' + ($p.ProcessId -join ', ') + ')') -ForegroundColor Green } else { Write-Host '🔴 Agent is NOT running.' -ForegroundColor Red }"
echo.
echo Recent log activity:
powershell -Command "if (Test-Path 'bot.log') { Get-Content 'bot.log' -Tail 10 } else { Write-Host 'No bot.log found yet.' }"
pause
