@echo off
setlocal
title SupaDiag - Setup e Configuracao de Coleta
cd /d "%~dp0"

echo =====================================================================
echo           SupaDiag - Painel de Setup e Gestao de Coleta
echo =====================================================================
echo.

if not exist "%~dp0venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual Python nao encontrado em .\venv
    echo Por favor, crie o ambiente virtual com:
    echo   python -m venv venv
    echo   .\venv\Scripts\activate
    echo   pip install -e .
    echo.
    pause
    exit /b 1
)

echo Iniciando o painel de Setup na porta 8501...
echo A interface abrira automaticamente no navegador: http://localhost:8501
echo Para encerrar o painel, pressione Ctrl+C nesta janela.
echo.

start "" "http://localhost:8501"

"%~dp0venv\Scripts\python.exe" -m streamlit run "%~dp0setup_app.py" --server.port 8501 --server.headless true --browser.gatherUsageStats false
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [AVISO] O painel de setup encerrou com codigo %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
