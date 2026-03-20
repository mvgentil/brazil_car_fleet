# 🚗 Frota de Veículos Brasil

Pipeline de dados da **frota de veículos por combustível e município** do Brasil, com ingestão local (Python) e processamento analítico no **Databricks** seguindo a arquitetura **Medallion (Bronze → Silver → Gold)**.

## Arquitetura

```
          Ingestão Local (Python)              Databricks (PySpark + SQL)
     ─────────────────────────────     ──────────────────────────────────────────
     extract_fleet.py                  01_bronze_brazil_car_fleet  → bronze.brazil_car_fleet
     extract_municipios.py             01_bronze_rfb_municipios    → bronze.rfb_municipios
     load.py (consolida xlsx → csv)    02_silver_dim_municipio     → silver.dim_municipio
                                       (próximos: dim_data, dim_combustivel, fato_frota)
```

### Camada Bronze (dados brutos)

| Tabela | Fonte | Descrição |
|--------|-------|-----------|
| `bronze.brazil_car_fleet` | CSVs consolidados da frota (Senatran) | Frota por UF, município e combustível — ingerida via `read_files` dos Volumes |
| `bronze.rfb_municipios` | CSV da Receita Federal | Código IBGE, nome do município e sigla UF |

### Camada Silver (dados curados)

| Tabela | Descrição |
|--------|-----------|
| `silver.dim_municipio` | Municípios enriquecidos com código IBGE, região e UF (join RFB + seed `uf_regiao`, normalização de acentos) |
| `silver.dim_data` | *(planejada)* — Extraída do `nm_file` com mês/ano |
| `silver.dim_combustivel` | *(planejada)* — 29 tipos agrupados em 6 categorias (Elétrico, Híbrido, Flex, etc.) |
| `silver.fato_frota` | *(planejada)* — Granularidade: município × combustível × mês/ano |

### Camada Gold (dados analíticos)

| Tabela | Uso |
|--------|-----|
| `frota_eletrica_e_hibrida_evolucao` | Tendência de eletrificação por estado |
| `frota_por_grupo_combustivel_regiao` | Comparativos regionais (flex vs combustão) |
| `frota_qualidade_dados` | % de registros "Não Identificado" por UF/mês |
| `frota_municipio_ranking` | Top municípios por grupo de combustível |

### Catálogo Databricks

```
brazil_car_fleet (catalog)
├── bronze (schema)
│   ├── brazil_car_fleet
│   └── rfb_municipios
├── silver (schema)
│   └── dim_municipio
├── raw_data (volume)
│   ├── fleet_raw/*.csv
│   └── rfb_municipios_raw/municipios.csv
```

## Estrutura do Repositório

```
src/
├── extract_fleet.py        # Baixa os .xlsx de frota por ano do gov.br
├── extract_municipios.py   # Baixa o CSV de municípios da Receita Federal
└── load.py                 # Consolida os .xlsx de cada ano em um único CSV

notebooks/
├── 01_bronze_brazil_car_fleet.ipynb   # Ingestão dos CSVs no catálogo Bronze
├── 01_bronze_rfb_municipios.ipynb     # Ingestão do CSV de municípios (RFB)
└── 02_silver_dim_municipio.ipynb      # Construção da dim_municipio com joins e normalização

data/
├── raw/{ano}/              # Arquivos .xlsx originais agrupados por ano
├── municipios.csv          # Cadastro de municípios (RFB)
└── frota_veiculos_{ano}.csv # Dados consolidados por ano
```

## Pré-requisitos

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) (gerenciador de pacotes)
- Databricks Workspace com Unity Catalog

## Instalação

```bash
uv sync
```

## Como executar

### 1. Extrair dados de frota

```bash
# Todos os anos (2024, 2025, 2026)
uv run src/extract_fleet.py

# Ano específico
uv run src/extract_fleet.py --year 2026

# Múltiplos anos
uv run src/extract_fleet.py --year 2024 2025
```

### 2. Extrair cadastro de municípios

```bash
uv run src/extract_municipios.py
```

### 3. Consolidar arquivos em CSV

```bash
# Todos os anos disponíveis
uv run src/load.py

# Ano específico
uv run src/load.py --year 2026
```

### 4. Databricks

1. Faça upload dos CSVs gerados para os **Volumes** do catálogo `brazil_car_fleet`
2. Execute os notebooks na ordem:
   - `01_bronze_brazil_car_fleet` — cria tabela Bronze da frota
   - `01_bronze_rfb_municipios` — cria tabela Bronze dos municípios
   - `02_silver_dim_municipio` — constrói a dimensão de municípios na Silver

## Fonte dos dados

| Dado | Fonte | URL |
|------|-------|-----|
| Frota por combustível | Senatran | `https://www.gov.br/transportes/pt-br/assuntos/transito/conteudo-Senatran/frota-de-veiculos-{ano}` |
| Municípios | Receita Federal | `https://www.gov.br/receitafederal/dados/municipios.csv` |
