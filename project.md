# 📋 Arquitetura e Especificação Técnica — Frota de Veículos Brasil
> **Databricks Medallion Architecture** · Lakeflow Pipelines (Spark Declarative Pipelines) · Unity Catalog · Serverless Compute · AI/BI Dashboards

---

## 1. Visão Geral da Arquitetura

O projeto implementa uma arquitetura medalhão orientada a eventos (*event-driven*) para processamento, enriquecimento e análise da frota de veículos brasileira por município e tipo de combustível:

```
 ┌───────────────────────┐      ┌─────────────────────────────┐      ┌──────────────────────────────┐
 │     Camada Bronze     │      │        Camada Silver        │      │         Camada Gold          │
 │   (Raw & Streaming)   │      │  (Star Schema & 100% IBGE)  │      │     (KPIs & Agregações)      │
 ├───────────────────────┤      ├─────────────────────────────┤      ├──────────────────────────────┤
 │ • frota_raw           │ ───► │ • dim_municipio (5.570 UFs) │ ───► │ • frota_eletrica_e_hibrida_ev│
 │ • frota_quarentena    │      │ • dim_combustivel (Grupos)  │      │ • frota_por_grupo_comb_reg   │
 │ • frota_quality_metric│      │ • dim_data (Mês / Ano / Ref)│      │ • frota_crescimento_mom      │
 │ • rfb_municipios_raw  │      │ • fato_frota (Surrogate FKs)│      │ • frota_crescimento_yoy      │
 └───────────────────────┘      └─────────────────────────────┘      │ • frota_crescimento_regiao   │
                                                                     │ • frota_municipio_ranking    │
                                                                     │ • frota_qualidade_dados      │
                                                                     └──────────────────────────────┘
                                                                                    │
                                                                                    ▼
                                                                     📊 Brazil Car Fleet Dashboard
```

---

## 2. Camada Bronze (Ingestão e Validação Bruta)

### 2.1 Componentes e Tabelas

| Tabela | Tipo | Fonte de Dados | Propósito e Regras de Qualidade |
|---|---|---|---|
| `bronze.frota_raw` | `@dp.table` (Streaming) | `/Volumes/brazil_car_fleet/raw_data/fleet_raw/` | Ingestão incremental via **Auto Loader** com schema estrito (`uf`, `municipio`, `combustivel_veiculo`, `qtd_veiculos`, `nm_file`) e `header=false`. Registros inválidos são direcionados para a quarentena via `@dp.expect_or_quarantine`. |
| `bronze.frota_quarentena` | `@dp.table` | Quarentena do Auto Loader | Armazena registros rejeitados (nulos em UF/município/combustível ou quantidades negativas). |
| `bronze.frota_quality_metrics` | `@dp.materialized_view` | `bronze.frota_raw` | Monitoramento de auditoria de variação volumétrica mês a mês (alerta de variação > ±5%). |
| `bronze.rfb_municipios_raw` | `@dp.materialized_view` | `/Volumes/.../rfb_municipios_raw/` | Tabela oficial de municípios da Receita Federal (códigos TOM e IBGE), codificação ISO-8859-1. |

---

## 3. Camada Silver (Modelo Dimensional / Star Schema)

### 3.1 `silver.dim_data`
Extraída e calculada a partir do nome do arquivo (`nm_file`) com regex semântica robusta a variações históricas (ex: `Maro`, `Março`, `Dezembro_20241`, `copy_of_`).

| Coluna | Tipo | Descrição | Exemplo |
|---|---|---|---|
| `id_data` | INT | Surrogate key (YYYYMM) | `202607` |
| `nm_mes` | STRING | Nome oficial do mês em português | `Julho` |
| `nr_mes` | INT | Número do mês (1 a 12) | `7` |
| `nr_ano` | INT | Ano de referência (4 dígitos) | `2026` |
| `dt_referencia`| DATE | Data do primeiro dia do mês | `2026-07-01` |
| `nm_file` | STRING | Rastreabilidade do arquivo de origem | `copy_of_D_Frota_...Julho_2026.xlsx` |

---

### 3.2 `silver.dim_municipio`
Construída pelo cruzamento sanitizado entre `bronze.frota_raw` e `bronze.rfb_municipios_raw`. 
- **Sanitização:** Remoção completa de acentos, pontuações e padronização para caixa alta.
- **Lookup duplo:** Correspondência primária por nome IBGE normalizado + sigla UF, e fallback por nome TOM (Tabela de Órgãos e Municípios da Receita Federal).
- **Correção de divergências históricas:** Dicionário de sinônimos para 14 grafias arcaicas do Senatran (ex: `SAO LUIZ DO PARAITINGA` ➔ `SAO LUIS DO PARAITINGA`, `ASSIS BRASIL`, `MOJI MIRIM`).
- **Resultado:** **100,00% de correspondência** (5.570 municípios brasileiros oficiais + 1 registro para não identificados).

| Coluna | Tipo | Descrição | Exemplo |
|---|---|---|---|
| `id_municipio` | INT | Surrogate key gerada via `dense_rank` | `1042` |
| `cd_ibge_municipio` | STRING | Código oficial IBGE (7 dígitos) | `3550308` |
| `cd_tom` | STRING | Código TOM da Receita Federal | `7107` |
| `nm_municipio` | STRING | Nome oficial padronizado | `SAO PAULO` |
| `nm_uf` | STRING | Nome por extenso do estado | `SAO PAULO` |
| `sigla_uf` | STRING | Sigla da unidade federativa | `SP` |
| `nm_regiao` | STRING | Macrorregião geográfica | `Sudeste` |

---

### 3.3 `silver.dim_combustivel`
Normalização de mais de 29 denominações técnicas do Senatran em grupos de inteligência analítica:

| Grupo Analítico (`nm_grupo`) | Categorias Técnicas Incluídas | `fl_identificado` |
|---|---|---|
| **Elétrico Puro** | `ELETRICO`, `ELETRICO/FONTE EXTERNA`, `ELETRICO/FONTE INTERNA`, `CELULA COMBUSTIVEL` | `true` |
| **Híbrido** | `HIBRIDO`, `HIBRIDO PLUG-IN`, `GASOLINA/ELETRICO`, `DIESEL/ELETRICO`, `ETANOL/ELETRICO`, `GASOLINA/ALCOOL/ELETRICO` | `true` |
| **Flex** | `ALCOOL/GASOLINA`, `GASOL/GAS NATURAL COMBUSTIVEL`, `GASOLINA/GAS NATURAL VEICULAR`, `ALCOOL/GAS NATURAL...` | `true` |
| **Combustão Fóssil** | `GASOLINA`, `DIESEL`, `GAS NATURAL VEICULAR`, `GAS METANO`, `GAS/NATURAL/LIQUEFEITO`, `GASOGENIO` | `true` |
| **Combustão Renovável** | `ALCOOL` | `true` |
| **Não Identificado** | `SEM INFORMACAO`, `VIDE/CAMPO/OBSERVACAO`, `NAO IDENTIFICADO`, `NAO SE APLICA` | `false` |

---

### 3.4 `silver.fato_frota`
Fato transacional consolidada com granularidade **Município × Combustível × Mês/Ano**:

```
┌────────────────────────────────────────────────────────┐
│                   silver.fato_frota                    │
├─────────────────┬──────────┬───────────────────────────┤
│ id_fato         │ BIGINT   │ PK incremental / hash     │
│ id_municipio    │ INT      │ FK → silver.dim_municipio │
│ id_combustivel  │ INT      │ FK → silver.dim_combustivel│
│ id_data         │ INT      │ FK → silver.dim_data      │
│ qt_veiculos     │ BIGINT   │ Quantidade de veículos    │
│ dt_ingestao     │ TIMESTAMP│ Data/hora da carga (audit)│
│ nm_file         │ STRING   │ Data Lineage (origem)     │
└─────────────────┴──────────┴───────────────────────────┘
```

---

## 4. Camada Gold (Materialized Views Analíticas)

1. **`gold.frota_eletrica_e_hibrida_evolucao`:** Série temporal mensal de veículos elétricos puros e híbridos por estado e região.
2. **`gold.frota_por_grupo_combustivel_regiao`:** Volume total por grupo de combustível × macrorregião geográfica × mês.
3. **`gold.frota_crescimento_mom_por_combustivel`:** Variação percentual mês a mês (*Month-over-Month*) por tipo de motorização.
4. **`gold.frota_crescimento_yoy_por_combustivel_regiao`:** Comparativo ano a ano (*Year-over-Year*) para o mesmo mês do ano anterior (lag 12).
5. **`gold.frota_crescimento_por_regiao`:** Crescimento percentual e absoluto acumulado no período total do dataset.
6. **`gold.frota_municipio_ranking`:** Ranking de cidades com maiores volumes gerais e por grupo de eletrificação.
7. **`gold.frota_qualidade_dados`:** Monitoramento da taxa de preenchimento e subnotificação por estado.

---

## 5. Orquestração e CI/CD (DataOps / GitOps)

- **Gatilho Orientado a Eventos:** `FileArrivalTrigger` monitorando `/Volumes/brazil_car_fleet/raw_data/fleet_raw/`.
- **Pipeline em Cascata:** A chegada de um novo arquivo dispara `raw_to_bronze` ➔ `bronze_to_silver` ➔ `silver_to_gold` automaticamente.
- **Validação Contínua (`ci_validation.yml`):** Execução de linting, testes de validação e verificação de integridade dos Asset Bundles em Pull Requests.
- **Deploy Contínuo em Produção (`deploy_prod.yml`):** Merge na branch `main` dispara `databricks bundle deploy --target prod` via Service Principal.
- **Automação Mensal (`ingestion_monthly.yml`):** GitHub Actions agendado (`0 6 15 * *`) executando `load.py --previous-month` em Produção.
- **Infraestrutura como Código:** Databricks Asset Bundles (DAB) versionando pipelines, jobs e dashboard.

---

## 6. Checklist de Implementação do Projeto

### Bronze
- [x] Ingestão streaming com Auto Loader e schema enforcement (`header=false`)
- [x] Tabela de quarentena para expectativas de dados inválidos
- [x] Materialized view de métricas de qualidade e anomalias de volume
- [x] Ingestão da base de municípios da Receita Federal (RFB) com encoding ISO-8859-1

### Silver
- [x] Dimensão Calendário (`dim_data`) com regex semântica multi-formato
- [x] Dimensão Municípios (`dim_municipio`) com enriquecimento IBGE, TOM e Região (100% match)
- [x] Dimensão Combustíveis (`dim_combustivel`) com agrupamento analítico e flags de identificação
- [x] Tabela Fato (`fato_frota`) com surrogate keys e data lineage preservado

### Gold
- [x] `frota_eletrica_e_hibrida_evolucao`
- [x] `frota_por_grupo_combustivel_regiao`
- [x] `frota_crescimento_mom_por_combustivel`
- [x] `frota_crescimento_yoy_por_combustivel_regiao`
- [x] `frota_crescimento_por_regiao`
- [x] `frota_municipio_ranking`
- [x] `frota_qualidade_dados`

### Visualização & Automação
- [x] AI/BI Dashboard nativo no Databricks com 12 widgets interativos e formatação percentual precisa
- [x] Orquestração com Databricks Asset Bundles e File Arrival Trigger despausado
- [x] Módulo Python conteinerizado em Docker para extração incremental automática do mês anterior
- [x] Workflow CI/CD no GitHub Actions

---

## 7. Backlog e Evoluções Futuras

- [ ] Refatorar `dim_data` para dimensão calendário canônica gerada deterministicamente por sequence temporal (2020 a 2030)
- [ ] Enriquecer `dim_municipio` com população estimada do Censo IBGE para calcular frota per capita e taxa de motorização
- [ ] Implementar alertas automáticos via Slack / Teams para anomalias de qualidade de dados na camada Bronze