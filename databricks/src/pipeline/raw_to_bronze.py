# Databricks notebook source
# MAGIC %md
# MAGIC # raw → bronze: Frota de Veículos & Municípios RFB
# MAGIC
# MAGIC Lakeflow Pipeline (Spark Declarative Pipelines) que lê CSVs individuais
# MAGIC do Volume `fleet_raw` e `rfb_municipios_raw` com schema estrito (header=false) e popula as tabelas bronze.
# MAGIC
# MAGIC ## Responsabilidades desta camada
# MAGIC - Ingerir dados brutos com schema estrito e nomes de colunas normalizados já na bronze
# MAGIC - Aplicar validações de qualidade **por linha** via Expectations
# MAGIC - Quarentenar linhas inválidas em `bronze.frota_quarentena`
# MAGIC - Monitorar variação mês-a-mês via materialized view de métricas
# MAGIC - Ingerir cadastro de municípios da Receita Federal (RFB) com schema estrito

# COMMAND ----------

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.types import LongType, StringType, StructType, StructField

# ──────────────────────────────────────────────────────────────────
# Configuração (passada via pipeline configuration no databricks.yml)
# ──────────────────────────────────────────────────────────────────

CATALOG = spark.conf.get("catalog", "brazil_car_fleet")
RAW_SCHEMA = spark.conf.get("raw_schema", "raw_data")
FLEET_VOLUME = spark.conf.get("fleet_volume", "fleet_raw")
RFB_VOLUME = spark.conf.get("rfb_volume", "rfb_municipios_raw")

FLEET_VOLUME_PATH = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/{FLEET_VOLUME}/"
RFB_VOLUME_PATH = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/{RFB_VOLUME}/"

# Threshold de qualidade: variação máxima aceitável do total de veículos entre meses consecutivos
TOTAL_VOLUME_MAX_VARIATION_PCT = 5.0

# Mês de referência extraído do nm_file (aceita "Marco", "Março" e "Maro" — ç perdido no encoding)
MES_REGEX = r"(?i)(janeiro|fevereiro|mar(?:co|ço|o)|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
MES_MAP = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "MARÇO": 3, "MARO": 3, "ABRIL": 4,
    "MAIO": 5, "JUNHO": 6, "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9,
    "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
}

# ──────────────────────────────────────────────────────────────────
# Schemas estritos dos arquivos CSV (header=false, ordem fixa)
# ──────────────────────────────────────────────────────────────────

FROTA_SCHEMA = StructType([
    StructField("uf", StringType(), True),
    StructField("municipio", StringType(), True),
    StructField("combustivel_veiculo", StringType(), True),
    StructField("qtd_veiculos", LongType(), True),
    StructField("nm_file", StringType(), True),
])

RFB_SCHEMA = StructType([
    StructField("cd_tom", StringType(), True),
    StructField("cd_municipio", StringType(), True),
    StructField("nm_municipio_tom", StringType(), True),
    StructField("nm_municipio", StringType(), True),
    StructField("sigla_uf", StringType(), True),
])


# ──────────────────────────────────────────────────────────────────
# bronze.frota_raw
# ──────────────────────────────────────────────────────────────────

@dp.table(
    name="frota_raw",
    comment="Dados brutos de frota por município e combustível — um registro por município × combustível × mês. Fonte: Detran/SENATRAN via Volume fleet_raw.",
    table_properties={
        "quality": "bronze",
        "pipelines.reset.allowed": "true",
    },
)
@dp.expect_or_drop("uf_nao_nula", "uf IS NOT NULL AND LENGTH(TRIM(uf)) > 0")
@dp.expect_or_drop("municipio_nao_nulo", "municipio IS NOT NULL AND LENGTH(TRIM(municipio)) > 0")
@dp.expect_or_drop("combustivel_nao_nulo", "combustivel_veiculo IS NOT NULL AND LENGTH(TRIM(combustivel_veiculo)) > 0")
@dp.expect_or_drop("qtd_nao_negativa", "qtd_veiculos >= 0")
@dp.expect("qtd_nao_nula", "qtd_veiculos IS NOT NULL")
def frota_raw():
    """
    Lê CSVs sem cabeçalho (header=false) do Volume via Auto Loader (streaming).
    Aplica o schema estrito com nomes normalizados diretamente na ingestão.
    Linhas que violam as expectations acima são descartadas automaticamente.
    """
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{FLEET_VOLUME_PATH}_schema/frota")
        .option("header", "false")
        .option("encoding", "UTF-8")
        .schema(FROTA_SCHEMA)
        .load(FLEET_VOLUME_PATH)
        # Normaliza textos
        .withColumn("uf", F.upper(F.trim(F.col("uf"))))
        .withColumn("municipio", F.upper(F.trim(F.col("municipio"))))
        .withColumn("combustivel_veiculo", F.upper(F.trim(F.col("combustivel_veiculo"))))
        # Metadados de ingestão
        .withColumn("dt_ingestao", F.current_timestamp())
        .withColumn("nm_arquivo_fonte", F.col("_metadata.file_name"))
    )


# ──────────────────────────────────────────────────────────────────
# bronze.frota_quarentena
# Linhas que violam expectations mas que queremos preservar para auditoria
# ──────────────────────────────────────────────────────────────────

@dp.table(
    name="frota_quarentena",
    comment="Linhas rejeitadas das validações de qualidade. Preservadas para auditoria e reprocessamento.",
    table_properties={"quality": "quarantine"},
)
@dp.expect_or_drop("uf_nao_nula_qr", "uf IS NOT NULL")
@dp.expect_or_drop("qtd_nao_negativa_qr", "qtd_veiculos >= 0 OR qtd_veiculos IS NULL")
def frota_quarentena():
    """
    Captura linhas com qtd_veiculos nula ou municipio/combustivel nulos
    que foram descartadas da tabela principal.
    """
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{FLEET_VOLUME_PATH}_schema/quarentena")
        .option("header", "false")
        .option("encoding", "UTF-8")
        .schema(FROTA_SCHEMA)
        .load(FLEET_VOLUME_PATH)
        .filter(
            F.col("municipio").isNull()
            | F.col("combustivel_veiculo").isNull()
            | (F.col("qtd_veiculos") < 0)
        )
        .withColumn("dt_ingestao", F.current_timestamp())
        .withColumn("nm_arquivo_fonte", F.col("_metadata.file_name"))
        .withColumn("motivo_rejeicao", F.concat_ws(", ",
            F.when(F.col("municipio").isNull(), F.lit("municipio_nulo")),
            F.when(F.col("combustivel_veiculo").isNull(), F.lit("combustivel_nulo")),
            F.when(F.col("qtd_veiculos") < 0, F.lit("qtd_negativa")),
        ))
    )


# ──────────────────────────────────────────────────────────────────
# bronze.frota_quality_metrics
# Métricas de qualidade mês-a-mês — batch, não streaming
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="frota_quality_metrics",
    comment=(
        "Métricas de qualidade por mês de referência: total de veículos, lotes (arquivos) "
        "que trazem o mesmo mês, variação percentual em relação ao mês anterior e flags de "
        "anomalia. Não bloqueia o pipeline — use para monitoramento e alertas externos."
    ),
    table_properties={"quality": "monitoring"},
)
def frota_quality_metrics():
    """
    Calcula, para cada mês de referência (derivado do nm_file):
    - total de veículos e de registros na bronze
    - qt_lotes: arquivos distintos com o mesmo mês (> 1 indica carga duplicada na bronze)
    - variação percentual vs. mês anterior, em ordem cronológica
    - flag se a variação excede ±5% e flag de mês faltante na sequência

    Usa READS do estado atual da tabela bronze.frota_raw (batch, não streaming).
    """
    mes_map_expr = F.create_map([F.lit(x) for pair in MES_MAP.items() for x in pair])

    monthly = (
        dp.read("frota_raw")
        .withColumn("nr_ano", F.regexp_extract("nm_file", r"(20\d{2})", 1).cast("int"))
        .withColumn("nr_mes", mes_map_expr[F.upper(F.regexp_extract("nm_file", MES_REGEX, 1))])
        .groupBy("nr_ano", "nr_mes")
        .agg(
            F.sum("qtd_veiculos").alias("total_veiculos"),
            F.count("*").alias("total_registros"),
            F.countDistinct("nm_arquivo_fonte").alias("qt_lotes"),
            F.concat_ws(", ", F.array_sort(F.collect_set("nm_arquivo_fonte"))).alias("nm_arquivos_fonte"),
        )
        .withColumn("id_data", F.col("nr_ano") * 100 + F.col("nr_mes"))
        .withColumn("dt_referencia", F.make_date("nr_ano", "nr_mes", F.lit(1)))
    )

    # Janela em ordem cronológica (não alfabética pelo nome do arquivo)
    from pyspark.sql.window import Window
    w = Window.orderBy("dt_referencia")

    return (
        monthly
        .withColumn("fl_periodo_duplicado", F.col("qt_lotes") > 1)
        .withColumn(
            "fl_mes_faltante",
            F.months_between("dt_referencia", F.lag("dt_referencia").over(w)) > 1,
        )
        .withColumn("total_veiculos_mes_anterior", F.lag("total_veiculos").over(w))
        .withColumn(
            "variacao_pct",
            F.when(
                F.col("total_veiculos_mes_anterior").isNotNull()
                & (F.col("total_veiculos_mes_anterior") != 0),
                F.round(
                    (F.col("total_veiculos") - F.col("total_veiculos_mes_anterior"))
                    / F.col("total_veiculos_mes_anterior") * 100,
                    2,
                ),
            )
        )
        .withColumn(
            "fl_anomalia_volume",
            F.abs(F.col("variacao_pct")) > F.lit(TOTAL_VOLUME_MAX_VARIATION_PCT),
        )
        .withColumn("dt_calculo", F.current_timestamp())
    )


# ──────────────────────────────────────────────────────────────────
# bronze.rfb_municipios_raw
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="rfb_municipios_raw",
    comment="Tabela de municípios da Receita Federal — código IBGE, nome e sigla UF. Ingerida com schema estrito.",
    table_properties={"quality": "bronze"},
)
@dp.expect_or_drop("codigo_ibge_valido", "cd_municipio RLIKE '^[0-9]+$'")
@dp.expect("nome_municipio_nao_nulo", "nm_municipio IS NOT NULL")
def rfb_municipios_raw():
    """
    Lê o CSV de municípios da Receita Federal do Volume rfb_municipios_raw com schema estrito.
    Descarta a linha de cabeçalho original via expectation (código numérico).
    """
    return (
        spark.read.format("csv")
        .option("header", "false")
        .option("sep", ";")
        .option("encoding", "ISO-8859-1")
        .schema(RFB_SCHEMA)
        .load(RFB_VOLUME_PATH)
        .withColumn("cd_municipio", F.trim(F.col("cd_municipio")))
        .withColumn("nm_municipio", F.upper(F.trim(F.col("nm_municipio"))))
        .withColumn("sigla_uf", F.upper(F.trim(F.col("sigla_uf"))))
        .withColumn("dt_ingestao", F.current_timestamp())
    )
