# Submissão — Denis Zinetti — Challenge 002

## Sobre mim

- **Nome:** Denis Zinetti
- **LinkedIn:** _a adicionar antes do PR_
- **Challenge escolhido:** 002 — Redesign de Suporte

---

## Executive Summary

Construí o **G4Desk**, uma central de operações de suporte que começa por uma pergunta que a maioria das entregas pula: *o que estes dados conseguem sustentar?* Testei os datasets com estatística (FDR 5%, grupos de controle, comparação com o acaso) e o resultado muda a proposta: **no Dataset 1 nenhuma das 8 variáveis explica o CSAT, o texto prevê o tipo do ticket no nível do acaso, 49% dos pares de tempo são impossíveis e a prioridade declarada não altera a chance de um ticket ser encerrado**; no Challenge 001, contas churnadas e retidas têm suporte indistinguível. O que **funciona** é o NLP do Dataset 2 (84,45% de acurácia, 8 classes; busca de casos similares 69% vs 19% do acaso). Por isso a proposta automatiza só onde há prova (classificação, roteamento com limiar de confiança escolhido por curva cobertura × acurácia, rascunho assistido com humano no controle), mede o resto em piloto e **não promete** ganho de CSAT nem de retenção.

---

## Solução

### Abordagem

1. Auditar o Dataset 1 (qualidade de timestamps, cobertura de CSAT, recorrência, texto) antes de analisar.
2. Testar estatisticamente drivers de CSAT e gargalos; transformar o que é política (não evidência) em índice de risco auditável — explicitamente **não** uma probabilidade de churn.
3. Treinar e avaliar classificador no Dataset 2 com separação estratificada de treino e teste.
4. Fazer o join real das cinco tabelas do Challenge 001 para validar a hipótese de que fricção de suporte merece atenção de retenção.
5. Transformar os achados em uma dashboard Dockerizada que funciona localmente e na VPS.

### Resultados / Findings

- **Aba “Diagnóstico estatístico”:** auditoria de dados, drivers de CSAT (Kruskal–Wallis + FDR), backlog por prioridade/tipo/canal, prova de sinal do texto e da busca de similares, tudo com n, p-valor e comparação ao acaso.
- **Onde o fluxo trava:** 67% dos tickets (5.700 de 8.469) não estão encerrados e a taxa é estatisticamente a mesma em Critical (66%) e Low (69%): a prioridade não orienta o atendimento. Tempos por canal/prioridade não são interpretados porque ~49% dos pares resolução × primeira resposta são impossíveis (resolução anterior à resposta); esses pares são descartados, não corrigidos.
- **O que impacta o CSAT:** nada detectável. 0 de 8 variáveis significativas após correção (menor p ajustado ≈ 0,89; ρ tempo × CSAT ≈ 0,00).
- **Classificador (Dataset 2):** split estratificado 80/20 (38.269 treino; 9.568 teste), TF-IDF 1–2 grams + regressão logística via SGD: **84,45% de acurácia e macro-F1 de 84,70%**. Curva cobertura × acurácia: com revisão humana abaixo de 50% de confiança, o roteamento automático atinge ~97% de acurácia cobrindo ~55% do volume. Os números são calculados no build.
- **Casos similares:** busca TF-IDF por cosseno com precisão@3 de ~69% (acaso ~19%) no Dataset 2; no Dataset 1 fica no nível do acaso, então não é exibida nesses tickets.
- **Copiloto:** rascunho via LLM opcional, sempre revisado por humano; cache, limite de requisições, isolamento do texto do cliente no prompt e fallback quando a API falha.
- **Retenção (Challenge 001):** join real por `account_id`; Mann–Whitney (FDR 5%) em 5 métricas de suporte: nenhuma difere entre churnadas e retidas. A hipótese “fricção de suporte antecipa churn” não é sustentada e nenhum ROI de retenção é somado.
- **ROI:** capacidade liberada no cenário base ≈ US$ 2.155/ano no volume do arquivo e ≈ US$ 7.636/ano no volume do briefing (30 mil tickets). Modesto e declarado como tal.

### Recomendações

1. **Atacar o backlog antes da velocidade:** 2 em cada 3 tickets não estão encerrados e a prioridade não muda isso. Priorizar a fila por risco/idade, não pelo rótulo de prioridade.
2. Assistir primeiro tickets de baixa/média prioridade não financeiros, com limiar de confiança de 50% (cobertura/acurácia medidas) e rascunho revisado.
3. Não automatizar cobrança, tickets críticos, baixa confiança ou exceções: permanecem humanos.
4. **Rodar um piloto controlado** (grupo com copiloto × grupo sem) medindo backlog, reabertura e CSAT: os dados atuais não permitem prometer ganho de satisfação ou retenção.
5. Instrumentar a abertura do ticket e corrigir o registro de timestamps: sem isso não existe SLA de primeira resposta.

### Proposta de automação com IA

A esteira de automação foi construída com guardrails rigorosos fundamentados nos dados. O fluxo divide os chamados entre automação zero-touch, assistência por copiloto e intervenção humana obrigatória (billing, críticos e risco de churn). Detalhes completos em [automation-proposal.md](docs/automation-proposal.md).

### ROI e limitações

O business case usa cenários conservador, base e ambicioso. Horas liberadas, valor de capacidade, qualidade e retenção são separados para não produzir dupla contagem. Veja [business-case.md](docs/business-case.md).

Os dois datasets do Challenge 002 não possuem chave relacional comum: eles são cruzados no nível da decisão operacional, não por join inventado. O cruzamento é feito por experimento: o Dataset 2 prova onde o NLP funciona (84,45%) e o Dataset 1 prova onde ele não funciona (acaso), o que define a regra de produto (revisão humana obrigatória no Dataset 1). O Challenge 001 é evidência complementar e, aqui, negativa: churnadas e retidas não diferem em suporte.

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
| Codex / Claude Code | Decomposição, implementação assistida, revisão de fluxos e documentação |
| Python / scikit-learn / SciPy | Preparação, testes estatísticos, classificação e busca verificáveis |
| Docker | Ambiente reproduzível local e de VPS |

### Workflow

1. Li os desafios, o guia de submissão e defini o Challenge 002 como entrega principal.
2. Evitei o erro metodológico de unir datasets que não compartilham uma chave.
3. Baixei os CSVs públicos, conferi cabeçalhos e volumes antes de escrever a transformação.
4. Separei o que pode ser automatizado do que exige julgamento humano.
5. Construí, testei e documentei uma aplicação reproduzível.

### Onde a IA errou e como corrigi

1. A primeira hipótese tratava os datasets do 002 como se pudessem ser unidos diretamente; a inspeção dos esquemas mostrou que não compartilham identificador.
2. O código “corrigia” durações somando 24h a diferenças negativas. Medi: ~49% dos pares são impossíveis. Passei a descartá-los.
3. A “busca de similares” agrupava por tipo + assunto e a documentação a chamava de similaridade. Medi leave-one-out: nível do acaso no Dataset 1. Troquei por TF-IDF/cosseno e o exponho só onde funciona (Dataset 2, 69% vs 19%).
4. Escrevi que tickets lentos com CSAT baixo “correlacionam com churn”. Testei no Challenge 001: não correlacionam. Reescrevi a proposta e retirei o ROI de retenção.
5. O limiar de 70% era intuição. A curva cobertura × acurácia mostrou que 50% automatiza mais que o dobro do volume mantendo ~97%.
Detalhes em `process-log/decision-log.md`.

### O que eu adicionei que a IA sozinha não faria

O julgamento principal foi **desconfiar do dataset antes de confiar no modelo**: auditar, testar contra o acaso e aceitar resultados negativos (sem driver de CSAT, sem sinal textual no Dataset 1, sem ligação suporte → churn) em vez de embelezá-los. O score é uma política explicável, o LLM produz rascunho revisável e não decide nem executa por conta própria, e o ROI é mostrado nos dois volumes.

---

## Evidências

- [x] Git history da implementação
- [x] Narrativa de decisão em `process-log/decision-log.md`
- [ ] Screenshots da dashboard local e da URL VPS — adicionar antes do PR
- [ ] URL pública da VPS — adicionar após deploy

_Submissão preparada em 14/10/2026._
