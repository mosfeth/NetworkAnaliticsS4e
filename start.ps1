# start.ps1 - Inicia o SupaDiag (monitor + servico agendado)
# Verifica venv, dependencias, servico no Agendador de Tarefas e inicia o monitor + dashboard Streamlit
# Baixa e instala Python automaticamente se nao estiver presente

Set-Location $PSScriptRoot

Write-Host "=========================================="
Write-Host "  SupaDiag - Inicializacao"
Write-Host "=========================================="
Write-Host ""

# Funcao: Verifica e instala Python se necessario
function Ensure-Python {
    $minVersion = "3.10"
    $pythonUrl = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
    $installerPath = "$env:TEMP\python-installer.exe"

    Write-Host "[0/6] Verificando Python..."
    try {
        $versionOutput = python --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $versionOutput -match "Python\s+(\d+\.\d+)") {
            $version = [version]$matches[1]
            $min = [version]$minVersion
            if ($version -ge $min) {
                Write-Host "Python $version encontrado (>= $minVersion). OK."
                return
            }
        }
    } catch {}

    Write-Host "Python $minVersion+ nao encontrado. Baixando instalador oficial..."
    try {
        Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath -UseBasicParsing
        Write-Host "Instalando Python (silencioso, para todos os usuarios)..."
        $args = "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0"
        $proc = Start-Process -FilePath $installerPath -ArgumentList $args -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            Write-Error "Falha ao instalar Python (codigo $($proc.ExitCode)). Instale manualmente em python.org"
            Read-Host "Pressione Enter para sair"
            exit 1
        }
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        Write-Host "Python instalado com sucesso."
    } catch {
        Write-Error "Erro ao baixar/instalar Python: $_"
        Write-Host "Baixe manualmente em: https://www.python.org/downloads/"
        Read-Host "Pressione Enter para sair"
        exit 1
    } finally {
        if (Test-Path $installerPath) { Remove-Item $installerPath -Force -ErrorAction SilentlyContinue }
    }
}

# 0. Garante Python
Ensure-Python

# 1. Verifica/cria ambiente virtual
if (-not (Test-Path "venv")) {
    Write-Host "[1/6] Criando ambiente virtual (venv)..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ERRO: Falha ao criar venv. Verifique se Python 3.10+ esta no PATH."
        Read-Host "Pressione Enter para sair"
        exit 1
    }
} else {
    Write-Host "[1/6] Ambiente virtual ja existe."
}

# 2. Ativa venv
Write-Host "[2/6] Ativando ambiente virtual..."
. venv\Scripts\Activate.ps1
Write-Host "Ambiente virtual ativado."

# 2.5. Mata processos supadiag.exe se estiverem rodando (evita erro WinError 32 ao reinstalar)
Write-Host "[2.5/6] Verificando processos supadiag.exe em execucao..."
$supadiagProcesses = Get-Process -Name "supadiag" -ErrorAction SilentlyContinue
if ($supadiagProcesses) {
    Write-Host "Encontrado(s) $($supadiagProcesses.Count) processo(s) supadiag.exe. Finalizando..."
    $supadiagProcesses | Stop-Process -Force
    Start-Sleep -Seconds 1
}

# Refresca PATH apos ativacao do venv
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + $env:Path
$env:Path = $PSScriptRoot + "\venv\Scripts;" + $env:Path

# 3. Instala/atualiza dependencias
Write-Host "[3/6] Verificando/Instalando dependencias..."
pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Error "ERRO: Falha ao instalar dependencias. Verifique se o pyproject.toml existe e ha conexao de rede."
    Read-Host "Pressione Enter para sair"
    exit 1
} else {
    Write-Host "Dependencias OK."
}
# Refresca PATH apos instalacao (Windows precisa disso para reconhecer novos comandos)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + $env:Path
if (Test-Path "venv\Scripts") { $env:Path = $PSScriptRoot + "\venv\Scripts;" + $env:Path }

# 4. Verifica arquivo .env
Write-Host "[4/6] Verificando configuracao (.env)..."
if (-not (Test-Path ".env")) {
    Write-Warning "AVISO: Arquivo .env nao encontrado. Copiando de .env.example..."
    Copy-Item .env.example .env
    Write-Host "EDITE o arquivo .env com suas credenciais do Supabase antes de continuar."
    Read-Host "Pressione Enter para continuar"
}

# 5. Verifica/instala servico no Agendador de Tarefas
Write-Host "[5/6] Verificando servico no Agendador de Tarefas..."
$supadiagCmd = if (Get-Command supadiag -ErrorAction SilentlyContinue) { "supadiag" } else { "python -m supadiag" }
& $supadiagCmd service status >$null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Servico nao encontrado. Instalando..."
    & $supadiagCmd service install
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ERRO: Falha ao instalar servico no Agendador de Tarefas."
        Write-Host "Verifique se esta rodando como Administrador se necessario."
        Read-Host "Pressione Enter para sair"
        exit 1
    }
    Write-Host "Servico instalado com sucesso (executa na inicializacao do sistema)."
} else {
    Write-Host "Servico ja instalado."
}

# 6. Verifica Streamlit
Write-Host "[6/6] Verificando Streamlit..."
python -c "import streamlit" >$null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando Streamlit..."
    pip install streamlit
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ERRO: Falha ao instalar Streamlit."
        Read-Host "Pressione Enter para sair"
        exit 1
    }
}
Write-Host "Streamlit OK."

Write-Host ""
Write-Host "=========================================="
Write-Host "  Iniciando SupaDiag"
Write-Host "=========================================="
Write-Host ""

# Testa conexao Supabase antes de iniciar
& $supadiagCmd check
if ($LASTEXITCODE -ne 0) {
    Write-Warning "AVISO: Conexao com Supabase falhou. Verifique .env e rede."
    Write-Host "O monitor tentara reconectar automaticamente."
    Write-Host ""
}

# Inicia monitor em background oculto - pode fechar esta janela, continua rodando
$venvPython = if (Test-Path "venv\Scripts\python.exe") { "$PSScriptRoot\venv\Scripts\python.exe" } else { "python" }
Write-Host "Iniciando coleta de metricas (monitor) em background..."
Start-Process "cmd.exe" -ArgumentList "/c", "$venvPython -m supadiag monitor" -WindowStyle Hidden

# Abre dashboard Streamlit em outra janela (pode fechar quando nao precisar)
Write-Host "Abrindo dashboard Streamlit (http://localhost:8501)..."
Start-Process "cmd.exe" -ArgumentList "/c", "streamlit run dashboard.py --server.port 8501 --server.headless true" -WindowStyle Normal

Write-Host ""
Write-Host "SupaDiag iniciado com sucesso!"
Write-Host ""
Write-Host "- Monitor rodando em background (feche as janelas, continua coletando)"
Write-Host "- Dashboard Streamlit: http://localhost:8501 (pode fechar)"
Write-Host "- Servico agendado no Windows Task Scheduler (inicia na inicializacao)"
Write-Host "- Ver diario: supadiag diary"
Write-Host "- Parar monitor: supadiag service remove ou feche o processo"
Write-Host ""
Read-Host "Pressione Enter para sair"