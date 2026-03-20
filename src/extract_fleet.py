import argparse
import os
import re
import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────
BASE_URL = "https://www.gov.br/transportes/pt-br/assuntos/transito/conteudo-Senatran/frota-de-veiculos-{year}"
YEARS = [2024, 2025, 2026]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def get_combustivel_links(url: str) -> list[str]:
    """Faz o request da página de frota e retorna os links de combustível."""
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    div_links = soup.find_all("div", id="parent-fieldname-text")

    if not div_links:
        print(f"  ⚠️  Nenhum conteúdo encontrado em {url}")
        return []

    links = div_links[0].find_all("a")

    return [
        link.get("href")
        for link in links
        if link.get("href") and "combustivel" in link.get("href").lower()
    ]


def download_file(url: str, dest_dir: str, index: int) -> None:
    """Baixa um arquivo .xlsx e salva no diretório de destino."""
    response = requests.get(url, headers=HEADERS, stream=True, allow_redirects=True, timeout=60)
    response.raise_for_status()

    filename = url.split("/")[-1]
    if not filename.endswith(".xlsx"):
        filename = f"combustivel_{index}.xlsx"

    filepath = os.path.join(dest_dir, filename)

    with open(filepath, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"  ✅ Baixado: {filename} ({response.status_code})")


def extract_fleet_data(years: list[int] | None = None):
    """Pipeline principal: itera por cada ano, extrai links e baixa os arquivos."""
    if years is None:
        years = YEARS

    for year in years:
        url = BASE_URL.format(year=year)
        year_dir = os.path.join(DATA_DIR, str(year))
        os.makedirs(year_dir, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"📅 Ano: {year}")
        print(f"🔗 URL: {url}")
        print(f"📂 Destino: {year_dir}")
        print(f"{'='*60}")

        try:
            links = get_combustivel_links(url)
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Erro ao acessar a página de {year}: {e}")
            continue

        if not links:
            print(f"  ⚠️  Nenhum link de combustível encontrado para {year}.")
            continue

        print(f"  📋 {len(links)} arquivo(s) encontrado(s)")

        for i, link in enumerate(links):
            try:
                download_file(link, year_dir, i)
            except requests.exceptions.RequestException as e:
                print(f"  ❌ Erro ao baixar {link}: {e}")

    print(f"\n{'='*60}")
    print("🏁 Extração concluída!")
    print(f"{'='*60}")

def main():
    parser = argparse.ArgumentParser(description="Extrai dados de frota de veículos por combustível do gov.br")
    parser.add_argument(
        "--year",
        type=int,
        nargs="+",
        help="Ano(s) específico(s) para extrair (ex: --year 2026 ou --year 2024 2025). Sem argumento = todos.",
    )
    args = parser.parse_args()

    if args.year:
        extract_fleet_data(args.year)
    else:
        extract_fleet_data()

if __name__ == "__main__":
    main()
