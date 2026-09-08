@echo off
chcp 65001 > nul
echo App Usage Tracker を終了しています...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$procs = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*main.py*' }); if ($procs.Count -gt 0) { $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Write-Host ('停止しました（' + $procs.Count + ' プロセス）') } else { Write-Host 'App Usage Tracker は動作していません。' }"

pause
