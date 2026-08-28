# Usar imagem oficial do Python 3.13 slim
FROM python:3.13-slim

# Instalar uv para gerenciamento ultra-rápido de dependências
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Diretório de trabalho
WORKDIR /app

# Copiar arquivos de dependências
COPY pyproject.toml uv.lock ./

# Instalar dependências congeladas
RUN uv sync --frozen --no-cache

# Copiar o código fonte e estrutura
COPY src/ ./src/

# Diretório para armazenamento temporário de downloads
RUN mkdir -p /app/data/raw

# Variáveis de ambiente padrão
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Ponto de entrada padrão: extrai o mês anterior dinamicamente e carrega no Databricks Volume
ENTRYPOINT ["python", "src/load.py"]
CMD ["--previous-month"]
