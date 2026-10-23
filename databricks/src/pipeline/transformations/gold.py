"""
silver → gold: Tabelas analíticas e de qualidade

Analíticas (consumidas pelo dashboard):
- gold.frota_eletrica_e_hibrida_evolucao — evolução mensal de elétricos puros + híbridos por UF
- gold.frota_por_grupo_combustivel_regiao — volume por grupo de combustível × região × mês
- gold.frota_qualidade_dados — percentual de combustível não identificado por UF e mês
- gold.frota_municipio_ranking — ranking de municípios no último mês, total e por grupo
- gold.frota_crescimento_mom_por_combustivel — variação mês a mês por grupo de combustível
- gold.frota_crescimento_yoy_por_combustivel_regiao — variação ano a ano por combustível × região
- gold.frota_crescimento_por_regiao — crescimento entre o primeiro e o último mês por região

Qualidade:
- gold.qualidade_volume_mensal — volume da bronze por mês, lotes por mês e anomalias de variação
- gold.qualidade_municipios_sem_match — grafias da Senatran sem código IBGE
- gold.qualidade_combustiveis_sem_mapeamento — combustíveis ausentes do seed de grupos
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from frota_common import com_periodo, id_periodo

SILVER = spark.conf.get("silver_schema")
GOLD = spark.conf.get("gold_schema")

# Variação máxima aceitável do total de veículos entre meses consecutivos
TOTAL_VOLUME_MAX_VARIATION_PCT = 5.0


def _read_silver():
    """Fato com todas as dimensões joinadas para reutilização."""
    fato = spark.read.table(f"{SILVER}.fato_frota")
    dim_mun = spark.read.table(f"{SILVER}.dim_municipio")
    dim_comb = spark.read.table(f"{SILVER}.dim_combustivel")
    dim_data = spark.read.table(f"{SILVER}.dim_data")

    return (
        fato
        .join(dim_mun.select("cd_ibge_municipio", "nm_municipio", "nm_uf", "sigla_uf", "nm_regiao"), "cd_ibge_municipio")
        .join(dim_comb.select("id_combustivel", "nm_combustivel", "nm_grupo", "fl_identificado", "fl_eletrificado"), "id_combustivel")
        .join(dim_data.select("id_data", "nm_mes", "nr_mes", "nr_ano", "dt_referencia"), "id_data")
    )


def _variacao_pct(atual: str, anterior: str):
    return F.round((F.col(atual) - F.col(anterior)) / F.nullif(F.col(anterior), F.lit(0)) * 100, 2)


# ──────────────────────────────────────────────────────────────────
# gold.frota_eletrica_e_hibrida_evolucao
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.frota_eletrica_e_hibrida_evolucao",
    comment=(
        "Evolução mensal da frota elétrica pura e híbrida por estado. "
        "Útil para tendência de eletrificação e análise de impacto de incentivos fiscais."
    ),
    table_properties={"quality": "gold"},
)
def frota_eletrica_e_hibrida_evolucao():
    return (
        _read_silver()
        .filter(F.col("fl_eletrificado"))
        .groupBy("nr_ano", "nr_mes", "nm_mes", "dt_referencia", "nm_uf", "sigla_uf", "nm_regiao", "nm_grupo")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_por_grupo_combustivel_regiao
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.frota_por_grupo_combustivel_regiao",
    comment=(
        "Volume total de frota por grupo de combustível × região geográfica × mês. "
        "Região nula = UF não identificada na fonte."
    ),
    table_properties={"quality": "gold"},
)
def frota_por_grupo_combustivel_regiao():
    return (
        _read_silver()
        .groupBy("nr_ano", "nr_mes", "nm_mes", "dt_referencia", "nm_regiao", "nm_grupo")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_qualidade_dados
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.frota_qualidade_dados",
    comment=(
        "Percentual de veículos com combustível 'Não Identificado' por UF e mês. "
        "Útil para monitorar qualidade da fonte e identificar UFs com subnotificação."
    ),
    table_properties={"quality": "gold"},
)
def frota_qualidade_dados():
    return (
        _read_silver()
        .groupBy("nr_ano", "nr_mes", "dt_referencia", "nm_uf", "sigla_uf", "nm_regiao")
        .agg(
            F.sum("qt_veiculos").alias("qt_total"),
            F.count("*").alias("nr_registros_total"),
            F.sum(F.when(~F.col("fl_identificado"), F.col("qt_veiculos")).otherwise(0)).alias("qt_nao_identificado"),
            F.count(F.when(~F.col("fl_identificado"), 1)).alias("nr_registros_nao_identificado"),
        )
        .withColumn(
            "pct_nao_identificado",
            F.round(F.col("qt_nao_identificado") / F.nullif(F.col("qt_total"), F.lit(0)) * 100, 2),
        )
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_municipio_ranking
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.frota_municipio_ranking",
    comment=(
        "Ranking de municípios no último mês disponível, por total de frota e por grupo de combustível. "
        "Frota é estoque (foto do mês): não somar entre meses. "
        "Útil para identificar mercados prioritários e benchmarks regionais."
    ),
    table_properties={"quality": "gold"},
)
def frota_municipio_ranking():
    df = _read_silver()
    chaves = ["dt_referencia", "cd_ibge_municipio", "nm_municipio", "nm_uf", "sigla_uf", "nm_regiao"]

    # Frota é estoque: o ranking usa apenas o último mês, nunca a soma dos meses
    ultimo_mes = df.agg(F.max("dt_referencia").alias("dt_referencia"))
    atual = df.join(ultimo_mes, "dt_referencia")

    agg = (
        atual.groupBy(*chaves, "nm_grupo")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos_total"))
    )

    # Ranking geral sobre o total do município (todos os grupos), só para UFs identificadas
    total_municipio = (
        agg.filter(F.col("sigla_uf").isNotNull())
        .groupBy(*chaves)
        .agg(F.sum("qt_veiculos_total").alias("qt_frota_municipio"))
        .withColumn("rank_geral", F.rank().over(Window.orderBy(F.desc("qt_frota_municipio"))))
    )

    w_grupo = Window.partitionBy("nm_grupo", F.col("sigla_uf").isNull()).orderBy(F.desc("qt_veiculos_total"))

    return (
        agg
        .withColumn(
            "rank_no_grupo",
            F.when(F.col("sigla_uf").isNotNull(), F.rank().over(w_grupo)),
        )
        .join(total_municipio, chaves, "left")
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_crescimento_mom_por_combustivel
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.frota_crescimento_mom_por_combustivel",
    comment=(
        "Variação mês a mês (MoM) do total de veículos por grupo de combustível, comparando com o "
        "mês calendário anterior (sem comparação quando o mês anterior não foi carregado). "
        "qt_adicionados = crescimento líquido da frota no mês."
    ),
    table_properties={"quality": "gold"},
)
def frota_crescimento_mom_por_combustivel():
    monthly = (
        _read_silver()
        .groupBy("nm_grupo", "nr_ano", "nr_mes", "dt_referencia")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
    )

    anterior = monthly.select(
        "nm_grupo",
        F.add_months("dt_referencia", 1).alias("dt_referencia"),
        F.col("qt_veiculos").alias("qt_veiculos_mes_anterior"),
    )

    return (
        monthly.join(anterior, ["nm_grupo", "dt_referencia"])
        .withColumn("qt_adicionados", F.col("qt_veiculos") - F.col("qt_veiculos_mes_anterior"))
        .withColumn("crescimento_mom_pct", _variacao_pct("qt_veiculos", "qt_veiculos_mes_anterior"))
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_crescimento_yoy_por_combustivel_regiao
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.frota_crescimento_yoy_por_combustivel_regiao",
    comment=(
        "Variação ano a ano (YoY) por grupo de combustível e região geográfica, comparando com o "
        "mesmo mês do ano anterior (por data, não por posição). "
        "Útil para análise de tendências estruturais de longo prazo."
    ),
    table_properties={"quality": "gold"},
)
def frota_crescimento_yoy_por_combustivel_regiao():
    monthly = (
        _read_silver()
        .groupBy("nm_grupo", "nm_regiao", "nr_ano", "nr_mes", "dt_referencia")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
    )

    ano_anterior = monthly.select(
        F.col("nm_grupo").alias("ant_grupo"),
        F.col("nm_regiao").alias("ant_regiao"),
        F.add_months("dt_referencia", 12).alias("ant_dt"),
        F.col("qt_veiculos").alias("qt_veiculos_ano_anterior"),
    )

    return (
        monthly.join(
            ano_anterior,
            (F.col("nm_grupo") == F.col("ant_grupo"))
            & F.col("nm_regiao").eqNullSafe(F.col("ant_regiao"))
            & (F.col("dt_referencia") == F.col("ant_dt")),
        )
        .drop("ant_grupo", "ant_regiao", "ant_dt")
        .withColumn("crescimento_yoy_pct", _variacao_pct("qt_veiculos", "qt_veiculos_ano_anterior"))
    )


# ──────────────────────────────────────────────────────────────────
# gold.frota_crescimento_por_regiao
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.frota_crescimento_por_regiao",
    comment=(
        "Crescimento acumulado de frota por região geográfica entre o primeiro e o último "
        "mês disponíveis no dataset. Útil para ranking de regiões por crescimento absoluto e relativo."
    ),
    table_properties={"quality": "gold"},
)
def frota_crescimento_por_regiao():
    monthly_regional = (
        _read_silver()
        .filter(F.col("nm_regiao").isNotNull())
        .groupBy("nm_regiao", "dt_referencia")
        .agg(F.sum("qt_veiculos").alias("qt_veiculos"))
    )

    limites = monthly_regional.agg(
        F.min("dt_referencia").alias("dt_inicio"),
        F.max("dt_referencia").alias("dt_fim"),
    )

    com_limites = monthly_regional.crossJoin(limites)
    inicio = (
        com_limites.filter(F.col("dt_referencia") == F.col("dt_inicio"))
        .select("nm_regiao", F.col("qt_veiculos").alias("qt_frota_inicio"), "dt_inicio")
    )
    fim = (
        com_limites.filter(F.col("dt_referencia") == F.col("dt_fim"))
        .select("nm_regiao", F.col("qt_veiculos").alias("qt_frota_fim"), "dt_fim")
    )

    return (
        inicio.join(fim, "nm_regiao")
        .withColumn("crescimento_absoluto", F.col("qt_frota_fim") - F.col("qt_frota_inicio"))
        .withColumn("crescimento_pct", _variacao_pct("qt_frota_fim", "qt_frota_inicio"))
        .withColumn("periodo_inicio", id_periodo(F.col("dt_inicio")))
        .withColumn("periodo_fim", id_periodo(F.col("dt_fim")))
        .drop("dt_inicio", "dt_fim")
    )


# ──────────────────────────────────────────────────────────────────
# gold.qualidade_volume_mensal
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.qualidade_volume_mensal",
    comment=(
        "Volume por mês de referência na bronze (todas as cargas) e na fato (lote vigente), "
        "quantidade de lotes por mês, variação vs. mês calendário anterior e flags de anomalia. "
        "Não bloqueia o pipeline — use para monitoramento e alertas."
    ),
    table_properties={"quality": "monitoring"},
)
def qualidade_volume_mensal():
    bronze = (
        com_periodo(spark.read.table("frota_raw"))
        .groupBy("id_data", "dt_referencia")
        .agg(
            F.sum("qtd_veiculos").alias("total_veiculos_bronze"),
            F.count("*").alias("total_registros_bronze"),
            F.countDistinct("nm_arquivo_fonte", "dt_arquivo_modificado").alias("qt_lotes"),
            F.concat_ws(", ", F.array_sort(F.collect_set("nm_arquivo_fonte"))).alias("nm_arquivos_fonte"),
        )
    )

    fato = (
        spark.read.table(f"{SILVER}.fato_frota")
        .groupBy("id_data")
        .agg(
            F.sum("qt_veiculos").alias("total_veiculos"),
            F.max("nm_arquivo_fonte").alias("nm_arquivo_vigente"),
        )
    )

    anterior = fato.join(bronze.select("id_data", "dt_referencia"), "id_data").select(
        F.add_months("dt_referencia", 1).alias("dt_referencia"),
        F.col("total_veiculos").alias("total_veiculos_mes_anterior"),
    )

    return (
        bronze.join(fato, "id_data", "left")
        .join(anterior, "dt_referencia", "left")
        .withColumn("fl_periodo_duplicado", F.col("qt_lotes") > 1)
        .withColumn("fl_mes_anterior_ausente", F.col("total_veiculos_mes_anterior").isNull())
        .withColumn("variacao_pct", _variacao_pct("total_veiculos", "total_veiculos_mes_anterior"))
        .withColumn("fl_anomalia_volume", F.abs(F.col("variacao_pct")) > F.lit(TOTAL_VOLUME_MAX_VARIATION_PCT))
        .withColumn("dt_calculo", F.current_timestamp())
    )


# ──────────────────────────────────────────────────────────────────
# gold.qualidade_municipios_sem_match
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.qualidade_municipios_sem_match",
    comment=(
        "Grafias de município da Senatran sem código IBGE (contabilizadas no membro -1 da fato). "
        "Corrija adicionando a grafia em seeds/municipio_correcoes.csv ou municipio_complemento.csv."
    ),
    table_properties={"quality": "monitoring"},
)
def qualidade_municipios_sem_match():
    return (
        spark.read.table(f"{SILVER}.map_municipio_senatran")
        .filter(F.col("metodo_match") == "sem_match")
    )


# ──────────────────────────────────────────────────────────────────
# gold.qualidade_combustiveis_sem_mapeamento
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{GOLD}.qualidade_combustiveis_sem_mapeamento",
    comment="Combustíveis ausentes de seeds/combustivel_grupo.csv (classificados como 'Não Identificado').",
    table_properties={"quality": "monitoring"},
)
def qualidade_combustiveis_sem_mapeamento():
    return (
        spark.read.table(f"{SILVER}.dim_combustivel")
        .filter(~F.col("fl_mapeado"))
    )
