$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$frontendPath = $PSScriptRoot
$projectRoot = Split-Path -Parent $frontendPath
$appPath = Join-Path $frontendPath 'app.py'
$requirementsPath = Join-Path $frontendPath 'requirements.txt'
$projectFile = Join-Path $projectRoot 'pyproject.toml'
$localEnvPath = Join-Path $frontendPath '.env'
$rootEnvPath = Join-Path $projectRoot '.env'
$venvPath = Join-Path $frontendPath 'venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $appPath -PathType Leaf)) {
    throw "Dashboard não encontrado: $appPath"
}
if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    throw "Lista de dependências do dashboard não encontrada: $requirementsPath"
}
if (-not (Test-Path -LiteralPath $projectFile -PathType Leaf)) {
    throw "Esta distribuição precisa incluir FrontEnd e pyproject.toml para instalar os módulos de IA: $projectRoot"
}
if (-not (Test-Path -LiteralPath $localEnvPath -PathType Leaf) -and -not (Test-Path -LiteralPath $rootEnvPath -PathType Leaf)) {
    throw "Arquivo .env ausente. Configure FrontEnd\.env (recomendado) ou .env na raiz com as credenciais do Supabase."
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "Criando ambiente virtual exclusivo do dashboard em $venvPath..." -ForegroundColor Yellow
    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        & $pythonLauncher.Source -3 -m venv $venvPath
    } else {
        $systemPython = Get-Command python.exe -ErrorAction Stop
        & $systemPython.Source -m venv $venvPath
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'Falha ao criar o venv do dashboard. Instale Python 3.10+ e tente novamente.'
    }
}

Write-Host 'Ativando o ambiente virtual exclusivo do dashboard...' -ForegroundColor Yellow
. (Join-Path $venvPath 'Scripts\Activate.ps1')
Write-Host "venv do dashboard ativo: $venvPath" -ForegroundColor Green

$moduleCheck = 'import importlib.util, sys; modules = (''streamlit'', ''streamlit_autorefresh'', ''supabase'', ''dotenv'', ''plotly'', ''pandas'', ''numpy'', ''torch'', ''sklearn'', ''supadiag''); sys.exit(any(importlib.util.find_spec(name) is None for name in modules))'
& $venvPython -c $moduleCheck
$dependenciesMissing = $LASTEXITCODE -ne 0
if (-not $dependenciesMissing) {
    & $venvPython -m pip check
    $dependenciesMissing = $LASTEXITCODE -ne 0
}

if ($dependenciesMissing) {
    Write-Host 'Instalando dependências do dashboard e da previsão de qualidade...' -ForegroundColor Yellow
    $projectWithAi = "$projectRoot[ai]"
    & $venvPython -m pip install -e $projectWithAi -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Falha ao instalar dependências do dashboard. Consulte o erro do pip acima.'
    }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw 'O ambiente virtual do dashboard ainda tem dependências incompatíveis.'
    }
} else {
    Write-Host 'Dependências do dashboard instaladas e compatíveis.' -ForegroundColor Green
}

function Stop-ListenerOnPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    $netstatLines = @(& netstat.exe -ano -p tcp 2>$null)
    $ownerIds = @($netstatLines | ForEach-Object {
        if ($_ -match ('^\s*TCP\s+\S+:' + $Port + '\s+\S+\s+LISTENING\s+(\d+)\s*$')) {
            [int]$Matches[1]
        }
    } | Sort-Object -Unique)

    foreach ($ownerId in $ownerIds) {
        if (-not $ownerId -or $ownerId -eq $PID) { continue }
        $process = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        Write-Host "Liberando porta $Port (PID $ownerId, $($process.ProcessName))..." -ForegroundColor Yellow
        Stop-Process -Id $ownerId -Force -ErrorAction Stop
    }

    if ($ownerIds.Count -eq 0) {
        Write-Host "Porta $Port livre." -ForegroundColor Green
        return
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

Stop-ListenerOnPort -Port 8502

$streamlitConfigPath = Join-Path $frontendPath 'data\streamlit_config'
New-Item -ItemType Directory -Force -Path $streamlitConfigPath | Out-Null
$env:STREAMLIT_CONFIG_DIR = $streamlitConfigPath
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
$env:PYTHONUNBUFFERED = '1'

Write-Host 'Iniciando somente o dashboard em http://127.0.0.1:8502 ...' -ForegroundColor Green
& $venvPython -m streamlit run $appPath `
    --server.address 127.0.0.1 `
    --server.port 8502 `
    --server.headless true `
    --browser.gatherUsageStats false

if ($LASTEXITCODE -ne 0) {
    throw "O dashboard encerrou com código $LASTEXITCODE."
}
