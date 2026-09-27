# ITA — backend

Agente de decisão financeira para a Batalha de Agentes Itaú.
FastAPI + Google ADK (Gemini 3.8 Flash) + BigQuery, publicado no Cloud Run.

```
app/
  main.py          cria o FastAPI e registra as rotas
  config.py        variáveis de ambiente
  schemas.py       modelos de entrada (ChatIn, SimulacaoIn, ComparacaoIn, ProdutoIn)
  routes/          contrato HTTP: caminhos, parâmetros e validação (só chamam os controllers)
    web.py  clientes.py  produtos.py  chat.py  graficos.py  demo.py
  controllers/     casos de uso: juntam repositório, services e agentes; erro vira resposta HTTP
    comum.py       extrato do cliente ou 404
    clientes.py  produtos.py  graficos.py  demo.py
    chat.py        /chat: mídia -> guard de entrada -> agentes -> gráfico escolhido -> trilha
  services/        regras de negócio, sem HTTP e sem LLM
    engine.py      motor determinístico: perfil, projeção, comparação, alertas
    simulacao.py   contas por trás das tools dos agentes
    produtos.py    regras de produto: quais produtos podem aparecer e se há oferta
    contratacao.py simular e contratar (demonstração) na conversa
    gatilhos.py    gatilhos proativos detectados no extrato
    graficos.py    gráficos como imagem (PNG)
    midia.py       áudio e imagem (transcrição e guard de imagem)
    guard_entrada.py / guardrails_saida.py   conferências em código antes e depois dos agentes
    formatos.py    R$ e datas no padrão brasileiro
  agents/          Google ADK + Gemini
    agentes.py     ORQUESTRADOR -> CLARIFICAÇÃO | PREVISIBILIDADE | PROATIVIDADE | PRODUTOS
    tools.py       tools dos agentes (perfil, projeção, simulações, busca de gastos, regras de produto)
    runner.py      Runner do ADK e sessões
  repositories/
    extratos.py    extrato do cliente no BigQuery (ou CSV local)
adk_agents/        entrada para `adk web` (Agent Platform / Antigravity / VS Code)
scripts/           gerador de dados sintéticos para teste local
deploy.sh          deploy no Cloud Run (Artifact Registry + Cloud Build + Cloud Run)
```

Regra das camadas: `routes -> controllers -> services / agents -> repositories`. Uma camada só chama a
de baixo. Os services não conhecem FastAPI; o único que chama o Gemini é o `midia.py` (transcrição do
áudio e leitura da foto), porque é conversão de mídia, não conversa com o cliente.

## Princípio

O chat é feito de agentes Gemini que decidem, recomendam e escrevem; os números
vêm de tools que buscam o extrato no BigQuery e calculam em código (`tools.py`,
`simulacao.py`, `engine.py`). Quais produtos podem
aparecer e se há oferta é decidido pelas regras de `produtos.py`, não pelo LLM. As regras da Res. Conjunta nº 8 estão no prompt de cada agente e os guardrails
de saída conferem cada resposta em código antes de ela chegar ao cliente.

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
