"""
Consulta direta ao banco PostgreSQL do VR Master.
Substitui a automacao visual — muito mais rapido e confiavel.
"""
import psycopg2
from datetime import datetime, date

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS


def conectar():
    """Conecta ao banco PostgreSQL do VR Master."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        connect_timeout=15,
    )


def obter_tabela_venda(data_consulta=None):
    """
    Retorna o nome da tabela de vendas para o mes/ano.
    O VR Master particiona vendas por mes: venda012026, venda022026, etc.
    """
    if data_consulta is None:
        data_consulta = date.today()
    mes = f"{data_consulta.month:02d}"
    ano = data_consulta.year
    return f"venda{mes}{ano}"


def consultar_vendas_por_produto(data_consulta=None):
    """
    Consulta vendas agrupadas por produto para uma data especifica.
    Retorna lista de dicts com os dados de cada produto.
    Equivalente a: Consulta Venda PDV > Exibicao: PRODUTO
    """
    if data_consulta is None:
        data_consulta = date.today()

    tabela_venda = obter_tabela_venda(data_consulta)

    conn = conectar()
    cur = conn.cursor()

    # Verificar se a tabela existe
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = %s AND table_schema = 'public'
        )
    """, (tabela_venda,))

    if not cur.fetchone()[0]:
        conn.close()
        raise ValueError(f"Tabela {tabela_venda} nao existe no banco.")

    # Query principal - replica a tela "Consulta de Venda PDV" com Exibicao PRODUTO
    query = f"""
        SELECT
            v.id_produto,
            p.descricaocompleta as descricao,
            SUM(v.quantidade) as quantidade,
            ROUND(AVG(v.precovenda), 2) as preco_venda,
            ROUND(SUM(v.valortotal), 2) as venda_bruta,
            ROUND(SUM(v.valortotal), 2) as venda_liquida,
            CASE WHEN SUM(v.valortotal) > 0
                THEN ROUND(
                    (SUM(v.valortotal) - SUM(v.custosemimposto * v.quantidade))
                    / NULLIF(SUM(v.valortotal), 0) * 100
                , 2)
                ELSE 0
            END as margem_liquida,
            CASE WHEN SUM(v.valortotal) > 0
                THEN ROUND(
                    (SUM(v.valortotal) - SUM(v.custocomimposto * v.quantidade))
                    / NULLIF(SUM(v.valortotal), 0) * 100
                , 2)
                ELSE 0
            END as margem_bruta,
            CASE WHEN SUM(v.custosemimposto * v.quantidade) > 0
                THEN ROUND(
                    (SUM(v.valortotal) - SUM(v.custosemimposto * v.quantidade))
                    / NULLIF(SUM(v.custosemimposto * v.quantidade), 0) * 100
                , 2)
                ELSE 0
            END as margem_sb_custo,
            CASE WHEN SUM(v.valortotal) > 0
                THEN ROUND(
                    (SUM(v.valortotal) - SUM(v.custosemimposto * v.quantidade))
                    / NULLIF(SUM(v.valortotal), 0) * 100
                , 2)
                ELSE 0
            END as margem_sb_venda
        FROM {tabela_venda} v
        JOIN produto p ON v.id_produto = p.id
        WHERE v.data = %s
        GROUP BY v.id_produto, p.descricaocompleta
        ORDER BY margem_sb_venda ASC
    """

    cur.execute(query, (data_consulta,))

    colunas = [desc[0] for desc in cur.description]
    resultados = []
    for row in cur.fetchall():
        item = dict(zip(colunas, row))
        # Converter Decimal para float
        for k, v in item.items():
            if hasattr(v, 'is_finite'):  # Decimal
                item[k] = float(v)
        resultados.append(item)

    # Totais
    total_venda = sum(r['venda_bruta'] for r in resultados)
    total_qtd = sum(r['quantidade'] for r in resultados)

    conn.close()

    return resultados, {
        'data': data_consulta,
        'total_produtos': len(resultados),
        'total_venda_bruta': total_venda,
        'total_quantidade': total_qtd,
    }


def obter_data_mais_recente():
    """Retorna a data mais recente com vendas no mes atual."""
    tabela_venda = obter_tabela_venda()
    conn = conectar()
    cur = conn.cursor()

    try:
        cur.execute(f"SELECT MAX(data) FROM {tabela_venda}")
        resultado = cur.fetchone()
        return resultado[0] if resultado else None
    finally:
        conn.close()


def consultar_vendas_pdv_realtime(data_consulta=None):
    """
    Consulta vendas PDV em tempo real via logestoque (tipo 4 = VENDA).
    Nao depende de fechamento de caixa.
    Usa precovenda do cadastro + custo do logestoque para calcular margem.
    Margem sobre venda = (PV - Custo) / PV * 100
    """
    if data_consulta is None:
        data_consulta = date.today()

    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            le.id_produto,
            p.descricaocompleta as descricao,
            SUM(le.quantidade) as quantidade,
            ROUND(pc.precovenda, 2) as preco_venda,
            ROUND(SUM(le.quantidade * pc.precovenda), 2) as venda_bruta,
            ROUND(SUM(le.quantidade * pc.precovenda), 2) as venda_liquida,
            CASE WHEN pc.precovenda > 0
                THEN ROUND(
                    (pc.precovenda - AVG(le.custosemimposto))
                    / NULLIF(pc.precovenda, 0) * 100
                , 2)
                ELSE 0
            END as margem_liquida,
            CASE WHEN pc.precovenda > 0
                THEN ROUND(
                    (pc.precovenda - AVG(le.custocomimposto))
                    / NULLIF(pc.precovenda, 0) * 100
                , 2)
                ELSE 0
            END as margem_bruta,
            CASE WHEN AVG(le.custosemimposto) > 0
                THEN ROUND(
                    (pc.precovenda - AVG(le.custosemimposto))
                    / NULLIF(AVG(le.custosemimposto), 0) * 100
                , 2)
                ELSE 0
            END as margem_sb_custo,
            CASE WHEN pc.precovenda > 0
                THEN ROUND(
                    (pc.precovenda - AVG(le.custosemimposto))
                    / NULLIF(pc.precovenda, 0) * 100
                , 2)
                ELSE 0
            END as margem_sb_venda
        FROM logestoque le
        JOIN produto p ON le.id_produto = p.id
        JOIN produtocomplemento pc ON le.id_produto = pc.id_produto AND pc.id_loja = 1
        WHERE le.datamovimento = %s
          AND le.id_tipomovimentacao = 4
          AND le.quantidade > 0
          AND pc.precovenda > 0
        GROUP BY le.id_produto, p.descricaocompleta, pc.precovenda
        HAVING SUM(le.quantidade) >= 0.5
        ORDER BY margem_sb_venda ASC
    """, (data_consulta,))

    colunas = [desc[0] for desc in cur.description]
    resultados = []
    for row in cur.fetchall():
        item = dict(zip(colunas, row))
        for k, v in item.items():
            if hasattr(v, 'is_finite'):
                item[k] = float(v)
        resultados.append(item)

    total_venda = sum(r['venda_bruta'] for r in resultados)
    total_qtd = sum(r['quantidade'] for r in resultados)

    conn.close()

    return resultados, {
        'data': data_consulta,
        'total_produtos': len(resultados),
        'total_venda_bruta': total_venda,
        'total_quantidade': total_qtd,
        'fonte': 'logestoque_realtime',
    }


if __name__ == "__main__":
    # Teste
    data = obter_data_mais_recente()
    print(f"Data mais recente com vendas: {data}")

    if data:
        produtos, totais = consultar_vendas_por_produto(data)
        print(f"\nTotal produtos: {totais['total_produtos']}")
        print(f"Total venda: R$ {totais['total_venda_bruta']:,.2f}")

        print(f"\nPrimeiros 10 (menor margem):")
        print(f"{'COD':>6} {'DESCRICAO':42s} {'QTD':>6} {'VENDA':>10} {'MG.VDA':>8}")
        print("-" * 78)
        for p in produtos[:10]:
            print(f"{p['id_produto']:>6} {str(p['descricao'])[:42]:42s} "
                  f"{p['quantidade']:>6.0f} {p['venda_bruta']:>10.2f} "
                  f"{p['margem_sb_venda']:>7.2f}%")
