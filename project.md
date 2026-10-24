# 📋 Arquitetura e Especificação Técnica — Frota de Veículos Brasil
> **Databricks Medallion Architecture** · Lakeflow Spark Declarative Pipelines · Unity Catalog · Serverless Compute · AI/BI Dashboards

---

## 1. Visão Geral da Arquitetura

Arquitetura medalhão orientada a eventos para a frota de veículos brasileira por município e tipo de combustível (fonte: SENATRAN; cadastro de municípios: Receita Federal).

```
 GitHub Actions (ingestion/)          Unity Catalog Volumes (raw_data)
 ┌──────────────────────────┐        ┌──────────────────────────────────┐
 │ load.py / extract_*.py   │ ─────► │ fleet_raw/          (CSV mensal) │
 └──────────────────────────┘        │ rfb_municipios_raw/ (RFB)        │
                                     └────────────────┬─────────────────┘
                                                      │ FileArrivalTrigger
                                                      ▼
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │ Pipeline único frota-medallion-<target> (serverless)                           │
 │                                                                                │
 │  Bronze                    Silver (Star Schema)          Gold                  │
 │  • frota_raw          ──►  • dim_data              ──►   • 10 tabelas analít.  │
 │  • frota_quarentena        • dim_municipio (IBGE)        • 3 tabelas de        │
 │  • rfb_municipios_raw      • map_municipio_senatran        qualidade           │
 │                            • dim_combustivel                                   │
 │                            • fato_frota                                        │
 └───────────────────────────────────────────────┬────────────────────────────────┘
                                                 ▼
                                   📊 Brazil Car Fleet Dashboard
```

**Código:** `databricks/src/pipeline/transformations/{bronze,silver,gold}.py` (datasets) e `databricks/src/pipeline/frota_common.py` (funções compartilhadas, sem datasets). As tabelas de referência ficam em `databricks/src/seeds/*.csv`.

**Ambientes:** catálogos `brazil_car_fleet_dev` (target `dev`) e `brazil_car_fleet` (target `prod`), com os schemas `raw_data`, `bronze`, `silver` e `gold`.

---

## 2. Regras de Modelagem

1. **Frota é estoque.** `qt_veiculos` é a frota registrada no mês: soma-se entre municípios e combustíveis, **nunca ao longo do tempo**. Indicadores "atuais" usam o último mês.
2. **Lote vigente por mês.** Um mesmo mês pode chegar em mais de um arquivo (arquivos anuais legados, `copy_of_...`, republicações). A `fato_frota` usa só o lote mais recente de cada mês (maior `dt_arquivo_modificado`, depois `dt_ingestao` e `nm_arquivo_fonte`). Um reenvio com o mesmo nome substitui o mês (`cloudFiles.allowOverwrites`).
3. **Grão IBGE.** `dim_municipio` tem 1 linha por `cd_ibge_municipio`; grafias da Senatran passam pelo de-para `map_municipio_senatran`. UF não identificada na fonte vai para o membro `-1`.
4. **Chaves determinísticas.** `id_data = yyyymm`, `cd_ibge_municipio` (código oficial) e `id_combustivel = xxhash64(nm_combustivel_norm)`. Nada de `monotonically_increasing_id`.
5. **Comparações por data.** MoM e YoY usam join em `add_months(dt_referencia, 1 | 12)`, não `lag`, para não comparar meses errados quando falta um mês.
6. **Penetração é razão de somas.** `SUM(qt_eletrificados) / SUM(qt_total)`, nunca a média de percentuais.
7. **Nenhuma linha some em silêncio.** Linhas inválidas vão para a quarentena; grafias e combustíveis sem mapeamento aparecem nas tabelas `qualidade_*`.

---

## 3. Camada Bronze

| Tabela | Tipo | Fonte | Regras |
|---|---|---|---|
| `bronze.frota_raw` | Streaming table (Auto Loader) | `/Volumes/<catalog>/raw_data/fleet_raw/` | CSV sem cabeçalho com 7 colunas: `uf, municipio, combustivel_veiculo, qtd_veiculos, nm_file, nr_ano, nr_mes`. As duas últimas são opcionais: nos arquivos antigos chegam nulas e o mês sai do `nm_file`. Guarda todas as linhas, com `nm_arquivo_fonte`, `dt_arquivo_modificado` e `dt_ingestao`. As regras de validade são monitoradas com `@dp.expect_all`. |
| `bronze.frota_quarentena` | Streaming table | `frota_raw` | Linhas que violam as regras (UF, município ou combustível vazios; quantidade nula ou negativa), com `motivo_rejeicao`. Ex.: cabeçalhos e linhas de total das planilhas. |
| `bronze.rfb_municipios_raw` | Materialized view | `/Volumes/<catalog>/raw_data/rfb_municipios_raw/` | Cadastro da Receita Federal (códigos TOM e IBGE), `;` e ISO-8859-1. Descarta linhas sem código numérico. |

---

## 4. Camada Silver (Star Schema)

### 4.1 `silver.dim_data`
Calendário mensal **contínuo** (gerado por `sequence`) entre o primeiro e o último mês carregado.

| Coluna | Tipo | Descrição |
|---|---|---|
| `id_data` | INT | Chave `yyyymm` (ex.: `202609`) |
| `dt_referencia` | DATE | Primeiro dia do mês |
| `nr_ano`, `nr_mes`, `nm_mes`, `nr_trimestre` | INT/STRING | Atributos do calendário |
| `fl_ultimo_mes` | BOOLEAN | Último mês carregado |
| `fl_possui_dados` | BOOLEAN | Mês com dados (falso = buraco na série) |

O mês vem das colunas `nr_ano`/`nr_mes` gravadas pela ingestão; para arquivos antigos, do nome do arquivo (regex aceita `Março`, `Marco` e `Maro`).

### 4.2 `silver.dim_municipio`
1 linha por município IBGE: cadastro da RFB + `seeds/municipio_complemento.csv` (municípios ausentes da RFB, ex.: Boa Esperança do Norte/MT, instalado em 2025) + membro `-1` "NÃO IDENTIFICADO". Total atual: **5.572 linhas** (5.571 municípios + membro `-1`).

| Coluna | Tipo | Descrição |
|---|---|---|
| `cd_ibge_municipio` | INT | Chave: código IBGE (7 dígitos) ou `-1` |
| `nm_municipio` | STRING | Nome oficial (RFB) |
| `sigla_uf`, `nm_uf`, `nm_regiao` | STRING | UF e região (`seeds/uf_regiao.csv`); nulos no membro `-1` |
| `fl_identificado` | BOOLEAN | Falso só no membro `-1` |

### 4.3 `silver.map_municipio_senatran`
De-para `(nm_uf_raw, nm_municipio_raw) → cd_ibge_municipio`. Os nomes são normalizados (sem acento, sem pontuação, caixa alta) e casados nesta ordem:

| `metodo_match` | Regra | Linhas (set/2026) |
|---|---|---|
| `complemento` | `seeds/municipio_complemento.csv` | 1 |
| `correcao` | Grafia corrigida por `seeds/municipio_correcoes.csv` (19 grafias históricas) | 17 |
| `ibge` | Nome RFB + UF | 5.536 |
| `tom` | Nome TOM + UF | 19 |
| `especial` | UF não identificada (SEM INFORMAÇÃO, NÃO SE APLICA etc.) → `-1` | 3 |
| `sem_match` | Sem código; vai para `-1` e aparece em `gold.qualidade_municipios_sem_match` | 0 |

### 4.4 `silver.dim_combustivel`
Tipos de combustível com grupo analítico de `seeds/combustivel_grupo.csv`. Tipos fora do seed viram "Não Identificado" com `fl_mapeado = false`.

| Grupo (`nm_grupo`) | Tipos | `fl_eletrificado` |
|---|---|---|
| **Elétrico Puro** | `ELETRICO`, `ELETRICO/FONTE EXTERNA`, `CELULA COMBUSTIVEL` | `true` |
| **Híbrido** | `ELETRICO/FONTE INTERNA`, `HIBRIDO`, `HIBRIDO PLUG-IN`, `HIBRIDO/GAS NATURAL VEICULAR`, `GASOLINA/ELETRICO`, `DIESEL/ELETRICO`, `ETANOL/ELETRICO`, `GASOLINA/ALCOOL/ELETRICO` | `true` |
| **Flex** | `ALCOOL/GASOLINA` e combinações com gás natural | `false` |
| **Combustão Fóssil** | `GASOLINA`, `DIESEL`, `GAS NATURAL VEICULAR`, `GAS METANO`, `GAS/NATURAL/LIQUEFEITO`, `GASOGENIO` | `false` |
| **Combustão Renovável** | `ALCOOL` | `false` |
| **Não Identificado** | `SEM INFORMACAO`, `VIDE/CAMPO/OBSERVACAO`, `NAO IDENTIFICADO`, `NAO SE APLICA` | `false` |

`ELETRICO/FONTE INTERNA` (motor elétrico alimentado por motor a combustão) é classificado como **Híbrido**.

### 4.5 `silver.fato_frota`
Grão **município IBGE × combustível × mês**, só com o lote vigente de cada mês.

| Coluna | Tipo | Descrição |
|---|---|---|
| `id_data` | INT | FK → `dim_data` |
| `cd_ibge_municipio` | INT | FK → `dim_municipio` (`-1` = não identificado) |
| `id_combustivel` | BIGINT | FK → `dim_combustivel` |
| `qt_veiculos` | BIGINT | Estoque de veículos (semi-aditiva: não somar no tempo) |
| `nm_arquivo_fonte` | STRING | Arquivo do lote vigente (linhagem) |
| `dt_ingestao` | TIMESTAMP | Momento da carga do lote |

Chaves nulas falham o pipeline (`@dp.expect_or_fail`).

---

## 5. Camada Gold

### 5.1 Analíticas (dashboard)

| Tabela | Grão | Conteúdo |
|---|---|---|
| `frota_mensal_uf_grupo` | mês × UF × grupo | Base dos filtros do dashboard (UF não identificada = `ND`) |
| `frota_eletrificacao_uf_mensal` | mês × UF | Total, elétricos, híbridos, penetração (0–1) e valores de 12 meses antes |
| `frota_municipio_atual` | município (último mês) | Frota, eletrificados, penetração e `rank_frota`, `rank_eletrificados`, `rank_penetracao` (este só com frota ≥ 10 mil) |
| `frota_eletrica_e_hibrida_evolucao` | mês × UF × grupo eletrificado | Série de elétricos puros e híbridos |
| `frota_por_grupo_combustivel_regiao` | mês × região × grupo | Volume por grupo e região |
| `frota_crescimento_mom_por_combustivel` | mês × grupo | Variação vs. mês anterior e `qt_adicionados` (líquido) |
| `frota_crescimento_yoy_por_combustivel_regiao` | mês × grupo × região | Variação vs. mesmo mês do ano anterior |
| `frota_crescimento_por_regiao` | região | Crescimento entre o primeiro e o último mês |
| `frota_eletrificada_crescimento_por_regiao` | região | O mesmo, só para eletrificados |
| `frota_qualidade_dados` | mês × UF | % da frota com combustível não identificado |

### 5.2 Qualidade (monitoramento, não bloqueiam o pipeline)

| Tabela | Conteúdo |
|---|---|
| `qualidade_volume_mensal` | Por mês: volume na bronze (linhas válidas) e na fato, `qt_lotes`, `qt_linhas_rejeitadas`, arquivo vigente, variação vs. mês anterior e flags `fl_periodo_duplicado`, `fl_mes_anterior_ausente`, `fl_anomalia_volume` (variação > ±5%) |
| `qualidade_municipios_sem_match` | Grafias sem código IBGE: corrigir em `seeds/municipio_correcoes.csv` ou `municipio_complemento.csv` |
| `qualidade_combustiveis_sem_mapeamento` | Combustíveis fora de `seeds/combustivel_grupo.csv` |

---

## 6. Dashboard (AI/BI)

`databricks/src/dashboard/brazil_car_fleet.lvdash.json`, publicado pelo bundle com `dataset_catalog`/`dataset_schema` do target (as queries usam nomes sem catálogo, ex.: `frota_mensal_uf_grupo`, `bronze.frota_quarentena`).

- **Filtros globais:** período, região, UF e grupo de combustível.
- **Visão Geral:** KPIs do último mês (frota, eletrificados, penetração) com variação anual, participação regional, crescimento por região, data da última ingestão.
- **Eletrificação:** evolução elétrico × híbrido, penetração mensal, veículos adicionados por mês, YoY região × grupo.
- **Estados e Municípios:** penetração por UF, top municípios por frota e por penetração.
- **Qualidade de Dados:** volume e variação mensal, lotes por mês, quarentena, municípios e combustíveis sem mapeamento, % não identificado por UF.

---

## 7. Orquestração e CI/CD

- **Gatilho:** job `orchestration_frota` com `file_arrival` em `/Volumes/<catalog>/raw_data/fleet_raw/` (espera 60 s após o último arquivo; mínimo de 5 min entre disparos). Uma task `pipeline_frota` com 1 retry.
- **`ingestion_monthly.yml`:** todo dia 15 (`0 6 15 * *`) ou manual (modos `previous-month`, `month`, `year` e opção `force`). Atualiza o cadastro da RFB e grava `frota_{ano}_{mes}.csv` no Volume; meses já carregados são pulados.
- **`ci_validation.yml`** (PRs): `ruff`, `pytest` (ingestão e consistência dos seeds) e `databricks bundle validate` em dev e prod.
- **`deploy_prod.yml`:** merge na `main` faz `databricks bundle deploy --target prod` via Service Principal, **sem** aprovar ações destrutivas e **sem** rodar o pipeline. O disparo manual aceita `auto_approve` (apagar/recriar recursos) e `run_pipeline` (necessário quando o deploy cria ou muda tabelas).

---

## 8. Backlog

- [ ] Enriquecer `dim_municipio` com população estimada do IBGE (frota per capita, taxa de motorização)
- [ ] Alertas (e-mail/Slack) a partir das tabelas `qualidade_*`
- [ ] Backfill mensal canônico (`load.py --year 2024 2025 2026`) e arquivamento dos CSVs anuais legados `frota_veiculos_202X.csv` do Volume de prod
