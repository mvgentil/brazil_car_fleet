"""
Cliente Databricks e caminhos de Volume compartilhados pelos scripts de ingestão.

Configuração (via ingestion/.env ou variáveis de ambiente):
    DATABRICKS_HOST                                  — URL do workspace
    DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET  — Service Principal (OAuth M2M), prioritário
    DATABRICKS_TOKEN                                 — Personal access token (fallback)
    DATABRICKS_CATALOG / DATABRICKS_RAW_SCHEMA       — destino dos Volumes raw
"""

import os

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from dotenv import load_dotenv

load_dotenv()

CATALOG = os.getenv("DATABRICKS_CATALOG", "brazil_car_fleet")
RAW_SCHEMA = os.getenv("DATABRICKS_RAW_SCHEMA", "raw_data")


def volume_path(volume: str) -> str:
    return f"/Volumes/{CATALOG}/{RAW_SCHEMA}/{volume}"


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


def file_exists(client: WorkspaceClient, path: str) -> bool:
    try:
        client.files.get_metadata(path)
        return True
    except NotFound:
        return False
