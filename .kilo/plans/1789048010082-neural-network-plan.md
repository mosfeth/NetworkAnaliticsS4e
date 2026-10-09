# Plano: Rede Neural para Classificação de Qualidade de Rede

## 1. Objetivo
Classificar automaticamente a qualidade da conexão como BOM/MÉDIO/RUIM baseado em métricas de rede, substituindo a lógica atual de regras fixas.

## 2. Arquitetura Proposta

### 2.1 Tipo de Rede
- **Tipo:** Rede Neural Feedforward (DNN) simples
- **Tarefa:** Classificação multiclasse (3 classes: BOM, MÉDIO, RUIM)
- **Complexidade:** Baixa para evitar overfitting com poucos dados iniciais

### 2.2 Camadas
```
Input (6 features)
    ↓
Dense(16, relu) + Dropout(0.2)
    ↓
Dense(8, relu) + Dropout(0.1)
    ↓
Dense(3, softmax)  # BOM, MÉDIO, RUIM
```

### 2.3 Parâmetros de Entrada (Features)
1. `avg_latency_ms` - Latência média da última hora
2. `avg_jitter_ms` - Jitter médio da última hora
3. `packet_loss_pct` - Perda de pacotes média (%)
4. `availability_pct` - Disponibilidade (%)
5. `hour_of_day` - Hora do dia (0-23)
6. `day_of_week` - Dia da semana (0-6)

### 2.4 Normalização
- StandardScaler para features numéricas
- One-hot encoding para hora/dia (opcional, pode usar normalização simples)

### 2.5 Classes de Saída
- 0: BOM
- 1: MÉDIO
- 2: RUIM

## 3. Estratégia de Treinamento

### 3.1 Dados
- Fonte: `machine_feedback` + `network_quality_metrics`
- Join por machine_id + timestamp próximo
- Mínimo: 100 amostras para treino inicial

### 3.2 Split
- Treino: 70%
- Validação: 20%
- Teste: 10%
- Stratified split para manter proporção das classes

### 3.3 Hiperparâmetros Iniciais
- Épocas: 50
- Batch size: 8
- Learning rate: 0.001
- Optimizer: Adam
- Loss: categorical_crossentropy
- Early stopping: patience=10

### 3.4 Balanceamento
- Se classes desbalanceadas: class_weight='balanced'
- Data augmentation: ruído pequeno nas features

## 4. Implementação Técnica

### 4.1 Dependências
- TensorFlow/Keras ou PyTorch
- scikit-learn (preprocessamento, métricas)
- numpy/pandas

### 4.2 Estrutura de Arquivos
```
src/supadiag/
    network_quality.py          # Módulo existente
    ml_model.py                 # Novo: modelo e treino
    ml_trainer.py               # Novo: script de treino periódico
FrontEnd/
    ml_dashboard.py             # Novo: visualização do modelo
```

### 4.3 Persistência
- Pesos salvos em `ml_model_weights` (JSON)
- Histórico em `ml_training_history`
- Scaler salvo junto com pesos

## 5. Ciclo de Vida

### 5.1 Treino Inicial
- Após 100 feedbacks acumulados
- Treino manual via script

### 5.2 Re-treino Periódico
- A cada 7 dias ou 50 novos feedbacks
- Automático via agendador

### 5.3 Avaliação Contínua
- Métricas: accuracy, precision, recall, f1
- Log no Supabase
- Alertas se performance cair

## 6. Integração FrontEnd

### 6.1 Visualização
- Mostrar acurácia do modelo atual
- Gráfico de evolução da acurácia
- Distribuição de classes previstas

### 6.2 Fallback
- Se modelo não treinado: usar regras atuais
- Se dados insuficientes: usar regras atuais

## 7. Próximos Passos
1. Implementar `ml_model.py` com arquitetura Keras
2. Criar script de treino `ml_trainer.py`
3. Integrar com `network_quality.py`
4. Adicionar botão "Treinar Modelo" no FrontEnd
5. Automatizar re-treino via agendador

## 8. Riscos
- Poucos dados iniciais → overfitting
- Solução: Começar com regras, migrar gradualmente
- Classes desbalanceadas → bias
- Solução: Class weights e data augmentation
