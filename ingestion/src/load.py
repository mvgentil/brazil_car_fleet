"""
Carga de arquivos de frota para o Volume raw do Databricks.

Cada arquivo .xlsx é:
  1. Lido com pandas
  2. Validado (schema) — falha individualmente, não bloqueia os demais
  3. Enriquecido com coluna nm_file (rastreabilidade)
  4. Serializado para CSV em memória
  5. Carregado no Databricks Volume via SDK

Destino no Volume:
  /Volumes/brazil_car_fleet/raw_data/fleet_raw/{arquivo}.csv

Uso:
    python src/load.py --previous-month        # Carga incremental do mês anterior (ideal para agendamento)
    python src/load.py --year 2026 --month 7  # Carga de um mês específico
    python src/load.py --year 2026            # Todos os arquivos de 2026 (backfill)
    python src/load.py                        # Todos os anos disponíveis

Configuração (via ingestion/.env ou variáveis de ambiente):
    DATABRICKS_HOST   — URL do workspace (ex: https://dbc-xxx.cloud.databricks.com)
    DATABRICKS_TOKEN  — Personal access token
"""

import argparse
import io
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


import pandas as pd
from databricks.sdk import WorkspaceClient
from dotenv import load_dotenv

from validate import validate_file, print_report, Status, normalize_column_name
from extract_fleet import extract_month, get_target_previous_period, MONTH_NAMES

load_dotenv()

# ──────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

CATALOG = os.getenv("DATABRICKS_CATALOG", "brazil_car_fleet")
RAW_SCHEMA = os.getenv("DATABRICKS_RAW_SCHEMA", "raw_data")
FLEET_VOLUME = os.getenv("DATABRICKS_FLEET_VOLUME", "fleet_raw")

VOLUME_BASE_PATH = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/{FLEET_VOLUME}"
COLUMN_ORDER = ["uf", "municipio", "combustivel_veiculo", "qtd_veiculos", "nm_file"]


# ──────────────────────────────────────────────────────────────────
# Databricks client
# ──────────────────────────────────────────────────────────────────

def get_databricks_client() -> WorkspaceClient:
    """
    Inicializa o cliente Databricks a partir de variáveis de ambiente.
    Suporta autenticação via Service Principal (OAuth M2M) ou Personal Access Token (PAT).
    """
    host = os.getenv("DATABRICKS_HOST")
    client_id = os.getenv("DATABRICKS_CLIENT_ID")
    client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")
    token = os.getenv("DATABRICKS_TOKEN")

    if not host:
        raise EnvironmentError("Configure DATABRICKS_HOST no arquivo ingestion/.env")

    # 1. Prioridade para Service Principal (OAuth M2M)
    if client_id and client_secret:
        # Remove DATABRICKS_TOKEN para evitar conflito com OAuth M2M no SDK
        os.environ.pop("DATABRICKS_TOKEN", None)
        return WorkspaceClient(host=host, client_id=client_id, client_secret=client_secret)

    # 2. Fallback para Personal Access Token (PAT)
    if token:
        return WorkspaceClient(host=host, token=token)

    raise EnvironmentError(
        "Credenciais Databricks não encontradas.\n"
        "Configure DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET (Service Principal) "
        "ou DATABRICKS_TOKEN (PAT) no arquivo ingestion/.env"
    )


# ──────────────────────────────────────────────────────────────────
# Upload individual
# ──────────────────────────────────────────────────────────────────

def upload_csv_to_volume(
    client: WorkspaceClient,
    df: pd.DataFrame,
    original_filename: str,
) -> str:
    """Serializa DataFrame para CSV e faz upload ao Volume.

    O arquivo é serializado em memória (sem escrever em disco).
    """
    csv_filename = os.path.splitext(original_filename)[0] + ".csv"
    volume_path = f"{VOLUME_BASE_PATH}/{csv_filename}"

    buffer = io.BytesIO()
    df.to_csv(buffer, index=False, header=False, encoding="utf-8")
    buffer.seek(0)

    client.files.upload(volume_path, buffer, overwrite=True)
    return volume_path


def load_single_file(
    filepath: str,
    client: WorkspaceClient,
    skip_validation: bool = False,
) -> bool:
    """Valida e envia um único arquivo .xlsx para o Databricks Volume."""
    filename = os.path.basename(filepath)
    print(f"  📄 Processando: {filename}")

    # 1. Validação de schema pré-upload
    if not skip_validation:
        report = validate_file(filepath)
        if report.status == Status.INVALID:
            print(f"     ❌ Schema inválido — pulando upload")
            print_report(report)
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
    missing_cols = set(COLUMN_ORDER) - set(df.columns)
    if missing_cols:
        print(f"     ❌ Colunas obrigatórias ausentes após normalização: {missing_cols}")
        return False

    df = df[COLUMN_ORDER]

    # 4. Upload para o Volume
    try:
        volume_path = upload_csv_to_volume(client, df, filename)
        print(f"     ✅ Enviado ao Volume: {volume_path} ({len(df):,} linhas)\n")
        return True
    except Exception as e:
        print(f"     ❌ Erro no upload para o Databricks Volume: {e}\n")
        return False


# ──────────────────────────────────────────────────────────────────
# Modos de Carga (Incremental / Anual / Arquivo Único)
# ──────────────────────────────────────────────────────────────────

def load_month(
    year: int,
    month: int,
    client: WorkspaceClient,
    skip_validation: bool = False,
) -> dict[str, list[str]]:
    """Extrai e carrega exclusivamente o arquivo de um determinado mês e ano."""
    month_name = MONTH_NAMES.get(month, str(month))
    print(f"\n📅 Carga Incremental do Mês: {month_name}/{year}")

    result: dict[str, list[str]] = {"uploaded": [], "skipped": [], "failed": []}

    # 1. Extrai o arquivo da web se necessário
    filepath = extract_month(year, month)
    if not filepath:
        print(f"⚠️  Não foi possível obter o arquivo de {month_name}/{year} para carga.")
        result["failed"].append(f"{month_name}_{year}")
        return result

    # 2. Carrega no volume
    success = load_single_file(filepath, client, skip_validation=skip_validation)
    filename = os.path.basename(filepath)
    if success:
        result["uploaded"].append(filename)
    else:
        result["failed"].append(filename)

    return result


def load_year(
    year: int,
    client: WorkspaceClient,
    skip_validation: bool = False,
) -> dict[str, list[str]]:
    """Processa todos os .xlsx locais de um ano: valida schema e faz upload individual."""
    year_dir = os.path.join(RAW_DIR, str(year))
    result: dict[str, list[str]] = {"uploaded": [], "skipped": [], "failed": []}

    if not os.path.isdir(year_dir):
        print(f"⚠️  Pasta não encontrada: {year_dir}")
        return result

    files = sorted(f for f in os.listdir(year_dir) if f.endswith(".xlsx"))

    if not files:
        print(f"⚠️  Nenhum arquivo .xlsx em {year_dir}")
        return result

    print(f"\n📅 Processando Ano Completo {year} — {len(files)} arquivo(s)\n")

    for filename in files:
        filepath = os.path.join(year_dir, filename)
        success = load_single_file(filepath, client, skip_validation=skip_validation)
        if success:
            result["uploaded"].append(filename)
        else:
            result["failed"].append(filename)

    return result


def main():
    parser = argparse.ArgumentParser(description="Carrega dados de frota no Databricks Volume.")
    parser.add_argument(
        "--previous-month",
        action="store_true",
        help="Executa carga incremental do mês anterior (calcula ano e mês dinamicamente).",
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
        help="Caminho para um arquivo .xlsx específico para carga avulsa.",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Pula a validação de schema antes do upload.",
    )
    args = parser.parse_args()

    client = get_databricks_client()
    totals = {"uploaded": 0, "skipped": 0, "failed": 0}

    if args.previous_month:
        target_year, target_month = get_target_previous_period()
        month_name = MONTH_NAMES.get(target_month, str(target_month))
        print(f"🎯 Modo Automático Incremental selecionado.")
        print(f"   Período Alvo: {month_name}/{target_year}")
        res = load_month(target_year, target_month, client, skip_validation=args.skip_validation)
        for k in totals:
            totals[k] += len(res[k])

    elif args.file:
        if not os.path.isfile(args.file):
            print(f"❌ Arquivo não encontrado: {args.file}")
            sys.exit(1)
        success = load_single_file(args.file, client, skip_validation=args.skip_validation)
        if success:
            totals["uploaded"] += 1
        else:
            totals["failed"] += 1

    elif args.month:
        if not args.year or len(args.year) != 1:
            parser.error("--month requer exatamente um --year especificado.")
        res = load_month(args.year[0], args.month, client, skip_validation=args.skip_validation)
        for k in totals:
            totals[k] += len(res[k])

    else:
        years = args.year or [2024, 2025, 2026]
        for year in years:
            res = load_year(year, client, skip_validation=args.skip_validation)
            for k in totals:
                totals[k] += len(res[k])

    # Resumo final
    print(f"\n{'═' * 60}")
    print("🏁 Carga concluída!")
    print(f"   ✅ Uploaded : {totals['uploaded']} arquivo(s)")
    print(f"   ❌ Failed   : {totals['failed']} arquivo(s)")
    print(f"{'═' * 60}")

    if totals["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
