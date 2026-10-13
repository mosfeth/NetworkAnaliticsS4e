# install_deps.ps1 - Instala/atualiza dependencias do SupaDiag no venv

Set-Location $PSScriptRoot

Write-Host "=========================================="
Write-Host "  SupaDiag - Instalacao de Dependencias"
Write-Host "=========================================="
Write-Host ""

# 1. Verifica/cria ambiente virtual
if (-not (Test-Path "venv")) {
    Write-Host "[1/3] Criando ambiente virtual (venv)..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ERRO: Falha ao criar venv. Verifique se Python 3.10+ esta no PATH."
        Read-Host "Pressione Enter para sair"
        exit 1
    }
} else {
    Write-Host "[1/3] Ambiente virtual ja existe."
}

# 2. Ativa venv e atualiza pip
Write-Host "[2/3] Ativando venv e atualizando pip..."
. venv\Scripts\Activate.ps1
Write-Host "Ambiente virtual ativado."
python -m pip install --upgrade pip >$null 2>&1

# 3. Instala dependencias
Write-Host "[3/3] Instalando dependencias do projeto..."
pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Error "ERRO: Falha na instalacao das dependencias."
    Read-Host "Pressione Enter para sair"
    exit 1
}

Write-Host ""
Write-Host "=========================================="
Write-Host "  Dependencias instaladas com sucesso!"
Write-Host "=========================================="
Write-Host ""
Write-Host "Para iniciar o coletor: .\start.bat"
Write-Host "Para iniciar o dashboard em outra maquina: FrontEnd\start.bat"
Write-Host "Para ajuda: supadiag --help"
Write-Host ""
Read-Host "Pressione Enter para sair"
