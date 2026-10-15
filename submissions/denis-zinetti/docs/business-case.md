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
| **Conservador** | 20 % | 3 min | 2,9 h (dataset) · 10,1 h (30 mil/ano) | US$ 616 · US$ 2.182 |
| **Base** | 35 % | 6 min | 10,0 h (dataset) · 35,4 h (30 mil/ano) | US$ 2.155 · US$ 7.636 |
| **Ambicioso** | 50 % | 9 min | 21,4 h (dataset) · 75,8 h (30 mil/ano) | US$ 4.617 · US$ 16.362 |

> Os valores são computados no build pelo `prepare_data.py` (aba **Visão executiva → ROI por cenário**) em dois volumes:
> o do arquivo (8.469 tickets, tratados como 1 ano) e o do briefing (~30.000 tickets/ano). Os dois são exibidos porque o ganho
> escala linearmente com o volume e escolher só o maior seria viés. **A conclusão honesta: capacidade liberada é modesta
> (≈ 425 h/ano no cenário base com 30 mil tickets) e não paga sozinha um projeto grande; o valor está em poder
> medir, com um piloto barato, o que de fato muda.**

*Exemplo de leitura, cenário Base no volume do briefing (1.010 tickets elegíveis/mês = 30.000 × 40,4% ÷ 12):*
```
1.010 × 35% × 6 min ÷ 60 = 35,4 h/mês → 35,4 × 12 × US$ 18 ≈ US$ 7.636/ano de capacidade
```

---

### Desperdício atual (visão complementar)

A aba Diagnóstico estima o desperdício em três fontes, sempre rotuladas como premissa: retrabalho do backlog parado (~20 mil h/ano no volume do briefing, alavanca de **processo**), triagem manual de tickets roteáveis e redação de respostas elegíveis (~970 h/ano juntas, alavanca de **IA**, ≈ US$ 17 mil/ano). O ROI de IA acima (cenário base) usa só a redação; a triagem é um ganho adicional. O ponto central: o maior desperdício não é endereçado por IA.

## 2. Qualidade de atendimento

**Não há evidência de que algum fator operacional mude o CSAT neste dataset.** Em 9 variáveis testadas
(canal, prioridade, tipo, assunto, produto, gênero, faixa etária, idade do produto e tempo pós-resposta; Kruskal–Wallis com FDR 5%) nenhuma é
significativa, e Spearman tempo × CSAT é ρ ≈ 0,00. Qualquer promessa de ganho de satisfação seria especulação.

**Não foi atribuído valor financeiro a este eixo** para evitar especulação sem fundamento.
O indicador de risco operacional (scoring explicável) é o proxy escolhido: sinaliza onde
a qualidade provavelmente está comprometida, sem prometer o quanto isso vale em reais.

---

## 3. Retenção de receita (evidência complementar — Challenge 001)

Foi feito o join real de contas, chamados e assinaturas (`account_id`) e testadas cinco métricas de suporte entre contas churnadas e retidas (Mann–Whitney, FDR 5%): tickets por conta, tempo de resolução, primeira resposta, CSAT e escalonamento. **Nenhuma diferença é significativa** (menor p ajustado ≈ 0,52).

Consequência para o business case: **nenhum valor de retenção é somado ao ROI.** A premissa “fricção de suporte antecipa churn” não é sustentada por esses dados, e projetar “ARR em risco × taxa de intervenção” criaria um número sem base. A fila de risco existe como política de cuidado com clientes de maior impacto e será avaliada em piloto, não por previsão.

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
