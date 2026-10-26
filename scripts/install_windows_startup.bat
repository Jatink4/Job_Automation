@echo off
echo Installing AI Job Agent to Windows Startup folder (auto-runs on boot)...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_BAT=D:\project upload to github\Job_Automation\scripts\start_always.bat"

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP_DIR%\AI_Job_Agent.lnk'); $s.TargetPath = '%TARGET_BAT%'; $s.WorkingDirectory = 'D:\project upload to github\Job_Automation'; $s.WindowStyle = 7; $s.Save(); Write-Host '✓ Startup shortcut created successfully!' -ForegroundColor Green"

echo.
echo =========================================================================
echo  The agent is now installed in your Windows Startup folder!
echo  It will launch silently in the background whenever you log into Windows.
echo =========================================================================
pause
