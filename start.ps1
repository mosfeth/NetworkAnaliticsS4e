$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Stop-ListenerOnPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    $netstatLines = @(& netstat.exe -ano -p tcp 2>$null)
    $ownerIds = @($netstatLines | ForEach-Object {
        if ($_ -match ('^\s*TCP\s+\S+:' + $Port + '\s+\S+\s+LISTENING\s+(\d+)\s*$')) {
            [int]$Matches[1]
        }
    } | Sort-Object -Unique)

    if ($ownerIds.Count -eq 0) {
        Write-Host "Porta $Port livre." -ForegroundColor Green
        return
    }

    foreach ($ownerId in $ownerIds) {
        if (-not $ownerId -or $ownerId -eq $PID) { continue }
        $process = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        Write-Host "Liberando porta $Port (PID $ownerId, $($process.ProcessName))..." -ForegroundColor Yellow
        Stop-Process -Id $ownerId -Force -ErrorAction Stop
    }

    $deadline = (Get-Date).AddSeconds(5)
    do {
        Start-Sleep -Milliseconds 250
        $remaining = @(& netstat.exe -ano -p tcp 2>$null | Where-Object {
            $_ -match ('^\s*TCP\s+\S+:' + $Port + '\s+\S+\s+LISTENING\s+\d+\s*$')
        })
    } while ($remaining.Count -gt 0 -and (Get-Date) -lt $deadline)

    if ($remaining.Count -gt 0) {
        throw "Não foi possível liberar a porta $Port. Feche o aplicativo que a está usando e tente novamente."
    }
    Write-Host "Porta $Port liberada." -ForegroundColor Green
}
$venvPath = Join-Path $PSScriptRoot 'venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "Criando ambiente virtual em .\venv..." -ForegroundColor Yellow
    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        & $pythonLauncher.Source -3 -m venv $venvPath
    } else {
        $systemPython = Get-Command python.exe -ErrorAction Stop
        & $systemPython.Source -m venv $venvPath
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw "Falha ao criar o ambiente virtual. Instale Python 3.10+ e tente novamente."
    }
}

Write-Host "Ativando o ambiente virtual..." -ForegroundColor Yellow
. (Join-Path $venvPath 'Scripts\Activate.ps1')
if ($env:VIRTUAL_ENV -ne $venvPath) {
    $env:VIRTUAL_ENV = $venvPath
}
Write-Host "venv ativo: $env:VIRTUAL_ENV" -ForegroundColor Green

# 8202 foi solicitada e 8502 é a porta efetiva do dashboard.
Stop-ListenerOnPort -Port 8202
Stop-ListenerOnPort -Port 8502

$moduleCheck = 'import importlib.util, sys; modules = (''supadiag'', ''streamlit'', ''supabase'', ''dotenv'', ''plotly'', ''pandas'', ''streamlit_autorefresh'', ''numpy'', ''torch'', ''sklearn'', ''fastai''); sys.exit(any(importlib.util.find_spec(name) is None for name in modules))'
Write-Host "Verificando dependências do dashboard e da IA..." -ForegroundColor Yellow
& $venvPython -c $moduleCheck
$dependenciesMissing = $LASTEXITCODE -ne 0
if (-not $dependenciesMissing) {
    & $venvPython -m pip check
    $dependenciesMissing = $LASTEXITCODE -ne 0
}

if ($dependenciesMissing) {
    $requirementsPath = Join-Path $PSScriptRoot 'requirements.txt'
    if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
        throw "O arquivo consolidado de dependências não foi encontrado: $requirementsPath"
    }

    Write-Host "Instalando/ajustando dependências no venv..." -ForegroundColor Yellow
    Write-Host "Usando lista consolidada: $requirementsPath" -ForegroundColor DarkGray
    & $venvPython -m pip install -e '.[ai]' -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "A instalação falhou. Consulte o erro do pip acima (lista: $requirementsPath)."
    }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "O ambiente virtual ainda tem dependências incompatíveis."
    }
} else {
    Write-Host "Todas as dependências estão instaladas e compatíveis." -ForegroundColor Green
}

# Repete a limpeza após a instalação, caso algum processo tenha ocupado a porta.
Stop-ListenerOnPort -Port 8202
Stop-ListenerOnPort -Port 8502

$streamlitConfigPath = Join-Path $PSScriptRoot 'data\streamlit_config'
New-Item -ItemType Directory -Force -Path $streamlitConfigPath | Out-Null
$env:STREAMLIT_CONFIG_DIR = $streamlitConfigPath
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'

$dashboardPath = Join-Path $PSScriptRoot 'FrontEnd\app.py'
if (-not (Test-Path -LiteralPath $dashboardPath -PathType Leaf)) {
    $legacyDashboardPath = Join-Path $PSScriptRoot 'dashboard.py'
    if (Test-Path -LiteralPath $legacyDashboardPath -PathType Leaf) {
        Write-Warning "FrontEnd\app.py não está nesta cópia do projeto. Usando dashboard.py (compatibilidade); atualize os arquivos do projeto para recuperar a interface completa."
        $dashboardPath = $legacyDashboardPath
    } else {
        throw "Dashboard não encontrado. Esperado: $(Join-Path $PSScriptRoot 'FrontEnd\app.py')"
    }
}

$monitorProcesses = @()
try {
    $monitorProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.CommandLine -and $_.CommandLine -match 'supadiag(\.exe)?\s+monitor'
    })
} catch {
    Write-Warning "Não foi possível consultar processos de monitor já ativos: $($_.Exception.Message)"
}
if ($monitorProcesses.Count -eq 0) {
    Write-Host "Iniciando o coletor de rede em segundo plano..." -ForegroundColor Yellow
    Start-Process -WindowStyle Hidden -FilePath $venvPython `
        -ArgumentList @('-m', 'supadiag', 'monitor') `
        -WorkingDirectory $PSScriptRoot
} else {
    Write-Host "Coletor de rede já está ativo." -ForegroundColor Green
}

Write-Host "Iniciando o dashboard em http://127.0.0.1:8502 ..." -ForegroundColor Green
& $venvPython -m streamlit run $dashboardPath `
    --server.address 127.0.0.1 `
    --server.port 8502 `
    --server.headless true `
    --browser.gatherUsageStats false

if ($LASTEXITCODE -ne 0) {
    throw "O dashboard encerrou com código $LASTEXITCODE."
}



