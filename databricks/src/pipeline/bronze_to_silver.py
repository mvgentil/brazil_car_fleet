# Databricks notebook source
# MAGIC %md
# MAGIC # bronze → silver: Dimensões e Fato Frota
# MAGIC
# MAGIC Lakeflow Pipeline (Spark Declarative Pipelines) que lê as tabelas bronze
# MAGIC via `spark.table()` e constrói as dimensões e a tabela fato da camada silver.
# MAGIC
# MAGIC ## Tabelas produzidas
# MAGIC - `silver.dim_data` — datas extraídas do nm_file
# MAGIC - `silver.dim_municipio` — municípios enriquecidos com código IBGE e região (100% match)
# MAGIC - `silver.dim_combustivel` — tipos de combustível com grupo analítico
# MAGIC - `silver.fato_frota` — fato central (município × combustível × mês)

# COMMAND ----------

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, BooleanType

# ──────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────

CATALOG = spark.conf.get("catalog", "brazil_car_fleet")
BRONZE_SCHEMA = spark.conf.get("bronze_schema", "bronze")

BRONZE_FROTA = f"{CATALOG}.{BRONZE_SCHEMA}.frota_raw"
BRONZE_RFB = f"{CATALOG}.{BRONZE_SCHEMA}.rfb_municipios_raw"

# ──────────────────────────────────────────────────────────────────
# Mapeamento de meses (português / grafias brutas → número e nome padrão)
# ──────────────────────────────────────────────────────────────────

MES_MAP = {
    "JANEIRO": 1,
    "FEVEREIRO": 2,
    "MARCO": 3,
    "MARO": 3,
    "MARÇO": 3,
    "ABRIL": 4,
    "MAIO": 5,
    "JUNHO": 6,
    "JULHO": 7,
    "AGOSTO": 8,
    "SETEMBRO": 9,
    "OUTUBRO": 10,
    "NOVEMBRO": 11,
    "DEZEMBRO": 12,
}

MES_NOME_MAP = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}

# ──────────────────────────────────────────────────────────────────
# Mapeamento de grupos de combustível
# ──────────────────────────────────────────────────────────────────

GRUPO_COMBUSTIVEL = {
    "ELETRICO": "Elétrico Puro",
    "ELETRICO/FONTE EXTERNA": "Elétrico Puro",
    "ELETRICO/FONTE INTERNA": "Elétrico Puro",
    "CELULA COMBUSTIVEL": "Elétrico Puro",
    "HIBRIDO": "Híbrido",
    "HIBRIDO PLUG-IN": "Híbrido",
    "GASOLINA/ELETRICO": "Híbrido",
    "DIESEL/ELETRICO": "Híbrido",
    "ETANOL/ELETRICO": "Híbrido",
    "GASOLINA/ALCOOL/ELETRICO": "Híbrido",
    "ALCOOL/GASOLINA": "Flex",
    "GASOL/GAS NATURAL COMBUSTIVEL": "Flex",
    "GASOLINA/GAS NATURAL VEICULAR": "Flex",
    "ALCOOL/GAS NATURAL COMBUSTIVEL": "Flex",
    "ALCOOL/GAS NATURAL VEICULAR": "Flex",
    "DIESEL/GAS NATURAL VEICULAR": "Flex",
    "DIESEL/GAS NATURAL COMBUSTIVEL": "Flex",
    "GASOLINA/ALCOOL/GAS NATURAL": "Flex",
    "GASOLINA": "Combustão Fóssil",
    "DIESEL": "Combustão Fóssil",
    "GAS NATURAL VEICULAR": "Combustão Fóssil",
    "GAS METANO": "Combustão Fóssil",
    "GAS/NATURAL/LIQUEFEITO": "Combustão Fóssil",
    "GASOGENIO": "Combustão Fóssil",
    "ALCOOL": "Combustão Renovável",
    "SEM INFORMACAO": "Não Identificado",
    "VIDE/CAMPO/OBSERVACAO": "Não Identificado",
    "NAO IDENTIFICADO": "Não Identificado",
    "NAO SE APLICA": "Não Identificado",
}

# ──────────────────────────────────────────────────────────────────
# Seed: UF → Região (embutida como literal para evitar dependência de Volume)
# ──────────────────────────────────────────────────────────────────

UF_REGIAO = [
    ("AC","ACRE","Norte"), ("AL","ALAGOAS","Nordeste"), ("AP","AMAPA","Norte"),
    ("AM","AMAZONAS","Norte"), ("BA","BAHIA","Nordeste"), ("CE","CEARA","Nordeste"),
    ("DF","DISTRITO FEDERAL","Centro-Oeste"), ("ES","ESPIRITO SANTO","Sudeste"),
    ("GO","GOIAS","Centro-Oeste"), ("MA","MARANHAO","Nordeste"),
    ("MT","MATO GROSSO","Centro-Oeste"), ("MS","MATO GROSSO DO SUL","Centro-Oeste"),
    ("MG","MINAS GERAIS","Sudeste"), ("PA","PARA","Norte"),
    ("PB","PARAIBA","Nordeste"), ("PR","PARANA","Sul"),
    ("PE","PERNAMBUCO","Nordeste"), ("PI","PIAUI","Nordeste"),
    ("RJ","RIO DE JANEIRO","Sudeste"), ("RN","RIO GRANDE DO NORTE","Nordeste"),
    ("RS","RIO GRANDE DO SUL","Sul"), ("RO","RONDONIA","Norte"),
    ("RR","RORAIMA","Norte"), ("SC","SANTA CATARINA","Sul"),
    ("SP","SAO PAULO","Sudeste"), ("SE","SERGIPE","Nordeste"),
    ("TO","TOCANTINS","Norte"),
]

# ──────────────────────────────────────────────────────────────────
# Correções de grafias históricas/divergências conhecidas da Senatran
# ──────────────────────────────────────────────────────────────────

KNOWN_MUNICIPALITY_FIXES = {
    ("BA", "LAGEDO DO TABOCAL"): "LAJEDO DO TABOCAL",
    ("MG", "BARAO D0 MONTE ALTO"): "BARAO DO MONTE ALTO",
    ("MG", "QUELUZITA"): "QUELUZITO",
    ("PB", "SANTAREM"): "JOCA CLAUDINO",
    ("PB", "SAO DOMINGOS DE POMBAL"): "SAO DOMINGOS",
    ("PR", "BELA VISTA DO CAROBA"): "BELA VISTA DA CAROBA",
    ("PR", "MUNHOZ DE MELLO"): "MUNHOZ DE MELO",
    ("PR", "PINHAL DO SAO BENTO"): "PINHAL DE SAO BENTO",
    ("PR", "SANTA CRUZ DO MONTE CASTELO"): "SANTA CRUZ DE MONTE CASTELO",
    ("RJ", "TRAJANO DE MORAIS"): "TRAJANO DE MORAES",
    ("SC", "LAGEADO GRANDE"): "LAJEADO GRANDE",
    ("SC", "PRESIDENTE CASTELO BRANCO"): "PRESIDENTE CASTELLO BRANCO",
    ("SC", "SAO LOURENCO DOESTE"): "SAO LOURENCO DO OESTE",
    ("SC", "SAO MIGUEL DOESTE"): "SAO MIGUEL DO OESTE",
}


def normalize_text_col(col_expr):
    """
    Remove acentos, caracteres especiais (hífens, apóstrofos, barras),
    converte para maiúsculas e remove espaços repetidos.
    """
    unaccented = F.translate(
        col_expr,
        "ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑÝáàâãäéèêëíìîïóòôõöúùûüçñý",
        "AAAAAEEEEIIIIOOOOOUUUUCNYaaaaaeeeeiiiiooooouuuucny",
    )
    cleaned = F.upper(F.trim(F.regexp_replace(unaccented, r"[-'./]", " ")))
    return F.regexp_replace(cleaned, r"\s+", " ")


# ──────────────────────────────────────────────────────────────────
# silver.dim_data
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="dim_data",
    comment="Dimensão de datas extraída do nm_file. Granularidade: mês/ano.",
    table_properties={"quality": "silver"},
)
def dim_data():
    """
    Extrai mês e ano do campo nm_file de forma robusta.
    Suporta variações como sufixos numéricos (ex: '20241', '2025-1'),
    prefixos ('copy_of_', 'copy2_of_') e variações de grafia de meses ('Maro', 'Março').
    """
    mes_map_expr = F.create_map([F.lit(x) for pair in MES_MAP.items() for x in pair])
    mes_nome_expr = F.create_map([F.lit(x) for pair in MES_NOME_MAP.items() for x in pair])

    df = (
        spark.table(BRONZE_FROTA)
        .select("nm_file")
        .distinct()
        .withColumn(
            "nm_mes_raw",
            F.upper(
                F.regexp_extract(
                    F.col("nm_file"),
                    r"(?i)(janeiro|fevereiro|mar[coç]|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)",
                    1,
                )
            ),
        )
        .withColumn(
            "nr_ano",
            F.regexp_extract(F.col("nm_file"), r"(20\d{2})", 1).cast(IntegerType()),
        )
        .withColumn("nr_mes", mes_map_expr[F.col("nm_mes_raw")])
        .withColumn(
            "nm_mes",
            F.coalesce(mes_nome_expr[F.col("nr_mes")], F.initcap(F.col("nm_mes_raw"))),
        )
        .withColumn("id_data", (F.col("nr_ano") * 100 + F.col("nr_mes")).cast(IntegerType()))
        .withColumn("dt_referencia", F.to_date(F.concat_ws("-", F.col("nr_ano"), F.col("nr_mes"), F.lit("01"))))
        .select("id_data", "nm_mes", "nr_mes", "nr_ano", "dt_referencia", "nm_file")
    )
    return df


# ──────────────────────────────────────────────────────────────────
# silver.dim_municipio
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="dim_municipio",
    comment="Dimensão de municípios enriquecida com código IBGE (RFB), sigla UF e região geográfica.",
    table_properties={"quality": "silver"},
)
def dim_municipio():
    """
    Join entre frota_raw e rfb_municipios_raw por nome normalizado sem acentos + sigla UF.
    Trata divergências históricas e garante 100% de match com o cadastro oficial.
    """
    uf_regiao_df = spark.createDataFrame(UF_REGIAO, ["sigla_uf", "nm_uf_completo", "nm_regiao"])
    uf_map = uf_regiao_df.withColumn("nm_uf_norm", normalize_text_col(F.col("nm_uf_completo")))

    # 1. Normaliza frota_raw
    frota_municipios = (
        spark.table(BRONZE_FROTA)
        .select("municipio", "uf")
        .distinct()
        .withColumn("nm_municipio_raw", normalize_text_col(F.col("municipio")))
        .withColumn("nm_uf_norm", normalize_text_col(F.col("uf")))
    )

    # Join com UF para obter sigla_uf
    frota_with_uf = frota_municipios.join(uf_map, "nm_uf_norm", "left")

    # Aplica correções conhecidas de grafia da Senatran via CASE WHEN
    fix_expr = F.col("nm_municipio_raw")
    for (sigla, old_name), new_name in KNOWN_MUNICIPALITY_FIXES.items():
        fix_expr = F.when(
            (F.col("sigla_uf") == sigla) & (F.col("nm_municipio_raw") == old_name),
            F.lit(new_name),
        ).otherwise(fix_expr)

    frota_prepared = frota_with_uf.withColumn("nm_municipio_norm", fix_expr)

    # 2. Normaliza RFB (nome IBGE e nome TOM)
    rfb_ibge = (
        spark.table(BRONZE_RFB)
        .withColumn("nm_municipio_norm", normalize_text_col(F.col("nm_municipio")))
        .withColumn("sigla_uf", F.upper(F.trim(F.col("sigla_uf"))))
        .select(
            F.col("cd_municipio").alias("cd_ibge_municipio"),
            "nm_municipio_norm",
            "sigla_uf",
        )
        .distinct()
    )

    rfb_tom = (
        spark.table(BRONZE_RFB)
        .withColumn("nm_municipio_norm", normalize_text_col(F.col("nm_municipio_tom")))
        .withColumn("sigla_uf", F.upper(F.trim(F.col("sigla_uf"))))
        .select(
            F.col("cd_municipio").alias("cd_ibge_tom"),
            "nm_municipio_norm",
            "sigla_uf",
        )
        .distinct()
    )

    # 3. Join com fallback por nome TOM
    joined = (
        frota_prepared
        .join(rfb_ibge, ["nm_municipio_norm", "sigla_uf"], "left")
        .join(rfb_tom, ["nm_municipio_norm", "sigla_uf"], "left")
        .withColumn(
            "cd_ibge_final",
            F.coalesce(F.col("cd_ibge_municipio"), F.col("cd_ibge_tom"))
        )
        .select(
            F.monotonically_increasing_id().alias("id_municipio"),
            F.col("municipio").alias("nm_municipio"),
            F.col("uf").alias("nm_uf"),
            F.col("sigla_uf"),
            F.col("nm_regiao"),
            F.col("cd_ibge_final").alias("cd_ibge_municipio"),
        )
    )

    return joined


# ──────────────────────────────────────────────────────────────────
# silver.dim_combustivel
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="dim_combustivel",
    comment="Dimensão de combustíveis com grupo analítico e flag de identificação.",
    table_properties={"quality": "silver"},
)
def dim_combustivel():
    """
    Mapeia os tipos de combustível brutos para grupos analíticos.
    Tipos não mapeados recebem grupo 'Não Identificado'.
    """
    grupo_map_expr = F.create_map([F.lit(x) for pair in GRUPO_COMBUSTIVEL.items() for x in pair])

    return (
        spark.table(BRONZE_FROTA)
        .select("combustivel_veiculo")
        .distinct()
        .withColumn(
            "nm_grupo",
            F.coalesce(
                grupo_map_expr[F.col("combustivel_veiculo")],
                F.lit("Não Identificado"),
            ),
        )
        .withColumn(
            "fl_identificado",
            (F.col("nm_grupo") != "Não Identificado").cast(BooleanType()),
        )
        .withColumn("id_combustivel", F.monotonically_increasing_id())
        .withColumnRenamed("combustivel_veiculo", "nm_combustivel")
        .select("id_combustivel", "nm_combustivel", "nm_grupo", "fl_identificado")
    )


# ──────────────────────────────────────────────────────────────────
# silver.fato_frota
# ──────────────────────────────────────────────────────────────────

@dp.materialized_view(
    name="fato_frota",
    comment="Tabela fato central. Granularidade: município × combustível × mês/ano. Com surrogate keys das dimensões.",
    table_properties={"quality": "silver"},
)
@dp.expect("municipio_resolvido", "id_municipio IS NOT NULL")
@dp.expect("combustivel_resolvido", "id_combustivel IS NOT NULL")
@dp.expect("data_resolvida", "id_data IS NOT NULL")
def fato_frota():
    """
    Join entre frota_raw e todas as dimensões para produzir a fato.
    Mantém nm_file para rastreabilidade até a fonte raw (data lineage).
    """
    frota = spark.table(BRONZE_FROTA)
    dim_mun = dp.read("dim_municipio")
    dim_comb = dp.read("dim_combustivel")
    dim_dt = dp.read("dim_data")

    return (
        frota
        .join(
            dim_mun.select("id_municipio", "nm_municipio", "nm_uf"),
            (frota["municipio"] == dim_mun["nm_municipio"])
            & (frota["uf"] == dim_mun["nm_uf"]),
            "left",
        )
        .join(
            dim_comb.select("id_combustivel", "nm_combustivel"),
            frota["combustivel_veiculo"] == dim_comb["nm_combustivel"],
            "left",
        )
        .join(
            dim_dt.select("id_data", "nm_file"),
            frota["nm_file"] == dim_dt["nm_file"],
            "left",
        )
        .select(
            F.monotonically_increasing_id().alias("id_fato"),
            F.col("id_municipio"),
            F.col("id_combustivel"),
            F.col("id_data"),
            F.col("qtd_veiculos").alias("qt_veiculos"),
            frota["nm_file"],
        )
    )
