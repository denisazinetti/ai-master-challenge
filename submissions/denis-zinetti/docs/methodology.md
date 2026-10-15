# Metodologia e qualidade de dados

Princípio: antes de propor automação, testar o que cada dataset consegue sustentar. Todos os números abaixo são calculados no build (`prepare_data.py`, `diagnostics.py`), nunca digitados.

## 1. Auditoria do Dataset 1 (8.469 tickets)

| Verificação | Resultado | Consequência |
|---|---|---|
| Abertura do ticket | Não existe | Não há SLA de primeira resposta; o indicador é exibido como **N/D**. |
| Primeira resposta × resolução | Em ~49% dos pares a resolução é **anterior** à primeira resposta | Pares impossíveis são descartados (`NaN`), não “corrigidos”. Uma versão anterior somava 24h aos negativos; isso fabricava durações e foi removido. |
| CSAT | Somente tickets encerrados (2.769) | Drivers de satisfação são testados só nessa base. |
| Recorrência | 98% dos clientes têm um único ticket | O fator “recorrência” do risco quase nunca dispara; é mantido por política, não por evidência. |
| Texto | 100% das descrições têm um placeholder não preenchido (`{product_purchased}`) | Placeholders são removidos antes de qualquer vetorização. |

## 2. O que influencia o CSAT?

Kruskal–Wallis para cada variável (canal, prioridade, tipo, assunto, produto, gênero, faixa etária, faixa de tempo pós-resposta), correção de Benjamini–Hochberg (FDR 5%), tamanho de efeito ε² e Spearman para tempo × CSAT. **Nenhuma das 8 variáveis é significativa** (menor p ajustado ≈ 0,89; ρ ≈ 0,00). Conclusão: não há alavanca comprovada sobre o CSAT; a proposta mede resultado em piloto em vez de prometer ganho.

## 3. Onde o fluxo trava?

O sinal confiável do dataset é o **status**: 67% dos tickets não estão encerrados, e a taxa é estatisticamente indistinta entre Critical e Low (χ², p ≈ 0,10). Ou seja, a prioridade declarada não está orientando o atendimento. Diferenças de tempo entre canal/prioridade não são interpretadas porque a duração é inválida em metade dos pares.

## 3.1 Combinações e desperdício

- **Ranking canal × prioridade × tipo:** média do tempo pós-resposta por combinação (n ≥ 10 pares válidos), com IC95 e teste de permutação (500 embaralhamentos) para a pior média. Resultado: 11,4h observado contra 11,2h esperado por acaso (p=0,35), ou seja, o ranking não é sinal.
- **Desperdício:** horas de agente = premissas explícitas (releitura de backlog 1×/mês × 5 min; triagem manual 2 min × cobertura automática medida; redação 6 min × 35% × elegíveis) multiplicadas por contagens reais. A sensibilidade do backlog (0,5×, 1×, 2×) é exibida. Espera do cliente (horas acima da mediana) é dado observado, só nos pares válidos, sem extrapolação.

## 4. Onde o texto funciona (prova de sinal)

| Experimento | Acurácia / precisão | Acaso |
|---|---|---|
| D1 · prever tipo de ticket pelo texto | ~21% | 20% |
| D1 · prever assunto pelo texto | ~6% | ~6% |
| D1 · casos similares (mesmo assunto) | ~5,5% | ~6% |
| D2 · classificar 8 categorias | 84,45% | ~19% |
| D2 · casos similares (mesma categoria, top-3) | ~69% | ~19% |

O texto do Dataset 1 não carrega sinal de categoria. Por isso a automação por texto é validada no Dataset 2 e, aplicada ao Dataset 1, passa sempre por revisão humana.

## 5. Limiar de confiança

O limiar de revisão (50%) vem da curva cobertura × acurácia em tickets de teste (Dataset 2): em 50% o roteamento automático atinge ~97% de acurácia cobrindo ~55% do volume; em 70% subiria a ~99,5%, mas só ~25% do volume ficaria automático. A curva está na aba Classificador NLP.

## 6. Índice de risco

Regra aditiva transparente (prioridade, resolução acima do P75 dos pares válidos, CSAT, recorrência, status). Como o Dataset 1 não tem driver estatístico de CSAT, os pesos são **política operacional**, não parâmetros ajustados — e isso está declarado na interface e no código. Não é probabilidade de churn.

## 7. Challenge 001 (retenção)

Join real por `account_id` entre contas, chamados e assinaturas. Teste de Mann–Whitney (FDR 5%) entre contas churnadas e retidas: tickets por conta, resolução, primeira resposta, CSAT e escalonamento **não diferem significativamente**. A hipótese “fricção de suporte antecipa churn” **não é sustentada** por esse dataset; ele é apresentado como evidência negativa, e nenhuma projeção de receita em risco é feita a partir dele.
