import datetime

import pandas as pd
import pytest

import extract_fleet
from extract_fleet import get_target_previous_period, parse_period_from_filename
from load import drop_total_rows
from validate import normalize_column_name


def test_drop_total_rows_remove_rodape_de_total():
    df = pd.DataFrame({
        "uf": ["SAO PAULO", None, None],
        "municipio": ["SAO PAULO", None, "X"],
        "combustivel_veiculo": ["GASOLINA", None, None],
        "qtd_veiculos": [10, 135907590, 1],
    })
    out = drop_total_rows(df)
    assert out["qtd_veiculos"].tolist() == [10, 1]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("UF", "uf"),
        ("Município", "municipio"),
        ("Combustível Veículo", "combustivel_veiculo"),
        ("Qtd. Veículos", "qtd_veiculos"),
    ],
)
def test_normalize_column_name(raw, expected):
    assert normalize_column_name(raw) == expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("D_Frota_por_UF_Municipio_COMBUSTIVEL_Abril_2025.xlsx", (2025, 4)),
        ("D_Frota_por_UF_Municipio_COMBUSTIVEL_Maro_2024.xlsx", (2024, 3)),
        ("D_Frota_por_UF_Municipio_COMBUSTIVEL_Março_2026.xlsx", (2026, 3)),
        ("D_Frota_por_UF_Municipio_COMBUSTIVEL_Dezembro_20241.xlsx", (2024, 12)),
        ("copy2_of_D_Frota_por_UF_Municipio_COMBUSTIVEL_Fevereiro_2025.xlsx", (2025, 2)),
        ("d_frota_por_uf_municipio_combustivel_agosto_2025-1.xlsx", (2025, 8)),
        ("/tmp/data/raw/2026/D_Frota_por_UF_Municipio_COMBUSTIVEL_setembro_2026.xlsx", (2026, 9)),
        ("frota_veiculos_2026.csv", None),
        ("D_Frota_Abril.xlsx", None),
    ],
)
def test_parse_period_from_filename(filename, expected):
    assert parse_period_from_filename(filename) == expected


@pytest.mark.parametrize(
    ("today", "months_back", "expected"),
    [
        (datetime.date(2026, 8, 15), 1, (2026, 7)),
        (datetime.date(2027, 1, 15), 1, (2026, 12)),
        (datetime.date(2027, 1, 15), 2, (2026, 11)),
        (datetime.date(2026, 3, 31), 2, (2026, 1)),
    ],
)
def test_get_target_previous_period(monkeypatch, today, months_back, expected):
    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(extract_fleet.datetime, "date", FakeDate)
    assert get_target_previous_period(months_back) == expected
