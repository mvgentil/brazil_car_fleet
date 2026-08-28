# 🚗 Brazil Car Fleet Analytics — Databricks Medallion Architecture

<div align="center">

![Databricks](https://img.shields.io/badge/Databricks-Lakeflow%20Pipelines-FF3621?style=for-the-badge&logo=databricks&logoColor=white)
![Databricks AI Dev Kit](https://img.shields.io/badge/Databricks-AI%20Dev%20Kit%20Skills-FF3621?style=for-the-badge&logo=databricks&logoColor=white)
![Apache Spark](https://img.shields.io/badge/Apache%20Spark-Serverless-E25A1C?style=for-the-badge&logo=apachespark&logoColor=white)
![Unity Catalog](https://img.shields.io/badge/Unity%20Catalog-Governance-00A4E4?style=for-the-badge&logo=databricks&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.13%20%7C%20uv-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-CI%2FCD-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)

**Pipeline de Dados End-to-End e Inteligência Analítica sobre a Frota Veicular Brasileira, Transição Energética (Elétricos e Híbridos) e Crescimento Regional.**

*Dados Oficiais do SENATRAN (Ministério dos Transportes) e Receita Federal do Brasil (RFB).*

</div>

---

## 📌 Sumário Executivo

Este projeto implementa uma plataforma moderna de engenharia de dados orientada a eventos (*event-driven*) na nuvem **Databricks**, cobrindo desde a extração automatizada de dados públicos governamentais até a disponibilização de dashboards interativos de inteligência de negócios (BI).

O desenvolvimento de ponta a ponta utilizou as **Skills do Databricks AI Dev Kit**, garantindo a aplicação rigorosa de boas práticas oficiais para **Lakeflow Pipelines**, **Unity Catalog**, **Databricks Asset Bundles (DAB)** e **AI/BI Dashboards**.

### Principais Destaques do Projeto:
- **Arquitetura Medalhão Declarativa:** Construída com **Databricks Lakeflow Pipelines** (Spark Declarative Pipelines), separando responsabilidades em camadas Bronze, Silver e Gold.
- **Desenvolvido com Databricks AI Dev Kit:** Adoção dos padrões oficiais de engenharia da Databricks através das skills especializadas (`databricks-jobs`, `databricks-pipelines`, `databricks-dabs`, `databricks-aibi-dashboards`, `databricks-unity-catalog`).
- **Data Quality & Schema Enforcement:** Ingestão streaming com **Auto Loader**, quarentena de registros inválidos via Expectations (`@dp.expect_or_quarantine`) e auditoria de volumetria.
- **Modelagem Dimensional Estrita (Star Schema):** 100% de correspondência com a malha oficial do IBGE (5.570 municípios) via cruzamento sanitizado com a base de códigos TOM da Receita Federal.
- **Orquestração Orientada a Eventos:** Disparo automático da esteira completa em cascata assim que um novo arquivo cai no **Unity Catalog Volume** (`FileArrivalTrigger`), sem necessidade de polling manual.
- **Ingestão Incremental Automatizada:** Módulo conteinerizado em **Docker** com **Astral uv** e agendado no **GitHub Actions** para carregamento mensal contínuo.
- **AI/BI Dashboard:** Painel analítico nativo no Databricks com 12 visualizações interativas, métricas de crescimento MoM/YoY e rankings de eletrificação.

---

## 🤖 Engenharia com Databricks AI Dev Kit

Todo o ecossistema de dados foi arquitetado e governado utilizando as capacidades e padrões recomendados pelas skills do **Databricks AI Dev Kit**:

| Skill Utilizada | Aplicação Prática no Projeto |
|---|---|
| **`databricks-pipelines`** | Estruturação dos pipelines declarativos (SDP / Lakeflow) em Python (`@dp.table`, `@dp.materialized_view`, `spark.conf` dinâmico e `@dp.expect_or_quarantine`). |
| **`databricks-dabs`** | Declaração de Infraestrutura como Código (IaC) modular em `databricks.yml`, com suporte a múltiplos targets (`dev`/`prod`), variáveis de catálogo/schema e empacotamento contínuo. |
| **`databricks-jobs`** | Configuração do workflow de orquestração com DAG multi-tarefas em cascata, controle de concorrência e gatilho orientado a eventos (`FileArrivalTrigger` em Volumes). |
| **`databricks-aibi-dashboards`** | Criação e versionamento do AI/BI Dashboard Lakeview em JSON (`brazil_car_fleet.lvdash.json`), especificando datasets analíticos, encodings, escalas e publicação nativa. |
| **`databricks-unity-catalog`** | Governança de dados de 3 níveis (`catalog.schema.table`), isolamento de Volumes brutos (`fleet_raw`, `rfb_municipios_raw`) e linragem de dependências entre tabelas Delta. |

---

## 📐 Arquitetura de Ponta a Ponta

```
 ┌────────────────────────┐
 │   GitHub Actions (CI)  │  (Agendamento mensal / Docker container)
 │   ou Execução Local    │
 └───────────┬────────────┘
             │ 1. Extrai dados do Senatran, valida integridade e gera CSV normalizado
             ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  Databricks Unity Catalog Volume (/Volumes/.../fleet_raw/)             │
 └───────────────────────────┬────────────────────────────────────────────┘
                             │ 2. Disparo por evento (File Arrival Trigger)
                             ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  Databricks Workflow Orchestration (Serverless Compute)                │
 │                                                                        │
 │  ┌─────────────────────────┐                                           │
 │  │ Pipeline 1: Raw → Bronze│ Auto Loader streaming + Expectations      │
 │  │                         │ frota_raw, frota_quarentena, rfb_raw      │
 │  └────────────┬────────────┘                                           │
 │               ▼                                                        │
 │  ┌─────────────────────────┐                                           │
 │  │ Pipeline 2: Bronze→Silver│ Dimensões & Fato (100% match IBGE)       │
 │  │                         │ dim_data, dim_municipio, fato_frota       │
 │  └────────────┬────────────┘                                           │
 │               ▼                                                        │
 │  ┌─────────────────────────┐                                           │
 │  │ Pipeline 3: Silver→Gold │ Agregações Analíticas e KPIs              │
 │  │                         │ evolucao_ev, crescimento_yoy, rankings    │
 │  └────────────┬────────────┘                                           │
 └───────────────┼────────────────────────────────────────────────────────┘
                 │ 3. Atualização automática
                 ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  📊 Databricks AI/BI Dashboard (Brazil Car Fleet Dashboard)            │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 🏛️ Governança no Unity Catalog

```
brazil_car_fleet (catalog)
├── raw_data (schema)
│   ├── fleet_raw/          ← Volume: CSVs particionados carregados pelo load.py
│   └── rfb_municipios_raw/ ← Volume: CSV de municípios da Receita Federal (TOM/IBGE)
├── bronze (schema)
│   ├── frota_raw           ← Tabela streaming com Auto Loader e schema enforcement
│   ├── frota_quarentena    ← Linhas rejeitadas pelas expectations de qualidade
│   ├── frota_quality_metrics ← Auditoria de variação mês a mês de volume
│   └── rfb_municipios_raw  ← Cadastro de municípios da Receita Federal
├── silver (schema)
│   ├── dim_data            ← Dimensão calendário (ano, mês, data_referencia, rastreabilidade)
│   ├── dim_municipio       ← 5.570 municípios normalizados com código IBGE e Região (100% match)
│   ├── dim_combustivel     ← Agrupamento: Elétrico Puro, Híbrido, Flex, Fóssil, Renovável
│   └── fato_frota          ← Fato transacional mensal com surrogate keys
└── gold (schema)
    ├── frota_eletrica_e_hibrida_evolucao           ← Tendência mensal de eletrificação
    ├── frota_por_grupo_combustivel_regiao          ← Volume por macrorregião × mês
    ├── frota_crescimento_mom_por_combustivel       ← Variação percentual mês a mês
    ├── frota_crescimento_yoy_por_combustivel_regiao← Variação anual (mesmo mês ano anterior)
    ├── frota_crescimento_por_regiao                ← Crescimento acumulado no período
    ├── frota_municipio_ranking                     ← Top municípios por volume e tipo
    └── frota_qualidade_dados                       ← Taxa de não identificados por UF/mês
```

---

## 📊 Principais Descobertas e Insights Analíticos

<div align="center">

| Métrica Analítica | Indicador Encontrado | Destaque Regional / Tendência |
|---|---|---|
| **Crescimento Acumulado de EVs/Híbridos (2024-2026)** | **+718,3% (Brasil)** | Destaque no **Norte (+914,7%)** e **Nordeste (+841,4%)** |
| **Top 1 Estado em Eletrificação** | **São Paulo (SP)** | **669.102 veículos** (188k elétricos puros + 480k híbridos) |
| **Top 2 e 3 Estados em Eletrificação** | **Minas Gerais (MG) e DF** | **177.146** (MG) e **155.708** (DF) veículos eletrificados |
| **Concentração da Frota Geral** | **Região Sudeste** | Concentra **48,9%** de todos os veículos automotores do país |
| **Qualidade da Base de Dados** | **> 99,8% Identificado** | Apenas ~0,15% da frota classificada como *Sem Informação* |

</div>

---

## 📁 Estrutura do Repositório

```
frota-veiculos-brasil/
├── .github/
│   └── workflows/
│       └── ingestion_monthly.yml    # Pipeline CI/CD agendado no GitHub Actions
│
├── ingestion/                       # Módulo Python de Ingestão e Validação
│   ├── Dockerfile                   # Imagem Docker leve com Python 3.13 + Astral uv
│   ├── .dockerignore
│   ├── pyproject.toml               # Gerenciador de dependências com uv
│   ├── uv.lock
│   ├── .env.example                 # Modelo de variáveis de ambiente
│   └── src/
│       ├── extract_fleet.py         # Scraping e download de .xlsx do gov.br
│       ├── extract_municipios.py    # Download do CSV da Receita Federal
│       ├── validate.py              # Validação de schema e integridade
│       └── load.py                  # Conversão e upload aos Volumes do Unity Catalog
│
├── databricks/                      # Databricks Asset Bundle (IaC)
│   ├── databricks.yml               # Configuração do Bundle e variáveis (dev/prod)
│   ├── resources/
│   │   ├── pipelines_bronze.yml     # Declaração do pipeline raw_to_bronze
│   │   ├── pipelines_silver.yml     # Declaração do pipeline bronze_to_silver
│   │   ├── pipelines_gold.yml       # Declaração do pipeline silver_to_gold
│   │   ├── workflow_orchestration.yml # Orquestração em cascata + File Arrival Trigger
│   │   └── dashboard_frota.yml      # Recurso IaC do Dashboard Lakeview
│   └── src/
│       ├── pipeline/
│       │   ├── raw_to_bronze.py     # Ingestão streaming + Auto Loader + Expectations
│       │   ├── bronze_to_silver.py  # Dimensões e Fato com joins e surrogate keys
│       │   └── silver_to_gold.py    # Materialized views analíticas e agregações
│       └── dashboard/
│           └── brazil_car_fleet.lvdash.json # Especificação completa do AI/BI Dashboard
│
├── project.md                       # Especificação técnica detalhada e documentação
└── README.md                        # Documentação principal do projeto
```

---

## 🛠️ Como Executar o Projeto

### Pré-requisitos
- Python 3.11+ e [uv](https://docs.astral.sh/uv/) instalados
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/index.html) (`>= 0.288.0`) autenticado via OAuth/PAT
- Docker (opcional, para execução conteinerizada)

---

### 1. Ingestão de Dados (Python / uv)

```bash
# 1. Acesse o diretório de ingestão
cd ingestion

# 2. Instale as dependências com uv
uv sync

# 3. Configure as variáveis de ambiente
cp .env.example .env
# Preencha .env com suas credenciais do Databricks:
#   - Opção 1 (Recomendada / Service Principal): DATABRICKS_CLIENT_ID e DATABRICKS_CLIENT_SECRET
#   - Opção 2 (PAT): DATABRICKS_TOKEN

# 4. Ingestão incremental automática do mês anterior:
uv run python src/load.py --previous-month

# 5. Ou ingestão de um período/arquivo específico:
uv run python src/load.py --year 2026 --month 7
```

---

### 2. Execução via Docker

```bash
cd ingestion

# Construir a imagem Docker
docker build -t brazil-car-fleet-ingestion .

# Executar a ingestão incremental do mês anterior
docker run --rm --env-file .env brazil-car-fleet-ingestion
```

---

### 3. Deploy da Infraestrutura no Databricks (DAB)

```bash
# Acesse o diretório databricks
cd databricks

# Validar as configurações do bundle
databricks bundle validate

# Fazer o deploy dos pipelines, jobs e dashboard no ambiente dev
databricks bundle deploy --target dev

# Executar o workflow de orquestração sob demanda
databricks bundle run orchestration_frota --target dev
```

---

---

## 🚀 Esteira de CI/CD e GitOps (GitHub Actions)

A plataforma opera com um fluxo contínuo de **GitOps e DataOps** dividido em 3 automações especializadas:

```
┌────────────────────────────────┐
│   Pull Request (branch → main) │ ──► 🧪 CI Validation: Testa código Python e valida sintaxe dos bundles
└────────────────────────────────┘
                 │
                 ▼ (Merge aprovado na main)
┌────────────────────────────────┐
│    Deploy em Produção (DAB)    │ ──► 🚀 deploy_prod.yml: Executa bundle deploy --target prod (Service Principal)
└────────────────────────────────┘
                 │
                 ▼ (Dia 15 de cada mês às 06:00 UTC)
┌────────────────────────────────┐
│   Ingestão Mensal de Dados     │ ──► 📅 ingestion_monthly.yml: Extrai mês anterior e deposita no Volume Prod
└────────────────────────────────┘
                 │
                 ▼ (FileArrivalTrigger dispara cascata automática)
┌────────────────────────────────┐
│ Pipelines Bronze→Silver→Gold   │ ──► 📊 Atualização instantânea do Dashboard Oficial de Produção
└────────────────────────────────┘
```

### 1. `ci_validation.yml` (Validação em PRs)
Disparado a cada **Pull Request** para a branch `main`:
- Configura Python 3.13 e valida dependências com `uv`;
- Executa testes de integridade de dados;
- Executa `databricks bundle validate` para ambos os ambientes (`dev` e `prod`).

### 2. `deploy_prod.yml` (Deploy Contínuo em Produção)
Disparado automaticamente a cada **Push / Merge** na branch `main`:
- Instala a Databricks CLI oficial;
- Autentica via **Service Principal (OAuth M2M)**;
- Valida e executa `databricks bundle deploy --target prod --force`;
- Promove pipelines declarativos e publica o **Brazil Car Fleet Dashboard** oficial.

### 3. `ingestion_monthly.yml` (Ingestão Agendada em Produção)
Agendado para rodar no **dia 15 de cada mês às 06:00 UTC**:
- Autentica com o Service Principal `flett_sp`;
- Executa `python src/load.py --previous-month`;
- Deposita o novo arquivo `.csv` no volume `/Volumes/brazil_car_fleet/raw_data/fleet_raw/`;
- O gatilho `FileArrivalTrigger` do job de produção detecta o novo arquivo e atualiza a esteira ponta a ponta.

---

### 🔑 Segredos do GitHub Actions (Repository Secrets)

Cadastre em **Settings ➔ Secrets and variables ➔ Actions**:

| Secret | Descrição | Exemplo |
|---|---|---|
| `DATABRICKS_HOST` | URL do workspace Databricks | `https://dbc-xxxx.cloud.databricks.com/` |
| `DATABRICKS_CLIENT_ID` | Application ID do Service Principal | `a5b53550-fe1d-4c12-9106-970b7a7d9f8c` |
| `DATABRICKS_CLIENT_SECRET` | OAuth Secret gerado no Databricks | `dapixxxxxxxxxxxxxxxxxxxxxxxx` |

---

## 👨‍💻 Autor

Desenvolvido por **Matheus Gentil**.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Matheus%20Gentil-blue?style=flat-square&logo=linkedin)](https://linkedin.com/in/matheusvgentil)
[![GitHub](https://img.shields.io/badge/GitHub-mvgentil-black?style=flat-square&logo=github)](https://github.com/mvgentil)
