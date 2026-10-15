# Decision log

## 1. Problema antes da ferramenta

O desafio não pede “um classificador”. Pede uma operação que reduza desperdício e mostre um fluxo realista de IA. A decisão foi construir um caminho curto: diagnóstico → prioridade → assistência → intervenção humana quando o risco exige.

## 2. Verificação de dados

Os arquivos públicos foram inspecionados antes da análise. O Dataset 1 tem métricas e texto; o Dataset 2 contém `Document` e oito rótulos em `Topic_group`; os arquivos do Challenge 001 permitem join por conta/assinatura. Não existe chave compartilhada entre os dois datasets do 002.

## 3. Escolhas de IA

- Classificação: TF-IDF + regressão logística, com teste estratificado e probabilidades.
- Recuperação de casos similares: TF-IDF por cosseno. A primeira versão agrupava por tipo + assunto exato e a documentação a descrevia como “casos similares”; medi leave-one-out e o resultado foi **nível do acaso (~5,5% vs ~6%) no Dataset 1** e ~69% (vs ~19%) no Dataset 2. Decisão: a busca é exposta onde funciona (Classificador, Dataset 2) e removida dos tickets do Dataset 1.
- LLM: chamada opcional e guardrailed para gerar rascunho; fallback explícito sem chave ou quando a API falha.

## 3.1 Onde a IA (e eu) errei, e o que mudei depois de medir

1. **“Corrigia” durações.** O código somava 24h a diferenças negativas entre timestamps. Auditar mostrou que ~49% dos pares têm resolução anterior à primeira resposta: não é virada de dia, é dado inválido. Passei a descartar esses pares e a declarar a limitação.
2. **Limiar de 70% por intuição.** A curva cobertura × acurácia mostrou que 70% deixa só ~25% do volume automático (acurácia ~99,5%), enquanto 50% cobre ~55% com ~97%. Limiar passou a 50%, justificado em dados.
3. **Regra de risco morta.** “Primeira resposta acima do P75” nunca disparava (não existe abertura de ticket). Removida.
4. **Afirmações sem base.** A proposta dizia que tickets lentos e com CSAT baixo “têm correlação direta com churn”. Ao testar o Challenge 001 (Mann–Whitney, FDR 5%), churnadas e retidas têm suporte indistinguível. Reescrevi o texto e removi qualquer ROI de retenção.
5. **Diagnóstico de CSAT.** Testei 8 variáveis com correção de múltiplas comparações: nenhuma é significativa. Em vez de inventar “drivers”, o produto afirma que não há alavanca comprovada e propõe piloto controlado.
6. **ROI.** O arquivo tem 8,5 mil tickets; o briefing diz ~30 mil/ano. Mostrei os dois volumes em vez de escolher o mais favorável.

## 4. Limites humanos

Não automatizar billing, prioridade crítica, baixa confiança, compensações, mudanças de dados ou envio de mensagem. Esses limites fazem parte do produto, não apenas da documentação.

## 5. Engenharia

API com cache por mtime, índice por id, limite de requisições, delimitação do texto do cliente no prompt, fallback para falha de LLM e dependências do frontend travadas (`npm ci` com lockfile) para build reprodutível.

## 6. Evidência a completar antes do PR

Capturar: dashboard local, detalhe de ticket, fallback do copiloto, healthcheck Docker e URL HTTPS publicada. Anexar os arquivos em `process-log/screenshots/`.
