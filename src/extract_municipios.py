import os
import requests

URL = "https://www.gov.br/receitafederal/dados/municipios.csv"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, "municipios.csv")

    print(f"🔗 Baixando: {URL}")
    response = requests.get(URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    with open(filepath, "wb") as f:
        f.write(response.content)

    print(f"✅ Salvo: {filepath} ({len(response.content)} bytes)")


if __name__ == "__main__":
    main()
