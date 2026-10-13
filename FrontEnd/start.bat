@echo off
setlocal
cd /d "%~dp0"
echo Iniciando somente o dashboard SupaDiag...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "START_EXIT_CODE=%ERRORLEVEL%"
if not "%START_EXIT_CODE%"=="0" (
    echo.
    echo O dashboard nao conseguiu iniciar. Consulte a mensagem acima.
    pause
)
exit /b %START_EXIT_CODE%
