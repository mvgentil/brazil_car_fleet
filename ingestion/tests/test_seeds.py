"""Consistência dos seeds usados pelo pipeline (databricks/src/seeds)."""

from pathlib import Path

import pandas as pd
import pytest

SEEDS = Path(__file__).resolve().parents[2] / "databricks" / "src" / "seeds"

GRUPOS_VALIDOS = {"Elétrico Puro", "Híbrido", "Flex", "Combustão Fóssil", "Combustão Renovável", "Não Identificado"}
GRUPOS_ELETRIFICADOS = {"Elétrico Puro", "Híbrido"}


def read_seed(nome: str) -> pd.DataFrame:
    return pd.read_csv(SEEDS / nome, dtype=str, keep_default_na=False, encoding="utf-8")


@pytest.fixture(scope="module")
def ufs() -> set[str]:
    return set(read_seed("uf_regiao.csv")["sigla_uf"])


def test_uf_regiao_tem_27_ufs(ufs):
    assert len(ufs) == 27


def test_combustivel_grupo():
    df = read_seed("combustivel_grupo.csv")
    assert df["nm_combustivel_norm"].is_unique
    assert set(df["nm_grupo"]) <= GRUPOS_VALIDOS
    # Chaves já normalizadas: maiúsculas, sem acento e sem espaços nas pontas
    assert (df["nm_combustivel_norm"] == df["nm_combustivel_norm"].str.strip().str.upper()).all()
    assert df["nm_combustivel_norm"].str.isascii().all()
    eletrificado = df["fl_eletrificado"] == "true"
    assert (eletrificado == df["nm_grupo"].isin(GRUPOS_ELETRIFICADOS)).all()


def test_municipio_correcoes(ufs):
    df = read_seed("municipio_correcoes.csv")
    assert set(df["sigla_uf"]) <= ufs
    assert not df.duplicated(["sigla_uf", "nm_senatran"]).any()


def test_municipio_complemento(ufs):
    df = read_seed("municipio_complemento.csv")
    assert set(df["sigla_uf"]) <= ufs
    assert df["cd_ibge_municipio"].str.fullmatch(r"\d{7}").all()
    assert df["cd_ibge_municipio"].is_unique
