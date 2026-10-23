"""
bronze → silver: Star Schema da frota

- silver.dim_data — calendário mensal contínuo (sem buracos) entre o primeiro e o último mês carregado
- silver.dim_municipio — 1 linha por município IBGE (cadastro RFB + complemento) + membro -1 "Não identificado"
- silver.map_municipio_senatran — de-para da grafia Senatran (UF, município) para o código IBGE
- silver.dim_combustivel — tipos de combustível com grupo analítico (seed combustivel_grupo.csv)
- silver.fato_frota — município IBGE × combustível × mês, usando apenas o lote mais recente de cada mês

Medida qt_veiculos é um ESTOQUE (frota registrada no mês): soma-se entre municípios e combustíveis,
nunca ao longo do tempo.
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from frota_common import (
    com_periodo,
    linha_valida,
    nm_mes,
    normalize_text_col,
    read_seed,
    sem_acento,
)

SILVER = spark.conf.get("silver_schema")
SEEDS_PATH = spark.conf.get("seeds_path")

NAO_IDENTIFICADO = -1


def _uf_regiao():
    return (
        read_seed(SEEDS_PATH, "uf_regiao.csv")
        .withColumn("nm_uf_norm", normalize_text_col(F.col("nm_uf")))
    )


# ──────────────────────────────────────────────────────────────────
# frota_periodo (temporária): linhas válidas da bronze com mês de referência
# ──────────────────────────────────────────────────────────────────

@dp.temporary_view(name="frota_periodo")
@dp.expect_or_fail("periodo_identificado", "id_data IS NOT NULL")
def frota_periodo():
    return (
        com_periodo(spark.read.table("frota_raw").filter(linha_valida()))
        .withColumn("nm_combustivel_norm", sem_acento(F.col("combustivel_veiculo")))
    )


# ──────────────────────────────────────────────────────────────────
# silver.dim_data
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{SILVER}.dim_data",
    comment="Calendário mensal contínuo entre o primeiro e o último mês carregado. Granularidade: mês.",
    table_properties={"quality": "silver"},
)
def dim_data():
    periodos = spark.read.table("frota_periodo").select("dt_referencia").distinct()
    limites = periodos.agg(F.min("dt_referencia").alias("dt_min"), F.max("dt_referencia").alias("dt_max"))

    return (
        limites
        .select(
            F.explode(F.sequence("dt_min", "dt_max", F.expr("INTERVAL 1 MONTH"))).alias("dt_referencia"),
            "dt_max",
        )
        .join(periodos.withColumn("fl_possui_dados", F.lit(True)), "dt_referencia", "left")
        .select(
            (F.year("dt_referencia") * 100 + F.month("dt_referencia")).alias("id_data"),
            "dt_referencia",
            F.year("dt_referencia").alias("nr_ano"),
            F.month("dt_referencia").alias("nr_mes"),
            nm_mes(F.month("dt_referencia")).alias("nm_mes"),
            F.quarter("dt_referencia").alias("nr_trimestre"),
            (F.col("dt_referencia") == F.col("dt_max")).alias("fl_ultimo_mes"),
            F.coalesce(F.col("fl_possui_dados"), F.lit(False)).alias("fl_possui_dados"),
        )
    )


# ──────────────────────────────────────────────────────────────────
# silver.dim_municipio
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{SILVER}.dim_municipio",
    comment=(
        "Municípios IBGE (cadastro da Receita Federal + complemento manual) com UF e região. "
        "Chave: cd_ibge_municipio. O membro -1 representa UF/município não identificados na fonte."
    ),
    table_properties={"quality": "silver"},
)
@dp.expect_or_fail("cd_ibge_nao_nulo", "cd_ibge_municipio IS NOT NULL")
def dim_municipio():
    uf = _uf_regiao().select("sigla_uf", "nm_uf", "nm_regiao")

    rfb = (
        spark.read.table("rfb_municipios_raw")
        .select(F.col("cd_municipio").cast("int").alias("cd_ibge_municipio"), "nm_municipio", "sigla_uf")
        .dropDuplicates(["cd_ibge_municipio"])
    )

    complemento = (
        read_seed(SEEDS_PATH, "municipio_complemento.csv")
        .select(F.col("cd_ibge_municipio").cast("int").alias("cd_ibge_municipio"), "nm_municipio", "sigla_uf")
        .join(rfb, "cd_ibge_municipio", "left_anti")
    )

    nao_identificado = spark.createDataFrame(
        [(NAO_IDENTIFICADO, "NÃO IDENTIFICADO", "NÃO IDENTIFICADO")],
        "cd_ibge_municipio INT, nm_municipio STRING, nm_uf STRING",
    ).select(
        "cd_ibge_municipio", "nm_municipio", "nm_uf",
        F.lit(None).cast("string").alias("sigla_uf"),
        F.lit(None).cast("string").alias("nm_regiao"),
        F.lit(False).alias("fl_identificado"),
    )

    municipios = (
        rfb.unionByName(complemento)
        .join(uf, "sigla_uf")  # descarta UFs fora das 27 (ex.: exterior)
        .select(
            "cd_ibge_municipio", "nm_municipio", "nm_uf", "sigla_uf", "nm_regiao",
            F.lit(True).alias("fl_identificado"),
        )
    )

    return municipios.unionByName(nao_identificado)


# ──────────────────────────────────────────────────────────────────
# silver.map_municipio_senatran
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{SILVER}.map_municipio_senatran",
    comment=(
        "De-para da grafia Senatran (uf, municipio) para o código IBGE. metodo_match: ibge, tom, "
        "correcao (seed municipio_correcoes.csv), complemento (seed municipio_complemento.csv), "
        "especial (UF não identificada → -1) ou sem_match (código nulo, auditado na gold)."
    ),
    table_properties={"quality": "silver"},
)
@dp.expect("municipio_mapeado", "cd_ibge_municipio IS NOT NULL")
def map_municipio_senatran():
    uf = _uf_regiao().select("nm_uf_norm", "sigla_uf")

    senatran = (
        spark.read.table("frota_periodo")
        .select(F.col("uf").alias("nm_uf_raw"), F.col("municipio").alias("nm_municipio_raw"))
        .distinct()
        .withColumn("nm_uf_norm", normalize_text_col(F.col("nm_uf_raw")))
        .withColumn("nm_municipio_norm", normalize_text_col(F.col("nm_municipio_raw")))
        .join(uf, "nm_uf_norm", "left")
    )

    correcoes = (
        read_seed(SEEDS_PATH, "municipio_correcoes.csv")
        .select(
            "sigla_uf",
            normalize_text_col(F.col("nm_senatran")).alias("nm_municipio_norm"),
            normalize_text_col(F.col("nm_rfb")).alias("nm_corrigido"),
        )
    )

    complemento = (
        read_seed(SEEDS_PATH, "municipio_complemento.csv")
        .select(
            "sigla_uf",
            normalize_text_col(F.col("nm_senatran")).alias("nm_municipio_norm"),
            F.col("cd_ibge_municipio").cast("int").alias("cd_complemento"),
        )
    )

    rfb = spark.read.table("rfb_municipios_raw").select(
        F.col("cd_municipio").cast("int").alias("cd"),
        "sigla_uf",
        normalize_text_col(F.col("nm_municipio")).alias("nm_busca"),
        normalize_text_col(F.col("nm_municipio_tom")).alias("nm_busca_tom"),
    )
    # Um código por (nome, UF); evita multiplicar linhas caso a RFB tenha homônimos normalizados
    rfb_ibge = rfb.groupBy("nm_busca", "sigla_uf").agg(F.min("cd").alias("cd_ibge"))
    rfb_tom = (
        rfb.groupBy(F.col("nm_busca_tom").alias("nm_busca"), "sigla_uf")
        .agg(F.min("cd").alias("cd_tom"))
    )

    joined = (
        senatran
        .join(correcoes, ["sigla_uf", "nm_municipio_norm"], "left")
        .join(complemento, ["sigla_uf", "nm_municipio_norm"], "left")
        .withColumn("nm_busca", F.coalesce(F.col("nm_corrigido"), F.col("nm_municipio_norm")))
        .join(rfb_ibge, ["nm_busca", "sigla_uf"], "left")
        .join(rfb_tom, ["nm_busca", "sigla_uf"], "left")
    )

    return joined.select(
        "nm_uf_raw",
        "nm_municipio_raw",
        "sigla_uf",
        "nm_municipio_norm",
        F.when(F.col("sigla_uf").isNull(), F.lit(NAO_IDENTIFICADO))
        .otherwise(F.coalesce("cd_complemento", "cd_ibge", "cd_tom"))
        .alias("cd_ibge_municipio"),
        F.when(F.col("sigla_uf").isNull(), F.lit("especial"))
        .when(F.col("cd_complemento").isNotNull(), F.lit("complemento"))
        .when(F.col("nm_corrigido").isNotNull() & F.coalesce("cd_ibge", "cd_tom").isNotNull(), F.lit("correcao"))
        .when(F.col("cd_ibge").isNotNull(), F.lit("ibge"))
        .when(F.col("cd_tom").isNotNull(), F.lit("tom"))
        .otherwise(F.lit("sem_match"))
        .alias("metodo_match"),
    )


# ──────────────────────────────────────────────────────────────────
# silver.dim_combustivel
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{SILVER}.dim_combustivel",
    comment=(
        "Tipos de combustível com grupo analítico (seed combustivel_grupo.csv). "
        "Chave determinística: id_combustivel = xxhash64(nm_combustivel_norm). "
        "Tipos ausentes do seed caem em 'Não Identificado' com fl_mapeado = false."
    ),
    table_properties={"quality": "silver"},
)
@dp.expect("combustivel_mapeado", "fl_mapeado")
def dim_combustivel():
    grupos = (
        read_seed(SEEDS_PATH, "combustivel_grupo.csv")
        .select(
            "nm_combustivel_norm",
            "nm_grupo",
            (F.lower("fl_eletrificado") == "true").alias("fl_eletrificado"),
            F.lit(True).alias("fl_mapeado"),
        )
    )

    return (
        spark.read.table("frota_periodo")
        .groupBy("nm_combustivel_norm")
        .agg(F.max("combustivel_veiculo").alias("nm_combustivel"))
        .join(grupos, "nm_combustivel_norm", "left")
        .select(
            F.xxhash64("nm_combustivel_norm").alias("id_combustivel"),
            "nm_combustivel",
            "nm_combustivel_norm",
            F.coalesce("nm_grupo", F.lit("Não Identificado")).alias("nm_grupo"),
            F.coalesce("fl_eletrificado", F.lit(False)).alias("fl_eletrificado"),
            (F.coalesce("nm_grupo", F.lit("Não Identificado")) != "Não Identificado").alias("fl_identificado"),
            F.coalesce("fl_mapeado", F.lit(False)).alias("fl_mapeado"),
        )
    )


# ──────────────────────────────────────────────────────────────────
# silver.fato_frota
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name=f"{SILVER}.fato_frota",
    comment=(
        "Fato central. Granularidade: município IBGE × combustível × mês. Usa apenas o lote "
        "(arquivo + versão) mais recente de cada mês, então republicações substituem o mês inteiro. "
        "qt_veiculos é estoque: não somar ao longo do tempo."
    ),
    table_properties={"quality": "silver"},
)
@dp.expect_or_fail("data_resolvida", "id_data IS NOT NULL")
@dp.expect_or_fail("municipio_resolvido", "cd_ibge_municipio IS NOT NULL")
@dp.expect_or_fail("combustivel_resolvido", "id_combustivel IS NOT NULL")
def fato_frota():
    frota = spark.read.table("frota_periodo")
    lote = ["id_data", "nm_arquivo_fonte", "dt_arquivo_modificado"]

    # 1. Lote vigente por mês: o arquivo com a versão mais recente
    w_lote = Window.partitionBy("id_data").orderBy(
        F.desc("dt_arquivo_modificado"), F.desc("dt_ingestao"), F.desc("nm_arquivo_fonte")
    )
    lote_vigente = (
        frota.groupBy(*lote).agg(F.max("dt_ingestao").alias("dt_ingestao"))
        .withColumn("rn", F.row_number().over(w_lote))
        .filter("rn = 1")
        .select(*lote)
    )

    mapa = spark.read.table(f"{SILVER}.map_municipio_senatran").select(
        F.col("nm_uf_raw").alias("uf"),
        F.col("nm_municipio_raw").alias("municipio"),
        "cd_ibge_municipio",
    )
    combustivel = spark.read.table(f"{SILVER}.dim_combustivel").select("nm_combustivel_norm", "id_combustivel")

    # 2. Chaves das dimensões; 3. agrega no grão (correções podem unir grafias do mesmo município)
    return (
        frota.join(lote_vigente, lote)
        .join(mapa, ["uf", "municipio"], "left")
        .join(combustivel, "nm_combustivel_norm", "left")
        .withColumn("cd_ibge_municipio", F.coalesce("cd_ibge_municipio", F.lit(NAO_IDENTIFICADO)))
        .groupBy("id_data", "cd_ibge_municipio", "id_combustivel")
        .agg(
            F.sum("qtd_veiculos").alias("qt_veiculos"),
            F.max("nm_arquivo_fonte").alias("nm_arquivo_fonte"),
            F.max("dt_ingestao").alias("dt_ingestao"),
        )
    )
