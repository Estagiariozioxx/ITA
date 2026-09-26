"""Configuração lida de variáveis de ambiente (Cloud Run / .env)."""
import os

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-01-97zr")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
BQ_TABLE = os.getenv(
    "BQ_TABLE", f"{PROJECT_ID}.hackathon_dados.extrato_sintetico"
)
MODEL = os.getenv("MODEL", "gemini-3.8-flash")

# "bigquery" (padrão, produção) ou "csv" (testes locais sem GCP)
DATA_SOURCE = os.getenv("DATA_SOURCE", "bigquery")
CSV_PATH = os.getenv("CSV_PATH", "data/extrato_amostra.csv")

# Valor da coluna `tipo` que indica saída de dinheiro. Confirme com:
#   SELECT tipo, COUNT(*) FROM `...extrato_sintetico` GROUP BY tipo
TIPO_SAIDA = os.getenv("TIPO_SAIDA", "S")

# Dia do mês em que as parcelas de uma compra nova são cobradas na simulação
DIA_VENCIMENTO_PADRAO = int(os.getenv("DIA_VENCIMENTO_PADRAO", "10"))

# Cache do extrato por cliente (segundos) para não repetir query no BigQuery
CACHE_TTL = int(os.getenv("CACHE_TTL", "600"))
