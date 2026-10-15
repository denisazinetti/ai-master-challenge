# Business case e ROI

## Contexto

O business case estima **capacidade potencialmente liberada** — não promessa de corte de equipe.
Há três mecanismos de valor distintos, calculados separadamente para evitar dupla contagem:
capacidade operacional, qualidade de atendimento e retenção de receita.

---

## 1. Capacidade operacional

### Premissas fixas

| Parâmetro | Valor | Justificativa |
|---|---|---|
| Tickets elegíveis/mês | ≈ total anual ÷ 12 × percentual elegível | Exclui Billing inquiry e prioridade Critical/High |
| Custo-hora do agente | US$ 18 | Referência de mercado para suporte tier-1 em operações globais |
| Assistência do copiloto | Apenas rascunho — agente revisa antes de enviar | Guardrail explícito; sem envio automático |

**Tickets elegíveis** = chamados de baixa ou média prioridade que não sejam Billing inquiry.
O número exato é calculado pelo `prepare_data.py` a partir dos dados reais do Dataset 1.

### Fórmula

```
horas_liberadas/mês = tickets_elegíveis/mês × taxa_de_assistência × minutos_poupados ÷ 60
valor_capacidade_anual = horas_liberadas/mês × 12 × custo_hora
```

O `tempo decorrido` registrado no Dataset 1 é o intervalo entre primeira resposta e resolução
(os timestamps existem; a abertura do ticket não). Os minutos poupados referem-se ao tempo de
escrita e triagem pelo agente, não ao tempo total do ticket — premissa separada e mais conservadora.

### Cenários

| Cenário | Taxa de assistência | Minutos poupados/ticket | Horas liberadas/mês* | Valor de capacidade/ano* |
|---|---|---|---|---|
| **Conservador** | 20 % | 3 min | *calculado no build* | *calculado no build* |
| **Base** | 35 % | 6 min | *calculado no build* | *calculado no build* |
| **Ambicioso** | 50 % | 9 min | *calculado no build* | *calculado no build* |

> Os valores numéricos finais são computados em tempo de build pelo `prepare_data.py`
> e exibidos na aba **Visão executiva → ROI por cenário**. Isso garante que os números
> reflitam o volume real do dataset, e não estimativas manuais.

*Exemplo de leitura para o cenário Base com 2.000 tickets elegíveis/mês:*
```
2.000 × 35% × 6 min ÷ 60 = 70 h/mês → 70 × 12 × US$ 18 = US$ 15.120/ano de capacidade
```

---

## 2. Qualidade de atendimento

A melhoria de SLA e CSAT é uma **meta operacional** apoiada pelas associações observadas nos
dados — não uma causalidade provada. O Dataset 1 mostra correlação entre tempo de resolução
acima do P75 e CSAT abaixo de 3, mas a direção causal não é verificável sem experimento
controlado.

**Não foi atribuído valor financeiro a este eixo** para evitar especulação sem fundamento.
O indicador de risco operacional (scoring explicável) é o proxy escolhido: sinaliza onde
a qualidade provavelmente está comprometida, sem prometer o quanto isso vale em reais.

---

## 3. Retenção de receita (evidência complementar — Challenge 001)

O Dataset do Challenge 001 permite estimar exposição de ARR nos segmentos com maior fricção
de suporte. O cálculo é:

```
ARR em risco (potencial) = ARR das contas com risco alto × taxa de intervenção bem-sucedida
```

| Parâmetro | Cenários | Nota |
|---|---|---|
| Taxa de intervenção bem-sucedida | 1 % / 3 % / 5 % | Conservador → Ambicioso |
| ARR base de referência | Join por account_id (Challenge 001) | Dados sintéticos; não transferir diretamente ao Dataset 2 |

> **Limitação crítica:** os dados do Challenge 001 são sintéticos e independentes dos tickets
> do Challenge 002. A associação entre fricção de suporte e churn é **descritiva**, não causal.
> Este eixo é apresentado como evidência complementar, não como projeção de receita garantida.

---

## 4. O que não está no business case

- **Custo de implementação:** horas de engenharia, infra, treinamento de equipe.
- **Risco de adoção:** agentes podem não usar o copiloto ou ignorar a triagem priorizada.
- **Drift do modelo:** o classificador foi validado no Dataset 2; performance em produção pode ser inferior.
- **Custo do LLM:** o copiloto usa API externa (opcional); sem LLM_API_KEY, opera em modo fallback sem custo.

---

## 5. Decisão de investimento

A proposta não recomenda automação total. O ROI justifica **começar pelo cenário Conservador**:
menor risco operacional, aprendizado sobre adoção real, e base de dados para calibrar os
cenários Base e Ambicioso com métricas observadas — não estimadas.
