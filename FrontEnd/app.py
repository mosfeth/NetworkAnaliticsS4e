# FrontEnd/app.py
# Dashboard Principal - AI Network Analyzer

import streamlit as st
from streamlit_autorefresh import st_autorefresh
from typing import Optional
import pandas as pd
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import json
import subprocess
import os
import sys
from pathlib import Path
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import settings
from repository import FrontendRepository, RepositoryError
from components import (
    render_dashboard_machine_card,
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
        color: #7db8ff;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #aab5c5;
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
    div[data-testid="stMetric"] {
        background: linear-gradient(145deg, #171b24, #1d2330);
        border: 1px solid #343d4d;
        border-radius: 14px;
        padding: 14px 16px;
        color: #f3f6fb;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.16);
    }
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"],
    div[data-testid="stMetric"] [data-testid="stMetricValue"],
    div[data-testid="stMetric"] [data-testid="stMetricValue"] div,
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
        color: #f3f6fb !important;
        opacity: 1 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] p {
        color: #c2cad8 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] svg {
        fill: currentColor;
    }
    div[class*="st-key-dashboard-machine-card"] div[data-testid="stMetric"] {
        min-height: 74px;
        padding: 7px 8px;
        border-radius: 9px;
        box-shadow: none;
    }
    div[class*="st-key-dashboard-machine-card"] [data-testid="stMetricLabel"] p {
        font-size: 0.68rem !important;
        line-height: 1.15 !important;
        margin-bottom: 2px;
    }
    div[class*="st-key-dashboard-machine-card"] [data-testid="stMetricValue"],
    div[class*="st-key-dashboard-machine-card"] [data-testid="stMetricValue"] div {
        font-size: 1rem !important;
        line-height: 1.15 !important;
        white-space: nowrap;
    }
    div[class*="st-key-dashboard-machine-card"] [data-testid="stMetricDelta"] {
        font-size: 0.65rem !important;
    }
    div[data-testid="stTabs"] button[role="tab"] {
        border-radius: 10px 10px 0 0;
        font-weight: 600;
    }
    div[data-testid="stSegmentedControl"] {
        padding: 4px;
        border-radius: 12px;
        background: #f1f5f9;
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


@st.cache_data(ttl=30)
def _cached_measurements_between(machine_id: str, start_at: str, end_at: str, limit: int):
    repo = get_repository()
    return repo.get_measurements_between(machine_id, start_at, end_at, limit=limit)


@st.cache_data(ttl=30)
def _cached_quality_events(machine_id: str, hours: int):
    repo = get_repository()
    try:
        return repo.get_device_status_events(machine_id=machine_id, hours=hours, limit=1000)
    except RepositoryError:
        return []


@st.cache_data(ttl=30)
def _cached_quality_events_between(machine_id: str, start_at: str, end_at: str, limit: int):
    repo = get_repository()
    try:
        return repo.get_device_status_events_between(machine_id, start_at, end_at, limit=limit)
    except RepositoryError:
        return []


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


@st.cache_data(ttl=60)
def _cached_model_metrics(machine_id: str):
    """Métricas reais do melhor modelo LSTM treinado, persistido no Supabase."""
    try:
        from supabase import create_client
        from config import settings as fe_settings
        sb = create_client(fe_settings.SUPABASE_URL, fe_settings.SUPABASE_KEY)
        rows = (
            sb.table("ml_model_weights")
            .select("model_version, accuracy, trained_at")
            .eq("model_name", f"network_quality_{machine_id}")
            .limit(10)
            .execute().data or []
        )
        rows = [r for r in rows if r.get("accuracy") is not None]
        rows.sort(key=lambda r: r["accuracy"], reverse=True)
        return rows[0] if rows else None
    except Exception:
        return None


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


def on_machine_card_click(client_id: str, machine_id: str) -> None:
    """Abre os detalhes já selecionando a máquina avaliada no card."""
    st.session_state.selected_quality_machine_id = machine_id
    on_client_click(client_id)


def run_traceroute_cli(machine_id: str) -> bool:
    """Executa traceroute via CLI e retorna True se sucesso."""
    venv_python = sys.executable
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
                    "event": "COLLECTOR_ERROR",
                    "message": f"[COLLECTOR] {machine_tag}: falha na coleta; conectividade não determinada",
                    "severity": "warning",
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
    """Renderiza cards compactos, um por equipamento monitorado."""
    st.html('<h1 class="main-header">Network analysis</h1>')
    
    # Tenta buscar clientes com máquinas agrupadas
    try:
        with st.spinner("Carregando clientes..."):
            clients_data = _cached_clients_summary()
        
        if client_id:
            clients_data = [c for c in clients_data if c["client"].id == client_id]

        _filter_client_summary_to_work_schedules(clients_data)
        
        if not clients_data:
            st.info("Nenhum cliente com máquinas ativas encontrado.")
            return
        
        cards = []
        for client_data in clients_data:
            internet_data = client_data.get("internet_machine")
            internet_measurement = internet_data.get("latest_measurement") if internet_data else None
            if client_data["local_machines"]:
                for machine_data in client_data["local_machines"]:
                    cards.append((client_data["client"], machine_data, internet_measurement))
            elif internet_data:
                # Mantém um card visível para clientes que ainda não têm máquina local.
                cards.append((client_data["client"], internet_data, None))

        # Três cards compactos por linha em telas largas; cada equipamento
        # recebe seus próprios dados, avaliações e ação para abrir a análise.
        columns = st.columns(3)
        for index, (client, machine_data, internet_measurement) in enumerate(cards):
            with columns[index % len(columns)]:
                render_dashboard_machine_card(
                    machine=machine_data["machine"],
                    client=client,
                    latest_measurement=machine_data.get("latest_measurement"),
                    on_open=on_machine_card_click,
                    on_feedback=_record_dashboard_feedback,
                    internet_measurement=internet_measurement,
                )
    
    except RepositoryError as e:
        st.error(f"Erro ao conectar ao Cloud: {e}")
    except Exception as e:
        st.error(f"Erro inesperado: {e}")


def _render_advanced_client_detail(repo: FrontendRepository, client_id: str) -> None:
    """Diagnósticos existentes: traceroute, alertas e feedback de IA."""
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
        
# ===== PREVISÃO 1H (LSTM) =====
        st.divider()
        st.subheader("Previsão de Qualidade (1h)")
        
        target_for_prediction = internet_machine if internet_machine else (local_machines[0] if local_machines else None)
        
        if target_for_prediction:
            # Botão Train Model
            col_train, col_pred = st.columns([1, 3])
            with col_train:
                best_model = _cached_model_metrics(target_for_prediction.id)
                if best_model:
                    trained_label = str(best_model.get("trained_at", ""))[:16].replace("T", " ")
                    st.metric(
                        "Acurácia do modelo",
                        f"{best_model['accuracy'] * 100:.1f}%",
                        help=f"Melhor treino salvo no Supabase (versão de {trained_label})",
                    )
                else:
                    st.caption("Nenhum modelo treinado salvo ainda.")
                if st.button("🚀 Treinar Modelo", key=f"train_{target_for_prediction.id}", use_container_width=True):
                    try:
                        venv_python = sys.executable
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
                        raise ValueError("Sem medições recentes suficientes para gerar o gráfico.")
                    elif reachable_count < 12:
                        st.info(
                            f"Dados insuficientes para previsão: {reachable_count}/12 medições alcançáveis. "
                            f"Aguarde mais medições ou verifique a conectividade."
                        )
                        raise ValueError("São necessárias pelo menos 12 medições alcançáveis.")
                    else:
                        prediction = predictor.predict_next_hour(target_for_prediction.id, measurements)
                    
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
                    forecast_timestamps = [last_ts + timedelta(hours=h) for h in range(1, 2)]
                    forecast_quality = prediction.forecast_classes
                    forecast_colors = ["#28a745" if c == 0 else "#ffc107" if c == 1 else "#dc3545" for c in forecast_quality]
                    
                    fig = go.Figure()

                    # Real (medido): círculos coloridos pela qualidade efetivamente medida
                    for i, (ts, q, color) in enumerate(zip(historical_timestamps, historical_quality, historical_colors)):
                        fig.add_trace(go.Scatter(
                            x=[ts],
                            y=[q],
                            mode='markers',
                            name='Real (medido)' if i == 0 else '',
                            marker=dict(size=8, color=color, line=dict(width=1, color='white')),
                            showlegend=(i == 0),
                            hovertemplate=f"<b>Real (medido)</b><br>Horário: %{{x|%H:%M}}<br>Qualidade: %{{y}}<extra></extra>"
                        ))

                    # Tendência dos valores reais
                    fig.add_trace(go.Scatter(
                        x=historical_timestamps,
                        y=historical_quality,
                        mode='lines',
                        name='Tendência real',
                        line=dict(color='#1f77b4', width=2, dash='dot'),
                        hoverinfo='skip'
                    ))

                    # Previsão (1h): losangos, destacados como NÃO medidos
                    for i, (ts, q, color, conf) in enumerate(zip(forecast_timestamps, forecast_quality, forecast_colors, prediction.forecast_confidences)):
                        fig.add_trace(go.Scatter(
                            x=[ts],
                            y=[q],
                            mode='markers',
                            name='Previsão (não medido)' if i == 0 else '',
                            marker=dict(
                                size=16,
                                color=color,
                                symbol='diamond',
                                line=dict(width=2, color='white')
                            ),
                            showlegend=(i == 0),
                            hovertemplate=f"<b>Previsão (não medido)</b><br>Horário: %{{x|%H:%M}}<br>Qualidade: %{{y}}<br>Confiança: {conf:.1%}<extra></extra>"
                        ))

                    # Linha de confiança da previsão
                    fig.add_trace(go.Scatter(
                        x=forecast_timestamps,
                        y=forecast_quality,
                        mode='lines',
                        name='Tendência prevista',
                        line=dict(color='#ff7f0e', width=2, dash='dash'),
                        hoverinfo='skip'
                    ))

                    # Divisória entre o que é real e o que é previsão
                    fig.add_vline(
                        x=last_ts,
                        line_width=1.5,
                        line_dash="dash",
                        line_color="#999999",
                    )
                    fig.add_annotation(
                        x=last_ts,
                        y=4.15,
                        text="A partir daqui: PREVISÃO",
                        showarrow=False,
                        font=dict(size=10, color="#666666"),
                        xanchor="left",
                    )
                    fig.add_annotation(
                        x=last_ts,
                        y=4.15,
                        text="REAL (medido) ",
                        showarrow=False,
                        font=dict(size=10, color="#666666"),
                        xanchor="right",
                    )

                    fig.update_layout(
                        title=f"Previsão de Qualidade (1h) - {target_for_prediction.tag}",
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
                    st.caption(
                        f"Previsão gerada em {prediction.predicted_at[:19].replace('T', ' ')} | "
                        f"Confiança: {prediction.confidence:.1%}"
                    )
                    st.caption(
                        "Círculos à esquerda da linha tracejada = valores REAIS medidos pelo coletor. "
                        "Losangos à direita = PREVISÃO do modelo para a próxima hora (não medidos)."
                    )
                except (FileNotFoundError, ValueError) as e:
                    st.info(str(e))
                except Exception as e:
                    st.error(f"Erro ao gerar previsão: {e}")
        
    except Exception as e:
        st.error(f"Erro ao carregar detalhes do cliente: {e}")


def _quality_frame(measurements: list[dict], events: list[dict], source: str) -> pd.DataFrame:
    rows = []
    measurement_stamps = set()
    for measurement in measurements:
        stamp = pd.to_datetime(measurement.get("measured_at"), errors="coerce", utc=True)
        if pd.notna(stamp):
            measurement_stamps.add(stamp)
        rows.append({
            "timestamp": measurement.get("measured_at"),
            "source": source,
            "latency_ms": measurement.get("latency_ms"),
            "jitter_ms": measurement.get("jitter_ms"),
            "packet_loss_percent": measurement.get("packet_loss_percent", 0),
            "status": measurement.get("status", ""),
        })
    for event in events:
        event_stamp = pd.to_datetime(event.get("measured_at"), errors="coerce", utc=True)
        if pd.notna(event_stamp) and event_stamp in measurement_stamps:
            continue
        event_type = event.get("event_type", "")
        loss = event.get("packet_loss_percent")
        if loss is None:
            loss = 100.0 if event_type == "unreachable" else 0.0
        rows.append({
            "timestamp": event.get("measured_at"),
            "source": source,
            "latency_ms": event.get("latency_ms"),
            "jitter_ms": event.get("jitter_ms"),
            "packet_loss_percent": loss,
            "status": event_type or "evento",
        })
    if not rows:
        return pd.DataFrame(columns=["timestamp", "source", "latency_ms", "jitter_ms", "packet_loss_percent", "status"])
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    frame["timestamp"] = frame["timestamp"].dt.tz_convert("America/Sao_Paulo")
    for metric in ("latency_ms", "jitter_ms", "packet_loss_percent"):
        frame[metric] = pd.to_numeric(frame[metric], errors="coerce")
    return frame.reset_index(drop=True)


def _quality_chart(local: pd.DataFrame, internet: pd.DataFrame, title: str) -> None:
    metrics = [
        ("latency_ms", "Latência", "ms", 80, 150),
        ("jitter_ms", "Jitter", "ms", 30, 50),
        ("packet_loss_percent", "Perda de pacotes", "%", 2, 5),
    ]
    colors = {"Local": "#60a5fa", "Internet": "#22d3ee"}
    frames = {"Local": local, "Internet": internet}
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=tuple(item[1] for item in metrics),
        row_heights=[0.4, 0.3, 0.3],
    )
    for row, (field, label, unit, warn, critical) in enumerate(metrics, start=1):
        for name, frame in frames.items():
            if frame.empty or frame[field].dropna().empty:
                continue
            is_loss = field == "packet_loss_percent"
            color = ("#fb7185" if name == "Local" else "#fbbf24") if is_loss else colors[name]
            values = frame.dropna(subset=[field])
            fig.add_trace(
                go.Scatter(
                    x=values["timestamp"], y=values[field], mode="lines+markers",
                    name=f"{name} · {label.lower()}", legendgroup=name,
                    line={"color": color, "width": 2.8 if is_loss else 2},
                    marker={"size": 6 if is_loss else 4},
                    fill="tozeroy" if is_loss else None,
                    fillcolor=("rgba(251, 113, 133, 0.20)" if name == "Local" else "rgba(251, 191, 36, 0.18)") if is_loss else None,
                    hovertemplate=f"%{{x|%d/%m %H:%M:%S}}<br>{name}: %{{y:.2f}} {unit}<extra></extra>",
                ), row=row, col=1,
            )
            if len(values) >= 5:
                smooth = values[field].rolling(5, min_periods=2).median()
                fig.add_trace(
                    go.Scatter(
                        x=values["timestamp"], y=smooth, mode="lines",
                        name=f"Tendência {name.lower()} · {label.lower()}",
                        legendgroup=name, showlegend=False,
                        line={"color": color, "width": 3},
                        hovertemplate=f"Tendência: %{{y:.2f}} {unit}<extra></extra>",
                    ), row=row, col=1,
                )
        fig.add_hline(y=warn, line_dash="dash", line_color="#d97706", opacity=0.7,
                      annotation_text=f"Atenção {warn} {unit}", annotation_position="top left", row=row, col=1)
        fig.add_hline(y=critical, line_dash="dot", line_color="#dc2626", opacity=0.7,
                      annotation_text=f"Crítico {critical} {unit}", annotation_position="bottom left", row=row, col=1)
        fig.update_yaxes(title_text=unit, rangemode="tozero", row=row, col=1)
    if all(frame.empty or frame["latency_ms"].dropna().empty for frame in frames.values()) and all(
        frame.empty or frame["jitter_ms"].dropna().empty for frame in frames.values()
    ):
        fig.add_annotation(
            text="Sem respostas ao ping: latência e jitter não podem ser calculados.",
            x=0.5, y=0.76, xref="paper", yref="paper", showarrow=False,
            font={"color": "#cbd5e1", "size": 14},
            bgcolor="rgba(15, 23, 42, 0.82)", borderpad=6,
        )
    loss_max = max(
        (float(frame["packet_loss_percent"].max()) for frame in frames.values()
         if not frame.empty and frame["packet_loss_percent"].notna().any()),
        default=0.0,
    )
    fig.update_xaxes(
        title_text="Horário local · São Paulo", showgrid=True, gridcolor="#334155",
        tickfont={"color": "#cbd5e1"}, title_font={"color": "#cbd5e1"},
        row=3, col=1, rangeslider_visible=True,
    )
    fig.update_yaxes(gridcolor="#334155", tickfont={"color": "#cbd5e1"})
    fig.update_yaxes(range=[0, max(10, min(110, loss_max * 1.1))], row=3, col=1)
    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        height=690, template="plotly_dark", hovermode="x unified",
        margin={"l": 20, "r": 25, "t": 75, "b": 30},
        legend={"orientation": "h", "y": 1.03, "x": 1, "xanchor": "right"},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.35)",
        font={"color": "#e2e8f0"},
    )
    st.plotly_chart(fig, use_container_width=True, key=f"quality_{title}")


def _metric_text(value, suffix: str = "") -> str:
    return f"{float(value):.2f}{suffix}" if value is not None and pd.notna(value) else "—"


WORK_SCHEDULE_FILE = settings.DATA_DIR / "work_schedules.json"
DEFAULT_WORK_SCHEDULE = {"enabled": True, "start": "07:00", "end": "18:00"}
MIN_FEEDBACKS_TO_TRAIN = 15
MIN_FEEDBACKS_PER_CLASS = 5


def _load_work_schedules() -> dict:
    try:
        data = json.loads(WORK_SCHEDULE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _work_schedule(machine_id: str) -> dict:
    schedule = _load_work_schedules().get(machine_id, {})
    result = {**DEFAULT_WORK_SCHEDULE, **schedule}
    try:
        time.fromisoformat(result["start"])
        time.fromisoformat(result["end"])
    except (TypeError, ValueError):
        result = DEFAULT_WORK_SCHEDULE.copy()
    return result


def _save_work_schedule(machine_id: str, schedule: dict) -> None:
    schedules = _load_work_schedules()
    schedules[machine_id] = {
        "enabled": bool(schedule["enabled"]),
        "start": schedule["start"].strftime("%H:%M"),
        "end": schedule["end"].strftime("%H:%M"),
    }
    WORK_SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = WORK_SCHEDULE_FILE.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(schedules, indent=2), encoding="utf-8")
    temporary_file.replace(WORK_SCHEDULE_FILE)


def _filter_records_to_work_schedule(records: list[dict], schedule: dict) -> list[dict]:
    if not schedule.get("enabled", True):
        return records
    start = time.fromisoformat(schedule["start"])
    end = time.fromisoformat(schedule["end"])
    filtered = []
    for record in records:
        measured_at = pd.to_datetime(record.get("measured_at"), errors="coerce", utc=True)
        if pd.isna(measured_at):
            continue
        local_time = measured_at.tz_convert("America/Sao_Paulo").time().replace(second=0, microsecond=0)
        if start <= end:
            inside = start <= local_time <= end
        else:
            inside = local_time >= start or local_time <= end
        if inside:
            filtered.append(record)
    return filtered


def _filter_client_summary_to_work_schedules(clients_data: list[dict]) -> None:
    """Mantém os cards do início consistentes com os horários de coleta configurados."""
    for client_data in clients_data:
        machines = list(client_data["local_machines"])
        if client_data.get("internet_machine"):
            machines.append(client_data["internet_machine"])
        for machine_data in machines:
            machine = machine_data["machine"]
            schedule = _work_schedule(machine.id)
            records = _filter_records_to_work_schedule(_cached_measurements(machine.id, 24, 2000), schedule)
            machine_data["status_events"] = _filter_records_to_work_schedule(
                machine_data.get("status_events", []), schedule
            )
            latest_measurement = records[-1] if records else None
            latest_failure = max(
                (event for event in machine_data["status_events"]
                 if event.get("event_type") in ("unreachable", "packet_loss")),
                key=lambda event: event.get("measured_at", ""),
                default=None,
            )
            if latest_failure and (
                not latest_measurement
                or latest_failure.get("measured_at", "") > latest_measurement.get("measured_at", "")
            ):
                latest_measurement = {
                    "latency_ms": latest_failure.get("latency_ms"),
                    "jitter_ms": latest_failure.get("jitter_ms"),
                    "packet_loss_percent": latest_failure.get("packet_loss_percent", 100.0),
                    "packets_sent": latest_failure.get("packets_sent", 0),
                    "packets_received": latest_failure.get("packets_received", 0),
                    "status": "unreachable",
                    "measured_at": latest_failure.get("measured_at"),
                }
            machine_data["latest_measurement"] = latest_measurement
            reachable = [record for record in records if record.get("status") in ("ok", "partial")]
            latencies = [float(r["latency_ms"]) for r in reachable if r.get("latency_ms") is not None]
            jitters = [float(r["jitter_ms"]) for r in reachable if r.get("jitter_ms") is not None]
            good_count = sum(1 for record in reachable if record.get("status") == "ok")
            availability = good_count / len(reachable) * 100 if reachable else 0
            status_detail = "Estável" if availability >= 95 else "Instável" if availability >= 80 else "Crítico" if availability > 0 else "Sem dados"
            machine_data["quality_metrics"] = {
                "avg_jitter": sum(jitters) / len(jitters) if jitters else None,
                "min_latency": min(latencies) if latencies else None,
                "max_latency": max(latencies) if latencies else None,
                "availability_pct": availability if reachable else None,
                "status_detail": status_detail,
            }


def _render_work_schedule_card(machine) -> None:
    current = _work_schedule(machine.id)
    with st.container(border=True):
        st.markdown(f"**{machine.tag} · horário de trabalho**")
        with st.form(f"work_schedule_form_{machine.id}"):
            enabled = st.checkbox(
                "Ignorar medições fora do horário de trabalho",
                value=current["enabled"],
                key=f"work_schedule_enabled_{machine.id}",
            )
            start_default = time.fromisoformat(current["start"])
            end_default = time.fromisoformat(current["end"])
            start_col, end_col = st.columns(2)
            start = start_col.time_input(
                "Início", value=start_default, step=900,
                key=f"work_schedule_start_{machine.id}",
            )
            end = end_col.time_input(
                "Fim", value=end_default, step=900,
                key=f"work_schedule_end_{machine.id}",
            )
            submitted = st.form_submit_button("Salvar horário", use_container_width=True)
        if submitted:
            if start == end:
                st.error("O horário de início e fim precisa ser diferente.")
            else:
                _save_work_schedule(machine.id, {"enabled": enabled, "start": start, "end": end})
                st.rerun()
        st.caption("Fuso horário: São Paulo. O horário salvo também controla a coleta deste equipamento.")


def _distinct_feedback_counts(feedbacks: list[dict]) -> dict[str, int]:
    counts = {"bom": 0, "medio": 0, "ruim": 0}
    seen_samples = set()
    for feedback in sorted(feedbacks, key=lambda item: item.get("created_at", ""), reverse=True):
        label = str(feedback.get("label", "")).lower()
        if label not in counts:
            continue
        notes = str(feedback.get("notes") or "")
        key = notes if notes.startswith("source_measurement_at=") else feedback.get("created_at")
        if key in seen_samples:
            continue
        seen_samples.add(key)
        counts[label] += 1
    return counts


def _start_feedback_training(machine_id: str) -> str:
    training_dir = settings.DATA_DIR / "ml_training"
    training_dir.mkdir(parents=True, exist_ok=True)
    lock_file = training_dir / f"{machine_id}.lock"
    if lock_file.exists() and lock_file.stat().st_mtime >= datetime.now().timestamp() - 3600:
        return "O treinamento deste equipamento já está em andamento."
    lock_file.unlink(missing_ok=True)

    project_root = Path(__file__).resolve().parents[1]
    log_file = training_dir / f"{machine_id}.log"
    command = [
        sys.executable, "-m", "supadiag.ml_auto_train",
        "--machine-id", machine_id, "--epochs", "15",
    ]
    try:
        with log_file.open("a", encoding="utf-8") as output:
            subprocess.Popen(
                command,
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return "Avaliações suficientes: treinamento automático iniciado em segundo plano."
    except OSError as exc:
        return f"Avaliação salva, mas não foi possível iniciar o treinamento: {exc}"


def _record_dashboard_feedback(machine, label: str, measurement: dict | None) -> None:
    """Salva a avaliação do card e inicia retreino quando o conjunto está balanceado."""
    try:
        repo = get_repository()
        saved = repo.save_feedback(machine.id, label, measurement)
        if not saved:
            st.error("Não foi possível salvar a avaliação.")
            return

        feedbacks = repo.list_machine_feedback(machine_id=machine.id, limit=2000)
        counts = _distinct_feedback_counts(feedbacks)
        total = sum(counts.values())
        if total >= MIN_FEEDBACKS_TO_TRAIN and all(
            value >= MIN_FEEDBACKS_PER_CLASS for value in counts.values()
        ):
            message = _start_feedback_training(machine.id)
        else:
            message = (
                f"Treino automático após {MIN_FEEDBACKS_TO_TRAIN} amostras distintas, com pelo menos "
                f"{MIN_FEEDBACKS_PER_CLASS} por classe. Agora: Boa {counts['bom']}, "
                f"Média {counts['medio']}, Ruim {counts['ruim']}."
            )
        st.success(f"Avaliação {label} registrada para {machine.tag}. {message}")
    except Exception as exc:
        st.error(f"Falha ao registrar a avaliação: {exc}")


def _render_link_summary(label: str, frame: pd.DataFrame) -> None:
    st.markdown(f"#### {label}")
    if frame.empty:
        st.info("Sem medições neste período.")
        return
    latest = frame.iloc[-1]
    latency_values = frame["latency_ms"].dropna()
    jitter_values = frame["jitter_ms"].dropna()
    loss_values = frame["packet_loss_percent"].dropna()
    latency_now = latest["latency_ms"]
    jitter_now = latest["jitter_ms"]
    loss_now = latest["packet_loss_percent"]
    cols = st.columns(3)
    cols[0].metric("Melhor latência", _metric_text(latency_values.min() if not latency_values.empty else None, " ms"),
                   delta=f"Agora {_metric_text(latency_now, ' ms')}", delta_color="off")
    cols[1].metric("Melhor jitter", _metric_text(jitter_values.min() if not jitter_values.empty else None, " ms"),
                   delta=f"Agora {_metric_text(jitter_now, ' ms')}", delta_color="off")
    average_loss = loss_values.mean() if not loss_values.empty else None
    cols[2].metric("Perda média", _metric_text(average_loss, "%"),
                   delta=f"Agora {_metric_text(loss_now, '%')}", delta_color="inverse")
    status = str(latest.get("status", "")).lower()
    if status == "unreachable":
        st.error(f"Conexão sem resposta na última amostra · {latest['timestamp'].strftime('%d/%m %H:%M:%S')}")
    elif status in ("partial", "packet_loss"):
        st.warning(f"Perda de conectividade detectada · {latest['timestamp'].strftime('%d/%m %H:%M:%S')}")
    elif status == "error":
        st.warning(f"Falha na coleta da última amostra; não há dados para concluir o estado da conexão · {latest['timestamp'].strftime('%d/%m %H:%M:%S')}")
    else:
        st.caption(f"Última amostra: {latest['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}")


def _degradation_signals(label: str, frame: pd.DataFrame) -> tuple[list[str], bool]:
    # A local collector failure has no network metrics and must not count as
    # a healthy zero-loss observation or distort the baseline window.
    frame = frame[frame["status"] != "error"]
    if len(frame) < 8:
        return [], False
    split = max(2, int(len(frame) * 0.75))
    baseline = frame.iloc[:split]
    recent = frame.iloc[split:]
    if recent.empty:
        return [], False
    signals = []
    thresholds = {
        "latency_ms": ("latência", 5.0, 80.0),
        "jitter_ms": ("jitter", 2.0, 30.0),
        "packet_loss_percent": ("perda de pacotes", 1.0, 2.0),
    }
    for metric, (name, absolute_rise, warning_level) in thresholds.items():
        before_values = baseline[metric].dropna()
        recent_values = recent[metric].dropna()
        if before_values.empty or recent_values.empty:
            continue
        before = float(before_values.median())
        after = float(recent_values.median())
        relative_rise = (after - before) / max(abs(before), 1.0)
        rose = after - before >= absolute_rise and relative_rise >= 0.2
        crossed = before < warning_level <= after
        if rose or crossed:
            signals.append(f"{label}: {name} passou de {_metric_text(before)} para {_metric_text(after)}")
    return signals, True


def _latency_comparison_chart(local: pd.DataFrame, internet: pd.DataFrame, title: str) -> None:
    fig = go.Figure()
    for frame, label, color in (
        (local, "Rede local / equipamento", "#60a5fa"),
        (internet, "Internet check / saída do monitor", "#f59e0b"),
    ):
        values = frame.dropna(subset=["latency_ms"])
        if values.empty:
            continue
        fig.add_trace(go.Scatter(
            x=values["timestamp"], y=values["latency_ms"], mode="lines+markers",
            name=label, line={"color": color, "width": 2}, marker={"size": 4},
            hovertemplate="%{x|%d/%m %H:%M:%S}<br>%{y:.2f} ms<extra>" + label + "</extra>",
        ))
    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        height=420, template="plotly_dark", hovermode="x unified",
        margin={"l": 20, "r": 25, "t": 65, "b": 30},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend={"orientation": "h", "y": 1.03, "x": 1, "xanchor": "right"},
    )
    fig.update_xaxes(title_text="Horário local · São Paulo", showgrid=True)
    fig.update_yaxes(title_text="Latência (ms)", rangemode="tozero", showgrid=True)
    st.plotly_chart(fig, use_container_width=True, key=f"latency_compare_{title}")


def _render_latency_diagnosis(local: pd.DataFrame, internet: pd.DataFrame, local_label: str) -> None:
    if local.empty or internet.empty:
        st.info("Selecione uma janela com amostras dos dois lados para comparar o equipamento e o internet check.")
        return
    local_series = local.dropna(subset=["latency_ms"]).set_index("timestamp")["latency_ms"].resample("5min").median()
    internet_series = internet.dropna(subset=["latency_ms"]).set_index("timestamp")["latency_ms"].resample("5min").median()
    paired = pd.concat({"local": local_series, "internet": internet_series}, axis=1).dropna()
    if len(paired) < 6:
        st.info("Ainda não há amostras simultâneas suficientes para comparar as oscilações. São necessários ao menos 6 intervalos de 5 minutos com dados dos dois lados.")
        return

    baseline = paired.iloc[:-1].tail(12).median()
    latest = paired.iloc[-1]
    local_rise = float(latest["local"] - baseline["local"])
    internet_rise = float(latest["internet"] - baseline["internet"])
    local_limit = max(5.0, abs(float(baseline["local"])) * 0.2)
    internet_limit = max(5.0, abs(float(baseline["internet"])) * 0.2)
    local_up = local_rise >= local_limit
    internet_up = internet_rise >= internet_limit
    correlation = paired.diff().corr().loc["local", "internet"]

    summary_cols = st.columns(3)
    summary_cols[0].metric("Aumento · rede local", f"{local_rise:+.1f} ms")
    summary_cols[1].metric("Aumento · internet check", f"{internet_rise:+.1f} ms")
    summary_cols[2].metric("Correlação das variações", f"{correlation:.2f}" if pd.notna(correlation) else "—")

    if local_up and internet_up:
        st.warning(f"As duas latências subiram juntas. É compatível com oscilação em um trecho compartilhado da rota até {local_label}, mas a correlação sozinha não identifica qual link causou a mudança.")
    elif local_up:
        st.warning(f"A latência até {local_label} subiu, enquanto o internet check permaneceu relativamente estável. O sinal aponta para o trecho local ou túnel entre os pontos.")
    elif internet_up:
        st.warning("O internet check subiu sem aumento semelhante na latência do equipamento. O sinal aponta para a saída de internet do ponto onde o monitor coleta.")
    else:
        st.success("Não há aumento relevante na última janela comparável. As duas séries permaneceram próximas à própria linha de base.")
    st.caption("Compara o último bloco de 5 minutos com a mediana dos até 60 minutos anteriores; considera aumento relevante acima de 5 ms e 20%. O internet check mede a saída do host coletor até um destino público, então coincidência temporal não prova causa isoladamente.")
    st.caption("Para separar conclusivamente a Starlink da internet cabeada na outra ponta, é necessário coletar um INTERNET-CHECK em cada ponta do túnel.")


def render_client_detail(repo: FrontendRepository, client_id: str) -> None:
    """Painel operacional de qualidade para o cliente selecionado."""
    client = repo.get_client(client_id)
    if not client:
        st.error("Cliente não encontrado.")
        if st.button("← Voltar aos clientes"):
            st.session_state.view_mode = "cards"
            st.session_state.selected_client_id = None
            st.rerun()
        return

    machines = repo.list_machines(client_id=client_id, active_only=True)
    local_machines = [machine for machine in machines if machine.tag != "INTERNET-CHECK"]
    internet_machine = next((machine for machine in machines if machine.tag == "INTERNET-CHECK"), None)

    top_left, top_right = st.columns([5, 2])
    with top_left:
        if st.button("← Clientes", key="quality_back"):
            st.session_state.view_mode = "cards"
            st.session_state.selected_client_id = None
            st.session_state.selected_machine_id = None
            st.rerun()
        st.title(client.name)
        st.caption("Análise de qualidade · latência, jitter, perda e sinais de degradação")
    with top_right:
        st.markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)
        if st.button("↻ Atualizar agora", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        st.caption(f"● Ao vivo · atualiza a cada 30s · agora {datetime.now().strftime('%H:%M:%S')}")

    if not local_machines and not internet_machine:
        st.info("Este cliente ainda não possui máquinas ativas para analisar.")
        return

    controls_left, controls_right = st.columns([1.3, 2.7])
    with controls_left:
        if local_machines:
            machine_options = {f"{machine.tag} · {machine.ip}": machine.id for machine in local_machines}
            selected_id = st.session_state.get("selected_quality_machine_id")
            labels = list(machine_options)
            selected_index = next((i for i, name in enumerate(labels) if machine_options[name] == selected_id), 0)
            selected_label = st.selectbox("Máquina local", labels, index=selected_index, key="quality_machine_picker")
            local_machine_id = machine_options[selected_label]
            local_machine = next(machine for machine in local_machines if machine.id == local_machine_id)
            st.session_state.selected_quality_machine_id = local_machine_id
        else:
            local_machine_id = None
            local_machine = None
            st.info("Sem máquina local cadastrada.")
    with controls_right:
        period_options = {"1 hora": 1, "6 horas": 6, "24 horas": 24, "7 dias": 168, "30 dias": 720}
        period_label = st.segmented_control("Janela do histórico", list(period_options), default="24 horas", key="quality_period")
        if period_label is None:
            period_label = "24 horas"
    hours = period_options[period_label]

    with st.expander("Horário de trabalho · ignorar medições fora do período", expanded=False):
        st.caption("O padrão é 07:00–18:00, no horário de São Paulo. O horário salvo também pausa a coleta do equipamento fora desse período.")
        schedule_cols = st.columns(2)
        if local_machine:
            with schedule_cols[0]:
                _render_work_schedule_card(local_machine)
        if internet_machine:
            with schedule_cols[1 if local_machine else 0]:
                _render_work_schedule_card(internet_machine)

    local_measurements = _cached_measurements(local_machine_id, hours, 2000) if local_machine_id else []
    local_events = _cached_quality_events(local_machine_id, hours) if local_machine_id else []
    internet_measurements = _cached_measurements(internet_machine.id, hours, 2000) if internet_machine else []
    internet_events = _cached_quality_events(internet_machine.id, hours) if internet_machine else []

    local_schedule = _work_schedule(local_machine_id) if local_machine_id else DEFAULT_WORK_SCHEDULE
    internet_schedule = _work_schedule(internet_machine.id) if internet_machine else DEFAULT_WORK_SCHEDULE
    local_measurements = _filter_records_to_work_schedule(local_measurements, local_schedule)
    local_events = _filter_records_to_work_schedule(local_events, local_schedule)
    internet_measurements = _filter_records_to_work_schedule(internet_measurements, internet_schedule)
    internet_events = _filter_records_to_work_schedule(internet_events, internet_schedule)

    local_frame = _quality_frame(local_measurements, local_events, "Local")
    internet_frame = _quality_frame(internet_measurements, internet_events, "Internet")
    st.caption("Comparações, gráficos, tendência e histórico consideram somente medições dentro dos horários salvos.")

    local_tab, internet_tab, comparison_tab, history_tab, events_tab, diagnostics_tab = st.tabs(
        ["Rede local", "Internet", "Comparação de rota", "Histórico completo", "Eventos", "Diagnóstico avançado"]
    )
    with local_tab:
        st.markdown(f"### Rede local · {local_machine.tag if local_machine else 'indisponível'}")
        latest_local_has_loss = False
        latest_local_collection_error = False
        if not local_frame.empty:
            latest_local = local_frame.iloc[-1]
            latest_local_collection_error = latest_local.get("status") == "error"
            latest_local_has_loss = (
                latest_local.get("status") in ("unreachable", "packet_loss")
                and float(latest_local.get("packet_loss_percent") or 0) > 0
            )
            if latest_local_collection_error:
                st.warning(
                    "Falha no processo de coleta da última amostra local. "
                    "Isso não confirma perda na rede; latência, jitter e perda estão indeterminados."
                )
            if latest_local_has_loss:
                st.error(
                    "O Supabase recebeu a amostra local, mas houve perda de conectividade: "
                    f"{_metric_text(latest_local.get('packet_loss_percent'), '%')}. "
                    "Quando nenhum ping recebe resposta, latência e jitter ficam indisponíveis."
                )
        if not latest_local_has_loss and not latest_local_collection_error:
            local_signals, enough_local_data = _degradation_signals("Rede local", local_frame)
            if local_signals:
                st.warning("Sinais recentes: " + " · ".join(local_signals))
            elif enough_local_data:
                st.success("Sem aumento sustentado detectado na rede local nesta janela.")
            else:
                st.info("Ainda são necessárias mais amostras para estabelecer uma linha de base local.")
        _render_link_summary("Resumo da rede local", local_frame)
        _quality_chart(local_frame, pd.DataFrame(columns=local_frame.columns), f"Rede local · {period_label}")
        st.caption("Linhas tracejadas indicam limites de atenção e críticos; a linha espessa mostra a mediana móvel de 5 amostras.")
    with internet_tab:
        st.markdown("### Internet · INTERNET-CHECK")
        st.caption("Esta série mede a conexão pública a partir do host que executa o coletor associado a este cliente.")
        if not internet_machine:
            st.info("Este cliente ainda não possui um equipamento INTERNET-CHECK.")
        else:
            current_records = _filter_records_to_work_schedule(
                _cached_measurements(internet_machine.id, 24, 1000), internet_schedule
            )
            current_frame = _quality_frame(current_records, [], "Internet")
            if current_frame.empty:
                st.info("Sem amostras de internet dentro do horário de trabalho configurado.")
            else:
                current = current_frame.iloc[-1]
                reachable = current_frame[current_frame["status"].isin(["ok", "partial"])]
                latest_response = reachable.iloc[-1] if not reachable.empty else None
                current_cols = st.columns(3)
                current_cols[0].metric("Latência da última resposta", _metric_text(latest_response["latency_ms"] if latest_response is not None else None, " ms"))
                current_cols[1].metric("Jitter da última resposta", _metric_text(latest_response["jitter_ms"] if latest_response is not None else None, " ms"))
                current_cols[2].metric("Perda atual", _metric_text(current["packet_loss_percent"], "%"))
                if latest_response is not None:
                    st.caption(f"Última resposta: {latest_response['timestamp'].strftime('%d/%m/%Y %H:%M:%S')} · horário de São Paulo")
                if current.get("status") == "unreachable":
                    st.error(
                        f"A última amostra não recebeu resposta · {current['timestamp'].strftime('%d/%m/%Y %H:%M:%S')} · "
                        f"perda {_metric_text(current['packet_loss_percent'], '%')}"
                    )
            current_events = _filter_records_to_work_schedule(
                _cached_quality_events(internet_machine.id, 24), internet_schedule
            )
            if current_events:
                latest_event = max(current_events, key=lambda event: event.get("measured_at", ""))
                if latest_event.get("event_type") in ("unreachable", "packet_loss"):
                    event_time = pd.to_datetime(latest_event["measured_at"], utc=True).tz_convert("America/Sao_Paulo")
                    st.error(f"Último evento de conectividade: {latest_event['event_type']} · {event_time.strftime('%d/%m/%Y %H:%M:%S')} · perda { _metric_text(latest_event.get('packet_loss_percent'), '%') }")

            st.markdown("#### Histórico de conexão com a Internet")
            now_sp = datetime.now(ZoneInfo("America/Sao_Paulo"))
            start_date_col, start_time_col, end_date_col, end_time_col = st.columns(4)
            start_date = start_date_col.date_input("Data inicial", value=(now_sp - timedelta(days=7)).date(), key=f"internet_start_date_{internet_machine.id}")
            start_clock = start_time_col.time_input("Hora inicial", value=time(0, 0), step=900, key=f"internet_start_time_{internet_machine.id}")
            end_date = end_date_col.date_input("Data final", value=now_sp.date(), key=f"internet_end_date_{internet_machine.id}")
            end_clock = end_time_col.time_input("Hora final", value=now_sp.time().replace(second=0, microsecond=0), step=900, key=f"internet_end_time_{internet_machine.id}")
            range_start = datetime.combine(start_date, start_clock, tzinfo=ZoneInfo("America/Sao_Paulo"))
            range_end = datetime.combine(end_date, end_clock, tzinfo=ZoneInfo("America/Sao_Paulo"))
            if range_start > range_end:
                st.error("A data e hora inicial precisam ser anteriores à data e hora final.")
            else:
                range_measurements = _cached_measurements_between(
                    internet_machine.id, range_start.astimezone(ZoneInfo("UTC")).isoformat(),
                    range_end.astimezone(ZoneInfo("UTC")).isoformat(), 20000,
                )
                range_events = _cached_quality_events_between(
                    internet_machine.id, range_start.astimezone(ZoneInfo("UTC")).isoformat(),
                    range_end.astimezone(ZoneInfo("UTC")).isoformat(), 20000,
                )
                range_measurements = _filter_records_to_work_schedule(range_measurements, internet_schedule)
                range_events = _filter_records_to_work_schedule(range_events, internet_schedule)
                internet_history = _quality_frame(range_measurements, range_events, "Internet")
                if internet_history.empty:
                    st.info("Nenhuma medição ou evento de conectividade nesse intervalo e horário de trabalho.")
                else:
                    _quality_chart(pd.DataFrame(columns=internet_history.columns), internet_history, "Histórico de latência, jitter e perda · Internet")
                    history_table = internet_history.sort_values("timestamp", ascending=False).copy()
                    history_table["timestamp"] = history_table["timestamp"].dt.strftime("%d/%m/%Y %H:%M:%S")
                    history_table = history_table.rename(columns={
                        "timestamp": "Horário", "source": "Conexão", "latency_ms": "Latência (ms)",
                        "jitter_ms": "Jitter (ms)", "packet_loss_percent": "Perda (%)", "status": "Estado",
                    })
                    st.dataframe(history_table, use_container_width=True, hide_index=True)
                    st.download_button(
                        "Baixar histórico da Internet (CSV)", internet_history.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"internet_{client.id[:8]}.csv", mime="text/csv",
                    )
    with comparison_tab:
        st.markdown("### Qual trecho oscilou?")
        _render_latency_diagnosis(local_frame, internet_frame, local_machine.tag if local_machine else "equipamento local")
        _latency_comparison_chart(local_frame, internet_frame, f"Latência local x internet · {period_label}")
        st.caption("O gráfico usa o período selecionado acima. Para ampliar ou reduzir a análise, altere a janela do histórico.")

    with history_tab:
        combined = pd.concat([local_frame, internet_frame], ignore_index=True)
        if combined.empty:
            st.info("Nenhuma amostra encontrada para o período selecionado.")
        else:
            history = combined.sort_values("timestamp", ascending=False).copy()
            history["timestamp"] = history["timestamp"].dt.strftime("%d/%m/%Y %H:%M:%S")
            history = history.rename(columns={
                "timestamp": "Horário", "source": "Conexão", "latency_ms": "Latência (ms)",
                "jitter_ms": "Jitter (ms)", "packet_loss_percent": "Perda (%)", "status": "Estado",
            })
            st.dataframe(history, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar histórico CSV", combined.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"qualidade_{client.id[:8]}_{period_label.replace(' ', '_')}.csv",
                mime="text/csv",
            )

    with events_tab:
        event_rows = []
        for link, events in (("Local", local_events), ("Internet", internet_events)):
            for event in events:
                event_rows.append({
                    "Horário": event.get("measured_at", ""),
                    "Conexão": link,
                    "Evento": event.get("event_type", ""),
                    "Latência (ms)": event.get("latency_ms"),
                    "Jitter (ms)": event.get("jitter_ms"),
                    "Perda (%)": event.get("packet_loss_percent"),
                })
        if event_rows:
            st.dataframe(pd.DataFrame(event_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum evento de conectividade registrado nesta janela.")

    with diagnostics_tab:
        st.markdown("#### Traceroute, regras de alerta e ferramentas de IA")
        st.caption("As ferramentas detalhadas existentes ficam separadas do painel de qualidade para manter esta análise fácil de ler.")
        if st.button("Abrir diagnóstico completo", key="open_advanced_diagnostics"):
            st.session_state.show_advanced_client_detail = True
        if st.session_state.get("show_advanced_client_detail"):
            _render_advanced_client_detail(repo, client_id)


def main() -> None:
    init_session_state()
    config_error = settings.validation_error()
    if config_error:
        st.title("Network analysis")
        st.error(config_error)
        st.code("SUPABASE_URL=https://SEU_PROJETO.supabase.co\nSUPABASE_SECRET_KEY=sb_secret_...", language="text")
        st.caption("Copie .env.example para .env, preencha as credenciais do Supabase e atualize esta página.")
        st.stop()
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
