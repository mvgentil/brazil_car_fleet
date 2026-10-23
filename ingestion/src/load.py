"""
Carga de arquivos de frota para o Volume raw do Databricks.

Cada arquivo .xlsx é:
  1. Baixado do site da Senatran (exceto no modo --file)
  2. Validado (schema) — falha individualmente, não bloqueia os demais
  3. Enriquecido com nm_file (rastreabilidade) e nr_ano/nr_mes (mês de referência)
  4. Serializado para CSV em memória
  5. Carregado no Databricks Volume via SDK com nome canônico por mês

Destino no Volume:
  /Volumes/{catalog}/raw_data/fleet_raw/frota_{ano}_{mes:02d}.csv

Um mês já presente no Volume é pulado (use --force para recarregar). Recarregar
substitui o arquivo e o pipeline passa a usar a versão mais recente daquele mês.

Uso:
    python src/load.py --previous-month        # Último mês publicado (tenta M-1 e M-2) — agendamento
    python src/load.py --year 2026 --month 7  # Um mês específico
    python src/load.py --year 2026            # Todos os meses publicados de 2026 (backfill)
    python src/load.py --file arquivo.xlsx    # Arquivo local avulso (mês extraído do nome)

Configuração: ver src/databricks_client.py
"""

import argparse
import datetime
import io
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


import pandas as pd
from databricks.sdk import WorkspaceClient

from databricks_client import file_exists, get_databricks_client, volume_path
from extract_fleet import MONTH_NAMES, extract_month, get_target_previous_period, parse_period_from_filename
from validate import normalize_column_name, print_report, validate_file

# ──────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────

FLEET_VOLUME = os.getenv("DATABRICKS_FLEET_VOLUME", "fleet_raw")
VOLUME_BASE_PATH = volume_path(FLEET_VOLUME)
COLUMN_ORDER = ["uf", "municipio", "combustivel_veiculo", "qtd_veiculos", "nm_file", "nr_ano", "nr_mes"]

# Quantos meses para trás o modo --previous-month procura (a Senatran publica com atraso)
PREVIOUS_MONTH_LOOKBACK = 2


def canonical_volume_path(year: int, month: int) -> str:
    return f"{VOLUME_BASE_PATH}/frota_{year}_{month:02d}.csv"


def new_result() -> dict[str, list[str]]:
    return {"uploaded": [], "skipped": [], "failed": []}


# ──────────────────────────────────────────────────────────────────
# Upload individual
# ──────────────────────────────────────────────────────────────────

def upload_csv_to_volume(client: WorkspaceClient, df: pd.DataFrame, volume_file: str) -> None:
    """Serializa DataFrame para CSV em memória (sem escrever em disco) e faz upload ao Volume."""
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False, header=False, encoding="utf-8")
    buffer.seek(0)
    client.files.upload(volume_file, buffer, overwrite=True)


def load_single_file(
    filepath: str,
    client: WorkspaceClient,
    year: int,
    month: int,
    skip_validation: bool = False,
) -> bool:
    """Valida e envia um único arquivo .xlsx para o Databricks Volume."""
    filename = os.path.basename(filepath)
    print(f"  📄 Processando: {filename} ({MONTH_NAMES[month]}/{year})")

    # 1. Validação de schema pré-upload
    if not skip_validation:
        results, has_failure = validate_file(filepath)
        if has_failure:
            print("     ❌ Schema inválido — pulando upload")
            print_report(results, filename)
            return False

    # 2. Ler arquivo
    try:
        df = pd.read_excel(filepath)
        df.columns = [normalize_column_name(c) for c in df.columns]
    except Exception as e:
        print(f"     ❌ Erro ao ler Excel: {e}\n")
        return False

    # 3. Adicionar rastreabilidade e ordenar colunas
    df["nm_file"] = filename
    df["nr_ano"] = year
    df["nr_mes"] = month
    missing_cols = set(COLUMN_ORDER) - set(df.columns)
    if missing_cols:
        print(f"     ❌ Colunas obrigatórias ausentes após normalização: {missing_cols}")
        return False

    df = df[COLUMN_ORDER]
    # Int64 (nullable) evita que um único nulo transforme a coluna em float ("123.0"),
    # o que faria o schema LongType da bronze ler a quantidade como NULL
    df["qtd_veiculos"] = pd.to_numeric(df["qtd_veiculos"], errors="coerce").astype("Int64")

    # 4. Upload para o Volume
    volume_file = canonical_volume_path(year, month)
    try:
        upload_csv_to_volume(client, df, volume_file)
        print(f"     ✅ Enviado ao Volume: {volume_file} ({len(df):,} linhas)\n")
        return True
    except Exception as e:
        print(f"     ❌ Erro no upload para o Databricks Volume: {e}\n")
        return False


# ──────────────────────────────────────────────────────────────────
# Modos de Carga (Mês / Último publicado / Ano)
# ──────────────────────────────────────────────────────────────────

def load_month(
    year: int,
    month: int,
    client: WorkspaceClient,
    skip_validation: bool = False,
    force: bool = False,
    missing_is_failure: bool = True,
) -> dict[str, list[str]]:
    """Extrai e carrega o arquivo de um determinado mês e ano."""
    label = f"{MONTH_NAMES[month]}/{year}"
    result = new_result()

    if not force and file_exists(client, canonical_volume_path(year, month)):
        print(f"⏭️  {label} já está no Volume — pulando (use --force para recarregar).")
        result["skipped"].append(label)
        return result

    filepath = extract_month(year, month)
    if not filepath:
        print(f"⚠️  Não foi possível obter o arquivo de {label}.")
        result["failed" if missing_is_failure else "skipped"].append(label)
        return result

    success = load_single_file(filepath, client, year, month, skip_validation=skip_validation)
    result["uploaded" if success else "failed"].append(label)
    return result


def load_latest_available(
    client: WorkspaceClient,
    skip_validation: bool = False,
    force: bool = False,
) -> dict[str, list[str]]:
    """Carrega o mês mais recente publicado, procurando de M-1 até M-PREVIOUS_MONTH_LOOKBACK.

    Para no primeiro mês que já estiver no Volume (nada novo publicado) ou que for carregado.
    Falha só se nenhum mês da janela estiver publicado — sinal de atraso anormal da fonte.
    """
    for months_back in range(1, PREVIOUS_MONTH_LOOKBACK + 1):
        year, month = get_target_previous_period(months_back)
        res = load_month(year, month, client, skip_validation, force, missing_is_failure=False)
        if res["uploaded"] or res["failed"]:
            return res
        if not force and file_exists(client, canonical_volume_path(year, month)):
            print("ℹ️  Nenhum mês mais recente publicado pela Senatran ainda.")
            return res

    print(f"❌ Nenhum dos últimos {PREVIOUS_MONTH_LOOKBACK} meses está publicado no site da Senatran.")
    res = new_result()
    res["failed"].append(f"últimos {PREVIOUS_MONTH_LOOKBACK} meses")
    return res


def load_year(
    year: int,
    client: WorkspaceClient,
    skip_validation: bool = False,
    force: bool = False,
) -> dict[str, list[str]]:
    """Baixa e carrega todos os meses publicados de um ano (meses não publicados são pulados)."""
    today = datetime.date.today()
    result = new_result()
    print(f"\n📅 Processando Ano Completo {year}\n")

    for month in range(1, 13):
        if (year, month) >= (today.year, today.month):
            break
        res = load_month(year, month, client, skip_validation, force, missing_is_failure=False)
        for k in result:
            result[k] += res[k]

    return result


def main():
    parser = argparse.ArgumentParser(description="Carrega dados de frota no Databricks Volume.")
    parser.add_argument(
        "--previous-month",
        action="store_true",
        help="Carrega o mês mais recente publicado (tenta o mês anterior e o retrasado).",
    )
    parser.add_argument(
        "--year",
        type=int,
        nargs="+",
        help="Ano(s) a processar (ex: --year 2026 ou --year 2024 2025).",
    )
    parser.add_argument(
        "--month",
        type=int,
        help="Mês específico (1 a 12) a processar (requer --year).",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Caminho para um arquivo .xlsx específico para carga avulsa (mês extraído do nome).",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Pula a validação de schema antes do upload.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recarrega meses que já estão no Volume.",
    )
    args = parser.parse_args()

    client = get_databricks_client()
    totals = new_result()

    if args.previous_month:
        print("🎯 Modo Automático Incremental selecionado.")
        res = load_latest_available(client, args.skip_validation, args.force)

    elif args.file:
        if not os.path.isfile(args.file):
            print(f"❌ Arquivo não encontrado: {args.file}")
            sys.exit(1)
        period = parse_period_from_filename(args.file)
        if not period:
            print(f"❌ Não foi possível identificar mês/ano no nome do arquivo: {args.file}")
            sys.exit(1)
        res = new_result()
        success = load_single_file(args.file, client, *period, skip_validation=args.skip_validation)
        res["uploaded" if success else "failed"].append(os.path.basename(args.file))

    elif args.month:
        if not args.year or len(args.year) != 1:
            parser.error("--month requer exatamente um --year especificado.")
        res = load_month(args.year[0], args.month, client, args.skip_validation, args.force)

    elif args.year:
        res = new_result()
        for year in args.year:
            year_res = load_year(year, client, args.skip_validation, args.force)
            for k in res:
                res[k] += year_res[k]

    else:
        parser.error("Informe --previous-month, --year [--month] ou --file.")

    for k in totals:
        totals[k] += res[k]

    # Resumo final
    print(f"\n{'═' * 60}")
    print("🏁 Carga concluída!")
    print(f"   ✅ Uploaded : {len(totals['uploaded'])} mês(es) {totals['uploaded']}")
    print(f"   ⏭️  Skipped  : {len(totals['skipped'])} mês(es) {totals['skipped']}")
    print(f"   ❌ Failed   : {len(totals['failed'])} mês(es) {totals['failed']}")
    print(f"{'═' * 60}")

    if totals["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
