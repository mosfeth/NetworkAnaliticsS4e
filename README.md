# SupaDiag

Monitoramento de latência, jitter e perda de pacotes com Supabase, dashboard Streamlit e alertas em tempo real.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-1.60%2B-red)
![Supabase](https://img.shields.io/badge/Supabase-2.6%2B-green)

---

## Visão Geral

SupaDiag é uma ferramenta de monitoramento de rede que coleta métricas de latência, jitter e perda de pacotes de máquinas clientes, armazena no Supabase e exibe em um dashboard web interativo com alertas em tempo real.

### Arquitetura

```
┌─────────────────────────────────────────────────────┐
│                   SupaDiag CLI                       │
│  (supadiag monitor, check, schema, diary, service)   │
├──────────┬──────────┬──────────┬────────────────────┤
│  ICMP    │  Tracer  │  Alertas │  Queue Local       │
│  Ping    │  Route   │  Rules   │  pending_measure.  │
└────┬─────┴────┬─────┴────┬─────┴────┬───────────────┘
     │          │          │          │
     ▼          ▼          ▼          ▼
┌─────────────────────────────────────────────────────┐
│                   Supabase (Cloud)                   │
│  clients │ machines │ measurements │ traceroutes    │
│  alert_rules │ alert_events        │ (RLS enabled)  │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              FrontEnd Streamlit                      │
│  http://localhost:8502                               │
│  Cards │ Métricas │ Traceroute │ Alertas            │
└─────────────────────────────────────────────────────┘
```

---

## Funcionalidades

- **Monitoramento contínuo**: coleta ICMP (ping) com 4 amostras por máquina, medições de latência, jitter e perda de pacotes
- **Traceroute**: estilo PingPlotter com análise por hop (windows `tracert` + unix `traceroute`)
- **Dashboard Streamlit**: visualização interativa com gráficos Plotly, cards de máquinas e filtros
- **Alertas em tempo real**: regras configuráveis por máquina com thresholds warn/crit, notificações no dashboard
- **Agendador Windows**: serviço executa automaticamente na inicialização do sistema (em background)
- **Fila local com retry**: medições enfileiradas localmente com retry em caso de falha de rede
- **RLS no Supabase**: Row Level Security para service_role

---

## Pré-requisitos

- **Python 3.10+**
- **Windows** (sistema operacional)
- **Conta Supabase** com projeto configurado
- **PowerShell 5.1+** (incluído no Windows)

---

## Instalação Rápida

### 1. Configurar Supabase

Crie um projeto no [Supabase](https://supabase.com) e execute o script SQL:

```bash
# Copie o conteúdo de sql/001_schema.sql para o SQL Editor do Supabase
# e execute-o no seu projeto.
```

### 2. Configurar variáveis de ambiente

```bash
copy .env.example .env
```

Edite o arquivo `.env` com suas credenciais:

```env
SUPABASE_URL=https://SEU_PROJETO.supabase.co
SUPABASE_SERVICE_ROLE_KEY=SUA_CHAVE_SERVICE_ROLE
SUPADIAG_DATA_DIR=data
```

> **⚠️ Nunca exponha sua `SUPABASE_SERVICE_ROLE_KEY` em repositórios públicos.**

### 3. Inicializar

Clique duas vezes em `start.bat` (ou execute `./start.bat` no PowerShell). O launcher ativa o `venv` da raiz, libera as portas 8202 e 8502, verifica e instala dependências ausentes/incompatíveis, inicia o coletor em segundo plano e abre o dashboard em `http://127.0.0.1:8502`.

O monitor continua rodando em segundo plano enquanto o dashboard estiver aberto. O launcher não instala uma tarefa automática no Agendador do Windows; use `supadiag service install` separadamente se desejar isso.
---

## Configuração (.env)

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `SUPABASE_URL` | URL do projeto Supabase | _(obrigatório)_ |
| `SUPABASE_SERVICE_ROLE_KEY` | Chave service_role (NUNCA anon) | _(obrigatório)_ |
| `SUPADIAG_DATA_DIR` | Diretório para dados locais | `./data` |

---

## Comandos CLI

### INICIALIZAÇÃO

| Comando | Descrição |
|---------|-----------|
| `start.bat` | Inicializa o ambiente, verifica dependências e abre o dashboard |
| `start.ps1` | Implementação PowerShell do launcher principal |

### DASHBOARD / INTERFACE

| Comando | Descrição |
|---------|-----------|
| `start.bat` | FrontEnd Streamlit em `http://127.0.0.1:8502` |

### VERIFICAÇÃO

| Comando | Descrição |
|---------|-----------|
| `supadiag check` | Testa conexão com Supabase |
| `supadiag schema` | Mostra script SQL de migração |

### CLIENTES (CRUD)

| Comando | Descrição |
|---------|-----------|
| `supadiag client add --name "Nome"` | Cria novo cliente |
| `supadiag client list` | Lista todos os clientes |
| `supadiag client update --id UUID --name "Novo Nome"` | Atualiza cliente |
| `supadiag client delete --id UUID` | Remove cliente (cascade: máquinas + medições) |

### MÁQUINAS (CRUD)

| Comando | Descrição |
|---------|-----------|
| `supadiag machine add --client-id UUID --tag "TAG" --ip "IP" --frequency SEGUNDOS` | Cadastra máquina |
| `supadiag machine list` | Lista máquinas |
| `supadiag machine update --id UUID [--tag TAG] [--ip IP] [--frequency N]` | Atualiza máquina |
| `supadiag machine delete --id UUID` | Remove máquina |

### MONITORAMENTO

| Comando | Descrição |
|---------|-----------|
| `supadiag monitor` | Monitoramento contínuo |
| `supadiag monitor --once` | Executa um ciclo de coleta |
| `supadiag monitor --cycles N` | Executa N ciclos |

### SERVIÇO (AGENDADOR DE TAREFAS)

| Comando | Descrição |
|---------|-----------|
| `supadiag service status` | Verifica se tarefa está instalada |
| `supadiag service install` | Instala no Agendador (inicia na inicializacao) |
| `supadiag service remove` | Remove do Agendador |

### DIÁRIO

| Comando | Descrição |
|---------|-----------|
| `supadiag diary [--lines N]` | Mostra últimas N linhas do memory.txt |

---

## FrontEnd Dashboard

O FrontEnd é um dashboard Streamlit separado que roda na **porta 8502** e oferece:

### Visão Geral (Cards)
- Grid de cards com status das máquinas (🟢 OK, 🟡 Parcial, 🔴 Crítico)
- Resumo: Total, OK, Parcial, Crítico, Sem dados, Alertas ativos
- Badges de alerta nos cards

### Detail View (Detalhes da Máquina)
- Métricas atuais: Latência, Jitter, Perda de Pacotes, Status
- Abas interativas:
  - **📊 Métricas**: Gráficos Plotly com histórico, presets de período, tabela de medições
  - **🔍 Traceroute**: Gráfico estilo PingPlotter com hops e histórico
  - **🔔 Alertas**: Status de alertas ativos, reconhecimento e histórico completo

### Sidebar
- Filtro por cliente
- Auto-atualizar (30s)
- Painel de alertas ativos

### Solução de Problemas

Se ao clicar em um card aparecer erro `Failed to fetch dynamically imported module`:

1. **Limpe o cache do navegador** para `localhost:8502`:
   - Chrome: `Ctrl+Shift+Delete` → "Imagens e arquivos em cache" → Limpar
   - Ou abra em **modo anônimo** (`Ctrl+Shift+N`)
2. **Atualize forçadamente** a página: `Ctrl+Shift+R`
3. Se persistir, **reinicie o Streamlit**: feche todas as janelas e execute `.\start.ps1` novamente

---

## Sistema de Alertas

### Como Funciona

1. O serviço de monitoramento avalia regras de alerta periodicamente (padrão: a cada 300s)
2. Para cada máquina ativa, verifica regras habilitadas (latência, loss, jitter)
3. Se uma métrica excede o **threshold_warn** → alerta como `firing`
4. Se excede o **threshold_crit** → alerta como `critical`
5. Quando o valor volta ao normal → alerta é `resolved`
6. **Cooldown** de 900s evita disparos repetidos
7. Usuários podem **reconhecer** alertas no dashboard

### Tabelas de Alertas no Supabase

- `alert_rules` — regras por máquina com thresholds warn/crit, métrica, evaluation_window, cooldown
- `alert_events` — eventos com status (firing, acknowledged, resolved), severidade, valores, timestamps

---

## Banco de Dados (Supabase)

### Tabelas

| Tabela | Descrição |
|--------|-----------|
| `clients` | Clientes cadastrados |
| `machines` | Máquinas monitoradas por cliente |
| `measurements` | Medições ICMP (latência, jitter, loss, status) |
| `traceroutes` | Resultados de traceroute por máquina |
| `traceroute_hops` | Detalhes por hop do traceroute |
| `alert_rules` | Regras de alerta por máquina |
| `alert_events` | Eventos de alerta disparados |

### Segurança

- **RLS habilitado** em todas as tabelas
- Acesso via `service_role` (API key) para leitura/escrita completa

### Índices Principais

- `idx_measurements_machine` — buscas por máquina
- `idx_measurements_measured_at` — ordenação temporal
- `idx_alert_events_machine` — eventos por máquina
- `idx_alert_events_status` — filtragem por status

---

## Estrutura do Projeto

```
SupaDiag/
├── FrontEnd/                    # Dashboard Streamlit (porta 8502)
│   ├── app.py                   # Dashboard principal
│   ├── components.py            # Componentes UI (cards, gráficos, alertas)
│   ├── repository.py            # Acesso a dados Supabase
│   ├── config.py                # Configurações
│   ├── start.bat              # Launcher isolado Streamlit
│   └── requirements.txt
├── src/supadiag/                # Módulos principais
│   ├── cli.py                   # CLI (supadiag)
│   ├── monitor.py               # Serviço de monitoramento
│   ├── icmp.py                  # Coleta ICMP
│   ├── traceroute.py            # Parser traceroute
│   ├── scheduler.py             # Agendador Windows
│   ├── queue.py                 # Fila local com retry
│   ├── supabase_repository.py   # Acesso a dados Supabase
│   ├── config.py                # Configurações
│   ├── models.py                # Modelos de dados
│   ├── diary.py                 # Diário de atividades
│   └── tui.py                   # TUI Textual
├── sql/001_schema.sql           # Migração SQL
├── tests/                       # Testes
├── .env.example                 # Exemplo de configuração
├── .env                         # Configuração local (não versionado)
├── .gitignore
├── pyproject.toml               # Dependências
├── start.bat / start.ps1        # Launcher
└── memory.txt                   # Diário do projeto
```

---

## Desenvolvimento

### Testes

```bash
pytest
```

### Dependências

```bash
pip install -e ".[dev]"
```

### Configurar Ambiente Virtual

```bash
python -m venv venv
.\venv\Scripts\activate
pip install -e ".[dev]"
```

---

## Fluxo Típico

1. Edite `.env` com credenciais do Supabase
2. Execute `.\start.ps1` (abre monitor em background + dashboard)
3. No dashboard Streamlit (`http://localhost:8502`): Adicione Clientes → Adicione Máquinas
4. O monitor coleta automaticamente conforme frequência de cada máquina
5. Acompanhe métricas em Métricas | Traceroute | Alertas
6. Configure regras de alerta conforme necessidade

---

## Licença

MIT

