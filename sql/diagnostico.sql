-- Rode no BigQuery Studio antes do deploy para confirmar as premissas do motor.

-- 1) Quais valores existem em `tipo`? (o motor assume 'S' = saída; ajuste TIPO_SAIDA se preciso)
SELECT tipo, COUNT(*) n, ROUND(SUM(vlr), 2) total, MIN(vlr) minimo, MAX(vlr) maximo
FROM `batalha-time-01-97zr.hackathon_dados.extrato_sintetico`
GROUP BY tipo;

-- 2) Janela de tempo, clientes e parcelamentos
SELECT MIN(anomesdia) inicio, MAX(anomesdia) fim,
       COUNT(DISTINCT id_usuario) clientes,
       COUNTIF(parcela_total > 1) linhas_parceladas,
       COUNT(DISTINCT IF(saldo_apos < 0, id_usuario, NULL)) clientes_ja_negativos
FROM `batalha-time-01-97zr.hackathon_dados.extrato_sintetico`;

-- 3) Categorias mais comuns
SELECT tipo, nom_cate_macro, nom_cate_micro, COUNT(*) n, ROUND(AVG(vlr), 2) ticket
FROM `batalha-time-01-97zr.hackathon_dados.extrato_sintetico`
GROUP BY 1, 2, 3 ORDER BY n DESC LIMIT 40;
