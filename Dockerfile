FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8080
WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY adk_agents ./adk_agents
COPY scripts ./scripts
COPY web ./web

# CSV sintético embutido para o modo DATA_SOURCE=csv (em produção o padrão é BigQuery)
RUN python scripts/gerar_dados_teste.py

# Roda sem root; credenciais ADC locais podem ser montadas em /home/app/.config/gcloud
RUN useradd --create-home app && chown -R app /srv
USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/health')"

# Cloud Run injeta $PORT
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
