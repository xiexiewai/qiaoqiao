param(
    [string]$Python = '',
    [string]$IndexUrl = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Path $PSScriptRoot -Parent
$buildPython = Join-Path $projectRoot '.venv-build\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    if (-not $Python) {
        $Python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $Python)) {
        throw 'Pass -Python with the full path to a 64-bit Python 3.15 interpreter.'
    }
    & $Python -m venv (Join-Path $projectRoot '.venv-build')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated build environment.' }
}

$pipArgs = @('-m', 'pip', 'install', '-r', (Join-Path $projectRoot 'requirements-build.txt'))
$wheelCache = Join-Path $projectRoot 'work\wheels'
if (Test-Path -LiteralPath $wheelCache) {
    $runtimeWheels = @(Get-ChildItem -LiteralPath $wheelCache -Filter '*.whl')
    if ($runtimeWheels.Count -gt 0) {
        & $buildPython -m pip install --no-index --find-links $wheelCache -r (Join-Path $projectRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Wheel cache is incomplete; falling back to the package index.' }
    }
    $pipArgs += @('--find-links', $wheelCache)
}
if ($IndexUrl) { $pipArgs += @('--index-url', $IndexUrl) }
& $buildPython @pipArgs
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
& $buildPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies are inconsistent.' }
& $buildPython (Join-Path $PSScriptRoot 'build_release.py')
if ($LASTEXITCODE -ne 0) { throw 'Release build failed.' }
