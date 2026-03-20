# 🚗 Frota de Veículos Brasil

Pipeline de extração e consolidação dos dados de **frota de veículos por combustível e município** publicados pelo [Senatran/Gov.br](https://www.gov.br/transportes/pt-br/assuntos/transito/conteudo-Senatran).

## Visão Geral

O projeto segue a arquitetura **Medallion (Bronze → Silver → Gold)** e atualmente implementa a camada de ingestão:

```
src/
├── extract_fleet.py        # Baixa os .xlsx de frota por ano do gov.br
├── extract_municipios.py   # Baixa o CSV de municípios da Receita Federal
└── load.py                 # Consolida os .xlsx de cada ano em um único CSV

data/
├── raw/{ano}/              # Arquivos .xlsx originais agrupados por ano
├── municipios.csv          # Cadastro de municípios (RFB)
└── frota_veiculos_{ano}.csv # Dados consolidados por ano
```

## Pré-requisitos

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) (gerenciador de pacotes)

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

## Fonte dos dados

| Dado | Fonte | URL |
|------|-------|-----|
| Frota por combustível | Senatran | `gov.br/transportes/.../frota-de-veiculos-{ano}` |
| Municípios | Receita Federal | `gov.br/receitafederal/dados/municipios.csv` |
