$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$pythonwPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) {
    throw 'Python environment missing. See README.md for setup.'
}
$linkName = ([string][char]0x6572) + ([string][char]0x6572) + '-Dev.lnk'
$shortcutPath = Join-Path $projectRoot $linkName
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '"' + (Join-Path $projectRoot 'run.py') + '" --dev'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = (Join-Path $projectRoot 'assets\qiaoqiao.ico') + ',0'
$shortcut.Description = 'Qiaoqiao development - isolated test data'
$shortcut.WindowStyle = 1
$shortcut.Save()
Write-Output $shortcutPath
