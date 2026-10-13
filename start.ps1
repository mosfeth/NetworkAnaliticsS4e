$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$venvPath = Join-Path $PSScriptRoot 'venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$activateScript = Join-Path $venvPath 'Scripts\Activate.ps1'
$envPath = Join-Path $PSScriptRoot '.env'

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "Criando ambiente virtual do coletor em $venvPath..." -ForegroundColor Yellow
    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        & $pythonLauncher.Source -3 -m venv $venvPath
    } else {
        $systemPython = Get-Command python.exe -ErrorAction Stop
        & $systemPython.Source -m venv $venvPath
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'Falha ao criar o venv do coletor. Instale Python 3.10+ e tente novamente.'
    }
}

Write-Host 'Ativando o ambiente virtual do coletor...' -ForegroundColor Yellow
. $activateScript
Write-Host "venv do coletor ativo: $venvPath" -ForegroundColor Green

$moduleCheck = 'import importlib.util, sys; sys.exit(any(importlib.util.find_spec(name) is None for name in (''supadiag'', ''supabase'', ''dotenv'', ''httpx'')))'
& $venvPython -c $moduleCheck
$dependenciesMissing = $LASTEXITCODE -ne 0
if (-not $dependenciesMissing) {
    & $venvPython -m pip check
    $dependenciesMissing = $LASTEXITCODE -ne 0
}

if ($dependenciesMissing) {
    Write-Host 'Instalando dependências essenciais do coletor...' -ForegroundColor Yellow
    & $venvPython -m pip install -e $PSScriptRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Falha ao instalar as dependências do coletor. Consulte o erro do pip acima.'
    }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw 'O ambiente virtual do coletor ainda tem dependências incompatíveis.'
    }
} else {
    Write-Host 'Dependências essenciais do coletor instaladas e compatíveis.' -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw "Arquivo .env ausente. Copie .env.example para .env e configure as credenciais do Supabase: $envPath"
}

$activeMonitors = @()
try {
    $activeMonitors = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and
        $_.CommandLine -match '(?i)(-m\s+supadiag\s+monitor|supadiag\.exe\s+monitor)'
    })
} catch {
    Write-Warning "Não foi possível verificar se já existe outro coletor ativo: $($_.Exception.Message)"
}

if ($activeMonitors.Count -gt 0) {
    $ids = ($activeMonitors | ForEach-Object { $_.ProcessId }) -join ', '
    Write-Host "O coletor já está ativo (PID $ids). Nenhuma segunda instância foi iniciada." -ForegroundColor Yellow
    exit 0
}

Write-Host 'Iniciando somente o coletor. O dashboard é iniciado separadamente em FrontEnd/start.bat.' -ForegroundColor Green
Write-Host 'Mantenha esta janela aberta para acompanhar as medições. Use Ctrl+C para parar.' -ForegroundColor DarkGray
& $venvPython -m supadiag monitor
if ($LASTEXITCODE -ne 0) {
    throw "O coletor encerrou com código $LASTEXITCODE."
}
