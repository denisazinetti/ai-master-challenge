# Metodologia e qualidade de dados

O Dataset 1 contém timestamps em `First Response Time` e `Time to Resolution`, mas não contém a abertura do ticket. Portanto, não é válido calcular tempo até primeira resposta: a aplicação mostra esse indicador como **N/D**.

Quando os dois timestamps existem, a análise calcula apenas o intervalo entre primeira resposta e resolução, corrigindo virada de dia. Esse é um proxy pós-resposta, não um SLA de primeira resposta.

O risco usa prioridade, esse proxy, CSAT, recorrência e status. Ausências não são preenchidas com valores inventados. A comparação do Challenge 001 é descritiva e não estabelece causalidade.
