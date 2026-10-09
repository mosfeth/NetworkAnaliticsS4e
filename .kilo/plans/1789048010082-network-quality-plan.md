# Plano: Sistema de Qualidade de Rede com Aprendizado Contínuo

## 1. Objetivo
Criar sistema que:
- Analisa oscilações de jitter/latência a cada hora
- Classifica a qualidade como BOM/MÉDIO/RUIM
- Armazena feedback do usuário
- Usa ML (regressão logística / árvore de decisão) após semanas de dados

## 2. Escopo
- Backend: `src/supadiag/network_quality.py`
- Banco: novas tabelas `network_quality_metrics` + `network_feedback`
- FrontEnd: exibição do status e coleta de feedback
- ML: script separado para treino periódico

## 3. Decisões Pendentes
1. **Onde armazenar as métricas horárias?** Tabela nova `network_quality_metrics` ou reutilizar `measurements`?
2. **Com que frequência calcular a média?** A cada hora fixa (ex: HH:00) ou sliding window de 1h?
3. **Como capturar o feedback do usuário?** Botão nos cards do FrontEnd ou CLI?
4. **Onde treinar o modelo?** Script separado executado periodicamente ou dentro do próprio monitor?
5. **Como armazenar o modelo treinado?** Arquivo pickle local ou tabela no Supabase?

## 4. Dados Atuais Disponíveis
- `measurements` já tem: `latency_ms`, `jitter_ms`, `packet_loss_percent`, `measured_at`, `machine_id`
- `machine_feedback` já tem: `label` (bom/medio/ruim), `latency_ms`, `jitter_ms`, `packet_loss_percent`
- Frequência de medição: ~5 minutos (configurável)

## 5. Próximo Passo
Responder à decisão 1: onde armazenar as métricas horárias?
- Opção A: Tabela nova `network_quality_metrics` (mais limpo, dedicado)
- Opção B: Reutilizar `measurements` com flag `is_hourly_aggregate` (menos tabelas)

Recomendo Opção A por clareza e separação de responsabilidades.
