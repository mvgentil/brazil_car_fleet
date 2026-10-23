"""
Extração e carga da tabela de municípios da Receita Federal.
Baixa o arquivo CSV oficial e, opcionalmente, faz upload direto para o Volume raw do Databricks.

Configuração: ver src/databricks_client.py (mesmas credenciais e catálogo do load.py).
"""

import argparse
import io
import os

import requests

from databricks_client import get_databricks_client, volume_path

URL = "https://www.gov.br/receitafederal/dados/municipios.csv"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

RFB_VOLUME = os.getenv("DATABRICKS_RFB_VOLUME", "rfb_municipios_raw")
VOLUME_PATH = f"{volume_path(RFB_VOLUME)}/municipios.csv"


def download_municipios(dest_path: str) -> bytes:
    """Baixa o CSV de municípios da Receita Federal."""
    print(f"🔗 Baixando: {URL}")
    response = requests.get(URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    with open(dest_path, "wb") as f:
        f.write(response.content)

    print(f"✅ Salvo localmente: {dest_path} ({len(response.content):,} bytes)")
    return response.content


def upload_to_volume(content: bytes):
    """Envia o arquivo para o Volume raw do Databricks."""
    client = get_databricks_client()
    client.files.upload(VOLUME_PATH, io.BytesIO(content), overwrite=True)
    print(f"✅ Upload concluído no Volume: {VOLUME_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Baixa e opcionalmente envia o CSV de municípios para o Databricks")
    parser.add_argument("--upload", action="store_true", help="Faz upload automático para o Volume do Databricks")
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, "municipios.csv")

    content = download_municipios(filepath)

    if args.upload:
        upload_to_volume(content)


if __name__ == "__main__":
    main()
