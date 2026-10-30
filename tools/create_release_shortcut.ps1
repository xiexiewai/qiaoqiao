param(
    [string]$ExecutablePath = '',
    [string]$ShortcutPath = ''
)

$ErrorActionPreference = 'Stop'
$appName = ([string][char]0x6572) + ([string][char]0x6572)
if (-not $ExecutablePath) {
    $ExecutablePath = Join-Path $PSScriptRoot ($appName + '.exe')
}
$executable = (Resolve-Path -LiteralPath $ExecutablePath).Path
if ([IO.Path]::GetExtension($executable) -ne '.exe') {
    throw 'ExecutablePath must point to the packaged application.'
}
if (-not $ShortcutPath) {
    $ShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) ($appName + '.lnk')
}
$shortcutFullPath = [IO.Path]::GetFullPath($ShortcutPath)
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutFullPath)
$shortcut.TargetPath = $executable
$shortcut.Arguments = ''
$shortcut.WorkingDirectory = Split-Path -Path $executable -Parent
$shortcut.IconLocation = $executable + ',0'
$shortcut.Description = 'Qiaoqiao - daily physical keyboard statistics'
$shortcut.Save()
Write-Output $shortcutFullPath
