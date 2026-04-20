"""
enviar_pedido.py
================
Le um arquivo JSON de pedido gerado pelo Dashboard de Estoque
(baixado em ~/Downloads) e cria o(s) pedido(s) de compra no VR Master.

Uso:
    python enviar_pedido.py                   # pega o mais recente em ~/Downloads
    python enviar_pedido.py <caminho.json>    # arquivo especifico
    python enviar_pedido.py --dry-run         # simula sem gravar

Situacao do pedido: DIGITADO (id=1). Para revisar/finalizar,
abra no VR Master -> Estoque -> Consulta de Pedido de Compra.
"""
import os
import sys
import glob
import json
from datetime import datetime, date
from decimal import Decimal

import psycopg2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS


def conectar():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS, connect_timeout=15
    )


def encontrar_json_mais_recente():
    downloads = os.path.expanduser('~/Downloads')
    candidatos = glob.glob(os.path.join(downloads, 'pedido_vrmaster_*.json'))
    if not candidatos:
        # tambem procurar no diretorio atual e no do script
        candidatos = (glob.glob('pedido_vrmaster_*.json') +
                      glob.glob(os.path.join(BASE_DIR, 'pedido_vrmaster_*.json')))
    if not candidatos:
        raise SystemExit(
            'Nenhum arquivo pedido_vrmaster_*.json encontrado.\n'
            'Gere o arquivo no dashboard (botao "Gerar Pedido VR").'
        )
    return max(candidatos, key=os.path.getmtime)


def buscar_custos_embalagens(cur, id_loja, id_fornecedor, ids_produtos):
    """Retorna {id_produto: (custocomimposto, qtdembalagem)}."""
    cur.execute("""
        SELECT pc.id_produto,
               COALESCE(pc.custocomimposto, 0) as custo,
               COALESCE(pf.qtdembalagem, 1) as emb
        FROM produtocomplemento pc
        LEFT JOIN produtofornecedor pf
            ON pc.id_produto = pf.id_produto AND pf.id_fornecedor = %s
        WHERE pc.id_produto = ANY(%s) AND pc.id_loja = %s
    """, (id_fornecedor, ids_produtos, id_loja))
    return {r[0]: (float(r[1] or 0), int(r[2] or 1)) for r in cur.fetchall()}


def inserir_pedido(cur, pedido, payload):
    """Insere um pedido (cabecalho + itens) e retorna id_pedido gerado."""
    id_forn = pedido['id_fornecedor']
    itens = pedido['itens']
    ids_prod = [it['id_produto'] for it in itens]

    custo_emb = buscar_custos_embalagens(
        cur, payload['id_loja'], id_forn, ids_prod
    )

    # Calcular valor total
    valor_total = Decimal('0')
    for it in itens:
        cu, _ = custo_emb.get(it['id_produto'], (0, 1))
        valor_total += Decimal(str(cu)) * Decimal(str(it['quantidade']))
    valor_total = valor_total.quantize(Decimal('0.01'))

    # Insert cabecalho
    cur.execute("""
        INSERT INTO pedido (
            id_loja, id_fornecedor, id_tipofretepedido, datacompra,
            valortotal, id_situacaopedido, desconto, id_comprador,
            id_divisaofornecedor, valordesconto, email,
            id_tipoatendidopedido, enviado, gerousugestao, conferido
        ) VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, 0, false, %s, false, false, false)
        RETURNING id
    """, (
        payload['id_loja'], id_forn, payload['id_tipofretepedido'],
        payload['data_compra'], valor_total, payload['id_situacaopedido'],
        payload['id_comprador'], payload['id_divisaofornecedor'],
        payload['id_tipoatendidopedido']
    ))
    id_pedido = cur.fetchone()[0]

    # Insert itens
    for it in itens:
        cu, em = custo_emb.get(it['id_produto'], (0, 1))
        qtd = Decimal(str(it['quantidade']))
        valor_item = (Decimal(str(cu)) * qtd).quantize(Decimal('0.01'))
        cur.execute("""
            INSERT INTO pedidoitem (
                id_loja, id_pedido, id_produto, quantidade,
                qtdembalagem, custocompra, dataentrega, desconto,
                valortotal, quantidadeatendida, id_tipopedido,
                custofinal, id_tipoatendidopedido,
                custoverba, valorrebaixa
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, 0, 0, %s, %s, 0, 0)
        """, (
            payload['id_loja'], id_pedido, it['id_produto'], qtd,
            em, cu, payload['data_compra'], valor_item,
            cu, payload['id_tipoatendidopedido']
        ))

    return id_pedido, float(valor_total)


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    args = [a for a in args if not a.startswith('--')]
    path = args[0] if args else encontrar_json_mais_recente()

    print(f'Arquivo: {path}')
    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    print(f"Data compra:    {payload['data_compra']}")
    print(f"Loja:           {payload['id_loja']}")
    print(f"Comprador:      {payload['id_comprador']}")
    print(f"Situacao:       {payload['id_situacaopedido']} (1=DIGITADO)")
    print(f"Pedidos:        {len(payload['pedidos'])} fornecedor(es)")
    total_itens = sum(len(p['itens']) for p in payload['pedidos'])
    print(f"Itens totais:   {total_itens}")
    print()

    conn = conectar()
    cur = conn.cursor()

    try:
        pedidos_criados = []
        for pedido in payload['pedidos']:
            print(f">>> {pedido['fornecedor_nome']} (id {pedido['id_fornecedor']})")
            for it in pedido['itens'][:5]:
                print(f"    {it['id_produto']:>6} - qtd {it['quantidade']}"
                      + (f"  {it.get('descricao','')[:45]}" if it.get('descricao') else ''))
            if len(pedido['itens']) > 5:
                print(f"    ... +{len(pedido['itens']) - 5} itens")

            if dry_run:
                print("    [DRY-RUN] nao gravou no banco")
                continue

            id_pedido, vt = inserir_pedido(cur, pedido, payload)
            pedidos_criados.append((id_pedido, pedido['fornecedor_nome'],
                                    len(pedido['itens']), vt))
            print(f"    Pedido #{id_pedido} criado (R$ {vt:,.2f})")
            print()

        if dry_run:
            conn.rollback()
            print("\n[DRY-RUN] Nada foi gravado. Remova --dry-run para efetivar.")
        else:
            conn.commit()
            print("\n" + "=" * 60)
            print(f" {len(pedidos_criados)} PEDIDO(S) CRIADO(S) NO VR MASTER")
            print("=" * 60)
            for id_ped, forn, n, vt in pedidos_criados:
                print(f"  #{id_ped:<6}  {forn:<45}  {n:>3} itens  R$ {vt:>11,.2f}")
            print("\nRevise/finalize em: VR Master -> Estoque -> Consulta Pedido de Compra")

            # Arquivar o JSON processado
            arquivados_dir = os.path.join(BASE_DIR, 'pedidos_enviados')
            os.makedirs(arquivados_dir, exist_ok=True)
            dest = os.path.join(arquivados_dir, os.path.basename(path))
            try:
                os.replace(path, dest)
                print(f"\nArquivo arquivado em: {dest}")
            except Exception as e:
                print(f"\n(nao foi possivel arquivar o JSON: {e})")

    except Exception as e:
        conn.rollback()
        print(f'\nERRO: {e}')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
