# Plano: Rede Neural PyTorch - Previsão 4h de Qualidade de Rede

## 1. Objetivo
Prever a qualidade da conexão (BOM/MÉDIO/RUIM) para as próximas 4 horas baseado em histórico de medições.

## 2. Arquitetura PyTorch

### 2.1 Tipo de Modelo
- **LSTM** (Long Short-Term Memory) - melhor para séries temporais
- **Alternativa:** Transformer simplificado se dados forem suficientes

### 2.2 Arquitetura LSTM Proposta
```
Input: (batch, sequence_length, features)
    ↓
LSTM(64, batch_first=True)
    ↓
Dropout(0.3)
    ↓
LSTM(32, batch_first=True)
    ↓
Dropout(0.2)
    ↓
Linear(32, 16)
    ↓
ReLU
    ↓
Linear(16, 3)  # BOM, MÉDIO, RUIM
    ↓
Softmax
```

### 2.3 Parâmetros de Entrada (Features por timestamp)
1. `latency_ms` - Latência normalizada
2. `jitter_ms` - Jitter normalizado
3. `packet_loss_percent` - Perda normalizada
4. `availability_pct` - Disponibilidade normalizada
5. `hour_sin` - Hora do dia (seno)
6. `hour_cos` - Hora do dia (cosseno)
7. `day_sin` - Dia da semana (seno)
8. `day_cos` - Dia da semana (cosseno)

**Total:** 8 features por timestamp

### 2.4 Janela Temporal
- **Sequence length:** 12 (últimas 12 medições = 1 hora se medição a cada 5min)
- **Previsão:** 4 passos à frente (4 horas)
- **Horizon:** 4

## 3. Tamanho da Base de Dados

### 3.1 Cálculo
- **Medições necessárias:** 1 máquina × 5min intervalo = 12 medições/hora
- **Janela de treino:** 12 medições (1 hora) → 1 previsão (4h)
- **Amostras por máquina:** 
  - 1 semana = 2.016 medições
  - Janelas possíveis: ~2.000 amostras
- **Mínimo absoluto:** 100 amostras (100 horas de dados = ~4 dias)
- **Ideal:** 500+ amostras (3+ semanas de dados)

### 3.2 Recomendação
- **Mínimo:** 100 amostras (4 dias de dados contínuos)
- **Bom:** 300 amostras (2+ semanas)
- **Ideal:** 500+ amostras (1+ mês)

## 4. Implementação Técnica

### 4.1 Dependências
```python
torch>=2.0
torchvision
numpy
pandas
scikit-learn
supabase-py
```

### 4.2 Estrutura de Arquivos
```
src/supadiag/
    network_quality.py          # Existente
    ml_model.py                 # Novo: arquitetura PyTorch
    ml_trainer.py               # Novo: treino e avaliação
    ml_predictor.py             # Novo: previsão 4h
FrontEnd/
    ml_dashboard.py             # Novo: gráfico previsão
```

### 4.3 Classes Principais

#### `NetworkQualityLSTM(nn.Module)`
- Arquitetura LSTM
- Método `forward()` para previsão
- Método `predict_sequence()` para 4h à frente

#### `NetworkQualityDataset(Dataset)`
- Cria janelas temporais
- Normalização de features
- Split treino/validação/teste

#### `NetworkQualityTrainer`
- Loop de treino
- Early stopping
- Salvamento de modelo
- Métricas de avaliação

#### `NetworkQualityPredictor`
- Carrega modelo treinado
- Faz previsão 4h à frente
- Retorna classe + probabilidades

## 5. Gráfico de Previsão

### 5.1 Estrutura
- **Eixo X:** Tempo (últimas 12h + próximas 4h)
- **Eixo Y:** Qualidade (BOM=3, MÉDIO=2, RUIM=1)
- **Linha:** Histórico real (últimas 12h)
- **Pontos:** Previsão (próximas 4h)
- **Cores:** Verde=BOM, Amarelo=MÉDIO, Vermelho=RUIM

### 5.2 Plotly
```python
fig.add_trace(go.Scatter(
    x=historical_timestamps,
    y=historical_quality,
    mode='lines',
    name='Histórico'
))
fig.add_trace(go.Scatter(
    x=forecast_timestamps,
    y=forecast_quality,
    mode='markers',
    marker=dict(size=10, color=forecast_colors),
    name='Previsão 4h'
))
```

## 6. Ciclo de Treinamento

### 6.1 Aquisição de Dados
```sql
SELECT 
    m.measured_at,
    m.latency_ms,
    m.jitter_ms,
    m.packet_loss_percent,
    EXTRACT(hour FROM m.measured_at) as hour,
    EXTRACT(dow FROM m.measured_at) as day_of_week
FROM measurements m
WHERE m.machine_id = ?
ORDER BY m.measured_at DESC
LIMIT 5000
```

### 6.2 Pré-processamento
1. Normalização: StandardScaler
2. Criação de janelas: 12h → 4h
3. Encoding de hora/dia: seno/cosseno
4. Balanceamento: oversampling se necessário

### 6.3 Treino
- Épocas: 100
- Batch size: 16
- Learning rate: 0.001
- Optimizer: Adam
- Scheduler: ReduceLROnPlateau
- Early stopping: patience=15

### 6.4 Avaliação
- Accuracy
- F1-score por classe
- Matriz de confusão
- Salvar métricas no Supabase

## 7. Integração FrontEnd

### 7.1 Página de Treino
- Botão "Treinar Modelo"
- Progresso de treino
- Métricas de avaliação
- Download de modelo

### 7.2 Gráfico de Previsão
- Na página de detalhes do cliente
- Mostrar últimas 12h + previsão 4h
- Atualizar a cada nova medição

### 7.3 Indicadores
- Acurácia do modelo
- Último treino
- Número de amostras usadas

## 8. Próximos Passos
1. Implementar `ml_model.py` com LSTM
2. Criar `ml_trainer.py` com loop de treino
3. Implementar `ml_predictor.py` para previsão 4h
4. Criar gráfico no FrontEnd
5. Adicionar botão de treino
6. Testar com dados reais

## 9. Riscos e Mitigações
- **Poucos dados:** Começar com modelo simples, aumentar complexidade gradualmente
- **Overfitting:** Dropout + early stopping + data augmentation
- **Classes desbalanceadas:** Class weights + oversampling
- **Latência alta:** Otimizar modelo para inferência rápida
