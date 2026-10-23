"""
Funções e constantes compartilhadas pelas camadas bronze, silver e gold do pipeline de frota.

Este módulo fica no root_path do pipeline (importável pelos arquivos de transformations/)
e não define datasets.
"""

import pandas as pd
from pyspark.sql import Column, SparkSession
from pyspark.sql import functions as F

# ──────────────────────────────────────────────────────────────────
# Regras de validade das linhas de frota (bronze → silver / quarentena)
# ──────────────────────────────────────────────────────────────────

REGRAS_FROTA = {
    "uf_nao_nula": "uf IS NOT NULL AND LENGTH(TRIM(uf)) > 0",
    "municipio_nao_nulo": "municipio IS NOT NULL AND LENGTH(TRIM(municipio)) > 0",
    "combustivel_nao_nulo": "combustivel_veiculo IS NOT NULL AND LENGTH(TRIM(combustivel_veiculo)) > 0",
    "qtd_valida": "qtd_veiculos IS NOT NULL AND qtd_veiculos >= 0",
}


def regra_ok(regra: str) -> Column:
    """Avalia a regra tratando NULL como violação (NOT NULL seria NULL e a linha sumiria dos dois lados)."""
    return F.coalesce(F.expr(f"({regra})"), F.lit(False))


def linha_valida() -> Column:
    cond = F.lit(True)
    for regra in REGRAS_FROTA.values():
        cond = cond & regra_ok(regra)
    return cond


def motivo_rejeicao() -> Column:
    return F.concat_ws(
        ", ",
        *[F.when(~regra_ok(regra), F.lit(nome)) for nome, regra in REGRAS_FROTA.items()],
    )


# ──────────────────────────────────────────────────────────────────
# Normalização de texto
# ──────────────────────────────────────────────────────────────────

def sem_acento(col_expr: Column) -> Column:
    """Remove acentos, converte para maiúsculas e colapsa espaços. Mantém pontuação."""
    unaccented = F.translate(
        col_expr,
        "ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑÝáàâãäéèêëíìîïóòôõöúùûüçñý",
        "AAAAAEEEEIIIIOOOOOUUUUCNYaaaaaeeeeiiiiooooouuuucny",
    )
    return F.regexp_replace(F.upper(F.trim(unaccented)), r"\s+", " ")


def normalize_text_col(col_expr: Column) -> Column:
    """
    Remove acentos, caracteres especiais (hífens, apóstrofos, pontos, barras),
    converte para maiúsculas e remove espaços repetidos. Usada para casar nomes de município.
    """
    cleaned = F.regexp_replace(sem_acento(col_expr), r"[-'./]", " ")
    return F.trim(F.regexp_replace(cleaned, r"\s+", " "))


# ──────────────────────────────────────────────────────────────────
# Mês de referência
# ──────────────────────────────────────────────────────────────────

# Aceita "Marco", "Março" e "Maro" (ç perdido no encoding do nome do arquivo)
MES_REGEX = r"(?i)(janeiro|fevereiro|mar(?:co|ço|o)|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"

MES_MAP = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "MARO": 3, "ABRIL": 4,
    "MAIO": 5, "JUNHO": 6, "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9,
    "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
}

MES_NOME_MAP = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def _map_expr(mapping: dict) -> Column:
    return F.create_map([F.lit(x) for pair in mapping.items() for x in pair])


def nm_mes(nr_mes: Column) -> Column:
    return _map_expr(MES_NOME_MAP)[nr_mes]


def com_periodo(df):
    """
    Adiciona nr_ano, nr_mes, id_data (yyyymm) e dt_referencia.
    Prioriza as colunas explícitas gravadas pela ingestão; para arquivos antigos, extrai do nm_file.
    """
    mes_txt = sem_acento(F.regexp_extract(F.col("nm_file"), MES_REGEX, 1))
    return (
        df
        .withColumn(
            "nr_ano",
            F.coalesce(F.col("nr_ano"), F.regexp_extract(F.col("nm_file"), r"(20\d{2})", 1).cast("int")),
        )
        .withColumn("nr_mes", F.coalesce(F.col("nr_mes"), _map_expr(MES_MAP)[mes_txt]))
        .withColumn("id_data", F.col("nr_ano") * 100 + F.col("nr_mes"))
        .withColumn("dt_referencia", F.make_date(F.col("nr_ano"), F.col("nr_mes"), F.lit(1)))
    )


def id_periodo(dt: Column) -> Column:
    return F.year(dt) * 100 + F.month(dt)


# ──────────────────────────────────────────────────────────────────
# Seeds (CSVs versionados em databricks/src/seeds, sincronizados pelo bundle)
# ──────────────────────────────────────────────────────────────────

def read_seed(seeds_path: str, nome: str):
    spark = SparkSession.builder.getOrCreate()
    pdf = pd.read_csv(f"{seeds_path}/{nome}", dtype=str, keep_default_na=False, encoding="utf-8")
    return spark.createDataFrame(pdf)
