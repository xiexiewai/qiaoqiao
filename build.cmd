@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Resolve the project from this file, including paths with spaces or another drive.
pushd "%~dp0"
if errorlevel 1 (
    echo [ERROR] Could not open the project directory.
    pause
    exit /b 1
)

echo Building Qiaoqiao. Please keep this window open.
echo.
rem Reuse all existing checks and forward optional -Python / -IndexUrl arguments.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build.ps1" %*
set "buildExitCode=%ERRORLEVEL%"
echo.
if "%buildExitCode%"=="0" (
    echo [SUCCESS] Build completed.
    echo Release files: "%~dp0releases"
) else (
    echo [ERROR] Build failed with exit code %buildExitCode%. See the output above.
)
popd

rem Keep diagnostics visible after a double-click without losing the build exit code.
pause
exit /b %buildExitCode%
