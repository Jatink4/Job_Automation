<#
.SYNOPSIS
    Configures a daily Windows Task Scheduler task for AI Job Discovery.
.DESCRIPTION
    Creates a scheduled task that executes main.py with --dry-run and all 3 profiles
    every morning. Found matches are deposited into SQLite and presented on your
    Streamlit review dashboard without auto-submitting.
#>

[CmdletBinding()]
param(
    [string]$Time = "09:00",
    [string]$TaskName = "AI_Job_Bot_Daily_Discovery",
    [switch]$Uninstall
)

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$PythonExe = "$ProjectRoot\.venv\Scripts\python.exe"
$MainPy = "$ProjectRoot\main.py"

if ($Uninstall) {
    Write-Host "Unregistering scheduled task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task removed successfully." -ForegroundColor Green
    return
}

if (-not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment python.exe not found at '$PythonExe'. Please run 'python -m venv .venv' first."
    return
}

Write-Host "Creating Scheduled Task: $TaskName" -ForegroundColor Cyan
Write-Host "Trigger: Daily at $Time" -ForegroundColor Cyan
Write-Host "Action: $PythonExe $MainPy --profile all --dry-run" -ForegroundColor Cyan

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$MainPy`" --profile all --dry-run" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Daily AI Job Discovery in Review-Before-Submit Mode" -Force | Out-Null

Write-Host "`n[SUCCESS] Daily scheduled task '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host "Jobs discovered on daily runs will appear in your Streamlit dashboard for review." -ForegroundColor Green
Write-Host "To run immediately: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "To remove: .\scripts\schedule_task.ps1 -Uninstall" -ForegroundColor Yellow
