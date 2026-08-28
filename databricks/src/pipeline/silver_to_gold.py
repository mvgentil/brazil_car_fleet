# Databricks notebook source
# MAGIC %md
# MAGIC # silver → gold: Tabelas Analíticas
# MAGIC
# MAGIC Lakeflow Pipeline (Spark Declarative Pipelines) que lê as tabelas silver
# MAGIC via `spark.table()` e produz as tabelas gold otimizadas para dashboards e análises.
# MAGIC
# MAGIC ## Tabelas produzidas
# MAGIC - `gold.frota_eletrica_e_hibrida_evolucao` — evolução mensal de EV + híbridos por UF
# MAGIC - `gold.frota_por_grupo_combustivel_regiao` — volume por grupo de combustível × região × mês
# MAGIC - `gold.frota_qualidade_dados` — percentual de registros não identificados por UF e mês
# MAGIC - `gold.frota_municipio_ranking` — top municípios por total de frota e por grupo
# MAGIC - `gold.frota_crescimento_mom_por_combustivel` — variação mês-a-mês por grupo de combustível
# MAGIC - `gold.frota_crescimento_yoy_por_combustivel_regiao` — variação ano-a-ano por combustível × região
# MAGIC - `gold.frota_crescimento_por_regiao` — crescimento acumulado de frota por região (período completo)

# COMMAND ----------

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

# ──────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────

CATALOG = spark.conf.get("catalog", "brazil_car_fleet")
SILVER_SCHEMA = spark.conf.get("silver_schema", "silver")

SILVER_FATO = f"{CATALOG}.{SILVER_SCHEMA}.fato_frota"
SILVER_DIM_MUN = f"{CATALOG}.{SILVER_SCHEMA}.dim_municipio"
SILVER_DIM_COMB = f"{CATALOG}.{SILVER_SCHEMA}.dim_combustivel"
SILVER_DIM_DATA = f"{CATALOG}.{SILVER_SCHEMA}.dim_data"


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _read_silver():
    """Lê a fato com todas as dimensões já joinadas para reutilização."""
    fato = spark.table(SILVER_FATO)
    dim_mun = spark.table(SILVER_DIM_MUN)
    dim_comb = spark.table(SILVER_DIM_COMB)
    dim_data = spark.table(SILVER_DIM_DATA)

    return (
        fato
        .join(dim_mun.select("id_municipio", "nm_municipio", "nm_uf", "sigla_uf", "nm_regiao"), "id_municipio", "left")
        .join(dim_comb.select("id_combustivel", "nm_combustivel", "nm_grupo", "fl_identificado"), "id_combustivel", "left")
        .join(dim_data.select("id_data", "nm_mes", "nr_mes", "nr_ano", "dt_referencia"), "id_data", "left")
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_eletrica_e_hibrida_evolucao
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="frota_eletrica_e_hibrida_evolucao",
    comment=(
        "Evolução mensal da frota elétrica pura e híbrida por estado. "
        "Útil para tendência de eletrificação e análise de impacto de incentivos fiscais."
    ),
    table_properties={"quality": "gold"},
)
def frota_eletrica_e_hibrida_evolucao():
    df = _read_silver()
    return (
        df.filter(F.col("nm_grupo").isin("Elétrico Puro", "Híbrido"))
        .groupBy("nr_ano", "nr_mes", "nm_mes", "dt_referencia", "nm_uf", "sigla_uf", "nm_regiao", "nm_grupo")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
        .orderBy("dt_referencia", "nm_uf", "nm_grupo")
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_por_grupo_combustivel_regiao
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="frota_por_grupo_combustivel_regiao",
    comment=(
        "Volume total de frota por grupo de combustível × região geográfica × mês. "
        "Útil para comparativos Norte/Sul/Sudeste e distribuição flex vs combustão."
    ),
    table_properties={"quality": "gold"},
)
def frota_por_grupo_combustivel_regiao():
    df = _read_silver()
    return (
        df.groupBy("nr_ano", "nr_mes", "nm_mes", "dt_referencia", "nm_regiao", "nm_grupo")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
        .orderBy("dt_referencia", "nm_regiao", "nm_grupo")
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_qualidade_dados
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="frota_qualidade_dados",
    comment=(
        "Percentual de registros 'Não Identificado' por UF e mês. "
        "Útil para monitorar qualidade da fonte e identificar UFs com subnotificação."
    ),
    table_properties={"quality": "gold"},
)
def frota_qualidade_dados():
    df = _read_silver()

    total_por_uf_mes = (
        df.groupBy("nr_ano", "nr_mes", "dt_referencia", "nm_uf", "sigla_uf", "nm_regiao")
        .agg(
            F.sum("qt_veiculos").alias("qt_total"),
            F.count("*").alias("nr_registros_total"),
        )
    )

    nao_identificado = (
        df.filter(~F.col("fl_identificado"))
        .groupBy("nr_ano", "nr_mes", "nm_uf")
        .agg(
            F.sum("qt_veiculos").alias("qt_nao_identificado"),
            F.count("*").alias("nr_registros_nao_identificado"),
        )
    )

    return (
        total_por_uf_mes
        .join(nao_identificado, ["nr_ano", "nr_mes", "nm_uf"], "left")
        .fillna(0, subset=["qt_nao_identificado", "nr_registros_nao_identificado"])
        .withColumn(
            "pct_nao_identificado",
            F.round(
                F.col("qt_nao_identificado") / F.col("qt_total") * 100,
                2,
            ),
        )
        .orderBy("dt_referencia", "nm_uf")
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_municipio_ranking
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="frota_municipio_ranking",
    comment=(
        "Ranking de municípios por total de frota e por grupo de combustível. "
        "Útil para identificar mercados prioritários e benchmarks regionais."
    ),
    table_properties={"quality": "gold"},
)
def frota_municipio_ranking():
    df = _read_silver()

    agg = (
        df.groupBy("nm_municipio", "nm_uf", "sigla_uf", "nm_regiao", "nm_grupo")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos_total"))
    )

    w_grupo = Window.partitionBy("nm_grupo").orderBy(F.desc("qt_veiculos_total"))
    w_geral = Window.orderBy(F.desc("qt_veiculos_total"))

    return (
        agg
        .withColumn("rank_no_grupo", F.rank().over(w_grupo))
        .withColumn("rank_geral", F.rank().over(w_geral))
        .orderBy("nm_grupo", "rank_no_grupo")
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_crescimento_mom_por_combustivel
# Absorvida de mv_kpi_mom_growth_by_fuel
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="frota_crescimento_mom_por_combustivel",
    comment=(
        "Variação mês-a-mês (MoM) do total de veículos por grupo de combustível. "
        "Útil para detectar aceleração ou desaceleração de adoção por tipo de frota."
    ),
    table_properties={"quality": "gold"},
)
def frota_crescimento_mom_por_combustivel():
    df = _read_silver()

    monthly = (
        df.groupBy("nm_grupo", "nr_ano", "nr_mes", "dt_referencia")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
    )

    w = Window.partitionBy("nm_grupo").orderBy("nr_ano", "nr_mes")

    return (
        monthly
        .withColumn("qt_veiculos_mes_anterior", F.lag("qt_veiculos").over(w))
        .withColumn(
            "crescimento_mom_pct",
            F.round(
                (F.col("qt_veiculos") - F.col("qt_veiculos_mes_anterior"))
                / F.nullif(F.col("qt_veiculos_mes_anterior"), F.lit(0))
                * 100,
                2,
            ),
        )
        .filter(F.col("qt_veiculos_mes_anterior").isNotNull())
        .orderBy("dt_referencia", "nm_grupo")
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_crescimento_yoy_por_combustivel_regiao
# Absorvida de mv_kpi_yoy_growth_by_fuel_region
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="frota_crescimento_yoy_por_combustivel_regiao",
    comment=(
        "Variação ano-a-ano (YoY) por grupo de combustível e região geográfica. "
        "Compara o mesmo mês do ano anterior (lag de 12 períodos). "
        "Útil para análise de tendências estruturais de longo prazo."
    ),
    table_properties={"quality": "gold"},
)
def frota_crescimento_yoy_por_combustivel_regiao():
    df = _read_silver()

    monthly = (
        df.groupBy("nm_grupo", "nm_regiao", "nr_ano", "nr_mes", "dt_referencia")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
    )

    # Lag de 12 meses = mesmo mês do ano anterior
    w = Window.partitionBy("nm_grupo", "nm_regiao").orderBy("nr_ano", "nr_mes")

    return (
        monthly
        .withColumn("qt_veiculos_ano_anterior", F.lag("qt_veiculos", 12).over(w))
        .withColumn(
            "crescimento_yoy_pct",
            F.round(
                (F.col("qt_veiculos") - F.col("qt_veiculos_ano_anterior"))
                / F.nullif(F.col("qt_veiculos_ano_anterior"), F.lit(0))
                * 100,
                2,
            ),
        )
        .filter(F.col("qt_veiculos_ano_anterior").isNotNull())
        .orderBy("dt_referencia", "nm_regiao", "nm_grupo")
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_crescimento_por_regiao
# Absorvida de mv_kpi_fleet_growth_by_region
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="frota_crescimento_por_regiao",
    comment=(
        "Crescimento acumulado de frota por região geográfica entre o primeiro e o último "
        "mês disponíveis no dataset. Útil para ranking de regiões por crescimento absoluto e relativo."
    ),
    table_properties={"quality": "gold"},
)
def frota_crescimento_por_regiao():
    df = _read_silver()

    monthly_regional = (
        df.groupBy("nm_regiao", "nr_ano", "nr_mes")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
    )

    # Período mínimo e máximo disponíveis no dataset
    min_periodo = monthly_regional.agg(
        F.min(F.col("nr_ano") * 100 + F.col("nr_mes")).alias("min_p")
    ).collect()[0]["min_p"]

    max_periodo = monthly_regional.agg(
        F.max(F.col("nr_ano") * 100 + F.col("nr_mes")).alias("max_p")
    ).collect()[0]["max_p"]

    frota_inicio = (
        monthly_regional
        .filter((F.col("nr_ano") * 100 + F.col("nr_mes")) == min_periodo)
        .withColumnRenamed("qt_veiculos", "qt_frota_inicio")
        .drop("nr_ano", "nr_mes")
    )

    frota_fim = (
        monthly_regional
        .filter((F.col("nr_ano") * 100 + F.col("nr_mes")) == max_periodo)
        .withColumnRenamed("qt_veiculos", "qt_frota_fim")
        .drop("nr_ano", "nr_mes")
    )

    return (
        frota_inicio.join(frota_fim, "nm_regiao")
        .withColumn(
            "crescimento_absoluto",
            F.col("qt_frota_fim") - F.col("qt_frota_inicio"),
        )
        .withColumn(
            "crescimento_pct",
            F.round(
                (F.col("qt_frota_fim") - F.col("qt_frota_inicio"))
                / F.nullif(F.col("qt_frota_inicio"), F.lit(0))
                * 100,
                2,
            ),
        )
        .withColumn("periodo_inicio", F.lit(min_periodo))
        .withColumn("periodo_fim", F.lit(max_periodo))
        .orderBy(F.desc("crescimento_pct"))
    )
