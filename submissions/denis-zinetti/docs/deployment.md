# Execução local e VPS

## Pré-requisito de dados

Baixe os três datasets indicados nos READMEs dos Challenges 001 e 002 e coloque os arquivos nos caminhos abaixo, que são ignorados pelo Git:

```text
solution/app/backend/app/data/raw/customer_support_tickets.csv
solution/app/backend/app/data/raw/all_tickets_processed_improved_v3.csv
solution/app/backend/app/data/raw/churn/ravenstack_*.csv
```

## Local — Docker

```bash
cd submissions/denis-zinetti/solution/docker
cp .env.example .env
docker compose -f compose.yml -f compose.local.yml up --build
```

No PowerShell, substitua `cp .env.example .env` por `Copy-Item .env.example .env`.

Abra `http://localhost:8080`. O mesmo build executa a preparação de dados e treina/avalia o classificador; não é necessário instalar Python ou Node na máquina anfitriã.

## VPS — Docker, Traefik e Let's Encrypt

1. Copie `.env.example` para `.env`, defina `APP_HOST`, `TRAEFIK_NETWORK` e `TRAEFIK_CERTRESOLVER` conforme o Traefik existente.
2. Garanta que DNS do domínio aponta para a VPS e que a rede informada é uma rede Docker externa acessível pelo Traefik.
3. Suba com:

```bash
docker compose -f compose.yml -f compose.vps.yml up -d --build
```

4. Verifique `https://$APP_HOST/health`. O Traefik emite/renova o certificado com o resolver configurado.

### Atualização e rollback

Atualize com o mesmo comando de subida. Para rollback, use a tag de imagem anterior no `compose.yml` ou faça checkout do commit anterior e execute novamente o build. Como a aplicação só gera artefatos a partir de dados públicos, não há estado de negócio crítico no container.
