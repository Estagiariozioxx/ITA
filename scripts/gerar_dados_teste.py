"""Gera um CSV sintético no MESMO formato da tabela do hackathon, para testar sem GCP.

    python scripts/gerar_dados_teste.py  ->  data/extrato_amostra.csv
"""
import csv
import datetime as dt
import os
import random

random.seed(7)
SAIDA, ENTRADA = "S", "E"


def gerar_usuario(uid, salario, aluguel, saldo_ini, parcelas, var_dia):
    linhas, saldo = [], saldo_ini
    d, fim = dt.date(2025, 1, 1), dt.date(2025, 6, 30)
    while d <= fim:
        mov = []
        if d.day == 15:
            mov.append((ENTRADA, "salario", salario, "Renda", "Salário", None, None))
        if d.day == 10:
            mov.append((SAIDA, "aluguel", aluguel, "Moradia", "Aluguel", None, None))
        if d.day == 20:
            mov.append((SAIDA, "conta de luz", round(random.uniform(120, 180), 2), "Moradia", "Energia", None, None))
        if d.day == 5:
            mov.append((SAIDA, "assin apple tv", 29.9, "Assinaturas", "Assinaturas", None, None))
        for descr, valor, inicio, total, dia in parcelas:
            k = (d.year - inicio.year) * 12 + d.month - inicio.month + 1
            if d.day == dia and 1 <= k <= total:
                mov.append((SAIDA, descr, valor, "Compras", "Eletrônicos", k, total))
        if random.random() < 0.8:
            mov.append((SAIDA, random.choice(["ifood", "mercado", "uber", "farmacia", "padaria"]),
                        round(random.uniform(0.4, 1.8) * var_dia, 2), "Consumo", "Diversos", None, None))
        for tipo, descr, vlr, macro, micro, pa, pt in mov:
            saldo += vlr if tipo == ENTRADA else -vlr
            linhas.append({
                "id_usuario": uid, "anomesdia": f"{d.isoformat()} 00:00:00 UTC",
                "anomes": d.year * 100 + d.month, "tipo": tipo, "descr": descr, "vlr": vlr,
                "nom_cate_macro": macro, "nom_cate_micro": micro, "saldo_apos": round(saldo, 2),
                "parcela_atual": pa, "parcela_total": pt,
            })
        d += dt.timedelta(days=1)
    return linhas


def main():
    rows = []
    # Camila: aperto depois do aluguel, 2 parcelas terminando em ~2 meses
    rows += gerar_usuario("camila-demo", 3800, 1300, 900,
                          [("magazine tv", 190, dt.date(2024, 9, 1), 12, 8),
                           ("loja roupas", 190, dt.date(2024, 9, 1), 11, 8)], 38)
    # Folgado: sobra dinheiro todo mês
    rows += gerar_usuario("folgado-demo", 7000, 1800, 3000, [], 45)
    # Endividado: sempre no negativo
    rows += gerar_usuario("aperto-demo", 2500, 1200, 100,
                          [("celular", 250, dt.date(2025, 2, 1), 12, 8)], 35)
    os.makedirs("data", exist_ok=True)
    with open("data/extrato_amostra.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} linhas em data/extrato_amostra.csv")


if __name__ == "__main__":
    main()
