# AGENTS.md — Padrões do projeto para agentes de código

Instruções para agentes (Claude Code, Codex, Gemini etc.) que trabalham neste repositório. A especificação de dados completa está em [`project.md`](project.md); a visão executiva, no [`README.md`](README.md).

## Contexto

- Frota de veículos do Brasil (SENATRAN) por município × combustível × mês, com cadastro de municípios da Receita Federal.
- **Ingestão** (`ingestion/`, Python 3.13 + uv) roda no GitHub Actions e grava CSVs em Volumes do Unity Catalog.
- **Pipeline** (`databricks/`, Databricks Asset Bundle) é um único Lakeflow Spark Declarative Pipeline serverless (`frota-medallion-<target>`) que publica bronze, silver e gold. Um job dispara o pipeline quando chega arquivo no Volume `fleet_raw`.
- **Dashboard** AI/BI em `databricks/src/dashboard/brazil_car_fleet.lvdash.json`.
- Workspace Databricks Free Edition. Perfil da CLI: `DEFAULT` (passe sempre `--profile DEFAULT`).
- Idioma: código, comentários, docs, commits e PRs em **português (pt-BR)**.

## Mapa do repositório

| Caminho | O que é |
|---|---|
| `databricks/databricks.yml` | Targets `dev` (catálogo `brazil_car_fleet_dev`) e `prod` (`brazil_car_fleet`) e variáveis de schema |
| `databricks/resources/pipeline_frota.yml` | Pipeline único; registra como fonte só `src/pipeline/transformations/**` |
| `databricks/resources/workflow_orchestration.yml` | Job `orchestration_frota` com trigger `file_arrival` |
| `databricks/resources/dashboard_frota.yml` | Dashboard com `dataset_catalog`/`dataset_schema` do target |
| `databricks/src/pipeline/transformations/{bronze,silver,gold}.py` | Datasets, um arquivo por camada |
| `databricks/src/pipeline/frota_common.py` | Funções compartilhadas (regras, normalização, período, seeds); não define datasets |
| `databricks/src/seeds/*.csv` | De-paras versionados: grupos de combustível, correções e complemento de municípios, UF/região |
| `ingestion/src/` | `load.py` (entrada), `extract_fleet.py`, `extract_municipios.py`, `validate.py`, `databricks_client.py` |
| `ingestion/tests/` | Testes da ingestão e da consistência dos seeds |
| `.github/workflows/` | `ci_validation.yml`, `deploy_prod.yml`, `ingestion_monthly.yml` |

## Regras de modelagem (não quebrar)

1. **Frota é estoque.** `qt_veiculos` nunca é somado ao longo do tempo. Indicador "atual" = último mês (`fl_ultimo_mes` / `MAX(dt_referencia)`).
2. **Lote vigente por mês.** A `fato_frota` usa só o arquivo mais recente de cada mês. Não deduplicar por linha nem com `.distinct()`.
3. **Grão IBGE.** `dim_municipio` tem 1 linha por `cd_ibge_municipio`, mais o membro `-1` (não identificado). Grafias novas da Senatran se resolvem em `seeds/municipio_correcoes.csv` ou `municipio_complemento.csv`, não no código.
4. **Chaves determinísticas** (`id_data = yyyymm`, código IBGE, `xxhash64`). Proibido `monotonically_increasing_id`.
5. **MoM/YoY por data** (`add_months`), nunca `lag` por posição.
6. **Penetração = `SUM(qt_eletrificados) / SUM(qt_total)`**, nunca média de percentuais.
7. **Classificações em seed.** Mudar o grupo de um combustível = editar `combustivel_grupo.csv` (os testes validam os grupos permitidos).
8. **Nada some em silêncio.** Linhas inválidas vão para `bronze.frota_quarentena`; sem-match e sem-mapeamento aparecem nas tabelas `gold.qualidade_*`.

## Padrões de código

### Pipeline (Lakeflow)
- `from pyspark import pipelines as dp`; datasets com `@dp.table` (streaming), `@dp.materialized_view` e `@dp.temporary_view`.
- Leitura de datasets do pipeline com `spark.read.table("nome")` / `spark.readStream.table("nome")` (não usar `dp.read`).
- Silver e gold publicadas com `name=f"{SILVER}.tabela"` / `f"{GOLD}.tabela"`; schemas e caminhos vêm de `spark.conf.get(...)` (configuração do `pipeline_frota.yml`), nunca fixos no código.
- Sem `orderBy`, `.collect()` ou `.toPandas()` dentro de datasets.
- Qualidade com expectations: `expect_all` para monitorar, `expect_or_fail` para chaves.
- Arquivo novo em `transformations/` entra no pipeline automaticamente (glob). Helpers vão para `frota_common.py`.
- Todo dataset tem `comment` explicando grão e uso, e `table_properties={"quality": ...}`.
- Mudar o tipo de um dataset (streaming ↔ MV) exige DROP da tabela; peça confirmação.

### Dashboard
- Queries sem catálogo (`frota_mensal_uf_grupo`, `bronze.frota_quarentena`); catálogo e schema vêm do bundle.
- Teste **todo SQL** novo ou alterado com `databricks experimental aitools tools query "<sql>" --profile DEFAULT` em `brazil_car_fleet_dev` antes do deploy.
- Versões de widget: counter, table e filter v2; gráficos v3.

### Ingestão (Python)
- `cd ingestion && uv sync`; rodar sempre com `uv run` (no Windows o `python` do sistema pode ser um atalho quebrado).
- `ruff` com `line-length = 120` e regras `E, F, W, I`; testes com `pytest`.
- Arquivo canônico no Volume: `frota_{ano}_{mes:02d}.csv`, sem cabeçalho, colunas na ordem de `COLUMN_ORDER` (inclui `nr_ano`, `nr_mes`).
- Credenciais só por variável de ambiente (`ingestion/.env` local; secrets no GitHub). Nunca commitar `.env`.

## Comandos

```bash
# Ingestão: lint e testes (o mesmo que o CI roda)
cd ingestion && uv run ruff check src tests && uv run pytest

# Bundle
cd databricks
databricks bundle validate --target dev --profile DEFAULT
databricks bundle validate --target prod --profile DEFAULT
databricks bundle deploy --target dev --profile DEFAULT
databricks bundle run pipeline_frota --target dev --profile DEFAULT

# Consultas ad hoc
databricks experimental aitools tools query "SELECT ..." --profile DEFAULT --output csv
```

## Ambientes e deploy

- **Dev** é onde se testa: deploy e execução locais com `--profile DEFAULT`.
- **Prod** só via GitHub Actions (Service Principal). **Não** rodar `bundle deploy --target prod` localmente: o `root_path` de prod depende do usuário, e o deploy local criaria uma segunda cópia do bundle.
- O deploy por merge na `main` não aprova ações destrutivas e **não roda o pipeline**. Se o PR cria ou muda tabelas, depois do merge rode `gh workflow run deploy_prod.yml -f run_pipeline=true`.
- Se o plano do deploy apagar ou recriar recursos (pipelines, por exemplo), o job de push falha de propósito; a migração é feita com `-f auto_approve=true`, só após confirmação do usuário.
- Apagar ou recriar um pipeline **não apaga as tabelas dele em prod**: elas ficam presas ao `pipeline_id` antigo e o pipeline novo falha com "already managed by pipeline". Antes de migrar, confira os donos (`databricks tables get <tabela> -o json` → `pipeline_id`).

## Ações que exigem confirmação explícita do usuário

- Qualquer `DROP`, `fs rm` ou exclusão em `brazil_car_fleet` (prod).
- `--auto-approve` / `auto_approve=true` em deploy.
- Apagar arquivos dos Volumes. Em especial, os CSVs anuais `frota_veiculos_2024/2025/2026.csv` do Volume de prod são a **única fonte de jan/2024 a jun/2026**.
- Merge de PRs, push na `main` e disparo da ingestão em prod.

## Validação depois de mudar o pipeline

Rode em dev (e em prod após o deploy) e compare com os valores esperados:

- Total por mês igual ao anterior à mudança (ex.: 202401 = 122.186.166; 202607 = 135.374.097; 202609 = 136.424.856), a menos que a mudança seja justamente nos totais.
- `fato_frota` sem duplicidade no grão (`id_data, cd_ibge_municipio, id_combustivel`) e sem chaves nulas.
- `qualidade_municipios_sem_match` e `qualidade_combustiveis_sem_mapeamento` vazias.
- `qualidade_volume_mensal` sem `fl_anomalia_volume` inesperado.
- Todas as tabelas usadas pelo dashboard existem no catálogo do target.

## Git

- Branch a partir da `main` atualizada; um PR por assunto.
- Commits no padrão `tipo: descrição` em pt-BR (`feat`, `fix`, `refactor`, `docs`, `ci`, `chore`).
- O CI (`ci_validation.yml`) precisa passar antes do merge.
