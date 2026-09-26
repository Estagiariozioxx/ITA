# ITA — backend

Agente de decisão financeira para a Batalha de Agentes Itaú.
FastAPI + Google ADK (Gemini 3.8 Flash) + BigQuery, publicado no Cloud Run.

```
app/
  config.py    variáveis de ambiente
  data.py      lê o extrato do cliente no BigQuery (ou CSV local)
  engine.py    motor determinístico: perfil, projeção, comparação, alertas  <- todos os números
  tools.py     ferramentas que os agentes chamam
  agents.py    ENTENDER -> ANTECIPAR -> ORIENTAR -> GUARDIÃO (SequentialAgent)
  main.py      API
adk_agents/    entrada para `adk web` (Agent Platform / Antigravity / VS Code)
scripts/       gerador de dados sintéticos para teste local
sql/           consultas de diagnóstico da base
deploy.sh      deploy no Cloud Run (Artifact Registry + Cloud Build + Cloud Run)
```

## Princípio

O LLM **nunca calcula**. Todo valor, data e percentual sai do `engine.py`;
o Gemini só interpreta, recomenda e explica. O Guardião revisa cada resposta
contra os princípios da Res. Conjunta nº 8 antes de ela chegar ao cliente.

## 1. Antes de tudo (BigQuery Studio)

Rode `sql/diagnostico.sql`. O motor assume `tipo = 'S'` para saídas.
Se for outro valor, defina `TIPO_SAIDA` no deploy.

## 2. Rodar localmente

```bash
pip install -r requirements-dev.txt

# sem GCP, com dados sintéticos
python scripts/gerar_dados_teste.py
DATA_SOURCE=csv uvicorn app.main:app --reload
pytest -q

# com BigQuery e Gemini de verdade (no Cloud Shell já existe ADC)
gcloud auth application-default login
gcloud auth application-default set-quota-project batalha-time-01-97zr
cp .env.example .env && export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload
```

Chat dos agentes no ADK Dev UI: `adk web adk_agents` e, no painel State,
adicione `{"id_usuario": "<id de um cliente>"}`.

### Com Docker

```bash
# demo sem GCP (CSV sintético embutido na imagem): http://localhost:8080/docs
docker compose up --build
curl localhost:8080/clientes/camila-demo/alertas

# BigQuery + Vertex com suas credenciais ADC: http://localhost:8081/docs
gcloud auth application-default login
docker compose --profile gcp up --build api-gcp
```

No modo demo, o `/chat` só funciona com `GOOGLE_API_KEY` e `GOOGLE_GENAI_USE_VERTEXAI=FALSE` no `.env`.
A mesma imagem é usada no Cloud Run (lá o padrão é `DATA_SOURCE=bigquery`).

## 3. Deploy

```bash
bash deploy.sh                 # Vertex AI via ADC (recomendado)
USE_API_KEY=1 bash deploy.sh   # usa o segredo gemini-api-key do Secret Manager
```

## Endpoints

| Método | Rota | Para quê |
|---|---|---|
| GET | `/clientes?limite=20` | lista ids |
| GET | `/demo/candidatos?limite=100` | acha a melhor "Camila" para a demo |
| GET | `/clientes/{id}/perfil` | raio-X (tela inicial) |
| GET | `/clientes/{id}/projecao?dias=90` | saldo dia a dia (gráfico) |
| POST | `/clientes/{id}/simular` | uma forma de compra (`valor, parcelas, entrada, meses_espera, taxa_juros_mensal`) |
| POST | `/clientes/{id}/comparar` | compara caminhos e recomenda (`valor, parcelas`) |
| GET | `/clientes/{id}/alertas` | avisos proativos (aperto, parcela terminando, sobra -> reserva/investir) |
| POST | `/jobs/alertas?limite=50` | varredura para o Cloud Scheduler |
| POST | `/chat` | conversa com os agentes (`id_usuario, mensagem, session_id?`) |

Resposta do `/chat`:

```json
{
  "session_id": "…",
  "resposta": "texto final validado pelo Guardião",
  "dados_tela": {"perfil": {...}, "comparacao": {...}},
  "trilha": [{"agente": "entender", "acao": "ferramenta", "ferramenta": "consultar_perfil"}, ...]
}
```

`dados_tela` traz as séries diárias para desenhar os gráficos; `trilha` mostra
cada agente trabalhando (bom para o painel "por dentro" da apresentação).

## Exemplos

```bash
URL=https://agente-xxxx.run.app
ID=$(curl -s "$URL/demo/candidatos?limite=100" | python3 -c "import sys,json;print(json.load(sys.stdin)['candidatos'][0]['id_usuario'])")

curl -s "$URL/clientes/$ID/alertas"
curl -s -X POST "$URL/clientes/$ID/comparar" -H 'content-type: application/json' -d '{"valor":3000,"parcelas":12}'
curl -s -X POST "$URL/chat" -H 'content-type: application/json' \
  -d "{\"id_usuario\":\"$ID\",\"mensagem\":\"Posso parcelar um celular de R\$ 3.000 em 12x?\"}"
```

Alerta proativo diário (opcional):

```bash
gcloud scheduler jobs create http ita-alertas --location=us-central1 \
  --schedule="0 8 * * *" --uri="$URL/jobs/alertas?limite=1000" --http-method=POST
```

## Limites conhecidos

- Sessões em memória: com `--session-affinity` a conversa fica na mesma instância;
  para produção, troque por `VertexAiSessionService` ou `DatabaseSessionService`.
- `SequentialAgent` aparece como obsoleto no ADK 2.x (em favor de Workflow), mas funciona.
- Projeção usa médias dos últimos 90 dias para o gasto variável; eventos únicos não são previstos.
