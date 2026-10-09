# FrontEnd/app.py
# Dashboard Principal - AI Network Analyzer

import streamlit as st
from streamlit_autorefresh import st_autorefresh
from typing import Optional
import pandas as pd
from datetime import datetime
import subprocess
import os

from config import settings
from repository import FrontendRepository, RepositoryError
from components import (
    render_client_card,
    render_machine_card,
    render_metrics_charts,
    render_sidebar_filters,
    render_status_badge,
    render_traceroute_tab,
    render_alert_tab,
    render_device_status_events,
)

# Configuração da página
st.set_page_config(
    page_title=settings.PAGE_TITLE,
    page_icon=settings.PAGE_ICON,
    layout=settings.LAYOUT,
    initial_sidebar_state="expanded",
)

# CSS customizado
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        font-weight: 800;
        color: #1f77b4;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        border-radius: 12px;
        padding: 20px;
        margin: 10px 0;
    }
    .stButton > button {
        border-radius: 8px;
        font-weight: 500;
    }
    div[data-testid="stHorizontalBlock"] > div {
        padding: 0 8px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_repository() -> FrontendRepository:
    """Inicializa repositório (cached)."""
    return FrontendRepository()


@st.cache_data(ttl=30)
def _cached_clients_summary():
    """Cache de clientes com máquinas (rede local + internet)."""
    repo = get_repository()
    return repo.get_clients_with_machines_summary()


@st.cache_data(ttl=30)
def _cached_measurements(machine_id: str, hours: int, limit: int):
    repo = get_repository()
    return repo.get_measurements(machine_id, hours=hours, limit=limit)


@st.cache_data(ttl=60)
def _cached_accuracy_data(machine_id: str):
    try:
        from supabase import create_client
        from config import settings as fe_settings
        sb = create_client(fe_settings.SUPABASE_URL, fe_settings.SUPABASE_KEY)
        feedbacks = sb.table("machine_feedback").select("*").eq("machine_id", machine_id).order("created_at", desc=True).limit(100).execute().data or []
        return feedbacks
    except Exception:
        return []


@st.cache_data(ttl=30)
def _cached_machine_feedback(limit: int):
    repo = get_repository()
    return repo.list_machine_feedback(limit=limit)


@st.cache_data(ttl=30)
def _cached_sidebar_events():
    repo = get_repository()
    return get_sidebar_events(repo, 30)


@st.cache_data(ttl=60)
def _cached_ai_feedbacks():
    try:
        from supabase import create_client
        from config import settings as fe_settings
        sb = create_client(fe_settings.SUPABASE_URL, fe_settings.SUPABASE_KEY)
        feedbacks = sb.table("machine_feedback").select("machine_id, label, packet_loss_percent, latency_ms, jitter_ms, created_at").order("created_at", desc=True).limit(15).execute().data or []
        return feedbacks
    except Exception:
        return []


@st.cache_data(ttl=30)
def _cached_sidebar_alerts():
    repo = get_repository()
    alerts = []
    try:
        active_alerts = repo.list_alert_rules()
        if active_alerts:
            for rule in active_alerts[:5]:
                machine_tag = rule.get("machine_tag", "")
                machine_id = rule.get("machine_id", "")
                if machine_id:
                    machine = repo.get_machine(machine_id)
                    machine_tag = machine.tag if machine else machine_id[:8]
                event = repo.get_active_alert_event(rule.get("id", ""))
                if event:
                    severity = event.get("severity", "warning")
                    metric = event.get("metric", "")
                    value = event.get("metric_value", 0)
                    if severity == "critical" or event.get("status") == "firing":
                        icon = "[CRITICAL]"
                    elif severity == "warning":
                        icon = "[WARNING]"
                    else:
                        icon = "[ACK]"
                    alerts.append((machine_tag, icon, metric, value, severity))
    except Exception:
        pass
    return alerts


def init_session_state() -> None:
    """Inicializa estado da sessão."""
    if "selected_client_id" not in st.session_state:
        st.session_state.selected_client_id = None
    if "selected_machine_id" not in st.session_state:
        st.session_state.selected_machine_id = None
    if "view_mode" not in st.session_state:
        st.session_state.view_mode = "cards"  # "cards" ou "detail"


def on_machine_click(machine_id: str) -> None:
    """Callback ao clicar em um card de máquina (compatibilidade)."""
    st.session_state.selected_machine_id = machine_id
    st.session_state.view_mode = "detail"
    st.rerun()


def on_client_click(client_id: str) -> None:
    """Callback ao clicar em um card de cliente."""
    st.session_state.selected_client_id = client_id
    st.session_state.view_mode = "client_detail"
    st.rerun()


def run_traceroute_cli(machine_id: str) -> bool:
    """Executa traceroute via CLI e retorna True se sucesso."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(project_dir, "venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = "python"
    try:
        with st.spinner(f"🔍 Executando traceroute..."):
            result = subprocess.run(
                [venv_python, "-m", "supadiag", "traceroute", "--machine-id", machine_id],
                capture_output=True,
                text=True,
                timeout=600,
            )
        if result.returncode == 0:
            st.success("Traceroute executado com sucesso!")
            return True
        else:
            st.error(f"Erro: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        st.error("Traceroute demorou muito. Tente novamente.")
        return False
    except FileNotFoundError:
        st.error("Python não encontrado.")
        return False


def format_event_time(timestamp: str) -> str:
    """Converte timestamp UTC para America/Sao_Paulo e formata como DD/MM HH:MM."""
    if not timestamp:
        return ""
    try:
        # Tenta parsear como ISO format
        if "T" in timestamp:
            dt = pd.to_datetime(timestamp)
        else:
            dt = pd.to_datetime(timestamp, errors="coerce")
        if dt is pd.NaT or dt is None:
            return timestamp[:5]  # DD/MM HH:MM fallback
        # Converte para America/Sao_Paulo
        if dt.tz is None:
            dt = dt.tz_localize("UTC")
        dt_sp = dt.tz_convert("America/Sao_Paulo")
        return dt_sp.strftime("%d/%m %H:%M")
    except Exception:
        return timestamp[:5] if len(timestamp) >= 5 else timestamp


def get_sidebar_events(repo: FrontendRepository, limit: int = 30) -> list[dict]:
    """Gera eventos da sidebar a partir de dados reais do Supabase."""
    events = []
    try:
        machines_data = repo.get_machines_with_latest_status()
    except Exception:
        return []
    
    for m in machines_data:
        machine = m["machine"]
        client = m["client"]
        latest = m["latest_measurement"]
        
        client_name = client.name if client else "?"
        machine_tag = machine.tag if machine else machine.id[:8]
        
        # Verifica alertas ativos
        try:
            alert_rules = repo.list_alert_rules(machine.id)
            for rule in alert_rules:
                event = repo.get_active_alert_event(rule.get("id", ""))
                if event:
                    severity = event.get("severity", "warning")
                    metric = event.get("metric", "")
                    value = event.get("metric_value", 0)
                    threshold = event.get("threshold_value", 0)
                    started = event.get("started_at", "")[:19].replace("T", " ")
                    
                    if severity == "critical" or event.get("status") == "firing":
                        icon = "[CRITICAL]"
                    elif severity == "warning":
                        icon = "[WARNING]"
                    else:
                        icon = "[ACK]"
                    event_type = "CRITICAL" if severity == "critical" else "WARNING" if severity == "warning" else "ACK"
                    
                    events.append({
                        "timestamp": started or "",
                        "event": event_type,
                        "message": f"{icon} {machine_tag}: {metric}={value} (>{threshold})",
                        "severity": severity,
                    })
        except Exception:
            pass
        
        # Status da máquina
        if latest:
            status = latest.get("status", "ok")
            latency = latest.get("latency_ms")
            loss = latest.get("packet_loss_percent")
            measured = latest.get("measured_at", "")[:19].replace("T", " ")
            
            if status == "unreachable":
                events.append({
                    "timestamp": measured,
                    "event": "UNREACHABLE",
                    "message": f"[CRITICAL] {machine_tag}: INALCANCAVEL (loss: {loss}%)",
                    "severity": "critical",
                })
            elif status == "partial":
                events.append({
                    "timestamp": measured,
                    "event": "PARTIAL",
                    "message": f"[WARNING] {machine_tag}: PARCIAL (lat: {latency}ms, loss: {loss}%)",
                    "severity": "warning",
                })
            elif status == "error":
                events.append({
                    "timestamp": measured,
                    "event": "ERROR",
                    "message": f"[CRITICAL] {machine_tag}: ERRO",
                    "severity": "critical",
                })
            else:
                events.append({
                    "timestamp": measured,
                    "event": "OK",
                    "message": f"[OK] {machine_tag}: OK ({latency}ms)",
                    "severity": "ok",
                })
    
    # Ordena por severidade (critical > warning > ack > ok) e tempo
    severity_order = {"critical": 0, "warning": 1, "ack": 2, "ok": 3}
    events.sort(key=lambda e: (severity_order.get(e.get("severity", "ok"), 3), e.get("timestamp", "")))
    
    return events[-limit:]


def render_cards_view(repo: FrontendRepository, client_id: Optional[str]) -> None:
    """Renderiza a view de cards (lista de clientes com máquinas agrupadas)."""
    st.html('<h1 class="main-header">AI Network Analyzer</h1>')
    st.html('<p class="sub-header">Clique em um cliente para ver métricas detalhadas</p>')
    
    # Tenta buscar clientes com máquinas agrupadas
    try:
        with st.spinner("Carregando clientes..."):
            clients_data = _cached_clients_summary()
        
        if client_id:
            clients_data = [c for c in clients_data if c["client"].id == client_id]
        
        if not clients_data:
            st.info("Nenhum cliente com máquinas ativas encontrado.")
            return
        
        # Métricas gerais
        total_clients = len(clients_data)
        total_local = sum(len(c["local_machines"]) for c in clients_data)
        total_internet = sum(1 for c in clients_data if c["internet_machine"])
        total_machines = total_local + total_internet
        
        ok_count = 0
        warning_count = 0
        critical_count = 0
        no_data_count = 0
        
        for c in clients_data:
            for m in c["local_machines"]:
                if m["latest_measurement"]:
                    status = m["latest_measurement"].get("status", "")
                    if status == "ok":
                        ok_count += 1
                    elif status == "partial":
                        warning_count += 1
                    elif status == "unreachable":
                        critical_count += 1
                else:
                    no_data_count += 1
            if c["internet_machine"] and c["internet_machine"]["latest_measurement"]:
                status = c["internet_machine"]["latest_measurement"].get("status", "")
                if status == "ok":
                    ok_count += 1
                elif status == "partial":
                    warning_count += 1
                elif status == "unreachable":
                    critical_count += 1
            elif c["internet_machine"]:
                no_data_count += 1
        
        # Alertas ativos
        alert_active_count = 0
        for c in clients_data:
            for m in c["local_machines"]:
                latest_alert = repo.get_latest_alert_event(m["machine"].id)
                if latest_alert and latest_alert.get("status") in ["firing", "acknowledged"]:
                    alert_active_count += 1
            if c["internet_machine"]:
                latest_alert = repo.get_latest_alert_event(c["internet_machine"]["machine"].id)
                if latest_alert and latest_alert.get("status") in ["firing", "acknowledged"]:
                    alert_active_count += 1
        
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("Clientes", total_clients)
        col2.metric("Máquinas Total", total_machines)
        col3.metric("Rede Local", total_local)
        col4.metric("Internet", total_internet)
        col5.metric("OK", ok_count)
        col6.metric("Alertas", alert_active_count)
        
        st.divider()
        
        # Seção de Qualidade de Rede
        st.markdown("### 📊 Qualidade de Rede")
        
        # Calcula métricas de qualidade agregadas
        quality_bom = 0
        quality_medio = 0
        quality_ruim = 0
        total_quality = 0
        avg_jitter_all = []
        avg_latency_all = []
        avg_loss_all = []
        
        for c in clients_data:
            internet = c.get("internet_machine")
            if internet:
                quality_metrics = internet.get("quality_metrics") or {}
                status = quality_metrics.get("quality_status")
                if status == "BOM":
                    quality_bom += 1
                elif status == "MEDIO":
                    quality_medio += 1
                elif status == "RUIM":
                    quality_ruim += 1
                total_quality += 1
                
                if quality_metrics.get("avg_jitter_ms") is not None:
                    avg_jitter_all.append(quality_metrics["avg_jitter_ms"])
                if quality_metrics.get("avg_latency_ms") is not None:
                    avg_latency_all.append(quality_metrics["avg_latency_ms"])
                if quality_metrics.get("packet_loss_pct") is not None:
                    avg_loss_all.append(quality_metrics["packet_loss_pct"])
        
        if total_quality > 0:
            q_col1, q_col2, q_col3, q_col4 = st.columns(4)
            q_col1.metric("BOM", quality_bom, delta=f"{quality_bom/total_quality*100:.0f}%")
            q_col2.metric("MÉDIO", quality_medio, delta=f"{quality_medio/total_quality*100:.0f}%")
            q_col3.metric("RUIM", quality_ruim, delta=f"{quality_ruim/total_quality*100:.0f}%")
            
            avg_jitter = round(sum(avg_jitter_all) / len(avg_jitter_all), 1) if avg_jitter_all else None
            avg_latency = round(sum(avg_latency_all) / len(avg_latency_all), 1) if avg_latency_all else None
            avg_loss = round(sum(avg_loss_all) / len(avg_loss_all), 2) if avg_loss_all else None
            
            q_col4.metric("Jitter Médio", f"{avg_jitter:.1f} ms" if avg_jitter is not None else "—")
        
        st.divider()
        
        # Cards por cliente (2 colunas)
        cols_per_row = 2
        for i in range(0, len(clients_data), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, col in enumerate(cols):
                idx = i + j
                if idx < len(clients_data):
                    c = clients_data[idx]
                    with col:
                        render_client_card(
                            client=c["client"],
                            local_machines=c["local_machines"],
                            internet_machine=c["internet_machine"],
                            on_click=on_client_click
                        )
    
    except RepositoryError as e:
        st.error(f"Erro ao conectar ao Cloud: {e}")
    except Exception as e:
        st.error(f"Erro inesperado: {e}")


def render_client_detail(repo: FrontendRepository, client_id: str) -> None:
    """Renderiza a view de detalhes de um cliente (todas as suas máquinas)."""
    if not client_id:
        st.session_state.view_mode = "cards"
        st.session_state.selected_client_id = None
        st.rerun()
        return
    
    try:
        client = repo.get_client(client_id)
        if not client:
            st.error("Cliente não encontrado.")
            if st.button("← Voltar"):
                st.session_state.view_mode = "cards"
                st.session_state.selected_client_id = None
                st.rerun()
            return
        
        # Obter todas as máquinas do cliente (incluindo INTERNET-CHECK)
        all_machines = repo.list_machines(client_id=client_id, active_only=True)
        internet_machine = next((m for m in all_machines if m.tag == "INTERNET-CHECK"), None)
        local_machines = [m for m in all_machines if m.tag != "INTERNET-CHECK"]
        
        # Header com botão voltar
        col1, col2 = st.columns([6, 1])
        with col1:
            st.html(f'<h1 class="main-header">{client.name}</h1>')
            st.html(f'<p class="sub-header">Total de máquinas: {len(local_machines)} local(is) + {1 if internet_machine else 0} internet check</p>')
        with col2:
            if st.button("← Voltar", use_container_width=True):
                st.session_state.view_mode = "cards"
                st.session_state.selected_client_id = None
                st.rerun()
        
        st.divider()
        
        # ===== MÉTRICAS GERAIS DO CLIENTE =====
        col1, col2, col3, col4 = st.columns(4)
        
        # Total de máquinas
        col1.metric("Total de Máquinas", len(local_machines) + (1 if internet_machine else 0))
        
        # Status geral (based on local machines only, as per spec)
        ok_count = sum(1 for m in local_machines if repo.get_latest_measurement(m.id) and repo.get_latest_measurement(m.id).get("status") == "ok")
        warning_count = sum(1 for m in local_machines if repo.get_latest_measurement(m.id) and repo.get_latest_measurement(m.id).get("status") == "partial")
        critical_count = sum(1 for m in local_machines if repo.get_latest_measurement(m.id) and repo.get_latest_measurement(m.id).get("status") == "unreachable")
        no_data_count = len(local_machines) - ok_count - warning_count - critical_count
        
        col2.metric("OK", ok_count)
        col3.metric("Parcial", warning_count)
        col4.metric("Critico", critical_count)
        
        # ===== TABELA DETALHADA DE MÁQUINAS LOCAIS =====
        st.subheader("Máquinas Locais")
        
        if local_machines:
            for machine in local_machines:
                latest = repo.get_latest_measurement(machine.id)
                status = latest.get("status", "") if latest else ""
                latency = latest.get("latency_ms") if latest else None
                loss = latest.get("packet_loss_percent", 0) if latest else 0
                
                col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
                
                with col1:
                    st.markdown(f"**{machine.tag}** • {machine.ip}")
                
                with col2:
                    # Status badge
                    status_color = "#28a745" if status == "ok" else "#ffc107" if status == "partial" else "#dc3545" if status == "unreachable" else "#6c757d"
                    status_icon = "🟢" if status == "ok" else "🟡" if status == "partial" else "🔴" if status == "unreachable" else "⚪"
                    st.html(f'<span style="background:{status_color};color:white;padding:2px 8px;border-radius:10px;font-size:0.75rem;">{status_icon} {status.upper()}</span>')
                
                with col3:
                    st.metric("Latência", f"{latency:.1f} ms" if latency is not None else "—")
                
                with col4:
                    st.metric("Perda", f"{loss:.1f}%")
                
                with col5:
                    st.button(f"Ver detalhes", key=f"detail_{machine.id}", on_click=lambda mid=machine.id: on_machine_click(mid), use_container_width=True)
                
                st.divider()
        else:
            st.info("Nenhuma máquina local configurada para este cliente.")
        
        # ===== INFORMAÇÕES DA INTERNET =====
        if internet_machine:
            st.subheader("Internet Check")
            latest = repo.get_latest_measurement(internet_machine.id)
            status = latest.get("status", "") if latest else ""
            latency = latest.get("latency_ms") if latest else None
            loss = latest.get("packet_loss_percent", 0) if latest else 0
            jitter = latest.get("jitter_ms") if latest else None
            measured_at = latest.get("measured_at", "") if latest else ""
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                status_color = "#28a745" if status == "ok" else "#ffc107" if status == "partial" else "#dc3545" if status == "unreachable" else "#6c757d"
                status_icon = "🟢" if status == "ok" else "🟡" if status == "partial" else "🔴" if status == "unreachable" else "⚪"
                st.markdown(f"**INTERNET-CHECK** {status_icon}")
                st.html(f'<span style="background:{status_color};color:white;padding:2px 8px;border-radius:10px;font-size:0.75rem;">{status.upper()}</span>')
            
            with col2:
                st.metric("Latência", f"{latency:.1f} ms" if latency is not None else "—")
                st.metric("Jitter", f"{jitter:.1f} ms" if jitter is not None else "—")
            
            with col3:
                st.metric("Perda", f"{loss:.1f}%")
            
            with col4:
                measured_dt = pd.to_datetime(measured_at) if measured_at else None
                if measured_dt:
                    measured_dt_sp = measured_dt.tz_convert("America/Sao_Paulo")
                    measured_str = measured_dt_sp.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    measured_str = "—"
                st.metric("Última Medição", measured_str)
            
            # Botão para ver detalhes do internet check
            st.button(f"Ver detalhes", key=f"detail_{internet_machine.id}", on_click=lambda mid=internet_machine.id: on_machine_click(mid), use_container_width=True, type="secondary")
        
        st.divider()
        
        # ===== EVENTOS DE STATUS DO DISPOSITIVO =====
        st.subheader("Eventos de Conectividade")
        try:
            status_events = repo.get_device_status_events(client_id=client_id, hours=24, limit=50)
            if status_events:
                for event in reversed(status_events):
                    event_type = event.get("event_type", "")
                    machine_id = event.get("machine_id", "")
                    loss = event.get("packet_loss_percent")
                    measured = event.get("measured_at", "")[:19].replace("T", " ")
                    prev = event.get("previous_status", "")
                    
                    if event_type == "unreachable":
                        icon = "🔴"
                        color = "#dc3545"
                        label = "INACESSÍVEL"
                    elif event_type == "reachable":
                        icon = "🟢"
                        color = "#28a745"
                        label = "RECUPERADO"
                    else:
                        icon = "🟡"
                        color = "#ffc107"
                        label = "PERDA DE PACOTES"
                    
                    st.html(
                        f'<span style="color:{color};font-size:0.8rem;">'
                        f'{measured} | {icon} <strong>{label}</strong> '
                        f'(loss: {loss:.1f}%'
                        + (f', anterior: {prev})' if prev else ')')
                        + '</span>'
                    )
            else:
                st.caption("Nenhum evento de conectividade nas últimas 24h")
        except Exception:
            st.caption("Dados de conectividade indisponíveis")
        
        st.divider()
        
        # ===== GRÁFICOS HISTÓRICOS =====
        st.subheader("Gráficos Históricos")
        
        # Gráfico da primeira máquina local (latência + jitter + perda)
        if local_machines:
            first_machine = local_machines[0]
            measurements = _cached_measurements(first_machine.id, hours=24, limit=settings.MAX_MEASUREMENTS)
            if measurements:
                render_metrics_charts(measurements, first_machine.tag, f"client_{first_machine.id}")
            else:
                st.info(f"Sem medições para {first_machine.tag}")
        
        # Gráfico da internet (se houver)
        if internet_machine:
            st.subheader("Internet Check - Histórico")
            measurements = _cached_measurements(internet_machine.id, hours=24, limit=settings.MAX_MEASUREMENTS)
            if measurements:
                render_metrics_charts(measurements, internet_machine.tag, f"client_internet_{internet_machine.id}")
            else:
                st.info("Sem medições para internet check")
        
        st.divider()
        
        # ===== GRÁFICO DE EVOLUÇÃO DOS ALERTAS =====
        st.subheader("Alertas Ativos")
        
        # Busca alertas ativos de todas as máquinas do cliente
        alert_count = 0
        for machine in local_machines:
            if internet_machine:
                alert_count += len(repo.get_alert_events(machine.id))
                alert_count += len(repo.get_alert_events(internet_machine.id))
            else:
                alert_count += len(repo.get_alert_events(machine.id))
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Alertas Ativos", alert_count)
        
        # Lista de alertas ativos (se houver)
        if alert_count > 0:
            with st.expander("Ver detalhes dos alertas"):
                for machine in local_machines:
                    if internet_machine:
                        events = repo.get_alert_events(machine.id) + repo.get_alert_events(internet_machine.id)
                    else:
                        events = repo.get_alert_events(machine.id)
                    
                    for event in events:
                        if event.get("status") in ["firing", "acknowledged"]:
                            severity = event.get("severity", "warning")
                            icon = "🔴" if severity == "critical" else "🟡" if severity == "warning" else "🟠"
                            st.markdown(f"{icon} {machine.tag} - {event.get('metric', '')}: {event.get('metric_value', 0)}")
        
# ===== PREVISÃO 4H (LSTM) =====
        st.divider()
        st.subheader("Previsão de Qualidade (4h)")
        
        target_for_prediction = internet_machine if internet_machine else (local_machines[0] if local_machines else None)
        
        if target_for_prediction:
            # Botão Train Model
            col_train, col_pred = st.columns([1, 3])
            with col_train:
                if st.button("🚀 Treinar Modelo", key=f"train_{target_for_prediction.id}", use_container_width=True):
                    try:
                        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        venv_python = os.path.join(project_dir, "venv", "Scripts", "python.exe")
                        if not os.path.exists(venv_python):
                            venv_python = "python"
                        with st.spinner(f"Treinando modelo para {target_for_prediction.tag}..."):
                            result = subprocess.run(
                                [venv_python, "-m", "supadiag", "ml-train", "--machine-id", target_for_prediction.id, "--epochs", "50"],
                                capture_output=True,
                                text=True,
                                timeout=600,
                            )
                        if result.returncode == 0:
                            st.success("Modelo treinado com sucesso!")
                            if result.stdout:
                                st.caption(result.stdout[-500:])
                        else:
                            st.error(f"Erro no treino: {result.stderr}")
                    except subprocess.TimeoutExpired:
                        st.error("Treino demorou muito. Tente novamente.")
                    except FileNotFoundError:
                        st.error("Python não encontrado.")
                    except Exception as e:
                        st.error(f"Erro ao treinar: {e}")
            
            with col_pred:
                try:
                    import torch
                    import numpy as np
                    import plotly.graph_objects as go
                    import sys
                    import os
                    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from src.supadiag.ml_predictor import NetworkQualityPredictor
                    from src.supadiag.config import load_settings
                    
                    backend_settings = load_settings()
                    repo_nq = get_repository()
                    predictor = NetworkQualityPredictor(backend_settings, repo_nq)
                    
                    measurements = _cached_measurements(target_for_prediction.id, hours=12, limit=100)
                    
                    reachable_count = len(measurements) if measurements else 0
                    
                    if reachable_count == 0:
                        st.warning(
                            "⚠️ Sem medições alcançáveis para previsão. "
                            "O dispositivo está inacessível ou sem dados recentes. "
                            "Verifique os eventos de conectividade abaixo."
                        )
                        try:
                            status_events = repo.get_device_status_events(
                                machine_id=target_for_prediction.id, hours=24, limit=10
                            )
                            if status_events:
                                with st.expander("Últimos eventos de conectividade"):
                                    for event in reversed(status_events):
                                        etype = event.get("event_type", "")
                                        loss = event.get("packet_loss_percent")
                                        measured = event.get("measured_at", "")[:16].replace("T", " ")
                                        icon = "🔴" if etype == "unreachable" else "🟢" if etype == "reachable" else "🟡"
                                        st.html(f"{measured} {icon} {etype} (loss: {loss:.1f}%)")
                        except Exception:
                            pass
                    elif reachable_count < 12:
                        st.info(
                            f"Dados insuficientes para previsão: {reachable_count}/12 medições alcançáveis. "
                            f"Aguarde mais medições ou verifique a conectividade."
                        )
                    else:
                        prediction = predictor.predict_next_4h(target_for_prediction.id, measurements)
                    
                    # Prepara dados para gráfico
                    historical_timestamps = []
                    historical_quality = []
                    historical_colors = []
                    
                    for m in measurements[-12:]:
                        ts = pd.to_datetime(m.get("measured_at", ""))
                        if ts.tz is not None:
                            ts = ts.tz_convert("America/Sao_Paulo")
                        historical_timestamps.append(ts)
                        
                        latency = m.get("latency_ms") or 0
                        jitter = m.get("jitter_ms") or 0
                        loss = m.get("packet_loss_percent") or 0
                        
                        if jitter < 20 and latency < 100 and loss < 0.5:
                            historical_quality.append(3)
                            historical_colors.append("#28a745")
                        elif jitter < 30 and latency < 150 and loss < 1:
                            historical_quality.append(2)
                            historical_colors.append("#ffc107")
                        else:
                            historical_quality.append(1)
                            historical_colors.append("#dc3545")
                    
                    last_ts = historical_timestamps[-1]
                    forecast_timestamps = [last_ts + timedelta(hours=h) for h in range(1, 5)]
                    forecast_quality = prediction.forecast_classes
                    forecast_colors = ["#28a745" if c == 0 else "#ffc107" if c == 1 else "#dc3545" for c in forecast_quality]
                    
                    fig = go.Figure()
                    
                    # Linha de histórico com pontos coloridos por qualidade
                    for i, (ts, q, color) in enumerate(zip(historical_timestamps, historical_quality, historical_colors)):
                        fig.add_trace(go.Scatter(
                            x=[ts],
                            y=[q],
                            mode='markers',
                            name='Histórico' if i == 0 else '',
                            marker=dict(size=8, color=color, line=dict(width=1, color='white')),
                            showlegend=(i == 0),
                            hovertemplate=f"<b>Histórico</b><br>Horário: %{{x|%H:%M}}<br>Qualidade: %{{y}}<extra></extra>"
                        ))
                    
                    # Linha conectando histórico
                    fig.add_trace(go.Scatter(
                        x=historical_timestamps,
                        y=historical_quality,
                        mode='lines',
                        name='Tendência',
                        line=dict(color='#1f77b4', width=2, dash='dot'),
                        hoverinfo='skip'
                    ))
                    
                    # Previsão 4h
                    for i, (ts, q, color, conf) in enumerate(zip(forecast_timestamps, forecast_quality, forecast_colors, prediction.forecast_confidences)):
                        fig.add_trace(go.Scatter(
                            x=[ts],
                            y=[q],
                            mode='markers',
                            name='Previsão' if i == 0 else '',
                            marker=dict(
                                size=16,
                                color=color,
                                symbol='diamond',
                                line=dict(width=2, color='white')
                            ),
                            showlegend=(i == 0),
                            hovertemplate=f"<b>Previsão {i+1}h</b><br>Horário: %{{x|%H:%M}}<br>Qualidade: %{{y}}<br>Confiança: {conf:.1%}<extra></extra>"
                        ))
                    
                    # Linha de confiança
                    fig.add_trace(go.Scatter(
                        x=forecast_timestamps,
                        y=forecast_quality,
                        mode='lines',
                        name='Tendência previsão',
                        line=dict(color='#ff7f0e', width=2, dash='dash'),
                        hoverinfo='skip'
                    ))
                    
                    fig.update_layout(
                        title=f"Previsão de Qualidade - {target_for_prediction.tag}",
                        xaxis_title="Horário (São Paulo)",
                        yaxis_title="Qualidade",
                        yaxis=dict(
                            tickmode='array',
                            tickvals=[1, 2, 3],
                            ticktext=['RUIM', 'MÉDIO', 'BOM'],
                            range=[0, 4]
                        ),
                        height=450,
                        template="plotly_white",
                        hovermode="x unified",
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=1.02,
                            xanchor="right",
                            x=1
                        ),
                        annotations=[
                            dict(
                                x=0.02,
                                y=0.98,
                                xref="paper",
                                yref="paper",
                                text="<b>Legenda:</b><br>🟢 BOM<br>🟡 MÉDIO<br>🔴 RUIM",
                                showarrow=False,
                                font=dict(size=11),
                                align="left",
                                bgcolor="rgba(255,255,255,0.8)",
                                bordercolor="#ccc",
                                borderwidth=1
                            )
                        ]
                    )
                    st.plotly_chart(fig, use_container_width=True, key="forecast_chart")
                    
                    st.caption(f"Previsão gerada em {prediction.predicted_at[:19].replace('T', ' ')} | Confiança: {prediction.confidence:.1%}")
                except Exception as e:
                    st.error(f"Erro ao gerar previsão: {e}")
        
        # ===== FEEDBACK DO USUÁRIO =====
        st.divider()
        st.subheader("Feedback da Qualidade")
        st.caption("Ajude a IA a aprender: classifique a qualidade atual da conexão.")
        
        target_machine_id = internet_machine.id if internet_machine else local_machines[0].id

        col_fb1, col_fb2, col_fb3 = st.columns(3)
        
        with col_fb1:
            if st.button("🟢 Bom", key="feedback_bom", use_container_width=True):
                try:
                    import sys
                    import os
                    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from src.supadiag.config import load_settings
                    from src.supadiag.network_quality import NetworkQualityAnalyzer
                    backend_settings = load_settings()
                    repo_nq = get_repository()
                    analyzer = NetworkQualityAnalyzer(backend_settings, repo_nq)
                    metrics = repo_nq.get_network_quality_metrics(target_machine_id, hours=1)
                    analyzer.save_user_feedback(
                        machine_id=target_machine_id,
                        label="bom",
                        avg_latency_ms=metrics.get("avg_latency"),
                        avg_jitter_ms=metrics.get("avg_jitter"),
                        packet_loss_pct=metrics.get("packet_loss_pct", 0.0),
                    )
                    st.success("Feedback registrado: Bom")
                except Exception as e:
                    st.error(f"Erro ao salvar feedback: {e}")
        
        with col_fb2:
            if st.button("🟡 Médio", key="feedback_medio", use_container_width=True):
                try:
                    import sys
                    import os
                    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from src.supadiag.config import load_settings
                    from src.supadiag.network_quality import NetworkQualityAnalyzer
                    backend_settings = load_settings()
                    repo_nq = get_repository()
                    analyzer = NetworkQualityAnalyzer(backend_settings, repo_nq)
                    metrics = repo_nq.get_network_quality_metrics(target_machine_id, hours=1)
                    analyzer.save_user_feedback(
                        machine_id=target_machine_id,
                        label="medio",
                        avg_latency_ms=metrics.get("avg_latency"),
                        avg_jitter_ms=metrics.get("avg_jitter"),
                        packet_loss_pct=metrics.get("packet_loss_pct", 0.0),
                    )
                    st.success("Feedback registrado: Médio")
                except Exception as e:
                    st.error(f"Erro ao salvar feedback: {e}")
        
        with col_fb3:
            if st.button("🔴 Ruim", key="feedback_ruim", use_container_width=True):
                try:
                    import sys
                    import os
                    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from src.supadiag.config import load_settings
                    from src.supadiag.network_quality import NetworkQualityAnalyzer
                    backend_settings = load_settings()
                    repo_nq = get_repository()
                    analyzer = NetworkQualityAnalyzer(backend_settings, repo_nq)
                    metrics = repo_nq.get_network_quality_metrics(target_machine_id, hours=1)
                    analyzer.save_user_feedback(
                        machine_id=target_machine_id,
                        label="ruim",
                        avg_latency_ms=metrics.get("avg_latency"),
                        avg_jitter_ms=metrics.get("avg_jitter"),
                        packet_loss_pct=metrics.get("packet_loss_pct", 0.0),
                    )
                    st.success("Feedback registrado: Ruim")
                except Exception as e:
                    st.error(f"Erro ao salvar feedback: {e}")
    
    except Exception as e:
        st.error(f"Erro ao carregar detalhes do cliente: {e}")


def main() -> None:
    init_session_state()
    repo = get_repository()
    
    # Health check silencioso na inicialização
    if "health_checked" not in st.session_state:
        ok, msg = repo.health_check()
        st.session_state.health_checked = True
        st.session_state.health_ok = ok
        st.session_state.health_msg = msg
    
# Sidebar
    filters = render_sidebar_filters(repo)
    
    # Sidebar content
    with st.sidebar:
        # Cloud status
        if st.session_state.get("health_ok"):
            st.success("Cloud Online")
        else:
            st.error("Cloud Offline")
        
        # Secao IA no sidebar
        st.divider()
        st.markdown("### Rede Neural")
        
        # Estatísticas gerais de IA
        try:
            all_feedbacks = _cached_machine_feedback(1000)
            if all_feedbacks:
                total_fb = len(all_feedbacks)
                bom = sum(1 for f in all_feedbacks if f.get("label") == "bom")
                medio = sum(1 for f in all_feedbacks if f.get("label") == "medio")
                ruim = sum(1 for f in all_feedbacks if f.get("label") == "ruim")
                acc = round((bom * 1.0 + medio * 0.5) / total_fb * 100, 1) if total_fb > 0 else 0
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Acurácia Global", f"{acc}%")
                with col2:
                    st.metric("Feedbacks", f"{total_fb}")
                
                st.progress(acc / 100)
            else:
                st.caption("Sem feedbacks ainda")
        except Exception:
            st.caption("Dados de IA indisponíveis")
        
        # Eventos de IA - Feedback de treinamento da rede neural
        st.divider()
        st.markdown("### Eventos IA")
        try:
            ai_events = _cached_ai_feedbacks()
            if ai_events:
                for event in reversed(ai_events[:15]):
                    ts = event.get("created_at", "")[:16].replace("T", " ")
                    label = event.get("label", "")
                    loss = event.get("packet_loss_percent", 0)
                    lat = event.get("latency_ms")
                    jitter = event.get("jitter_ms")
                    label_color = "#28a745" if label == "bom" else "#ffc107" if label == "medio" else "#dc3545"
                    st.html(
                        f"{ts} | "
                        f'<span style="color:{label_color};">{label.upper()}</span> | '
                        f"Loss: {loss}% | Lat: {lat}ms | Jitter: {jitter}ms"
                    )
            else:
                st.caption("Nenhum evento de treinamento registrado")
        except Exception as e:
            st.caption(f"Eventos IA indisponíveis: {e}")

        # Alertas ativos no sidebar
        st.divider()
        st.markdown("### Alertas Ativos")
        
        try:
            alert_data = _cached_sidebar_alerts()
            if alert_data:
                for machine_tag, icon, metric, value, severity in alert_data:
                    st.markdown(f"{icon} **{machine_tag}** ({metric}: {value})")
            else:
                st.html("<span style='color: #28a745; font-size: 0.85rem;'>Nenhum alerta ativo</span>")
        except Exception:
            st.caption("Nenhum dado de alerta disponivel")
        
        # Ultimos eventos no sidebar
        st.divider()
        st.markdown("### Ultimos Eventos")
        try:
            events = _cached_sidebar_events()
            for event in reversed(events):
                timestamp = format_event_time(event.get("timestamp", ""))
                message = event.get("message", "")[:80]
                color = "#888"
                severity = event.get("severity", "ok")
                if severity == "critical":
                    color = "#dc3545"
                elif severity == "warning":
                    color = "#ffc107"
                elif severity == "ok":
                    color = "#28a745"
                st.html(f'<span style="color:{color};font-size:0.75rem;">{timestamp} | {message}</span>')
        except Exception:
            st.caption("Nenhum evento disponível")
    
    # Auto-refresh (sempre ativo, a cada 30 segundos)
    st_autorefresh(interval=30_000, key="auto_refresh")
    
    # Roteamento de views
    if st.session_state.view_mode == "client_detail" and st.session_state.selected_client_id:
        render_client_detail(repo, st.session_state.selected_client_id)
    else:
        render_cards_view(repo, filters["client_id"])


if __name__ == "__main__":
    main()
