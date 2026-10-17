# -*- coding: utf-8 -*-
"""
SupaDiag Setup - Painel de Configuração e Gestão da Lógica de Coleta de Rede
Iniciado por setup.bat na raiz do projeto.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Adiciona a pasta src ao sys.path para importar supadiag
ROOT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT_DIR / "src"))

import streamlit as st

from supadiag.config import load_settings, ensure_runtime_files
from supadiag.diary import Diary
from supadiag.models import (
    Client,
    Machine,
    validate_client_name,
    validate_tag,
    validate_ip,
    validate_frequency,
)
from supadiag.queue import LocalQueue
from supadiag.scheduler import WindowsScheduler
from supadiag.supabase_repository import SupabaseRepository, RepositoryError
from supadiag.icmp import measure_host

# Configuração da página Streamlit
st.set_page_config(
    page_title="SupaDiag - Painel de Setup & Coleta",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilização visual moderna e limpa
st.markdown(
    """
<style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.0rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .card-kpi {
        background: linear-gradient(135deg, #F8FAFC 0%, #EDF2F7 100%);
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .badge-ok {
        background-color: #DCFCE7;
        color: #166534;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .badge-error {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .badge-warn {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 3px 8px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.85rem;
    }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def get_services():
    """Inicializa configurações, repositórios e instâncias de serviço."""
    settings = load_settings(ROOT_DIR)
    ensure_runtime_files(settings)
    diary = Diary(settings.memory_file)
    repo = SupabaseRepository(settings)
    queue = LocalQueue(settings.queue_file)
    scheduler = WindowsScheduler(settings)
    return settings, diary, repo, queue, scheduler


def format_iso_timestamp(iso_str: str | None) -> str:
    """Converte ISO timestamp UTC para horário legível."""
    if not iso_str:
        return "-"
    try:
        # Trata formato ISO
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # Converte para hora local
        local_dt = dt.astimezone()
        return local_dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(iso_str)[:19]


def run_ping_test(ip: str, client_id: str = "temp", machine_id: str = "temp", count: int = 4):
    """Executa um teste ICMP local no IP fornecido."""
    try:
        sample = measure_host(ip=ip, client_id=client_id, machine_id=machine_id, count=count, timeout_seconds=1.5)
        return True, sample
    except Exception as exc:
        return False, str(exc)


# =========================================================================
# COMPONENTES DE RENDERIZAÇÃO
# =========================================================================

def render_sidebar(settings, repo, queue, scheduler):
    """Renderiza a barra lateral com status dos serviços e navegação."""
    with st.sidebar:
        st.markdown("### 🛠️ **SupaDiag Setup**")
        st.caption("Central de Configuração da Coleta")
        st.divider()

        # Checagem Supabase Cloud
        with st.spinner("Checando Cloud..."):
            cloud_ok, cloud_msg = repo.health_check()
        if cloud_ok:
            st.success(f"☁️ **Supabase:** {cloud_msg}")
        else:
            st.error(f"☁️ **Supabase:** {cloud_msg}")

        # Checagem Scheduler do Windows
        sched_status = scheduler.status()
        if sched_status.installed:
            st.success("🛡️ **Serviço Coletor:** Ativo")
        else:
            st.warning("🛡️ **Serviço Coletor:** Inativo")

        # Fila local
        q_size = queue.size()
        st.caption(f"📦 Fila Local Offline: **{q_size}** pendente(s)")

        st.divider()

        page = st.radio(
            "Navegação do Setup",
            [
                "🏢 Clientes",
                "🖥️ Máquinas & IPs Locais",
                "📜 Eventos no Banco",
                "⚙️ Lógica de Coleta & Serviço",
            ],
            index=0,
            key="setup_nav_page",
        )

        st.divider()
        if st.button("🔄 Recarregar Dados", use_container_width=True):
            st.rerun()

        st.caption(f"📁 Pasta de dados: `{settings.data_dir}`")
        return page


def render_clients_tab(repo, diary):
    """Aba de Gestão de Clientes: cadastro, edição e listagem."""
    st.markdown('<div class="main-header">🏢 Gestão de Clientes</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Cadastre e configure as empresas/clientes que possuem equipamentos monitorados.</div>', unsafe_allow_html=True)

    try:
        clients = repo.list_clients()
        machines = repo.list_machines(active_only=False)
    except Exception as exc:
        st.error(f"Erro ao carregar dados do Supabase: {exc}")
        return

    # Contagem de máquinas por cliente
    client_machine_counts = {}
    for m in machines:
        client_machine_counts[m.client_id] = client_machine_counts.get(m.client_id, 0) + 1

    # Cards KPI
    col_kpi1, col_kpi2 = st.columns(2)
    with col_kpi1:
        st.metric("Total de Clientes Cadastrados", len(clients))
    with col_kpi2:
        st.metric("Total de Equipamentos / Máquinas", len(machines))

    st.write("")
    tab_list, tab_add = st.tabs(["📋 Lista de Clientes", "➕ Novo Cliente"])

    with tab_list:
        if not clients:
            st.info("Nenhum cliente cadastrado no Supabase ainda. Utilize a aba 'Novo Cliente' ao lado para começar.")
        else:
            # Tabela de clientes
            table_data = []
            for c in clients:
                table_data.append({
                    "Nome do Cliente": c.name,
                    "Máquinas Vinculadas": client_machine_counts.get(c.id, 0),
                    "Data de Cadastro": format_iso_timestamp(c.created_at),
                    "ID": c.id,
                })
            st.dataframe(table_data, use_container_width=True, hide_index=True)

            st.write("")
            st.markdown("#### ⚙️ Ações para o Cliente")
            client_options = {f"{c.name} ({client_machine_counts.get(c.id, 0)} máquinas)": c for c in clients}
            selected_label = st.selectbox("Selecione um cliente para editar ou remover:", list(client_options.keys()))

            if selected_label:
                selected_client = client_options[selected_label]
                col_edit, col_del = st.columns([1, 1])

                with col_edit:
                    with st.expander(f"✏️ Editar Nome: **{selected_client.name}**", expanded=False):
                        new_name = st.text_input("Novo Nome do Cliente", value=selected_client.name, key=f"edit_name_{selected_client.id}")
                        if st.button("💾 Salvar Novo Nome", key=f"btn_save_{selected_client.id}", type="primary"):
                            try:
                                valid_name = validate_client_name(new_name)
                                updated = repo.update_client(selected_client.id, valid_name)
                                diary.log("CLIENTE_ATUALIZADO", updated.name, {"client_id": updated.id})
                                st.success(f"Cliente '{updated.name}' atualizado com sucesso!")
                                time.sleep(0.8)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao atualizar: {e}")

                with col_del:
                    with st.expander(f"🗑️ Excluir Cliente: **{selected_client.name}**", expanded=False):
                        st.warning("⚠️ Atenção: Remover o cliente também removerá todas as máquinas e medições associadas a ele no Supabase!")
                        confirm = st.checkbox("Estou ciente e desejo excluir permanentemente", key=f"confirm_{selected_client.id}")
                        if st.button("Confirmar Exclusão", key=f"btn_del_{selected_client.id}", type="secondary", disabled=not confirm):
                            try:
                                repo.delete_client(selected_client.id)
                                diary.log("CLIENTE_REMOVIDO", selected_client.name, {"client_id": selected_client.id})
                                st.success("Cliente removido com sucesso!")
                                time.sleep(0.8)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao excluir: {e}")

    with tab_add:
        st.markdown("#### ➕ Cadastrar Novo Cliente")
        with st.form("form_add_client", clear_on_submit=True):
            client_name = st.text_input("Nome da Empresa / Cliente *", placeholder="Ex: Matriz São Paulo, Komatsu, etc.")
            submitted = st.form_submit_button("💾 Salvar Cliente", type="primary", use_container_width=True)

            if submitted:
                if not client_name or not client_name.strip():
                    st.error("O nome do cliente não pode ser vazio.")
                else:
                    try:
                        valid_name = validate_client_name(client_name)
                        created = repo.create_client(valid_name)
                        diary.log("CLIENTE_CRIADO", created.name, {"client_id": created.id})
                        st.success(f"✅ Cliente '{created.name}' cadastrado com sucesso!")
                        time.sleep(0.8)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Falha ao salvar cliente: {e}")


def render_machines_tab(repo, diary):
    """Aba de Gestão de Máquinas, IPs da rede local e frequência."""
    st.markdown('<div class="main-header">🖥️ Equipamentos & IPs da Rede Local</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Configure os IPs dos hosts da rede local a serem coletados, tags amigáveis e frequência em segundos.</div>', unsafe_allow_html=True)

    try:
        clients = repo.list_clients()
        machines = repo.list_machines(active_only=False)
    except Exception as exc:
        st.error(f"Erro ao carregar do Supabase: {exc}")
        return

    client_map = {c.id: c.name for c in clients}

    tab_list_mach, tab_add_mach = st.tabs(["📋 Equipamentos Cadastrados", "➕ Novo Equipamento"])

    with tab_list_mach:
        # Filtro por cliente
        col_filtro1, col_filtro2 = st.columns([2, 1])
        with col_filtro1:
            filtro_cliente = st.selectbox(
                "Filtrar por Cliente:",
                ["(Todos os Clientes)"] + [f"{c.name}" for c in clients],
                key="filtro_cli_mach",
            )
        with col_filtro2:
            filtro_status = st.selectbox("Status:", ["Todos", "Apenas Ativas", "Apenas Inativas"])

        # Filtragem
        filtered_machines = machines
        if filtro_cliente != "(Todos os Clientes)":
            client_id_sel = next((c.id for c in clients if c.name == filtro_cliente), None)
            if client_id_sel:
                filtered_machines = [m for m in filtered_machines if m.client_id == client_id_sel]

        if filtro_status == "Apenas Ativas":
            filtered_machines = [m for m in filtered_machines if m.active]
        elif filtro_status == "Apenas Inativas":
            filtered_machines = [m for m in filtered_machines if not m.active]

        if not filtered_machines:
            st.info("Nenhum equipamento encontrado para o filtro selecionado.")
        else:
            # Tabela de máquinas
            table_mach = []
            for m in filtered_machines:
                table_mach.append({
                    "Tag / Identificador": m.tag,
                    "IP Rede Local": m.ip,
                    "Cliente": client_map.get(m.client_id, "Desconhecido"),
                    "Frequência": f"{m.frequency_seconds}s",
                    "Status": "🟢 Ativa" if m.active else "🔴 Inativa",
                    "Cadastrado em": format_iso_timestamp(m.created_at),
                })
            st.dataframe(table_mach, use_container_width=True, hide_index=True)

            st.write("")
            st.markdown("#### ⚙️ Gerenciar Equipamento Selecionado")
            mach_options = {f"{m.tag} — IP: {m.ip} ({client_map.get(m.client_id, 'Sem cliente')})": m for m in filtered_machines}
            selected_mach_label = st.selectbox("Selecione o equipamento:", list(mach_options.keys()))

            if selected_mach_label:
                m_sel = mach_options[selected_mach_label]

                col_m1, col_m2 = st.columns([1, 1])

                with col_m1:
                    with st.expander("✏️ Editar Dados do Equipamento & IP Local", expanded=True):
                        with st.form(f"form_edit_mach_{m_sel.id}"):
                            # Dropdown cliente
                            current_cli_idx = 0
                            for idx, c in enumerate(clients):
                                if c.id == m_sel.client_id:
                                    current_cli_idx = idx
                                    break

                            new_client = st.selectbox(
                                "Cliente:",
                                options=[c.id for c in clients],
                                format_func=lambda x: client_map.get(x, x),
                                index=current_cli_idx,
                            )
                            new_tag = st.text_input("Tag / Identificador:", value=m_sel.tag)
                            new_ip = st.text_input("IP da Rede Local:", value=m_sel.ip)
                            new_freq = st.number_input("Frequência de Coleta (segundos):", min_value=10, max_value=86400, value=m_sel.frequency_seconds, step=5)
                            new_active = st.checkbox("Coleta Ativa", value=m_sel.active)

                            btn_save_mach = st.form_submit_button("💾 Salvar Alterações", type="primary", use_container_width=True)
                            if btn_save_mach:
                                try:
                                    valid_tag = validate_tag(new_tag)
                                    valid_ip_val = validate_ip(new_ip)
                                    valid_freq = validate_frequency(new_freq)

                                    updated = repo.update_machine(
                                        machine_id=m_sel.id,
                                        client_id=new_client,
                                        tag=valid_tag,
                                        ip=valid_ip_val,
                                        frequency_seconds=valid_freq,
                                        active=new_active,
                                    )
                                    diary.log("MAQUINA_ATUALIZADA", updated.tag, {"machine_id": updated.id, "ip": updated.ip})
                                    st.success(f"Equipamento '{updated.tag}' atualizado com sucesso!")
                                    time.sleep(0.8)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erro ao atualizar: {e}")

                with col_m2:
                    with st.expander("⚡ Testar Ping ICMP Agora neste IP", expanded=True):
                        st.write(f"Testar conectividade da máquina atual até o IP **{m_sel.ip}** ({m_sel.tag}):")
                        if st.button("🚀 Disparar Teste de Ping", key=f"ping_test_{m_sel.id}", use_container_width=True):
                            with st.spinner(f"Disparando 4 pacotes ICMP para {m_sel.ip}..."):
                                ok, sample_or_err = run_ping_test(m_sel.ip, m_sel.client_id, m_sel.id, count=4)
                                if ok:
                                    s = sample_or_err
                                    st.success(f"Status: **{s.status.upper()}**")
                                    col_r1, col_r2, col_r3 = st.columns(3)
                                    col_r1.metric("Latência Média", f"{s.latency_ms or '-'} ms")
                                    col_r2.metric("Jitter", f"{s.jitter_ms or '-'} ms")
                                    col_r3.metric("Perda de Pacotes", f"{s.packet_loss_percent}%")
                                    st.caption(f"Pacotes enviados: {s.packets_sent} | Recebidos: {s.packets_received}")
                                else:
                                    st.error(f"Falha ao executar ping: {sample_or_err}")

                    with st.expander("🗑️ Excluir Equipamento"):
                        st.warning("Deseja remover este equipamento e suas medições do Supabase?")
                        confirm_m_del = st.checkbox("Confirmar exclusão desta máquina", key=f"del_chk_{m_sel.id}")
                        if st.button("Excluir Permanentemente", key=f"del_btn_{m_sel.id}", disabled=not confirm_m_del, type="secondary"):
                            try:
                                repo.delete_machine(m_sel.id)
                                diary.log("MAQUINA_REMOVIDA", m_sel.tag, {"machine_id": m_sel.id})
                                st.success("Máquina removida!")
                                time.sleep(0.8)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao remover: {e}")

    with tab_add_mach:
        st.markdown("#### ➕ Cadastrar Novo Equipamento / IP da Rede Local")
        if not clients:
            st.warning("Você precisa cadastrar ao menos um Cliente antes de adicionar equipamentos.")
        else:
            with st.form("form_add_machine", clear_on_submit=True):
                col_a1, col_a2 = st.columns(2)
                with col_a1:
                    sel_client_add = st.selectbox(
                        "Cliente *",
                        options=[c.id for c in clients],
                        format_func=lambda x: client_map.get(x, x),
                    )
                    add_tag = st.text_input("Tag / Identificador da Máquina *", placeholder="Ex: Gateway-Borda, Caixa-01, Servidor-SQL")
                with col_a2:
                    add_ip = st.text_input("IP da Rede Local *", placeholder="Ex: 192.168.1.1, 10.0.0.5")
                    add_freq = st.number_input("Frequência de Coleta (segundos) *", min_value=10, max_value=86400, value=60, step=5)

                col_presets = st.columns(4)
                with col_presets[0]:
                    st.caption("Sugestões de Frequência: 10s (crítico), 30s (padrão NOC), 60s (normal), 300s (baixo tráfego)")

                add_active = st.checkbox("Ativa para coleta contínua", value=True)

                submitted_mach = st.form_submit_button("💾 Salvar Equipamento", type="primary", use_container_width=True)
                if submitted_mach:
                    try:
                        valid_tag = validate_tag(add_tag)
                        valid_ip_val = validate_ip(add_ip)
                        valid_freq = validate_frequency(add_freq)

                        created_m = repo.create_machine(
                            client_id=sel_client_add,
                            tag=valid_tag,
                            ip=valid_ip_val,
                            frequency_seconds=valid_freq,
                        )
                        diary.log("MAQUINA_CRIADA", created_m.tag, {"machine_id": created_m.id, "ip": created_m.ip})
                        st.success(f"✅ Equipamento '{created_m.tag}' (IP: {created_m.ip}) cadastrado com sucesso!")
                        time.sleep(0.8)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao cadastrar equipamento: {e}")


def render_events_tab(repo):
    """Aba de Visualização dos Últimos Eventos Registrados no Banco de Dados."""
    st.markdown('<div class="main-header">📜 Últimos Eventos Registrados no Banco</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Acompanhe os eventos de mudança de status, perda de pacotes, alertas e medições gravadas na nuvem.</div>', unsafe_allow_html=True)

    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 1, 1])
    with col_ctrl1:
        event_source = st.radio(
            "Origem dos Eventos:",
            [
                "🔌 Status / Conectividade (device_status_events)",
                "🚨 Alertas Disparados (alert_events)",
                "📊 Amostras Recentes (measurements)",
            ],
            horizontal=True,
        )
    with col_ctrl2:
        limit = st.selectbox("Quantidade a exibir:", [25, 50, 100, 200], index=1)
    with col_ctrl3:
        if st.button("🔄 Atualizar Eventos", use_container_width=True):
            st.rerun()

    st.divider()

    # 1. EVENTOS DE STATUS DO DISPOSITIVO
    if "device_status_events" in event_source:
        try:
            events = repo.list_device_status_events(limit=limit)
            if not events:
                st.info("Nenhum evento de conectividade registrado até o momento.")
            else:
                table_events = []
                for ev in events:
                    # Informações do join
                    m_info = ev.get("machines") or {}
                    c_info = ev.get("clients") or {}
                    tag = m_info.get("tag", ev.get("machine_id", "")[:8])
                    ip = m_info.get("ip", "-")
                    client_name = c_info.get("name", ev.get("client_id", "")[:8])

                    ev_type = ev.get("event_type", "-")
                    if ev_type == "reachable":
                        tipo_label = "🟢 Restabelecido (Reachable)"
                    elif ev_type == "unreachable":
                        tipo_label = "🔴 Inacessível (Unreachable)"
                    elif ev_type == "packet_loss":
                        tipo_label = "🟡 Perda de Pacotes"
                    else:
                        tipo_label = ev_type

                    table_events.append({
                        "Data / Hora": format_iso_timestamp(ev.get("measured_at")),
                        "Cliente": client_name,
                        "Equipamento": tag,
                        "IP": ip,
                        "Evento": tipo_label,
                        "Perda (%)": f"{ev.get('packet_loss_percent') or 0}%",
                        "Latência (ms)": ev.get("latency_ms") or "-",
                        "Jitter (ms)": ev.get("jitter_ms") or "-",
                        "Pacotes": f"{ev.get('packets_received') or 0}/{ev.get('packets_sent') or 0}",
                        "Status Anterior": ev.get("previous_status") or "-",
                    })
                st.dataframe(table_events, use_container_width=True, hide_index=True)
                st.caption(f"Exibindo os últimos {len(events)} eventos de conectividade.")
        except Exception as exc:
            st.error(f"Erro ao consultar eventos de conectividade: {exc}")

    # 2. EVENTOS DE ALERTA
    elif "alert_events" in event_source:
        try:
            alerts = repo.list_alert_events(limit=limit)
            if not alerts:
                st.info("Nenhum evento de alerta registrado no banco.")
            else:
                table_alerts = []
                for a in alerts:
                    table_alerts.append({
                        "Início": format_iso_timestamp(a.get("started_at")),
                        "Status": a.get("status", "").upper(),
                        "Severidade": a.get("severity", "").upper(),
                        "Valor Medido": a.get("metric_value"),
                        "Limiar": a.get("threshold_value"),
                        "Resolvido em": format_iso_timestamp(a.get("resolved_at")),
                        "ID Máquina": str(a.get("machine_id", ""))[:8],
                    })
                st.dataframe(table_alerts, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Erro ao consultar alertas: {exc}")

    # 3. ÚLTIMAS MEDIÇÕES
    else:
        try:
            measurements = repo.latest_measurements(limit=limit)
            if not measurements:
                st.info("Nenhuma medição encontrada.")
            else:
                table_meas = []
                for row in measurements:
                    m_info = row.get("machines") or {}
                    if isinstance(m_info, list):
                        m_info = m_info[0] if m_info else {}
                    tag = m_info.get("tag", str(row.get("machine_id", ""))[:8])
                    ip = m_info.get("ip", "-")

                    st_val = row.get("status", "")
                    if st_val == "ok":
                        st_label = "🟢 OK"
                    elif st_val == "partial":
                        st_label = "🟡 Parcial"
                    else:
                        st_label = "🔴 Inacessível"

                    table_meas.append({
                        "Horário": format_iso_timestamp(row.get("measured_at")),
                        "Equipamento": tag,
                        "IP": ip,
                        "Status": st_label,
                        "Latência (ms)": row.get("latency_ms"),
                        "Jitter (ms)": row.get("jitter_ms"),
                        "Perda (%)": f"{row.get('packet_loss_percent') or 0}%",
                        "Pacotes": f"{row.get('packets_received') or 0}/{row.get('packets_sent') or 0}",
                    })
                st.dataframe(table_meas, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Erro ao consultar medições: {exc}")


def render_collection_logic_tab(settings, repo, queue, scheduler):
    """Aba de Configuração da Lógica de Coleta, Serviço do Windows e Diagnósticos."""
    st.markdown('<div class="main-header">⚙️ Lógica de Coleta & Serviço</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Gerencie o agendador de tarefas em background, a fila local de resiliência e parâmetros de coleta.</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 🛡️ Agendador de Tarefas do Windows")
        st.write(
            "O coletor pode rodar em background como uma tarefa agendada do Windows, "
            "garantindo que as medições continuem sendo coletadas mesmo após reinicializações."
        )

        sched_status = scheduler.status()
        if sched_status.installed:
            st.success("✅ **O serviço do coletor está INSTALADO no Windows.**")
        else:
            st.warning("⚠️ **O serviço do coletor NÃO está instalado no Windows.**")

        with st.expander("Detalhes técnicos do Agendador"):
            st.code(sched_status.output or "Sem saída de status", language="text")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("🔧 Instalar no Agendador", type="primary", use_container_width=True):
                try:
                    res = scheduler.install()
                    st.success("Tarefa registrada no Windows com sucesso!")
                    time.sleep(1)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Falha ao instalar: {exc}")
        with col_b2:
            if st.button("🛑 Remover do Agendador", type="secondary", use_container_width=True):
                try:
                    res = scheduler.remove()
                    st.info("Tarefa removida do Agendador do Windows.")
                    time.sleep(1)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Falha ao remover: {exc}")

    with col2:
        st.markdown("#### 📦 Fila Local de Resiliência (Offline)")
        st.write(
            "Caso a internet caia ou o Supabase fique temporariamente inacessível, "
            "as medições coletadas são salvas na fila SQLite local para reenvio automático."
        )

        col_q1, col_q2 = st.columns(2)
        col_q1.metric("Amostras Pendentes", queue.size())
        col_q2.metric("Dead-Letter (Falhas Graves)", queue.dead_letter_size())

        st.caption(f"Arquivo do banco local: `{settings.queue_file}`")
        st.caption(f"Retenção de histórico: **{settings.retention_days} dias**")

    st.divider()

    st.markdown("#### ⚡ Diagnóstico e Teste Rápido de IP Local")
    st.write("Digite qualquer endereço IP ou Host para validar conectividade e latência direta da máquina coletora:")

    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        test_ip = st.text_input("IP ou Host para teste avulso:", value="8.8.8.8", key="manual_ping_ip")
    with col_t2:
        st.write("")
        st.write("")
        btn_run_manual = st.button("🚀 Testar Ping", use_container_width=True)

    if btn_run_manual:
        with st.spinner(f"Executando ping de 4 pacotes para {test_ip}..."):
            ok, res_sample = run_ping_test(test_ip, count=4)
            if ok:
                st.success(f"Teste finalizado! Status: **{res_sample.status.upper()}**")
                col_m1, col_m2, col_m3 = st.columns(3)
                col_m1.metric("Latência Média", f"{res_sample.latency_ms or '-'} ms")
                col_m2.metric("Jitter", f"{res_sample.jitter_ms or '-'} ms")
                col_m3.metric("Perda de Pacotes", f"{res_sample.packet_loss_percent}%")
            else:
                st.error(f"Erro no teste: {res_sample}")

    st.divider()
    st.markdown("#### ☁️ Credenciais e Variáveis de Ambiente")
    # Mascara chave por segurança
    key_masked = settings.supabase_key[:6] + "..." + settings.supabase_key[-4:] if len(settings.supabase_key) > 10 else "***"
    st.text(f"URL: {settings.supabase_url}")
    st.text(f"Chave Service Role: {key_masked}")
    st.caption("Configurado via arquivo `.env` na raiz do projeto.")


# =========================================================================
# FUNÇÃO PRINCIPAL
# =========================================================================

def main():
    settings, diary, repo, queue, scheduler = get_services()
    page = render_sidebar(settings, repo, queue, scheduler)

    if page == "🏢 Clientes":
        render_clients_tab(repo, diary)
    elif page == "🖥️ Máquinas & IPs Locais":
        render_machines_tab(repo, diary)
    elif page == "📜 Eventos no Banco":
        render_events_tab(repo)
    elif page == "⚙️ Lógica de Coleta & Serviço":
        render_collection_logic_tab(settings, repo, queue, scheduler)


if __name__ == "__main__":
    main()
