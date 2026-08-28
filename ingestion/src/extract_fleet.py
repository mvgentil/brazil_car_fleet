import argparse
import datetime
import os
import re
import sys
import requests
from bs4 import BeautifulSoup

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────
BASE_URL = "https://www.gov.br/transportes/pt-br/assuntos/transito/conteudo-Senatran/frota-de-veiculos-{year}"
YEARS = [2024, 2025, 2026]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

MONTH_ALIASES: dict[int, list[str]] = {
    1: ["janeiro"],
    2: ["fevereiro"],
    3: ["marco", "março", "maro"],
    4: ["abril"],
    5: ["maio"],
    6: ["junho"],
    7: ["julho"],
    8: ["agosto"],
    9: ["setembro"],
    10: ["outubro"],
    11: ["novembro"],
    12: ["dezembro"],
}

MONTH_NAMES: dict[int, str] = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}


def get_target_previous_period(months_back: int = 1) -> tuple[int, int]:
    """Calcula o ano e mês alvo relativo à data atual.

    Por padrão (months_back=1), retorna o mês imediatamente anterior.
    Exemplos:
      - Em 2026-08, retorna (2026, 7) [Julho/2026].
      - Em 2027-01, retorna (2026, 12) [Dezembro/2026].
    """
    today = datetime.date.today()
    # Primeiro dia do mês atual
    first_of_current = today.replace(day=1)
    # Subtrai 1 dia para pegar o último dia do mês anterior
    target = first_of_current - datetime.timedelta(days=1)

    for _ in range(months_back - 1):
        target = target.replace(day=1) - datetime.timedelta(days=1)

    return target.year, target.month


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


def download_file(url: str, dest_dir: str, index: int = 0) -> str:
    """Baixa um arquivo .xlsx e salva no diretório de destino. Retorna o caminho do arquivo."""
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
    return filepath


def extract_month(year: int, month: int) -> str | None:
    """Extrai exclusivamente o arquivo de um determinado mês e ano.

    Busca na página oficial do Senatran pelo link que contenha o nome do mês.
    Retorna o caminho local do arquivo baixado ou None se não encontrado.
    """
    month_name = MONTH_NAMES.get(month, str(month))
    aliases = MONTH_ALIASES.get(month, [month_name.lower()])

    url = BASE_URL.format(year=year)
    year_dir = os.path.join(DATA_DIR, str(year))
    os.makedirs(year_dir, exist_ok=True)

    print(f"\n🔍 Buscando arquivo de {month_name}/{year} em: {url}")

    try:
        links = get_combustivel_links(url)
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Erro ao acessar a página de {year}: {e}")
        return None

    if not links:
        print(f"  ⚠️  Nenhum link de combustível encontrado na página de {year}.")
        return None

    # Procura o link que contenha qualquer uma das variações do nome do mês
    matched_link = None
    for link in links:
        link_lower = link.lower()
        if any(alias in link_lower for alias in aliases):
            matched_link = link
            break

    if not matched_link:
        print(f"  ⚠️  O arquivo de {month_name}/{year} ainda não está publicado no site da Senatran.")
        return None

    print(f"  🔗 Link encontrado: {matched_link}")
    return download_file(matched_link, year_dir)


def extract_fleet_data(years: list[int] | None = None) -> list[str]:
    """Pipeline principal de backfill: itera por cada ano, extrai links e baixa todos os arquivos."""
    if years is None:
        years = YEARS

    downloaded = []
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
                path = download_file(link, year_dir, i)
                downloaded.append(path)
            except requests.exceptions.RequestException as e:
                print(f"  ❌ Erro ao baixar {link}: {e}")

    print(f"\n{'='*60}")
    print("🏁 Extração concluída!")
    print(f"{'='*60}")
    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Extrai dados de frota de veículos por combustível do gov.br")
    parser.add_argument(
        "--year",
        type=int,
        nargs="+",
        help="Ano(s) específico(s) para extrair (ex: --year 2026 ou --year 2024 2025).",
    )
    parser.add_argument(
        "--month",
        type=int,
        help="Mês específico (1 a 12) a ser extraído (usado junto com --year).",
    )
    parser.add_argument(
        "--previous-month",
        action="store_true",
        help="Extrai automaticamente o mês imediatamente anterior à data de hoje (ex: em agosto busca julho).",
    )
    args = parser.parse_args()

    if args.previous_month:
        target_year, target_month = get_target_previous_period()
        print(f"🎯 Modo incremental: Extraindo mês anterior ({MONTH_NAMES[target_month]}/{target_year})...")
        extract_month(target_year, target_month)
    elif args.month:
        if not args.year or len(args.year) != 1:
            parser.error("--month requer exatamente um --year especificado.")
        extract_month(args.year[0], args.month)
    elif args.year:
        extract_fleet_data(args.year)
    else:
        extract_fleet_data()


if __name__ == "__main__":
    main()
