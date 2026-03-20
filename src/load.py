import argparse
import os
import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_year(year: int) -> None:
    """Lê todos os .xlsx de um ano, concatena e salva como CSV."""
    year_dir = os.path.join(RAW_DIR, str(year))

    if not os.path.isdir(year_dir):
        print(f"⚠️  Pasta não encontrada: {year_dir}")
        return

    files = [f for f in os.listdir(year_dir) if f.endswith(".xlsx")]

    if not files:
        print(f"⚠️  Nenhum arquivo .xlsx em {year_dir}")
        return

    dfs = []
    for filename in sorted(files):
        filepath = os.path.join(year_dir, filename)
        df = pd.read_excel(filepath)
        df["file_name"] = filename
        dfs.append(df)
        print(f"  📄 {filename} ({len(df)} linhas)")

    combined = pd.concat(dfs, ignore_index=True)

    out_path = os.path.join(OUT_DIR, f"frota_veiculos_{year}.csv")
    combined.to_csv(out_path, index=False)
    print(f"✅ Salvo: {out_path} ({len(combined)} linhas total)\n")


def main():
    parser = argparse.ArgumentParser(description="Agrupa arquivos xlsx por ano em um único CSV")
    parser.add_argument(
        "--year",
        type=int,
        nargs="+",
        help="Ano(s) específico(s) (ex: --year 2026). Sem argumento = todos os anos disponíveis.",
    )
    args = parser.parse_args()

    if args.year:
        years = args.year
    else:
        # Detecta todas as pastas de ano em data/raw/
        years = sorted(
            int(d) for d in os.listdir(RAW_DIR)
            if os.path.isdir(os.path.join(RAW_DIR, d)) and d.isdigit()
        )

    for year in years:
        print(f"📅 Processando {year}...")
        load_year(year)

    print("🏁 Concluído!")


if __name__ == "__main__":
    main()