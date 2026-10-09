# FrontEnd Start Script - usa venv isolado
# Limpa instancias duplicadas antes de iniciar

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SupaDiag - Iniciando..." -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# 1. Mata processos na porta 8502
Write-Host "`n[1/4] Verificando porta 8502..." -ForegroundColor Yellow
$port8502 = netstat -ano | Select-String ":8502"
if ($port8502) {
    foreach ($conn in $port8502) {
        if ($conn -match '(\d+)\s*$') {
            $pid = $Matches[1]
            Write-Host "  Matando processo na porta 8502: PID $pid" -ForegroundColor Red
            taskkill /PID $pid /F 2>$null
            Start-Sleep -Seconds 1
        }
    }
} else {
    Write-Host "  Porta 8502 livre" -ForegroundColor Green
}

# 2. Mata monitores duplicados (mantem apenas 1)
Write-Host "`n[2/4] Verificando monitores..." -ForegroundColor Yellow
$monitorProcs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*supadiag monitor*' -and $_.CommandLine -notlike '*powershell*' }
$monitorCount = ($monitorProcs | Measure-Object).Count
if ($monitorCount -gt 1) {
    Write-Host "  Encontrados $monitorCount monitores. Mantendo apenas 1..." -ForegroundColor Yellow
    $monitorsToKill = $monitorProcs | Select-Object -Skip 1
    foreach ($m in $monitorsToKill) {
        Write-Host "  Matando monitor duplicado: PID $($m.ProcessId)" -ForegroundColor Red
        taskkill /PID $m.ProcessId /F 2>$null
    }
    Start-Sleep -Seconds 1
} else {
    Write-Host "  Apenas 1 monitor encontrado (ou nenhum)" -ForegroundColor Green
}

# 3. Inicia monitor se nao estiver rodando
Write-Host "`n[3/4] Verificando se monitor esta rodando..." -ForegroundColor Yellow
$monitorProcs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*supadiag monitor*' -and $_.CommandLine -notlike '*powershell*' }
if (($monitorProcs | Measure-Object).Count -eq 0) {
    Write-Host "  Iniciando monitor..." -ForegroundColor Green
    $venvPython = Join-Path $PSScriptRoot "..\venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        $venvPython = "python"
    }
    Start-Process -NoNewWindow -FilePath $venvPython -ArgumentList "-m supadiag monitor"
    Start-Sleep -Seconds 2
} else {
    Write-Host "  Monitor ja rodando (PID $($monitorProcs[0].ProcessId))" -ForegroundColor Green
}

# 4. Inicia FrontEnd
Write-Host "`n[4/4] Iniciando FrontEnd na porta 8502..." -ForegroundColor Green
Set-Location $PSScriptRoot
& ".\venv\Scripts\Activate.ps1"
python -m streamlit run app.py --server.port 8502 --server.headless true
