"""
raw → bronze: Frota de Veículos & Municípios RFB

- bronze.frota_raw — todas as linhas dos CSVs do Volume fleet_raw (Auto Loader), sem descarte;
  as regras de validade são monitoradas via expectations e aplicadas na silver
- bronze.frota_quarentena — linhas que violam as regras, com o motivo da rejeição
- bronze.rfb_municipios_raw — cadastro de municípios da Receita Federal (código IBGE)
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType

from frota_common import REGRAS_FROTA, linha_valida, motivo_rejeicao

CATALOG = spark.conf.get("catalog")
RAW_SCHEMA = spark.conf.get("raw_schema")
FLEET_VOLUME = spark.conf.get("fleet_volume")
RFB_VOLUME = spark.conf.get("rfb_volume")

FLEET_VOLUME_PATH = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/{FLEET_VOLUME}/"
RFB_VOLUME_PATH = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/{RFB_VOLUME}/"

# CSVs sem cabeçalho, ordem fixa. nr_ano/nr_mes são opcionais: nos arquivos antigos (5 colunas)
# chegam nulos e o período é extraído do nm_file na silver.
FROTA_SCHEMA = StructType([
    StructField("uf", StringType(), True),
    StructField("municipio", StringType(), True),
    StructField("combustivel_veiculo", StringType(), True),
    StructField("qtd_veiculos", LongType(), True),
    StructField("nm_file", StringType(), True),
    StructField("nr_ano", IntegerType(), True),
    StructField("nr_mes", IntegerType(), True),
    StructField("_rescued_data", StringType(), True),
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
    comment=(
        "Dados brutos de frota por município e combustível (SENATRAN), uma linha por "
        "município × combustível × mês de cada arquivo carregado. Append-only: um mesmo mês "
        "pode aparecer em mais de um arquivo (lote); a silver usa apenas o lote mais recente."
    ),
    table_properties={
        "quality": "bronze",
        "pipelines.reset.allowed": "true",
    },
)
@dp.expect_all(REGRAS_FROTA)
def frota_raw():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        # Reenvio de um arquivo com o mesmo nome (correção de um mês) volta a ser processado
        .option("cloudFiles.allowOverwrites", "true")
        .option("header", "false")
        .option("encoding", "UTF-8")
        .schema(FROTA_SCHEMA)
        .load(FLEET_VOLUME_PATH)
        .withColumn("uf", F.upper(F.trim(F.col("uf"))))
        .withColumn("municipio", F.upper(F.trim(F.col("municipio"))))
        .withColumn("combustivel_veiculo", F.upper(F.trim(F.col("combustivel_veiculo"))))
        # Metadados do lote: arquivo de origem + versão (data de modificação) + momento da carga
        .withColumn("nm_arquivo_fonte", F.col("_metadata.file_name"))
        .withColumn("dt_arquivo_modificado", F.col("_metadata.file_modification_time"))
        .withColumn("dt_ingestao", F.current_timestamp())
    )


# ──────────────────────────────────────────────────────────────────
# bronze.frota_quarentena
# ──────────────────────────────────────────────────────────────────

@dp.table(
    name="frota_quarentena",
    comment="Linhas da frota_raw que violam as regras de validade. Preservadas para auditoria e reprocessamento.",
    table_properties={"quality": "quarantine"},
)
def frota_quarentena():
    return (
        spark.readStream.table("frota_raw")
        .filter(~linha_valida())
        .withColumn("motivo_rejeicao", motivo_rejeicao())
    )


# ──────────────────────────────────────────────────────────────────
# bronze.rfb_municipios_raw
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="rfb_municipios_raw",
    comment="Tabela de municípios da Receita Federal — código TOM, código IBGE, nomes e sigla UF.",
    table_properties={"quality": "bronze"},
)
@dp.expect_or_drop("codigo_ibge_valido", "cd_municipio RLIKE '^[0-9]+$'")
@dp.expect("nome_municipio_nao_nulo", "nm_municipio IS NOT NULL")
def rfb_municipios_raw():
    """A linha de cabeçalho original é descartada pela expectation de código numérico."""
    return (
        spark.read.format("csv")
        .option("header", "false")
        .option("sep", ";")
        .option("encoding", "ISO-8859-1")
        .schema(RFB_SCHEMA)
        .load(RFB_VOLUME_PATH)
        .withColumn("cd_municipio", F.trim(F.col("cd_municipio")))
        .withColumn("nm_municipio", F.upper(F.trim(F.col("nm_municipio"))))
        .withColumn("nm_municipio_tom", F.upper(F.trim(F.col("nm_municipio_tom"))))
        .withColumn("sigla_uf", F.upper(F.trim(F.col("sigla_uf"))))
        .withColumn("dt_ingestao", F.current_timestamp())
    )
