# Submissão — Denis Zinetti — Challenge 002

## Sobre mim

- **Nome:** Denis Zinetti
- **LinkedIn:** _a adicionar antes do PR_
- **Challenge escolhido:** 002 — Redesign de Suporte

---

## Executive Summary

Construí o **G4Desk**, uma central de inteligência operacional que usa chamados para priorizar trabalho de suporte e acionar prevenção de retenção antes do cancelamento. A solução combina diagnóstico de gargalos com um classificador NLP avaliado em 47 mil tickets, um índice explicável de risco operacional e um copiloto de resposta que mantém aprovação humana. O resultado é uma rotina que o diretor pode acompanhar por ROI e o agente pode usar no ticket seguinte — não um dashboard desconectado da operação.

---

## Solução

### Abordagem

1. Perfilar o Dataset 1 para identificar variáveis operacionais, tempos, satisfação e recorrência.
2. Transformar os sinais operacionais em índice de risco auditável — explicitamente **não** uma probabilidade de churn.
3. Treinar e avaliar classificador no Dataset 2 com separação estratificada de treino e teste.
4. Fazer o join real das cinco tabelas do Challenge 001 para validar a hipótese de que fricção de suporte merece atenção de retenção.
5. Transformar os achados em uma dashboard Dockerizada que funciona localmente e na VPS.

### Resultados / Findings

- A tela executiva torna visíveis volume, primeira resposta, resolução, CSAT, risco e capacidade potencialmente liberada.
- A central ordena tickets por urgência de negócio, combinando prioridade, tempos, satisfação, recorrência e status.
- O classificador usa `Document → Topic_group` do Dataset 2. No split estratificado 80/20 (38.269 treino; 9.568 teste), TF-IDF 1–2 grams + regressão logística via SGD atingiu **84,45% de acurácia** e **macro-F1 de 84,70%** nas oito categorias. O artefato inclui métricas por categoria e matriz de confusão; os números são calculados no build, nunca preenchidos manualmente.
- O copiloto recupera casos resolvidos similares e gera somente um rascunho de resposta, que exige revisão humana.
- A seção “Validação de retenção” apresenta comparação entre contas churnadas e retidas após join por `account_id` e receita de assinaturas por `account_id`.

### Recomendações

1. Assistir primeiro tickets de baixa/média prioridade não financeiros: o ganho é de velocidade com risco operacional controlado.
2. Criar uma fila de risco alto para suporte + CS, com playbook em até um dia útil.
3. Não automatizar cobrança, tickets críticos, baixa confiança do classificador ou exceções: esses casos devem permanecer humanos.

### Proposta de automação com IA

A esteira de automação foi construída com guardrails rigorosos fundamentados nos dados. O fluxo divide os chamados entre automação zero-touch, assistência por copiloto e intervenção humana obrigatória (billing, críticos e risco de churn). Detalhes completos em [automation-proposal.md](docs/automation-proposal.md).

### ROI e limitações

O business case usa cenários conservador, base e ambicioso. Horas liberadas, valor de capacidade, qualidade e retenção são separados para não produzir dupla contagem. Veja [business-case.md](docs/business-case.md).

Os dois datasets do Challenge 002 não possuem chave relacional comum: eles são cruzados no nível da decisão operacional, não por join inventado. O Challenge 001 é evidência complementar; correlação entre suporte e churn não estabelece causalidade e não é transferida para os tickets do 002.

### Como rodar

Veja [deployment.md](docs/deployment.md). O caminho mais simples é:

```bash
cd solution/docker
cp .env.example .env
docker compose -f compose.yml -f compose.local.yml up --build
```

No PowerShell: `Copy-Item .env.example .env` no lugar de `cp`.

Abra `http://localhost:8080`. A mesma imagem aceita o override `compose.vps.yml` para Traefik/Let's Encrypt.

---

## Process Log — Como usei IA

> Este bloco é obrigatório. A entrega inclui também `process-log/decision-log.md`.

### Ferramentas usadas

| Ferramenta | Para que usei |
|---|---|
| Codex | Decomposição, implementação assistida, revisão de fluxos e documentação |
| Python / scikit-learn | Preparação, diagnóstico e classificação verificável |
| Docker | Ambiente reproduzível local e de VPS |

### Workflow

1. Li os desafios, o guia de submissão e defini o Challenge 002 como entrega principal.
2. Evitei o erro metodológico de unir datasets que não compartilham uma chave.
3. Baixei os CSVs públicos, conferi cabeçalhos e volumes antes de escrever a transformação.
4. Separei o que pode ser automatizado do que exige julgamento humano.
5. Construí, testei e documentei uma aplicação reproduzível.

### Onde a IA errou e como corrigi

A primeira hipótese tratava os datasets do 002 como se pudessem ser unidos diretamente. A inspeção dos esquemas mostrou que eles não compartilham identificador. Corrigi o desenho: Dataset 1 passou a medir operação, Dataset 2 passou a validar classificação e o join relacional ficou restrito às tabelas do Challenge 001.

### O que eu adicionei que a IA sozinha não faria

O julgamento principal foi evitar “previsão de churn” sem rótulo comum e evitar automação total. O score é um indicador operacional explicável e o LLM produz rascunho revisável, não decide nem executa por conta própria.

---

## Evidências

- [x] Git history da implementação
- [x] Narrativa de decisão em `process-log/decision-log.md`
- [ ] Screenshots da dashboard local e da URL VPS — adicionar antes do PR
- [ ] URL pública da VPS — adicionar após deploy

_Submissão preparada em 14/10/2026._
