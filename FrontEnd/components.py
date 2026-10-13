# FrontEnd/components.py
# Componentes de UI reutilizáveis para o dashboard Streamlit

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from typing import Optional, List, Dict, Any

from repository import Machine, Measurement, Client

# Import settings for sidebar caption
from config import settings


def _reachability_label(machine_data: dict) -> tuple[str, str]:
    """Retorna (icon, color) baseado no status de alcançabilidade."""
    latest = machine_data.get("latest_measurement")
    status_events = machine_data.get("status_events", [])
    
    if latest and latest.get("status") == "ok":
        return "🟢", "#28a745"
    elif latest and latest.get("status") == "partial":
        return "🟡", "#ffc107"
    elif latest and latest.get("status") in ("unreachable", "error"):
        return "🔴", "#dc3545"
    elif status_events:
        last_event = status_events[0]
        etype = last_event.get("event_type", "")
        if etype == "unreachable":
            return "🔴", "#dc3545"
        elif etype == "packet_loss":
            return "🟡", "#ffc107"
        elif etype == "reachable":
            return "🟢", "#28a745"
    return "⚪", "#6c757d"


def render_client_card(
    client: Client,
    local_machines: List[Dict[str, Any]],
    internet_machine: Optional[Dict[str, Any]],
    on_click: callable,
    on_feedback: Optional[callable] = None,
) -> None:
    """
    Renderiza um card consolidado por cliente com:
    - Rede local (máquinas locais)
    - Internet (INTERNET-CHECK)
    
    Args:
        client: Objeto Client
        local_machines: Lista de dicts com machine + latest_measurement
        internet_machine: Dict com machine + latest_measurement do INTERNET-CHECK ou None
        on_click: Callback ao clicar no card
    """
    # Calcula acurácia baseada nos feedbacks da internet
    accuracy = 0
    try:
        from supabase import create_client
        from config import settings as fe_settings
        sb = create_client(fe_settings.SUPABASE_URL, fe_settings.SUPABASE_KEY)
        target_id = internet_machine["machine"].id if internet_machine else (local_machines[0]["machine"].id if local_machines else None)
        if target_id:
            feedbacks = sb.table("machine_feedback").select("label").eq("machine_id", target_id).execute().data or []
            if feedbacks:
                total = len(feedbacks)
                score = sum(1.0 if f["label"] == "bom" else 0.5 if f["label"] == "medio" else 0.0 for f in feedbacks)
                accuracy = round(score / total * 100, 1)
    except Exception:
        accuracy = 0
    
    # Calcula status geral do cliente
    total_machines = len(local_machines) + (1 if internet_machine else 0)
    ok_count = 0
    warning_count = 0
    critical_count = 0
    no_data_count = 0
    
    for m in local_machines:
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
    
    if internet_machine and internet_machine["latest_measurement"]:
        status = internet_machine["latest_measurement"].get("status", "")
        if status == "ok":
            ok_count += 1
        elif status == "partial":
            warning_count += 1
        elif status == "unreachable":
            critical_count += 1
    elif internet_machine:
        no_data_count += 1
    
    # Status geral do card
    if critical_count > 0:
        overall_status_color = "#dc3545"
        overall_status_icon = "🔴"
        overall_status_text = "CRÍTICO"
    elif warning_count > 0:
        overall_status_color = "#ffc107"
        overall_status_icon = "🟡"
        overall_status_text = "ATENÇÃO"
    elif ok_count > 0:
        overall_status_color = "#28a745"
        overall_status_icon = "🟢"
        overall_status_text = "OK"
    else:
        overall_status_color = "#6c757d"
        overall_status_icon = "⚪"
        overall_status_text = "SEM DADOS"
    
    # Última medição de qualquer máquina
    last_measured_at = "—"
    all_measurements = [m["latest_measurement"] for m in local_machines if m["latest_measurement"]]
    if internet_machine and internet_machine["latest_measurement"]:
        all_measurements.append(internet_machine["latest_measurement"])
    
    if all_measurements:
        latest_overall = max(all_measurements, key=lambda x: x.get("measured_at", ""))
        try:
            dt_utc = pd.to_datetime(latest_overall["measured_at"])
            if dt_utc.tz is not None:
                last_measured_at = dt_utc.tz_convert("America/Sao_Paulo").strftime("%Y-%m-%d %H:%M")
            else:
                last_measured_at = dt_utc.strftime("%Y-%m-%d %H:%M")
        except Exception:
            last_measured_at = latest_overall.get("measured_at", "")[:16].replace('T', ' ')
    
    # Calcula latência média da rede local
    local_latencies = [m["latest_measurement"].get("latency_ms") for m in local_machines if m["latest_measurement"] and m["latest_measurement"].get("latency_ms") is not None]
    avg_local_latency = sum(local_latencies) / len(local_latencies) if local_latencies else None
    
    # Dados da internet
    internet_latency = None
    internet_loss = None
    if internet_machine and internet_machine["latest_measurement"]:
        internet_latency = internet_machine["latest_measurement"].get("latency_ms")
        internet_loss = internet_machine["latest_measurement"].get("packet_loss_percent")
    
    internet_jitter = None
    internet_min_latency = None
    internet_max_latency = None
    internet_availability = None
    internet_status_color = "#6c757d"
    internet_status_label = "Sem dados"
    
    if internet_machine:
        quality = internet_machine.get("quality_metrics") or {}
        internet_jitter = quality.get("avg_jitter")
        internet_min_latency = quality.get("min_latency")
        internet_max_latency = quality.get("max_latency")
        internet_availability = quality.get("availability_pct")
        status_detail = quality.get("status_detail") or "Sem dados"
        internet_status_color = "#28a745" if status_detail == "Estável" else "#ffc107" if status_detail == "Instável" else "#dc3545" if status_detail == "Crítico" else "#6c757d"
        internet_status_label = status_detail
    
    # Card HTML
    card_html = f"""
<div style="
    border: 1px solid #e0e0e0;
    border-radius: 12px;
    padding: 20px;
    margin: 8px 0;
    background: white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    transition: box-shadow 0.2s, transform 0.2s;
    cursor: pointer;
" onmouseover="this.style.boxShadow='0 6px 20px rgba(0,0,0,0.12)'; this.style.transform='translateY(-2px)'"
   onmouseout="this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)'; this.style.transform='translateY(0)'"
   onclick="document.getElementById('hidden_btn_{client.id}').click();">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px;">
            <div>
                <h3 style="margin: 0 0 4px 0; color: #1f77b4; font-size: 1.3rem; font-weight: 700;">
                    {client.name}
                </h3>
                <p style="margin: 0; color: #888; font-size: 0.85rem;">
                    {len(local_machines)} máquina(s) local(is) • {1 if internet_machine else 0} internet check
                </p>
                <p style="margin: 4px 0 0 0; color: #888; font-size: 0.75rem;">
                    Acurácia IA: <span style="color: {'#28a745' if accuracy >= 80 else '#ffc107' if accuracy >= 50 else '#dc3545'}; font-weight: 600;">{accuracy}%</span>
                </p>
            </div>
            <div style="text-align: right;">
                <span style="
                    background: {overall_status_color};
                    color: white;
                    padding: 6px 14px;
                    border-radius: 16px;
                    font-size: 0.8rem;
                    font-weight: 600;
                    display: inline-block;
                ">
                    {overall_status_icon} {overall_status_text}
                </span>
            </div>
        </div>
        
        <!-- Métricas da Rede Local -->
        <div style="margin-bottom: 16px; padding: 12px; background: #f8f9fa; border-radius: 8px; border-left: 3px solid #1f77b4;">
            <div style="font-size: 0.75rem; color: #666; text-transform: uppercase; font-weight: 600; margin-bottom: 8px; display: flex; gap: 8px; align-items: center;">
                🖥️ Rede Local
                <span style="background:#1f77b4;color:white;padding:1px 6px;border-radius:4px;font-size:0.65rem;">{len(local_machines)} ativa(s)</span>
            </div>
            <div style="display: flex; gap: 16px;">
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 1.5rem; font-weight: 700; color: {'#28a745' if avg_local_latency and avg_local_latency < 50 else '#ffc107' if avg_local_latency and avg_local_latency < 150 else '#dc3545' if avg_local_latency else '#6c757d'};">
                        {f'{avg_local_latency:.1f} ms' if avg_local_latency is not None else '—'}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Lat. Média</div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 1.5rem; font-weight: 700; color: {'#28a745' if ok_count > 0 and critical_count == 0 and warning_count == 0 else '#ffc107' if warning_count > 0 else '#dc3545' if critical_count > 0 else '#6c757d'};">
                        {ok_count}/{total_machines}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">OK / Total</div>
                </div>
            </div>
        </div>
        
        <!-- Status de Alcançabilidade das Máquinas Locais -->
        <div style="margin-bottom: 16px; padding: 12px; background: #f8f9fa; border-radius: 8px; border-left: 3px solid #6c757d;">
            <div style="font-size: 0.75rem; color: #666; text-transform: uppercase; font-weight: 600; margin-bottom: 8px;">
                📡 Alcançabilidade
            </div>
            {_render_reachability_list(local_machines)}
        </div>
        
        <!-- Métricas da Internet -->
        <div style="padding: 12px; background: #f8f9fa; border-radius: 8px; border-left: 3px solid #28a745;">
            <div style="font-size: 0.75rem; color: #666; text-transform: uppercase; font-weight: 600; margin-bottom: 8px; display: flex; gap: 8px; align-items: center; justify-content: space-between;">
                <span>🌐 Internet</span>
                <span style="background:{internet_status_color};color:white;padding:1px 6px;border-radius:4px;font-size:0.65rem;">{internet_status_label}</span>
            </div>
            <div style="display: flex; gap: 16px;">
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 1.5rem; font-weight: 700; color: {'#28a745' if internet_latency and internet_latency < 50 else '#ffc107' if internet_latency and internet_latency < 150 else '#dc3545' if internet_latency else '#6c757d'};">
                        {f'{internet_latency:.1f} ms' if internet_latency is not None else '—'}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Latência</div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 1.5rem; font-weight: 700; color: {'#28a745' if internet_loss is not None and internet_loss == 0 else '#ffc107' if internet_loss is not None and internet_loss < 5 else '#dc3545' if internet_loss is not None else '#6c757d'};">
                        {f'{internet_loss:.1f}%' if internet_loss is not None else '—'}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Perda</div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 1.5rem; font-weight: 700; color: #1f77b4;">
                        {f'{internet_jitter:.1f} ms' if internet_jitter is not None else '—'}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Jitter</div>
                </div>
            </div>
            <div style="display: flex; gap: 16px; margin-top: 10px;">
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 0.85rem; font-weight: 600; color: #333;">
                        {internet_status_label}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Status</div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 0.85rem; font-weight: 600; color: #333;">
                        {f'{internet_min_latency:.1f} ms' if internet_min_latency is not None else '—'}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Min</div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 0.85rem; font-weight: 600; color: #333;">
                        {f'{internet_max_latency:.1f} ms' if internet_max_latency is not None else '—'}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Max</div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="font-size: 0.85rem; font-weight: 600; color: #333;">
                        {f'{internet_availability:.1f}%' if internet_availability is not None else '—'}
                    </div>
                    <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Disponibilidade</div>
                </div>
            </div>
        </div>
        
        <div style="margin-top: 12px; text-align: center; color: #888; font-size: 0.75rem;">
            Última atualização: {last_measured_at}
        </div>
    </div>
    """

    # Renderiza card + botão
    container = st.container()
    with container:
        st.html(card_html)
        
        # Botão para ver detalhes do cliente
        if st.button(f"Ver detalhes: {client.name}", key=f"client_card_{client.id}", use_container_width=True):
            on_click(client.id)

        # Feedback por equipamento: cada voto fica associado à máquina e à
        # última amostra apresentada no card (rede local ou Internet).
        if on_feedback:
            feedback_machines = list(local_machines)
            if internet_machine:
                feedback_machines.append(internet_machine)
            if feedback_machines:
                st.markdown("**Como está a conexão?**")
            for machine_data in feedback_machines:
                machine = machine_data["machine"]
                measurement = machine_data.get("latest_measurement")
                st.caption(f"{machine.tag} · classifique a amostra atual")
                feedback_cols = st.columns(3)
                for col, (label, sentiment) in zip(
                    feedback_cols,
                    (("🟢 Boa", "bom"), ("🟡 Média", "medio"), ("🔴 Ruim", "ruim")),
                ):
                    if col.button(
                        label,
                        key=f"dashboard_feedback_{machine.id}_{sentiment}",
                        use_container_width=True,
                        disabled=not measurement,
                    ):
                        on_feedback(machine, sentiment, measurement)


def render_machine_card(
    machine: Machine,
    client: Client,
    latest_measurement: Optional[dict],
    latest_traceroute: Optional[dict],
    latest_alert_event: Optional[dict],
    on_click: callable
) -> None:
    """
    Renderiza um card de máquina com informações resumidas.
    
    Args:
        machine: Objeto Machine
        client: Objeto Client
        latest_measurement: Última medição (dict) ou None
        latest_traceroute: Último traceroute (dict) ou None
        latest_alert_event: Último evento de alerta (dict) ou None
        on_click: Callback ao clicar no card
    """
    # Calcula acurácia baseada nos feedbacks da máquina
    accuracy = 0
    try:
        from supabase import create_client
        from config import settings as fe_settings
        sb = create_client(fe_settings.SUPABASE_URL, fe_settings.SUPABASE_KEY)
        feedbacks = sb.table("machine_feedback").select("label").eq("machine_id", machine.id).execute().data or []
        if feedbacks:
            total = len(feedbacks)
            score = sum(1.0 if f["label"] == "bom" else 0.5 if f["label"] == "medio" else 0.0 for f in feedbacks)
            accuracy = round(score / total * 100, 1)
    except Exception:
        accuracy = 0
    
    # Determina cor do status
    if latest_measurement:
        status = latest_measurement.get("status", "")
        latency = latest_measurement.get("latency_ms")
        loss = latest_measurement.get("packet_loss_percent")
        
        if status == "ok":
            status_color = "#28a745"  # verde
            status_icon = "🟢"
            status_text = "OK"
        elif status == "partial":
            status_color = "#ffc107"  # amarelo
            status_icon = "🟡"
            status_text = "PARCIAL"
        elif status == "unreachable":
            status_color = "#dc3545"  # vermelho
            status_icon = "🔴"
            status_text = "INALCANÇÁVEL"
        else:
            status_color = "#6c757d"  # cinza
            status_icon = "⚪"
            status_text = "ERRO"
    else:
        status_color = "#6c757d"
        status_icon = "⚪"
        status_text = "SEM DADOS"
        latency = None
        loss = None
    
    # Converte timestamp para horário de São Paulo
    last_measured_at = "—"
    if latest_measurement and latest_measurement.get("measured_at"):
        try:
            dt_utc = pd.to_datetime(latest_measurement["measured_at"])
            if dt_utc.tz is not None:
                last_measured_at = dt_utc.tz_convert("America/Sao_Paulo").strftime("%Y-%m-%d %H:%M")
            else:
                last_measured_at = dt_utc.strftime("%Y-%m-%d %H:%M")
        except Exception:
            last_measured_at = latest_measurement.get("measured_at", "")[:16].replace('T', ' ')
    
    # Traceroute badge
    traceroute_badge = render_traceroute_badge(latest_traceroute)
    
    # Alert badge
    alert_badge = render_alert_badge(
        latest_alert_event.get("status") if latest_alert_event else None,
        latest_alert_event.get("severity") if latest_alert_event else None,
        latest_alert_event.get("metric") if latest_alert_event else None,
    )
    
    # Card HTML customizado
    acc_color = "#28a745" if accuracy >= 80 else "#ffc107" if accuracy >= 50 else "#dc3545"
    acc_label = f"{accuracy}%" if accuracy > 0 else "Sem dados"
    card_html = f"""
    <div style="
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
        background: white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        transition: box-shadow 0.2s, transform 0.2s;
        cursor: pointer;
    " onmouseover="this.style.boxShadow='0 4px 12px rgba(0,0,0,0.1)'; this.style.transform='translateY(-2px)'"
       onmouseout="this.style.boxShadow='0 2px 4px rgba(0,0,0,0.05)'; this.style.transform='translateY(0)'">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
                <h4 style="margin: 0 0 4px 0; color: #1f77b4; font-size: 1.1rem; display: flex; align-items: center; gap: 10px;">
                    {machine.tag}
                    <span style="
                        background: {acc_color};
                        color: white;
                        padding: 2px 8px;
                        border-radius: 8px;
                        font-size: 0.7rem;
                        font-weight: 600;
                    ">
                        Acuracia: {acc_label}
                    </span>
                </h4>
                <p style="margin: 0; color: #666; font-size: 0.9rem;">
                    {client.name if client else f"Cliente: {machine.client_id[:8]}..."}
                </p>
                <p style="margin: 4px 0 0 0; color: #888; font-size: 0.8rem; font-family: monospace;">
                    {machine.ip} • {machine.frequency_seconds}s
                </p>
            </div>
            <div style="text-align: right;">
                <span style="
                    background: {status_color};
                    color: white;
                    padding: 4px 10px;
                    border-radius: 12px;
                    font-size: 0.75rem;
                    font-weight: 600;
                    display: inline-block;
                ">
                    {status_text}
                </span>
            </div>
        </div>
        <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid #f0f0f0; display: flex; gap: 16px;">
            <div style="flex: 1; text-align: center;">
                <div style="font-size: 1.3rem; font-weight: 600; color: {'#28a745' if latency and latency < 50 else '#ffc107' if latency and latency < 150 else '#dc3545' if latency else '#6c757d'};">
                    {f'{latency:.1f} ms' if latency is not None else '—'}
                </div>
                <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Latência</div>
            </div>
            <div style="flex: 1; text-align: center;">
                <div style="font-size: 1.3rem; font-weight: 600; color: {'#28a745' if loss is not None and loss == 0 else '#ffc107' if loss is not None and loss < 5 else '#dc3545' if loss is not None else '#6c757d'};">
                    {f'{loss:.1f}%' if loss is not None else '—'}
                </div>
                <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Perda</div>
            </div>
            <div style="flex: 1; text-align: center;">
                <div style="font-size: 1.3rem; font-weight: 600; color: #1f77b4;">
                    {last_measured_at}
                </div>
                <div style="font-size: 0.7rem; color: #888; text-transform: uppercase;">Última</div>
            </div>
        </div>
        <div style="margin-top: 8px; text-align: center; display: flex; gap: 8px; justify-content: center;">
            {traceroute_badge}
            {alert_badge}
        </div>
    </div>
    """
    
    # Renderiza card + botão com label da máquina (clicável)
    container = st.container()
    with container:
        st.html(card_html)
        
        # Botoes de feedback
        col_good, col_med, col_bad = st.columns(3)
        
        with col_good:
            if st.button(
                "Bom",
                key=f"fb_good_{machine.id}",
                use_container_width=True,
            ):
                _save_feedback(machine.id, "bom", latest_measurement)
                st.success("Feedback: Bom")
        
        with col_med:
            if st.button(
                "Medio",
                key=f"fb_med_{machine.id}",
                use_container_width=True,
            ):
                _save_feedback(machine.id, "medio", latest_measurement)
                st.success("Feedback: Medio")
        
        with col_bad:
            if st.button(
                "Ruim",
                key=f"fb_bad_{machine.id}",
                use_container_width=True,
            ):
                _save_feedback(machine.id, "ruim", latest_measurement)
                st.success("Feedback: Ruim")
        
        st.caption("De feedback para treinar a IA")
        
        # Botao para ver detalhes
        if st.button(f"Ver detalhes: {machine.tag}", key=f"card_{machine.id}", use_container_width=True):
            on_click(machine.id)


def render_dashboard_machine_card(
    machine: Machine,
    client: Client,
    latest_measurement: Optional[dict],
    on_open: callable,
    on_feedback: Optional[callable] = None,
    internet_measurement: Optional[dict] = None,
) -> None:
    """One compact equipment card with local/internet signals and one overall rating."""
    statuses = [(latest_measurement or {}).get("status", "")]
    if internet_measurement:
        statuses.append(internet_measurement.get("status", ""))
    status = (
        "unreachable" if "unreachable" in statuses
        else "partial" if "partial" in statuses
        else "ok" if "ok" in statuses
        else ""
    )
    status_labels = {
        "ok": ("Estável", "🟢"),
        "partial": ("Atenção", "🟡"),
        "unreachable": ("Crítico", "🔴"),
    }
    status_label, status_icon = status_labels.get(status, ("Sem dados", "⚪"))

    def value_text(field: str, suffix: str) -> str:
        value = latest_measurement.get(field) if latest_measurement else None
        try:
            return f"{float(value):.1f}{suffix}" if value is not None else "—"
        except (TypeError, ValueError):
            return "—"

    with st.container(border=True, key=f"dashboard-machine-card-{machine.id}"):
        title_col, status_col = st.columns([3, 1])
        title_col.markdown(f"**{machine.tag}**")
        status_col.markdown(f"{status_icon} {status_label}")
        st.caption(f"{client.name} · {machine.ip}")

        st.caption("Internet" if machine.tag == "INTERNET-CHECK" else "Rede local")
        local_metrics = st.columns(3)
        local_metrics[0].metric("Latência", value_text("latency_ms", " ms"))
        local_metrics[1].metric("Jitter", value_text("jitter_ms", " ms"))
        local_metrics[2].metric("Perda", value_text("packet_loss_percent", "%"))

        if internet_measurement:
            st.caption("Internet")
            internet_metrics = st.columns(3)
            for column, (field, label, suffix) in zip(
                internet_metrics,
                (("latency_ms", "Latência", " ms"), ("jitter_ms", "Jitter", " ms"),
                 ("packet_loss_percent", "Perda", "%")),
            ):
                value = internet_measurement.get(field)
                try:
                    formatted = f"{float(value):.1f}{suffix}" if value is not None else "—"
                except (TypeError, ValueError):
                    formatted = "—"
                column.metric(label, formatted)
            internet_time = internet_measurement.get("measured_at")
            if internet_time:
                try:
                    parsed_internet_time = pd.to_datetime(internet_time, utc=True).tz_convert("America/Sao_Paulo")
                    st.caption(f"Amostra da Internet · {parsed_internet_time.strftime('%d/%m/%Y %H:%M:%S')}")
                except (TypeError, ValueError):
                    pass

        measured_at = latest_measurement.get("measured_at") if latest_measurement else None
        if measured_at:
            try:
                timestamp = pd.to_datetime(measured_at, utc=True).tz_convert("America/Sao_Paulo")
                st.caption(f"Última amostra · {timestamp.strftime('%d/%m/%Y %H:%M:%S')}")
            except (TypeError, ValueError):
                st.caption("Última amostra disponível")
        else:
            st.caption("Aguardando a primeira amostra")

        if on_feedback:
            st.caption("Avalie a qualidade geral da conexão · rede local + Internet")
            buttons = st.columns(3)
            for column, (button_label, sentiment) in zip(
                buttons,
                (("🟢 Boa", "bom"), ("🟡 Média", "medio"), ("🔴 Ruim", "ruim")),
            ):
                if column.button(
                    button_label,
                    key=f"dashboard_feedback_{machine.id}_{sentiment}",
                    use_container_width=True,
                    disabled=not latest_measurement,
                ):
                    on_feedback(machine, sentiment, latest_measurement)

        if st.button("Abrir análise", key=f"open_machine_{machine.id}", use_container_width=True):
            on_open(client.id, machine.id)


def _save_feedback(machine_id: str, label: str, measurement: Optional[dict]) -> None:
    """
    Salva feedback do operador no Supabase.
    
    Args:
        machine_id: ID da máquina
        label: "bom", "medio", ou "ruim"
        measurement: Última medição (para extrair métricas)
    
    IMPORTANTE:
        Esta função é o elo entre o operador e a IA.
        Cada feedback treina o modelo. Quanto mais feedbacks,
        melhor a classificação automática fica.
    """
    try:
        from repository import FrontendRepository
        repo = FrontendRepository()
        result = repo.save_feedback(machine_id, label, measurement)
        if result:
            st.success("Feedback salvo!")
        else:
            st.error("Falha ao salvar feedback")
    except Exception as exc:
        st.error(f"Erro ao salvar feedback: {exc}")


def render_metrics_charts(measurements: list[dict], machine_tag: str, key_suffix: str = "") -> None:
    """
    Renderiza gráficos de métricas (latência, jitter, perda) usando Plotly.
    
    Args:
        measurements: Lista de medições (dict) ordenadas cronologicamente
        machine_tag: Tag da máquina para título
        key_suffix: Sufixo único para o key do gráfico forçar re-render
    """
    if not measurements:
        st.info("Nenhuma medição disponível para o período selecionado.")
        return
    
    # Prepara dados para DataFrame com conversão para horário de São Paulo
    try:
        rows = []
        for m in measurements:
            ts = m.get("measured_at", "")
            dt = pd.to_datetime(ts)
            if dt.tz is not None and not pd.isna(dt):
                dt_sp = dt.tz_convert("America/Sao_Paulo")
            else:
                dt_sp = dt
            rows.append({
                "timestamp": dt_sp,
                "latency_ms": m.get("latency_ms"),
                "jitter_ms": m.get("jitter_ms"),
                "packet_loss_percent": m.get("packet_loss_percent", 0),
                "status": m.get("status", ""),
            })
        df = pd.DataFrame(rows)
    except Exception as exc:
        st.error(f"Erro ao processar dados do gráfico: {exc}")
        return
    
    # Cria subplots: latência + jitter (mesmo eixo Y) e perda (eixo separado)
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        subplot_titles=("Latência e Jitter (ms)", "Perda de Pacotes (%)"),
        row_heights=[0.65, 0.35]
    )

    if df["latency_ms"].dropna().empty and df["jitter_ms"].dropna().empty:
        fig.add_annotation(
            text="Sem respostas ao ping: latência e jitter não podem ser calculados.",
            xref="paper", yref="paper", x=0.5, y=0.73,
            showarrow=False, font={"color": "#6b7280", "size": 13},
        )
    
    # Latência
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["latency_ms"],
            mode="lines+markers",
            name="Latência (ms)",
            line=dict(color="#1f77b4", width=2),
            marker=dict(size=4),
            connectgaps=False,
        ),
        row=1, col=1
    )
    
    # Jitter
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["jitter_ms"],
            mode="lines+markers",
            name="Jitter (ms)",
            line=dict(color="#ff7f0e", width=1.5, dash="dot"),
            marker=dict(size=3),
            connectgaps=False,
        ),
        row=1, col=1
    )
    
    # Perda de pacotes (barras)
    colors = ["#28a745" if v == 0 else "#ffc107" if v < 5 else "#dc3545" for v in df["packet_loss_percent"]]
    fig.add_trace(
        go.Bar(
            x=df["timestamp"],
            y=df["packet_loss_percent"],
            name="Perda (%)",
            marker_color=colors,
            opacity=0.7,
        ),
        row=2, col=1
    )
    
    # Linha de referência para perda
    fig.add_hline(y=1, line_dash="dash", line_color="#ffc107", row=2, col=1, annotation_text="1%")
    fig.add_hline(y=5, line_dash="dash", line_color="#dc3545", row=2, col=1, annotation_text="5%")
    
    # Layout
    fig.update_layout(
        height=500,
        title=f"Métricas de Rede - {machine_tag}",
        title_x=0.5,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        margin=dict(l=50, r=30, t=60, b=40),
    )
    
    fig.update_xaxes(title_text="Tempo", row=2, col=1)
    fig.update_yaxes(title_text="ms", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1, range=[0, max(10, df["packet_loss_percent"].max() * 1.2 if not df["packet_loss_percent"].isna().all() else 10)])
    
    chart_key = f"metrics_chart_{machine_tag}_{key_suffix}"
    st.plotly_chart(fig, use_container_width=True, key=chart_key)
    
    # Estatísticas resumidas
    col1, col2, col3, col4 = st.columns(4)
    
    valid_latency = df["latency_ms"].dropna()
    valid_jitter = df["jitter_ms"].dropna()
    
    with col1:
        st.metric(
            "Latência Média",
            f"{valid_latency.mean():.1f} ms" if not valid_latency.empty else "—",
            delta=f"Min: {valid_latency.min():.1f} / Max: {valid_latency.max():.1f}" if not valid_latency.empty else None
        )
    with col2:
        st.metric(
            "Jitter Médio",
            f"{valid_jitter.mean():.1f} ms" if not valid_jitter.empty else "—",
            delta=f"Max: {valid_jitter.max():.1f}" if not valid_jitter.empty else None
        )
    with col3:
        avg_loss = df["packet_loss_percent"].mean()
        st.metric(
            "Perda Média",
            f"{avg_loss:.2f}%",
            delta=f"Total: {df['packet_loss_percent'].sum():.1f}%"
        )
    with col4:
        uptime = (df["status"] == "ok").sum() / len(df) * 100
        st.metric(
            "Disponibilidade",
            f"{uptime:.1f}%",
            delta=f"{(df['status'] == 'ok').sum()}/{len(df)} amostras"
        )


def render_status_badge(status: str) -> str:
    """Retorna HTML para badge de status."""
    badges = {
        "ok": ("🟢 OK", "#28a745"),
        "partial": ("🟡 PARCIAL", "#ffc107"),
        "unreachable": ("🔴 INALCANÇÁVEL", "#dc3545"),
        "error": ("⚪ ERRO", "#6c757d"),
    }
    text, color = badges.get(status, ("❓ DESCONHECIDO", "#6c757d"))
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:600;">{text}</span>'


def render_sidebar_filters(repo) -> dict:
    """
    Renderiza filtros na sidebar e retorna parâmetros selecionados.
    
    Returns:
        Dict com: client_id
    """
    with st.sidebar:
        st.markdown("## ⚙️ Filtros")
        
        # Filtro por cliente
        clients = repo.list_clients()
        client_options = {"Todos": None}
        client_options.update({c.name: c.id for c in clients})
        
        selected_client_name = st.selectbox(
            "Filtrar por cliente",
            options=list(client_options.keys()),
            index=0
        )
        selected_client_id = client_options[selected_client_name]
        
        st.divider()
        st.caption("AI Network Analyzer")
    
    return {
        "client_id": selected_client_id,
    }


def render_traceroute_chart(traceroute: dict, machine_tag: str) -> None:
    """
    Renderiza gráfico estilo PingPlotter: hop-a-hop latency/loss.
    
    Args:
        traceroute: Dicionário com traceroute e hops do Supabase
        machine_tag: Tag da máquina para título
    """
    hops = traceroute.get("traceroute_hops", [])
    if not hops:
        st.info("Nenhum hop de traceroute disponível.")
        return
    
    # Ordena hops por número
    hops = sorted(hops, key=lambda h: h["hop_number"])
    
    # Prepara dados
    hop_nums = [h["hop_number"] for h in hops]
    ips = [h.get("ip") or "*" for h in hops]
    hostnames = [h.get("hostname") or "" for h in hops]
    latencies = [h.get("latency_ms") for h in hops]
    losses = [h.get("packet_loss_percent", 0) for h in hops]
    
    # Labels para eixo X
    labels = []
    for i, (ip, host) in enumerate(zip(ips, hostnames)):
        label = f"Hop {hop_nums[i]}\n{ip}"
        if host:
            label += f"\n({host})"
        labels.append(label)
    
    # Cria figura com dois eixos Y
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        subplot_titles=("Latência por Hop (ms)", "Perda por Hop (%)"),
        row_heights=[0.7, 0.3]
    )
    
    # Latência - barras
    lat_colors = []
    for lat in latencies:
        if lat is None:
            lat_colors.append("#6c757d")  # cinza para timeout
        elif lat < 20:
            lat_colors.append("#28a745")  # verde
        elif lat < 50:
            lat_colors.append("#ffc107")  # amarelo
        elif lat < 100:
            lat_colors.append("#fd7e14")  # laranja
        else:
            lat_colors.append("#dc3545")  # vermelho
    
    fig.add_trace(
        go.Bar(
            x=list(range(len(hop_nums))),
            y=[lat if lat is not None else 0 for lat in latencies],
            name="Latência (ms)",
            marker_color=lat_colors,
            text=[f"{lat:.1f}ms" if lat is not None else "timeout" for lat in latencies],
            textposition="outside",
            hovertemplate="Hop %{x}<br>Latência: %{y:.1f}ms<extra></extra>",
        ),
        row=1, col=1
    )
    
    # Perda - barras
    loss_colors = ["#28a745" if l == 0 else "#ffc107" if l < 10 else "#dc3545" for l in losses]
    
    fig.add_trace(
        go.Bar(
            x=list(range(len(hop_nums))),
            y=losses,
            name="Perda (%)",
            marker_color=loss_colors,
            text=[f"{l:.0f}%" for l in losses],
            textposition="outside",
            hovertemplate="Hop %{x}<br>Perda: %{y:.1f}%<extra></extra>",
        ),
        row=2, col=1
    )
    
    # Linhas de referência
    fig.add_hline(y=1, line_dash="dash", line_color="#ffc107", row=2, col=1, annotation_text="1%")
    fig.add_hline(y=5, line_dash="dash", line_color="#dc3545", row=2, col=1, annotation_text="5%")
    
    # Configura eixo X com labels dos hops
    fig.update_xaxes(
        tickmode="array",
        tickvals=list(range(len(hop_nums))),
        ticktext=labels,
        tickangle=-45,
        row=2, col=1
    )
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    
    fig.update_yaxes(title_text="ms", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1, range=[0, 100])
    
    # Layout
    dest_reached = "✅" if traceroute.get("destination_reached") else "❌"
    fig.update_layout(
        height=550,
        title=f"🔍 Traceroute - {machine_tag} {dest_reached}",
        title_x=0.5,
        hovermode="x unified",
        showlegend=False,
        margin=dict(l=50, r=30, t=60, b=100),
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Tabela de hops
    with st.expander("📋 Detalhes dos Hops"):
        df_hops = pd.DataFrame([
            {
                "Hop": h["hop_number"],
                "IP": h.get("ip") or "*",
                "Hostname": h.get("hostname") or "—",
                "Latência (ms)": f"{h.get('latency_ms'):.1f}" if h.get("latency_ms") else "timeout",
                "Perda (%)": f"{h.get('packet_loss_percent', 0):.1f}",
            }
            for h in sorted(traceroute.get("traceroute_hops", []), key=lambda x: x["hop_number"])
        ])
        st.dataframe(df_hops, width="stretch", hide_index=True)


def render_traceroute_badge(traceroute: dict | None) -> str:
    """Retorna HTML para badge de traceroute no card."""
    if not traceroute:
        return '<span style="background:#6c757d;color:white;padding:2px 8px;border-radius:10px;font-size:0.7rem;font-weight:600;">🔍 Sem traceroute</span>'
    
    total_hops = traceroute.get("total_hops", 0)
    reached = traceroute.get("destination_reached", False)
    
    if reached:
        color = "#28a745"
        text = f"🔍 Traceroute: {total_hops} hops ✅"
    else:
        color = "#ffc107"
        text = f"🔍 Traceroute: {total_hops} hops ⚠️"
    
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:10px;font-size:0.7rem;font-weight:600;">{text}</span>'


def render_traceroute_tab(repo, machine_id: str, machine_tag: str) -> None:
    """Renderiza aba de traceroute no detail view."""
    traceroute = repo.get_latest_traceroute(machine_id)
    
    if not traceroute:
        st.warning("Nenhum traceroute disponível para esta máquina.")
        if st.button("🔄 Verificar agora"):
            st.rerun()
        return
    
    # Info do traceroute
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Hops", traceroute.get("total_hops", 0))
    with col2:
        reached = "✅ Sim" if traceroute.get("destination_reached") else "❌ Não"
        st.metric("Destino Alcançado", reached)
    with col3:
        st.metric("Max Hops Config", traceroute.get("max_hops", 30))
    with col4:
        measured = traceroute.get("measured_at", "")[:16].replace("T", " ")
        st.metric("Última Execução", measured)
    
    st.divider()
    
    # Gráfico principal
    render_traceroute_chart(traceroute, traceroute.get("target_ip", "IP"))
    
    # Histórico
    with st.expander("📜 Histórico de Traceroutes"):
        history = repo.get_traceroute_history(machine_id, limit=20)
        if history:
            df_hist = pd.DataFrame([
                {
                    "Data": h["measured_at"][:16].replace("T", " "),
                    "Hops": h.get("total_hops", 0),
                    "Alcançado": "✅" if h.get("destination_reached") else "❌",
                }
                for h in history
            ])
            st.dataframe(df_hist, width="stretch", hide_index=True)
        else:
            st.info("Sem histórico de traceroutes.")


def render_alert_tab(repo, machine_id: str, machine_tag: str) -> None:
    """Renderiza aba de alertas no detail view."""
    # Busca eventos de alerta
    alert_events = repo.get_alert_events(machine_id)
    
    if not alert_events:
        st.success("✅ Nenhum evento de alerta registrado para esta máquina.")
        return
    
    # Status atual
    firing_events = [e for e in alert_events if e.get("status") == "firing"]
    acknowledged_events = [e for e in alert_events if e.get("status") == "acknowledged"]
    resolved_events = [e for e in alert_events if e.get("status") == "resolved"]
    
    st.markdown("### 🔔 Status dos Alertas")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("🔴 Ativos", len(firing_events))
    with col2:
        st.metric("🟠 Reconhecidos", len(acknowledged_events))
    with col3:
        st.metric("✅ Resolvidos", len(resolved_events))
    
    st.divider()
    
    # Alertas ativos em destaque
    if firing_events or acknowledged_events:
        st.markdown("### ⚠️ Alertas Ativos")
        for event in firing_events + acknowledged_events:
            severity = event.get("severity", "")
            metric = event.get("metric", "")
            value = event.get("metric_value", 0)
            threshold = event.get("threshold_value", 0)
            started = event.get("started_at", "")
            
            if severity == "critical":
                icon = "🔴"
                color = "#dc3545"
                label = "CRÍTICO"
            elif severity == "warning":
                icon = "🟡"
                color = "#ffc107"
                label = "AVISO"
            elif severity == "firing":
                icon = "🔴"
                color = "#dc3545"
                label = "FIRE"
            else:
                icon = "🟠"
                color = "#fd7e14"
                label = "ACK"
            
            st.html(f"""
            <div style="
                border-left: 4px solid {color};
                padding: 10px 16px;
                margin: 8px 0;
                background: {'#fff5f5' if severity == 'critical' else '#fffcf0'};
                border-radius: 4px;
            ">
                <div style="font-weight: 600; color: {color};">
                    {icon} {label} — {machine_tag}
                </div>
                <div style="font-size: 0.9rem; color: #333; margin-top: 4px;">
                    Métrica: <strong>{metric}</strong> = <strong>{value}</strong> (threshold: {threshold})
                </div>
                <div style="font-size: 0.8rem; color: #888; margin-top: 2px;">
                    Início: {started[:19].replace('T', ' ') if started else '—'}
                </div>
            </div>
            """)
        
        st.divider()
    
    # Histórico de eventos
    with st.expander("📜 Histórico Completo de Alertas"):
        df_alerts = pd.DataFrame([
            {
                "Data/Hora": e.get("started_at", "")[:19].replace("T", " "),
                "Severidade": e.get("severity", "").upper(),
                "Métrica": e.get("metric", ""),
                "Valor": e.get("metric_value", 0),
                "Threshold": e.get("threshold_value", 0),
                "Status": e.get("status", "").upper(),
                "Regra ID": e.get("rule_id", "")[:8],
            }
            for e in alert_events
        ])
        if not df_alerts.empty:
            # Colorir linhas por severidade
            st.dataframe(df_alerts, width="stretch", hide_index=True)
        else:
            st.info("Sem histórico de alertas.")
    
    # Botão para reconhecer alertas ativos
    if firing_events:
        st.divider()
        if st.button("🔔 Reconhecer todos os alertas ativos", use_container_width=True):
            for event in firing_events:
                repo.update_alert_event(event.get("id", ""), {
                    "status": "acknowledged",
                    "acknowledged_at": pd.to_datetime(event.get("started_at", "")).isoformat(),
                    "acknowledged_by": "frontend_user",
                })
            st.rerun()


def render_sparkline(sparkline_data: list[dict], color: str = "#1f77b4") -> None:
    """
    Renderiza mini gráfico sparkline (latência 24h).
    
    Args:
        sparkline_data: Lista de dicts com latency_ms e measured_at
        color: Cor da linha
    """
    if not sparkline_data:
        return
    
    # Filtra dados válidos
    valid_data = [d for d in sparkline_data if d.get("latency_ms") is not None]
    if not valid_data:
        return
    
    # Prepara dados
    timestamps = [pd.to_datetime(d["measured_at"]).tz_convert("America/Sao_Paulo") for d in valid_data]
    latencies = [d["latency_ms"] for d in valid_data]
    
    # Cria sparkline compacto
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=latencies,
        mode="lines",
        line=dict(color=color, width=1.5),
        fill="tozeroy",
        fillcolor=f"{color}20",  # 20% opacity
        hovertemplate="%{y:.1f}ms<br>%{x}<extra></extra>",
        showlegend=False,
    ))
    
    fig.update_layout(
        height=60,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_alert_badge(
    alert_status: str | None,
    severity: str | None = None,
    metric: str | None = None
) -> str:
    """Retorna HTML para badge de alerta no card."""
    if not alert_status:
        return '<span style="background:#28a745;color:white;padding:2px 10px;border-radius:10px;font-size:0.7rem;font-weight:600;">✓ Sem alertas</span>'
    
    if alert_status == "firing" or severity == "critical":
        color = "#dc3545"
        text = f"🔴 ALERTA ATIVO"
    elif alert_status == "acknowledged":
        color = "#fd7e14"
        text = f"🟠 RECONHECIDO"
    elif severity == "warning":
        color = "#ffc107"
        text = f"🟡 AVISO"
    else:
        color = "#6c757d"
        text = f"⚪ {alert_status.upper()}"
    
    metric_label = f" ({metric})" if metric else ""
    
    return f'<span style="background:{color};color:white;padding:2px 10px;border-radius:10px;font-size:0.7rem;font-weight:600;">{text}{metric_label}</span>'


def render_device_status_events(events: list[dict]) -> None:
    """Renderiza lista de eventos de status do dispositivo."""
    if not events:
        st.caption("Nenhum evento de conectividade")
        return
    
    for event in reversed(events):
        event_type = event.get("event_type", "")
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
        
        prev_str = f", anterior: {prev}" if prev else ""
        st.html(
            f'<span style="color:{color};font-size:0.8rem;">'
            f'{measured} | {icon} <strong>{label}</strong> '
            f'(loss: {loss:.1f}%{prev_str})'
            f'</span>'
        )


def _render_reachability_list(local_machines: list[dict]) -> str:
    """Renderiza lista de alcançabilidade das máquinas locais."""
    if not local_machines:
        return '<span style="color:#888;font-size:0.8rem;">Nenhuma máquina local</span>'
    
    items = []
    for m in local_machines:
        machine = m["machine"]
        icon, color = _reachability_label(m)
        
        latest = m.get("latest_measurement")
        measured = latest.get("measured_at", "")[:16].replace("T", " ") if latest else "—"
        
        status_events = m.get("status_events", [])
        event_str = ""
        if status_events:
            last_event = status_events[0]
            etype = last_event.get("event_type", "")
            loss = last_event.get("packet_loss_percent")
            event_str = f" | {etype} (loss: {loss:.1f}%)" if loss is not None else f" | {etype}"
        
        items.append(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:4px 0;border-bottom:1px solid #eee;">'
            f'<span>{icon} <strong>{machine.tag}</strong> • {machine.ip}</span>'
            f'<span style="color:{color};font-size:0.75rem;">{measured}{event_str}</span>'
            f'</div>'
        )
    
    return "".join(items)
