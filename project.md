# Plano de Projeto — Frota de Veículos por Combustível e Município (Brasil)
> Databricks Medallion Architecture · Bronze → Silver → Gold

---

## 1. Visão Geral da Arquitetura

```
Bronze (raw)             Silver (curated)                  Gold (analytical)
──────────────────       ─────────────────────────────     ─────────────────────────
frota_raw           →    dim_municipio                 →   frota_por_regiao
rfb_municipios_raw  →    dim_combustivel                   frota_eletrica_evolucao
                    →    dim_data                      →   frota_flex_vs_combustao
seed: uf_regiao     →    fato_frota                    →   frota_por_estado_mes
```

### Tabelas Bronze

| Tabela                   | Fonte                        | Descrição                                      |
|--------------------------|------------------------------|------------------------------------------------|
| `bronze.frota_raw`       | Arquivos xlsx do Detran/Senatran | Dados de frota por município e combustível, exatamente como vieram |
| `bronze.rfb_municipios_raw` | CSV da Receita Federal    | Código do município, nome e sigla UF — ingerido sem transformação |

---

## 2. Bronze → Silver

### 2.1 dim_data

Extraída a partir do campo `nm_file` com regex. Mapeie o nome do mês em português para o número do mês.

| Coluna         | Tipo    | Exemplo        |
|----------------|---------|----------------|
| `id_data`      | INT     | `202404`       |
| `nm_mes`       | STRING  | `Abril`        |
| `nr_mes`       | INT     | `4`            |
| `nr_ano`       | INT     | `2024`         |
| `dt_referencia`| DATE    | `2024-04-01`   |

**Lógica de extração:**
```python
# Padrão: D_Frota_por_UF_Municipio_COMBUSTIVEL_Abril_2024.xlsx
regexp_extract(nm_file, r'_([A-Za-záéíóúãõêç]+)_(\d{4})\.xlsx', 1)  # mês
regexp_extract(nm_file, r'_([A-Za-záéíóúãõêç]+)_(\d{4})\.xlsx', 2)  # ano
```

---

### 2.2 dim_municipio

Construída a partir do join entre `bronze.frota_raw` e `bronze.rfb_municipios_raw`, enriquecida com `nm_regiao` via seed table. O código da Receita Federal é equivalente ao código IBGE de 7 dígitos — padrão federal comum a todos os sistemas.

| Coluna              | Tipo   | Exemplo          |
|---------------------|--------|------------------|
| `id_municipio`      | INT    | surrogate key    |
| `cd_ibge_municipio` | STRING | `1200013`        |
| `nm_municipio`      | STRING | `ACRELANDIA`     |
| `nm_uf`             | STRING | `ACRE`           |
| `sigla_uf`          | STRING | `AC`             |
| `nm_regiao`         | STRING | `Norte`          |

**Estratégia de join e normalização de nomes:**

O nome do município no `frota_raw` vem em caixa alta e sem acento (padrão Detran). O CSV da Receita Federal pode ter acentuação. Antes do join é obrigatório normalizar os dois lados: remover acentos, colocar em upper case e remover caracteres especiais. O join é feito por `nm_municipio_normalizado + sigla_uf`.

Após o join, registre quantos municípios do `frota_raw` ficaram sem match — isso indica inconsistências de grafia que precisam de tratamento manual ou fuzzy matching.

---

### 2.3 dim_combustivel

Normalize os 29 tipos distintos em dois níveis: o tipo exato e o grupo analítico.

| Coluna               | Tipo    | Exemplo                   |
|----------------------|---------|---------------------------|
| `id_combustivel`     | INT     | surrogate key             |
| `nm_combustivel`     | STRING  | `GASOLINA/ALCOOL/ELETRICO`|
| `nm_grupo`           | STRING  | `Híbrido`                 |
| `fl_identificado`    | BOOLEAN | `true` / `false`          |

**Proposta de agrupamento:**

| Grupo              | Combustíveis incluídos |
|--------------------|------------------------|
| `Elétrico Puro`    | ELETRICO, ELETRICO/FONTE EXTERNA, ELETRICO/FONTE INTERNA, CELULA COMBUSTIVEL |
| `Híbrido`          | HIBRIDO, HIBRIDO PLUG-IN, GASOLINA/ELETRICO, DIESEL/ELETRICO, ETANOL/ELETRICO, GASOLINA/ALCOOL/ELETRICO |
| `Flex`             | ALCOOL/GASOLINA, GASOL/GAS NATURAL COMBUSTIVEL, GASOLINA/GAS NATURAL VEICULAR, ALCOOL/GAS NATURAL COMBUSTIVEL, ALCOOL/GAS NATURAL VEICULAR, DIESEL/GAS NATURAL VEICULAR, DIESEL/GAS NATURAL COMBUSTIVEL, GASOLINA/ALCOOL/GAS NATURAL |
| `Combustão Fóssil` | GASOLINA, DIESEL, GAS NATURAL VEICULAR, GAS METANO, GAS/NATURAL/LIQUEFEITO, GASOGENIO |
| `Combustão Renovável` | ALCOOL |
| `Não Identificado` | Sem Informação, VIDE/CAMPO/OBSERVACAO, Não Identificado, Não se Aplica |

> **Nota:** o grupo `Não Identificado` tem `fl_identificado = false`. Mantenha esses registros na fato — eles representam volume real da frota e são relevantes para detectar qualidade de dados por município/estado. **Não remova, filtre na camada Gold** quando necessário.

---

### 2.4 fato_frota

Tabela central da Silver. Granularidade: **município × combustível × mês/ano**.

| Coluna          | Tipo    | Observação                       |
|-----------------|---------|----------------------------------|
| `id_fato`       | BIGINT  | surrogate key                    |
| `id_municipio`  | INT     | FK → dim_municipio               |
| `id_combustivel`| INT     | FK → dim_combustivel             |
| `id_data`       | INT     | FK → dim_data                    |
| `qt_veiculos`   | INT     | quantidade registrada            |
| `nm_file`       | STRING  | rastreabilidade até a fonte raw  |

> Mantenha `nm_file` na Silver para rastreabilidade (data lineage). Facilita reprocessamento se uma fonte for corrigida.

---

## 3. Silver → Gold

As tabelas Gold são derivadas analíticas, otimizadas para consumo em dashboards e análises. Sugestões:

### 3.1 `frota_eletrica_e_hibrida_evolucao`
Evolução mensal da frota elétrica + híbrida por estado.
Útil para: tendência de eletrificação, impacto de incentivos fiscais.

### 3.2 `frota_por_grupo_combustivel_regiao`
Volume total por grupo de combustível × região × mês.
Útil para: comparativos Norte/Sul/Sudeste, distribuição de flex vs combustão.

### 3.3 `frota_qualidade_dados`
Percentual de registros `Não Identificado` por UF e mês.
Útil para: monitorar qualidade da fonte, identificar UFs com subnotificação.

### 3.4 `frota_municipio_ranking`
Top municípios por total de frota, por grupo de combustível.
Útil para: identificar mercados prioritários, benchmarks regionais.

---

## 4. Decisões de Qualidade de Dados

| Situação                              | Tratamento recomendado                                               |
|---------------------------------------|----------------------------------------------------------------------|
| `Sem Informação`                      | Mapear para grupo `Não Identificado`, `fl_identificado = false`     |
| `VIDE/CAMPO/OBSERVACAO`               | Idem                                                                |
| `Não se Aplica`                       | Idem — pode indicar categoria não aplicável ao município (ex: GNV em zona rural sem posto) |
| `Não Identificado`                    | Idem                                                                |
| Município duplicado em UFs diferentes | Resolver via `cd_ibge_municipio` (ver sugestão 2.2)                 |
| Meses faltando para algum município   | Não preencher com zero — deixar ausente e tratar na camada Gold     |

---

## 5. Checklist de Implementação

### Bronze → Silver
- [ ] Ingerir CSV da Receita Federal como `bronze.rfb_municipios_raw`
- [ ] Criar seed table `uf_regiao` (27 linhas: sigla_uf → nm_uf, nm_regiao)
- [ ] Criar `dim_municipio` com normalização de nomes + join RFB + enriquecimento de região
- [ ] Auditar municípios sem match no join e corrigir grafias divergentes
- [ ] Criar `dim_data` com parser do `nm_file`
- [ ] Criar `dim_combustivel` com mapeamento de `nm_grupo` e `fl_identificado`
- [ ] Criar `fato_frota` com joins nas dimensões e surrogate keys

### Silver → Gold
- [ ] `frota_eletrica_e_hibrida_evolucao`
- [ ] `frota_por_grupo_combustivel_regiao`
- [ ] `frota_qualidade_dados`
- [ ] `frota_municipio_ranking`

### Opcional / Melhorias futuras
- [ ] Adicionar `populacao_estimada` (IBGE) na `dim_municipio` para calcular frota per capita
- [ ] Criar alerta de qualidade de dados quando `% Não Identificado > threshold` por UF/mês
- [ ] Implementar fuzzy matching para municípios sem match no join RFB

---

## 6. Diagrama de Relacionamento (Silver)

```
dim_data ──────────────────────┐
                               │
dim_municipio ─────────────── fato_frota
                               │
dim_combustivel ───────────────┘
```

---

*Gerado para o projeto Frota Brasil · Databricks Medallion Architecture*