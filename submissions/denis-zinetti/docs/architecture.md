# Arquitetura

O G4Desk é um monólito intencionalmente simples: React compilado é servido pelo FastAPI, que entrega dados preparados, classificação e o endpoint opcional de LLM. Um único container reduz configuração para quem avalia e mantém o deploy em VPS previsível.

```text
CSVs públicos → prepare_data.py → dashboard.json → FastAPI → React
                                           └────→ copiloto LLM opcional
```

O classificador é treinado offline a partir do Dataset 2, com separação estratificada treino/teste. A versão demonstrada usa TF-IDF com bigramas e regressão logística: é reproduzível, rápida e retorna probabilidades, usadas para sinalizar revisão humana. Uma evolução natural é substituir o vetorizador por embeddings de sentença, mantendo a mesma interface de classificação.

O risco de retenção é uma regra operacional explicável, não um modelo que afirme prever churn. O LLM nunca tem permissão para enviar mensagens, concluir tickets ou alterar dados.
