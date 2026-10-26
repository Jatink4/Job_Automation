Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\project upload to github\Job_Automation"
WshShell.Run """D:\project upload to github\Job_Automation\.venv\Scripts\python.exe"" main.py --watch --interval 60 --sites all", 0, False
