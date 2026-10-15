# Arquitetura

O G4Desk é um monólito intencionalmente simples: React compilado é servido pelo FastAPI, que entrega dados preparados, classificação e o endpoint opcional de LLM. Um único container reduz configuração para quem avalia e mantém o deploy em VPS previsível.

```text
CSVs públicos → prepare_data.py ─┬→ dashboard.json  ─┐
                 (diagnostics.py)  ├→ classifier.joblib ├→ FastAPI → React
                                   └→ similar_cases.joblib ┘   └→ copiloto LLM opcional
```

`diagnostics.py` concentra os testes estatísticos (auditoria, drivers de CSAT, prova de sinal, curva de limiar, busca de casos similares). Os artefatos são gerados durante o build da imagem, a partir de CSVs públicos.

O classificador é treinado offline a partir do Dataset 2, com separação estratificada treino/teste. A versão demonstrada usa TF-IDF com bigramas e regressão logística: é reproduzível, rápida e retorna probabilidades, usadas para sinalizar revisão humana abaixo de 50% de confiança (limiar escolhido pela curva cobertura × acurácia em dados de teste). Uma evolução natural é substituir o vetorizador por embeddings de sentença, mantendo a mesma interface de classificação.

O risco de retenção é uma regra operacional explicável, não um modelo que afirme prever churn. A API limita requisições por IP (copiloto: 10/min), isola o texto do cliente do prompt, degrada para fallback se o LLM falhar e mantém os dados em cache por mtime. O LLM nunca tem permissão para enviar mensagens, concluir tickets ou alterar dados.
