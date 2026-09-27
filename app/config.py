"""Configuração lida de variáveis de ambiente (Cloud Run / .env)."""
import os

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "batalha-time-01-97zr")
# Local do Vertex AI para o Gemini (não do Cloud Run): gemini-3.8-flash só existe no endpoint global
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
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

# Taxas ILUSTRATIVAS da simulação/contratação no WhatsApp quando a oferta não traz a taxa do cenário
# (a base do hackathon não tem tabela de taxas do banco; o ITA sempre avisa que são ilustrativas)
TAXA_REF_FINANCIAMENTO = float(os.getenv("TAXA_REF_FINANCIAMENTO", "0.019"))  # 1,9% ao mês
TAXA_REF_CREDITO = float(os.getenv("TAXA_REF_CREDITO", "0.045"))              # 4,5% ao mês
TAXA_ADM_CONSORCIO = float(os.getenv("TAXA_ADM_CONSORCIO", "0.15"))           # 15% sobre a carta

# Nível de raciocínio do Gemini nos agentes: MINIMAL, LOW, MEDIUM, HIGH ou vazio (padrão do modelo).
# As contas ficam nas tools, então LOW basta e responde bem mais rápido.
THINKING_LEVEL = os.getenv("THINKING_LEVEL", "LOW").strip().upper() or None

# Cache do extrato por cliente (segundos) para não repetir query no BigQuery
CACHE_TTL = int(os.getenv("CACHE_TTL", "600"))
