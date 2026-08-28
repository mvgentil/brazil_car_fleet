"""
Validação de schema — Pré-Ingestão.

Verifica apenas a estrutura dos arquivos .xlsx de frota antes do upload ao Volume.
Detecta colunas faltando, tipos errados e UFs inválidas.

Validações de qualidade de dados (variação mês-a-mês, distribuição por UF,
outliers de município) são feitas na camada raw → bronze do pipeline DLT.

Uso standalone:
    python src/validate.py --file data/raw/2026/arquivo.xlsx

Uso programático:
    from validate import validate_file
    results, has_failure = validate_file("arquivo.xlsx")
"""

import argparse
import io
import os
import sys
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

# Garante encoding UTF-8 no console Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ──────────────────────────────────────────────────────────────────
# Configuração e constantes
# ──────────────────────────────────────────────────────────────────

EXPECTED_COLUMNS = {"uf", "municipio", "combustivel_veiculo", "qtd_veiculos"}

VALID_UFS = {
    "ACRE", "ALAGOAS", "AMAPA", "AMAZONAS", "BAHIA", "CEARA",
    "DISTRITO FEDERAL", "ESPIRITO SANTO", "GOIAS", "MARANHAO",
    "MATO GROSSO", "MATO GROSSO DO SUL", "MINAS GERAIS", "PARA",
    "PARAIBA", "PARANA", "PERNAMBUCO", "PIAUI", "RIO DE JANEIRO",
    "RIO GRANDE DO NORTE", "RIO GRANDE DO SUL", "RONDONIA", "RORAIMA",
    "SANTA CATARINA", "SAO PAULO", "SERGIPE", "TOCANTINS",
    # Categorias especiais presentes nos dados brutos do Detran/Senatran
    "Não Identificado", "Não se Aplica", "Sem Informação",
}


def normalize_column_name(col: str) -> str:
    """Normaliza nome da coluna removendo acentos, caracteres especiais e espaços.
    Ex: 'Município' -> 'municipio', 'Qtd. Veículos' -> 'qtd_veiculos'
    """
    col_str = str(col)
    norm = unicodedata.normalize('NFKD', col_str).encode('ASCII', 'ignore').decode('utf-8')
    norm = norm.lower().strip().replace(' ', '_').replace('.', '')
    if norm == 'uf':
        return 'uf'
    if 'municipio' in norm:
        return 'municipio'
    if 'combustivel' in norm:
        return 'combustivel_veiculo'
    if 'qtd' in norm or 'veiculo' in norm:
        return 'qtd_veiculos'
    return norm


# ──────────────────────────────────────────────────────────────────
# Tipos de resultado
# ──────────────────────────────────────────────────────────────────

class Status(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class ValidationResult:
    """Resultado de uma validação individual."""
    check_name: str
    status: Status
    message: str
    details: list[str] = field(default_factory=list)

    @property
    def icon(self) -> str:
        return {Status.PASS: "✅", Status.WARN: "⚠️", Status.FAIL: "❌"}[self.status]


# ──────────────────────────────────────────────────────────────────
# Validação de schema
# ──────────────────────────────────────────────────────────────────

def _check_schema(df: pd.DataFrame) -> ValidationResult:
    """Valida estrutura do DataFrame: colunas obrigatórias, tipos e nulos."""
    issues: list[str] = []

    # Normaliza colunas do DataFrame
    df.columns = [normalize_column_name(c) for c in df.columns]

    # Colunas presentes
    missing_cols = EXPECTED_COLUMNS - set(df.columns)
    if missing_cols:
        return ValidationResult(
            check_name="Schema",
            status=Status.FAIL,
            message=f"Colunas obrigatórias ausentes: {missing_cols}",
        )

    # Nulos em colunas obrigatórias
    for col in EXPECTED_COLUMNS:
        null_count = df[col].isna().sum()
        if null_count > 0:
            issues.append(f"  · {col}: {null_count:,} valores nulos")

    # Qtd. Veículos deve ser numérico e >= 0
    qty_col = df["qtd_veiculos"]
    if not pd.api.types.is_numeric_dtype(qty_col):
        issues.append("  · 'qtd_veiculos' não é numérico")
    else:
        negative_count = (qty_col < 0).sum()
        if negative_count > 0:
            issues.append(f"  · {negative_count:,} valores negativos em 'qtd_veiculos'")

    # UFs válidas
    ufs_no_arquivo = set(df["uf"].dropna().unique())
    ufs_invalidas = ufs_no_arquivo - VALID_UFS
    if ufs_invalidas:
        issues.append(f"  · UFs desconhecidas: {ufs_invalidas}")

    if issues:
        has_fail = any("não é numérico" in i or "ausentes:" in i for i in issues)
        return ValidationResult(
            check_name="Schema",
            status=Status.FAIL if has_fail else Status.WARN,
            message=f"{len(issues)} problema(s) estrutural(is) encontrado(s)",
            details=issues,
        )

    return ValidationResult(
        check_name="Schema",
        status=Status.PASS,
        message=(
            f"Estrutura OK — {len(df):,} linhas, "
            f"{len(ufs_no_arquivo)} UFs, "
            f"{df['qtd_veiculos'].sum():,.0f} veículos total"
        ),
    )


# ──────────────────────────────────────────────────────────────────
# Orquestração e relatório
# ──────────────────────────────────────────────────────────────────

def validate_file(file_path: str) -> tuple[list[ValidationResult], bool]:
    """Executa validação de schema em um arquivo xlsx.

    Args:
        file_path: Caminho para o arquivo .xlsx a validar.

    Returns:
        Tuple de (lista de resultados, has_failure).
    """
    results: list[ValidationResult] = []

    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        results.append(ValidationResult(
            check_name="Leitura do Arquivo",
            status=Status.FAIL,
            message=f"Erro ao ler {file_path}: {e}",
        ))
        return results, True

    results.append(_check_schema(df))
    has_failure = any(r.status == Status.FAIL for r in results)
    return results, has_failure


def print_report(results: list[ValidationResult], file_name: str = "") -> None:
    """Exibe o relatório de validação formatado no console."""
    print(f"\n{'─' * 60}")
    print(f"🔍 Validação de Schema{f' — {file_name}' if file_name else ''}")
    print(f"{'─' * 60}")

    for result in results:
        print(f"\n{result.icon} [{result.check_name}] {result.message}")
        for detail in result.details:
            print(detail)

    counts = {s: sum(1 for r in results if r.status == s) for s in Status}
    print(f"\n{'─' * 60}")
    print(
        f"📊 Resumo: {counts[Status.PASS]} pass · "
        f"{counts[Status.WARN]} warn · {counts[Status.FAIL]} fail"
    )

    if counts[Status.FAIL] > 0:
        print("🚫 SCHEMA INVÁLIDO — upload bloqueado")
    elif counts[Status.WARN] > 0:
        print("⚠️  SCHEMA COM AVISOS — upload prosseguirá (verifique os detalhes)")
    else:
        print("✅ SCHEMA APROVADO — arquivo pronto para upload")

    print(f"{'─' * 60}\n")


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Valida schema de arquivos .xlsx de frota antes do upload ao Volume"
    )
    parser.add_argument("--file", required=True, help="Arquivo .xlsx a validar")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"❌ Arquivo não encontrado: {args.file}")
        sys.exit(1)

    results, has_failure = validate_file(args.file)
    print_report(results, os.path.basename(args.file))

    sys.exit(1 if has_failure else 0)


if __name__ == "__main__":
    main()
