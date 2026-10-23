# 🚗 Brazil Car Fleet Analytics — Databricks Medallion Architecture

<div align="center">

[![Databricks](https://img.shields.io/badge/Databricks-Lakeflow%20Pipelines-FF3621?style=flat-square&logo=databricks&logoColor=white)](https://databricks.com)
[![Databricks AI Dev Kit](https://img.shields.io/badge/Databricks-AI%20Dev%20Kit-FF3621?style=flat-square&logo=databricks&logoColor=white)](https://github.com/databrickslabs)
[![Apache Spark](https://img.shields.io/badge/Spark-Serverless-E25A1C?style=flat-square&logo=apachespark&logoColor=white)](https://spark.apache.org)
[![Unity Catalog](https://img.shields.io/badge/Unity%20Catalog-Governance-00A4E4?style=flat-square&logo=databricks&logoColor=white)](https://www.databricks.com/product/unity-catalog)
[![Python 3.13](https://img.shields.io/badge/Python-3.13%20%7C%20uv-3776AB?style=flat-square&logo=python&logoColor=white)](https://docs.astral.sh/uv/)
[![GitHub Actions](https://img.shields.io/badge/CI%2FCD-DataOps%20%7C%20GitOps-2088FF?style=flat-square&logo=githubactions&logoColor=white)](https://github.com/features/actions)

**Plataforma de Engenharia de Dados End-to-End para Análise da Frota Veicular Brasileira, Eletrificação (EV/Híbridos) e Crescimento Regional.**

*Fontes Oficiais: SENATRAN (Ministério dos Transportes) & Receita Federal do Brasil (RFB)*

<br>

[![Brazil Car Fleet Dashboard](assets/dashboard.png)](assets/dashboard.pdf)

<sub>📊 *Visualização do Databricks AI/BI Dashboard. Clique na imagem para abrir o relatório completo em PDF.*</sub>

</div>

---

## 📌 Visão Geral do Projeto

Este projeto implementa uma plataforma corporativa de dados orientada a eventos (**Event-Driven DataOps**) no ecossistema **Databricks**, cobrindo todo o ciclo de vida dos dados:
1. **Extração e Ingestão Incremental:** Automação em Python com Astral `uv` e Docker, agendada via GitHub Actions.
2. **Arquitetura Medalhão Declarativa:** Construída com **Databricks Lakeflow Pipelines** (Spark Declarative Pipelines), garantindo validações de qualidade por linha via Expectations e governança no **Unity Catalog**.
3. **Modelagem Dimensional (Star Schema):** enriquecimento com o código IBGE dos municípios (cadastro da Receita Federal) e deduplicação no grão município × combustível × mês.
4. **Infraestrutura como Código (IaC):** Versionamento de pipelines, orquestração e dashboards via **Databricks Asset Bundles (DAB)** com isolamento multi-ambiente (`dev` e `prod`).
5. **Business Intelligence:** Painel analítico nativo no **Databricks AI/BI (Lakeview)**.

> 🤖 **Desenvolvido com Databricks AI Dev Kit:** A arquitetura adotou rigorosamente os padrões oficiais de engenharia da Databricks através das skills especializadas (`databricks-pipelines`, `databricks-jobs`, `databricks-dabs`, `databricks-aibi-dashboards`, `databricks-unity-catalog`).

---

## 📈 Principais Insights do Dashboard

<div align="center">

| Indicador Analítico | Métrica Consolidada | Destaque Regional / Tendência |
|---|---|---|
| **Crescimento de Eletrificados (2024–2026)** | **+294,4% (Brasil)** | Aceleração expressiva no **Norte** e **Nordeste** |
| **Taxa de veículos elétricos** | **0,89%** | Frota de veículos eletrificados consolidada em agosto/2026 |
| **Líder Nacional em Eletrificação** | **São Paulo (SP)** | **334 mil veículos** (94 mil elétricos puros + 240 mil híbridos) |
| **Top 2 e 3 Estados em Frota EV/Híbrida** | **Minas Gerais (MG) e DF** | **88 mil** (MG) e **77 mil** (DF) veículos eletrificados |
| **Concentração da Frota Total** | **Região Sudeste** | Concentra **46,86%** de todos os veículos automotores do país |

*Confira o relatório visual completo exportado em:* [**`assets/dashboard.pdf`**](assets/dashboard.pdf)

</div>

---

## 📐 Arquitetura da Solução

```
 ┌────────────────────────┐
 │  GitHub Actions / uv   │  (Ingestão agendada todo dia 15 ou sob demanda)
 └───────────┬────────────┘
             │ 1. Download do Senatran, validação de schema e upload em CSV
             ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  Unity Catalog Volume (/Volumes/.../fleet_raw/)                        │
 └───────────────────────────┬────────────────────────────────────────────┘
                             │ 2. Disparo por evento (FileArrivalTrigger)
                             ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  Databricks Workflow Orchestration (Serverless)                        │
 │                                                                        │
 │  ┌──────────────────────────────────────────────────────────────────┐  │
 │  │ Pipeline único frota-medallion (Lakeflow, serverless)            │  │
 │  │  bronze: Auto Loader + expectations + quarentena                 │  │
 │  │  silver: Star Schema IBGE (lote mais recente por mês)            │  │
 │  │  gold:   KPIs (MoM/YoY por data) + tabelas de qualidade          │  │
 │  └────────────┬─────────────────────────────────────────────────────┘  │
 └───────────────┼────────────────────────────────────────────────────────┘
                 │ 3. Atualização automática
                 ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  📊 Databricks AI/BI Dashboard (Brazil Car Fleet Dashboard)            │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 🏛️ Governança e Modelo de Dados (Unity Catalog)

A governança opera com isolamento multi-ambiente via Databricks Asset Bundles:
* **Desenvolvimento:** Catálogo `brazil_car_fleet_dev` (testes isolados e prototipação).
* **Produção:** Catálogo `brazil_car_fleet` (dados homologados e consumo de BI).

```
brazil_car_fleet (catalog)
├── raw_data (schema)
│   ├── fleet_raw/          ← Volume: CSVs particionados de frota
│   └── rfb_municipios_raw/ ← Volume: Base territorial da Receita Federal (TOM/IBGE)
├── bronze (schema)
│   ├── frota_raw           ← Tabela streaming (Auto Loader, todas as linhas + metadados do lote)
│   ├── frota_quarentena    ← Linhas que violam as regras, com motivo da rejeição
│   └── rfb_municipios_raw  ← Cadastro oficial de municípios
├── silver (schema)
│   ├── dim_data              ← Calendário mensal contínuo (fl_possui_dados, fl_ultimo_mes)
│   ├── dim_municipio         ← 1 linha por município IBGE + membro -1 (não identificado)
│   ├── map_municipio_senatran← De-para grafia Senatran → código IBGE (com método do match)
│   ├── dim_combustivel       ← Grupos: Elétrico Puro, Híbrido, Flex, Fóssil, Renovável (seed)
│   └── fato_frota            ← Município IBGE × combustível × mês (estoque: não somar no tempo)
└── gold (schema)
    ├── frota_eletrica_e_hibrida_evolucao           ← Tendência mensal de eletrificação
    ├── frota_por_grupo_combustivel_regiao          ← Volume por macrorregião × mês
    ├── frota_crescimento_mom_por_combustivel       ← Variação mês a mês e veículos adicionados
    ├── frota_crescimento_yoy_por_combustivel_regiao← Variação anual comparativa
    ├── frota_crescimento_por_regiao                ← Crescimento acumulado no período
    ├── frota_municipio_ranking                     ← Top municípios no último mês, por volume e tipo
    ├── frota_qualidade_dados                       ← % de combustível não identificado por UF
    ├── qualidade_volume_mensal                     ← Volume, lotes e anomalias por mês
    ├── qualidade_municipios_sem_match              ← Grafias sem código IBGE
    └── qualidade_combustiveis_sem_mapeamento       ← Combustíveis fora do seed de grupos
```

---

## 📁 Estrutura do Repositório

```
frota-veiculos-brasil/
├── .github/workflows/
│   ├── ci_validation.yml        # Validação de código e bundles em PRs
│   ├── deploy_prod.yml          # Deploy contínuo em Produção no merge na main
│   └── ingestion_monthly.yml    # Ingestão mensal agendada via Service Principal
│
├── assets/
│   └── dashboard.pdf              # Export do Dashboard Lakeview
│
├── ingestion/                       # Módulo de Extração e Ingestão em Python
│   ├── Dockerfile                   # Imagem Docker conteinerizada (Python 3.13 + uv)
│   ├── pyproject.toml / uv.lock     # Gerenciamento de dependências ultra-rápido
│   └── src/
│       ├── extract_fleet.py         # Scraping e download de dados do Senatran
│       ├── extract_municipios.py    # Download territorial da Receita Federal
│       ├── validate.py              # Validação de schema e integridade pré-carga
│       └── load.py                  # Upload streaming para Volumes do Unity Catalog
│
├── databricks/                      # Infraestrutura como Código (DAB)
│   ├── databricks.yml               # Definição dos targets dev e prod
│   ├── resources/                   # Declaração dos pipelines, jobs e dashboard
│   └── src/
│       ├── pipeline/                # frota_common.py + transformations/ (bronze.py, silver.py, gold.py)
│       ├── seeds/                   # De-paras versionados (UF/região, combustível, correções de município)
│       └── dashboard/               # Especificação JSON do AI/BI Dashboard
│
├── project.md                       # Especificação técnica e arquitetura de dados
└── README.md                        # Documentação executiva do projeto
```

---

## 🛠️ Como Executar o Projeto

### Pré-requisitos
- Python 3.11+ e [uv](https://docs.astral.sh/uv/)
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/index.html) (`>= 0.288.0`)
- Docker (opcional)

### 1. Ingestão de Dados Local

```bash
cd ingestion
uv sync

# Carga incremental: mês mais recente publicado (tenta o mês anterior e o retrasado)
uv run python src/load.py --previous-month

# Um mês específico, ou todos os meses publicados de um ano (backfill)
uv run python src/load.py --year 2026 --month 7
uv run python src/load.py --year 2024 2025 2026

# Recarregar um mês que já está no Volume (ex.: republicação da Senatran)
uv run python src/load.py --year 2026 --month 7 --force

# Cadastro de municípios da Receita Federal
uv run python src/extract_municipios.py --upload

# Lint e testes
uv run ruff check src tests && uv run pytest
```

Cada mês vira um arquivo `frota_{ano}_{mes}.csv` no Volume, com as colunas `nr_ano`/`nr_mes`; meses já carregados são pulados, salvo com `--force`.

### 2. Deploy da Infraestrutura com DAB

```bash
cd databricks

# Validar sintaxe e integridade dos recursos
databricks bundle validate --target dev

# Fazer o deploy no catálogo de desenvolvimento
databricks bundle deploy --target dev

# Disparar o workflow sob demanda
databricks bundle run orchestration_frota --target dev
```

---

## 🚀 Esteira de CI/CD e GitOps

A plataforma conta com automação completa via **GitHub Actions**:

1. **`ci_validation.yml` (Pull Requests):** Lint (`ruff`), testes (`pytest`, incluindo a consistência dos seeds do pipeline) e `databricks bundle validate` em `dev` e `prod`.
2. **`deploy_prod.yml` (Deploy em Produção):** Disparado automaticamente no merge para a branch `main`, executando `databricks bundle deploy --target prod` via Service Principal (OAuth M2M).
3. **`ingestion_monthly.yml` (Ingestão Agendada):** Execução no dia 15 de cada mês (mês mais recente publicado) ou manual com modo `previous-month`, `month` ou `year`; atualiza também o cadastro de municípios da Receita Federal.

---

### 🔑 Segredos do GitHub Actions (Repository Secrets)

Cadastre em **Settings ➔ Secrets and variables ➔ Actions**:

| Secret | Descrição | Exemplo |
|---|---|---|
| `DATABRICKS_HOST` | URL do workspace Databricks | `https://dbc-xxxx.cloud.databricks.com/` |
| `DATABRICKS_CLIENT_ID` | Application ID do Service Principal | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `DATABRICKS_CLIENT_SECRET` | OAuth Secret gerado no Databricks | `dapixxxxxxxxxxxxxxxxxxxxxxxx` |

---

## 👨‍💻 Autor

Desenvolvido por **Matheus Gentil**.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Matheus%20Gentil-blue?style=flat-square&logo=linkedin)](https://www.linkedin.com/in/mvgentil/)
[![GitHub](https://img.shields.io/badge/GitHub-mvgentil-black?style=flat-square&logo=github)](https://github.com/mvgentil)
