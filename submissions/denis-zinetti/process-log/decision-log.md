# Decision log

## 1. Problema antes da ferramenta

O desafio não pede “um classificador”. Pede uma operação que reduza desperdício e mostre um fluxo realista de IA. A decisão foi construir um caminho curto: diagnóstico → prioridade → assistência → intervenção humana quando o risco exige.

## 2. Verificação de dados

Os arquivos públicos foram inspecionados antes da análise. O Dataset 1 tem métricas e texto; o Dataset 2 contém `Document` e oito rótulos em `Topic_group`; os arquivos do Challenge 001 permitem join por conta/assinatura. Não existe chave compartilhada entre os dois datasets do 002.

## 3. Escolhas de IA

- Classificação: TF-IDF + regressão logística, com teste estratificado e probabilidades.
- Recuperação: sobreposição lexical de descrições dentro do mesmo tipo de ticket, limitada à fila priorizada para manter resposta imediata. Uma evolução para embeddings de sentença está documentada, mas não foi simulada como entregue.
- LLM: chamada opcional e guardrailed para gerar rascunho; fallback explícito sem chave.

## 4. Limites humanos

Não automatizar billing, prioridade crítica, baixa confiança, compensações, mudanças de dados ou envio de mensagem. Esses limites fazem parte do produto, não apenas da documentação.

## 5. Evidência a completar antes do PR

Capturar: dashboard local, detalhe de ticket, fallback do copiloto, healthcheck Docker e URL HTTPS publicada. Anexar os arquivos em `process-log/screenshots/`.
