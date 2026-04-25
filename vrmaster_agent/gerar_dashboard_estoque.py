"""
Gera dashboard HTML de gestao de estoque (DDV) para colaboradores.
- Visao por Mercadologico e Fornecedor
- Alertas de ruptura (DDV baixo) e excesso de estoque
- Melhores praticas de gestao
"""
import os
import sys
import json
import math
import logging
from datetime import datetime, date, timedelta
from collections import defaultdict

import psycopg2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS, ID_LOJA

LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"dashboard_estoque_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# DDV ideal por setor (dias) - pode calibrar depois
DDV_IDEAL = {
    'ACOUGUE': 5,
    'PADARIA': 3,
    'HORTIFRUTI': 4,
    'PERECIVEIS DO AUTOSERVICO': 10,
    'BEBIDAS': 15,
    'MERCEARIA DOCE': 20,
    'MERCEARIA SALGADA': 20,
    'COMMODITIES': 25,
    'LIMPEZA': 25,
    'HIGIENE E PERFUMARIA': 25,
    'BAZAR': 30,
    'PROCESSADOS': 15,
}
DDV_IDEAL_PADRAO = 15

# Excesso: DDV acima deste multiplicador do ideal = excesso
FATOR_EXCESSO = 3.0


def conectar():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS, connect_timeout=15
    )


def buscar_dados():
    """Busca todos os dados necessarios para o dashboard."""
    conn = conectar()
    cur = conn.cursor()

    # 1. Estoque em tempo real (produtocomplemento) + mercadologico
    logger.info("Buscando estoque em tempo real (produtocomplemento)...")
    cur.execute("""
        SELECT
            pc.id_produto,
            p.descricaocompleta,
            COALESCE(m1.descricao, 'SEM SETOR') as setor,
            COALESCE(m2.descricao, 'SEM CATEGORIA') as categoria,
            pc.estoque,
            pc.custocomimposto,
            pc.customediocomimposto,
            pc.dataultimaentrada,
            pc.dataultimavenda,
            pc.precovenda
        FROM produtocomplemento pc
        JOIN produto p ON pc.id_produto = p.id
        LEFT JOIN mercadologico m1
            ON p.mercadologico1 = m1.mercadologico1 AND m1.nivel = 1
        LEFT JOIN mercadologico m2
            ON p.mercadologico1 = m2.mercadologico1
            AND p.mercadologico2 = m2.mercadologico2 AND m2.nivel = 2
        WHERE pc.id_loja = %s
          AND pc.id_situacaocadastro = 1
    """, (ID_LOJA,))

    produtos_raw = []
    prod_ids = []
    for row in cur.fetchall():
        produtos_raw.append({
            'id': row[0],
            'desc': row[1] or '',
            'setor': row[2],
            'cat': row[3],
            'est': float(row[4] or 0),
            'custo': float(row[5] or 0),
            'custo_medio': float(row[6] or 0),
            'ult_entrada_data': row[7],
            'ult_venda_data': row[8],
            'preco_venda': float(row[9] or 0),
        })
        prod_ids.append(row[0])

    # 2. Calcular VMD pelos ultimos 7 dias de vendas (igual ao VR tipo PADRAO)
    logger.info("Calculando VMD (vendas ultimos 7 dias)...")
    from datetime import date as _date
    hoje = _date.today()
    data_7d = hoje - timedelta(days=7)

    # Determinar tabelas de venda necessarias
    tabelas_venda = set()
    for d in [hoje, data_7d]:
        tabelas_venda.add(f"venda{d.month:02d}{d.year}")

    # Verificar quais tabelas existem
    vmd_por_produto = {}
    for tabela in tabelas_venda:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = %s AND table_schema = 'public'
            )
        """, (tabela,))
        if not cur.fetchone()[0]:
            continue

        cur.execute(f"""
            SELECT id_produto, SUM(quantidade) as total
            FROM {tabela}
            WHERE data >= %s
            GROUP BY id_produto
        """, (data_7d,))
        for row in cur.fetchall():
            pid = row[0]
            vmd_por_produto[pid] = vmd_por_produto.get(pid, 0) + float(row[1])

    # Converter total 7d para VMD
    for pid in vmd_por_produto:
        vmd_por_produto[pid] = round(vmd_por_produto[pid] / 7, 3)

    # Calcular faturamento 30 dias para curva ABC
    logger.info("Calculando curva ABC (faturamento 30 dias)...")
    data_30d = hoje - timedelta(days=30)
    tabelas_30d = set()
    for d in [hoje, data_30d]:
        tabelas_30d.add(f"venda{d.month:02d}{d.year}")

    fat_por_produto = {}
    for tabela in tabelas_30d:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = %s AND table_schema = 'public'
            )
        """, (tabela,))
        if not cur.fetchone()[0]:
            continue
        cur.execute(f"""
            SELECT id_produto, SUM(valortotal) as total
            FROM {tabela}
            WHERE data >= %s
            GROUP BY id_produto
        """, (data_30d,))
        for row in cur.fetchall():
            pid = row[0]
            fat_por_produto[pid] = fat_por_produto.get(pid, 0) + float(row[1])

    # Classificar curva ABC
    fat_ordenado = sorted(fat_por_produto.items(), key=lambda x: -x[1])
    total_fat = sum(v for _, v in fat_ordenado)
    curva_abc = {}
    acum = 0
    for pid, fat in fat_ordenado:
        acum += fat
        pct = acum / total_fat * 100 if total_fat > 0 else 100
        if pct <= 80:
            curva_abc[pid] = 'A'
        elif pct <= 95:
            curva_abc[pid] = 'B'
        else:
            curva_abc[pid] = 'C'

    # Montar lista final de produtos
    produtos = []
    for p in produtos_raw:
        vmd = vmd_por_produto.get(p['id'], 0)
        if vmd < 0.01 and p['est'] <= 0:
            continue  # Sem venda e sem estoque = irrelevante

        ddv = round(p['est'] / vmd, 1) if vmd > 0 and p['est'] >= 0 else None
        p['vmd'] = vmd
        p['ddv'] = ddv
        p['curva'] = curva_abc.get(p['id'], 'C')
        p['fat30d'] = fat_por_produto.get(p['id'], 0)
        produtos.append(p)

    # 2. Embalagem por produto/fornecedor
    logger.info("Buscando embalagens por fornecedor...")
    cur.execute("""
        SELECT pf.id_produto, pf.id_fornecedor, pf.qtdembalagem
        FROM produtofornecedor pf
        WHERE pf.qtdembalagem > 0
    """)
    embalagens = {}
    for row in cur.fetchall():
        embalagens[(row[0], row[1])] = int(row[2])

    # 3. Fornecedores por produto (ultimo que entregou) + data ultima entrada real
    logger.info("Buscando fornecedores e ultima entrada real...")
    cur.execute("""
        SELECT DISTINCT ON (nei.id_produto)
            nei.id_produto, ne.id_fornecedor, f.razaosocial, ne.dataentrada
        FROM notaentradaitem nei
        JOIN notaentrada ne ON nei.id_notaentrada = ne.id
        JOIN fornecedor f ON ne.id_fornecedor = f.id
        ORDER BY nei.id_produto, ne.dataentrada DESC
    """)
    fornecedores = {}
    ultima_entrada_real = {}  # {id_produto: date}
    for row in cur.fetchall():
        fornecedores[row[0]] = {
            'id_forn': row[1],
            'nome': row[2],
            'ultima_entrada': row[3].strftime('%d/%m') if row[3] else '',
            'ultima_entrada_date': row[3],
        }
        ultima_entrada_real[row[0]] = row[3]

    # 3. Lead times
    logger.info("Calculando lead times...")
    cur.execute("""
        WITH entradas_seq AS (
            SELECT ne.id_fornecedor, ne.dataentrada,
                   LAG(ne.dataentrada) OVER (
                       PARTITION BY ne.id_fornecedor ORDER BY ne.dataentrada
                   ) as data_anterior
            FROM notaentrada ne
            WHERE ne.dataentrada >= CURRENT_DATE - INTERVAL '90 days'
        )
        SELECT id_fornecedor,
               ROUND(AVG(dataentrada - data_anterior), 0) as intervalo_medio
        FROM entradas_seq
        WHERE data_anterior IS NOT NULL
          AND (dataentrada - data_anterior) > 0
          AND (dataentrada - data_anterior) < 60
        GROUP BY id_fornecedor
        HAVING COUNT(*) >= 2
    """)
    lead_times = {}
    for row in cur.fetchall():
        lead_times[row[0]] = int(row[1])

    # 4. Padrao historico de entradas: qtd mediana por entrada + num de entradas (180d)
    logger.info("Analisando padrao historico de entradas...")
    cur.execute("""
        WITH ent AS (
            SELECT nei.id_produto, nei.quantidade
            FROM notaentradaitem nei
            JOIN notaentrada ne ON nei.id_notaentrada = ne.id
            WHERE ne.dataentrada >= CURRENT_DATE - INTERVAL '180 days'
              AND nei.quantidade > 0
        )
        SELECT id_produto,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY quantidade) as qtd_mediana,
               COUNT(*) as num_entradas,
               MAX(quantidade) as qtd_max
        FROM ent
        GROUP BY id_produto
        HAVING COUNT(*) >= 2
    """)
    padrao_entrada = {}
    for row in cur.fetchall():
        padrao_entrada[row[0]] = {
            'qtd_mediana': float(row[1]) if row[1] is not None else 0,
            'num_entradas': int(row[2]),
            'qtd_max': float(row[3]) if row[3] is not None else 0,
        }

    conn.close()

    # Separar produtos obsoletos (sem entrada nos ultimos 12 meses)
    data_limite_obsoleto = hoje - timedelta(days=365)
    produtos_ativos = []
    produtos_obsoletos = []

    # Enriquecer produtos com fornecedor e lead time
    for p in produtos:
        f = fornecedores.get(p['id'], {})
        p['forn'] = f.get('nome', 'SEM FORNECEDOR')
        p['forn_curto'] = p['forn'][:30]
        p['ult_entrada'] = f.get('ultima_entrada', '')
        p['ult_entrada_date'] = f.get('ultima_entrada_date')
        id_forn = f.get('id_forn')
        p['id_forn'] = id_forn
        p['lead_time'] = lead_times.get(id_forn, 7) if id_forn else 7

        # Verificar se e obsoleto (sem entrada nos ultimos 12 meses)
        ue_date = ultima_entrada_real.get(p['id'])
        if ue_date is None or ue_date < data_limite_obsoleto:
            p['status'] = 'obsoleto'
            p['dias_sem_entrada'] = (hoje - ue_date).days if ue_date else None
            p['ddv_ideal'] = DDV_IDEAL.get(p['setor'], DDV_IDEAL_PADRAO)
            p['valor_estoque'] = p['est'] * p['custo'] if p['est'] > 0 else 0
            p['qtd_comprar'] = 0
            p['embalagem'] = 1
            produtos_obsoletos.append(p)
            continue

        # Classificar produtos ativos normalmente
        ddv_ideal = DDV_IDEAL.get(p['setor'], DDV_IDEAL_PADRAO)
        p['ddv_ideal'] = ddv_ideal
        if p['est'] < 0:
            p['status'] = 'negativo'
        elif p['ddv'] is not None and p['ddv'] <= p['lead_time']:
            p['status'] = 'ruptura'
        elif p['ddv'] is not None and p['ddv'] <= (p['lead_time'] + 3):
            p['status'] = 'alerta'
        elif p['ddv'] is not None and p['ddv'] > (ddv_ideal * FATOR_EXCESSO):
            p['status'] = 'excesso'
        else:
            p['status'] = 'ok'

        # Valor em estoque
        p['valor_estoque'] = p['est'] * p['custo'] if p['est'] > 0 else 0

        # Embalagem e padrao historico de entradas
        id_forn = f.get('id_forn')
        emb = embalagens.get((p['id'], id_forn), 1) if id_forn else 1
        p['embalagem'] = emb

        pe = padrao_entrada.get(p['id'])
        if pe:
            p['qtd_tipica'] = pe['qtd_mediana']
            p['num_entradas'] = pe['num_entradas']
            p['dias_cobertura'] = round(pe['qtd_mediana'] / p['vmd'], 0) if p['vmd'] > 0 else None
        else:
            p['qtd_tipica'] = None
            p['num_entradas'] = 0
            p['dias_cobertura'] = None

        # Qtd sugerida: combina formula DDV com padrao historico
        # - Base: (DDV ideal * VMD) - estoque atual
        # - Se ha padrao historico estavel (>=2 entradas) e cobre ao menos o lead time,
        #   usa a mediana historica como piso (respeita o que ja funciona com o fornecedor)
        if p['vmd'] > 0 and p['status'] in ('ruptura', 'alerta', 'negativo'):
            qtd_ideal = ddv_ideal * p['vmd']
            qtd_base = max(0, qtd_ideal - max(0, p['est']))

            if (p['qtd_tipica'] and p['dias_cobertura'] is not None
                    and p['dias_cobertura'] >= p['lead_time']
                    and p['dias_cobertura'] <= ddv_ideal * FATOR_EXCESSO):
                # Padrao historico razoavel — usa como piso
                qtd_base = max(qtd_base, p['qtd_tipica'])

            if emb > 1:
                qtd_comprar = -(-int(qtd_base) // emb) * emb  # ceil division
            else:
                qtd_comprar = max(1, int(qtd_base + 0.99))
            p['qtd_comprar'] = qtd_comprar
        else:
            p['qtd_comprar'] = 0

        produtos_ativos.append(p)

    logger.info(f"{len(produtos_obsoletos)} produtos obsoletos (sem entrada ha 12+ meses)")
    return produtos_ativos, produtos_obsoletos


def gerar_estatisticas(produtos):
    """Gera resumos por setor e por fornecedor."""
    # Por setor
    setores = defaultdict(lambda: {
        'total': 0, 'ruptura': 0, 'alerta': 0, 'ok': 0, 'excesso': 0,
        'negativo': 0, 'valor_estoque': 0, 'valor_excesso': 0
    })
    for p in produtos:
        s = setores[p['setor']]
        s['total'] += 1
        s[p['status']] += 1
        s['valor_estoque'] += p['valor_estoque']
        if p['status'] == 'excesso':
            # Valor excedente = (estoque - ideal) * custo
            ideal_qtd = p['vmd'] * p['ddv_ideal']
            excedente = max(0, p['est'] - ideal_qtd)
            s['valor_excesso'] += excedente * p['custo']

    # Por fornecedor
    fornecedores = defaultdict(lambda: {
        'total': 0, 'ruptura': 0, 'alerta': 0, 'ok': 0, 'excesso': 0,
        'negativo': 0, 'lead_time': 0, 'valor_estoque': 0
    })
    for p in produtos:
        f = fornecedores[p['forn']]
        f['total'] += 1
        f[p['status']] += 1
        f['lead_time'] = p['lead_time']
        f['valor_estoque'] += p['valor_estoque']

    return dict(setores), dict(fornecedores)


def gerar_html(produtos, setores, fornecedores, obsoletos=None):
    """Gera o dashboard HTML completo — orientado a acao, mobile-first."""
    import json
    if obsoletos is None:
        obsoletos = []
    agora = datetime.now().strftime('%d/%m/%Y %H:%M')

    total = len(produtos)
    rupturas = sum(1 for p in produtos if p['status'] == 'ruptura')
    alertas = sum(1 for p in produtos if p['status'] == 'alerta')
    excessos = sum(1 for p in produtos if p['status'] == 'excesso')
    negativos = sum(1 for p in produtos if p['status'] == 'negativo')
    oks = total - rupturas - alertas - excessos - negativos
    n_obsoletos = len(obsoletos)
    valor_obsoletos = sum(p['valor_estoque'] for p in obsoletos)
    precisa_comprar = rupturas + negativos + alertas

    rupt_curva_a = sum(1 for p in produtos if p['status'] in ('ruptura','negativo') and p.get('curva') == 'A')
    alerta_curva_a = sum(1 for p in produtos if p['status'] == 'alerta' and p.get('curva') == 'A')

    valor_total = sum(p['valor_estoque'] for p in produtos)
    valor_excesso = sum(
        max(0, p['est'] - p['vmd'] * p['ddv_ideal']) * p['custo']
        for p in produtos if p['status'] == 'excesso'
    )

    produtos_json = json.dumps([{
        'cod': str(p['id']).zfill(6), 'id': p['id'], 'desc': p['desc'][:55],
        'setor': p['setor'], 'cat': p['cat'], 'forn': p['forn'], 'id_forn': p.get('id_forn'),
        'est': round(p['est'], 1), 'vmd': round(p['vmd'], 3),
        'ddv': round(p['ddv'], 1) if p['ddv'] is not None else None,
        'ddv_ideal': p['ddv_ideal'], 'lt': p['lead_time'], 'status': p['status'],
        'valor': round(p['valor_estoque'], 2), 'ult_entrada': p['ult_entrada'],
        'curva': p.get('curva', 'C'), 'fat30d': round(p.get('fat30d', 0), 2),
        'emb': p.get('embalagem', 1), 'qtd_comprar': p.get('qtd_comprar', 0),
        'qtd_tipica': round(p['qtd_tipica'], 0) if p.get('qtd_tipica') else None,
        'num_ent': p.get('num_entradas', 0),
        'cobertura': p.get('dias_cobertura'),
    } for p in produtos], ensure_ascii=False)

    obsoletos_json = json.dumps([{
        'cod': str(p['id']).zfill(6), 'id': p['id'], 'desc': p['desc'][:55],
        'setor': p['setor'], 'cat': p['cat'],
        'forn': p.get('forn', 'SEM FORNECEDOR'),
        'est': round(p['est'], 1), 'vmd': round(p.get('vmd', 0), 3),
        'valor': round(p.get('valor_estoque', 0), 2),
        'ult_entrada': p.get('ult_entrada', ''),
        'dias_sem_entrada': p.get('dias_sem_entrada'),
        'curva': p.get('curva', 'C'),
    } for p in obsoletos], ensure_ascii=False)

    setores_json = json.dumps({k: v for k, v in sorted(setores.items())}, ensure_ascii=False)
    fornecedores_json = json.dumps({
        k: v for k, v in sorted(fornecedores.items(), key=lambda x: -x[1]['ruptura'])
        if v['total'] >= 3
    }, ensure_ascii=False)

    ddv_ideal_html = "<br>".join(f'<b>{k}:</b> {v} dias' for k,v in sorted(DDV_IDEAL.items()))

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta http-equiv="refresh" content="900">
<title>MERKAL - Estoque</title>
<style>
:root{{--bg:#0a0a1a;--bg2:#111126;--bg3:#161638;--card:#141428;--sec:#0e1628;--accent:#4fc3f7;--danger:#ff4444;--warn:#ffaa00;--ok:#22cc66;--excess:#cc66ff;--muted:#888;--border:#1e3050;--text:#e8e8e8;--dim:#aaa;--radius:14px}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5;font-size:15px;-webkit-font-smoothing:antialiased;padding-bottom:72px}}
a{{color:var(--accent);text-decoration:none}}
.hdr{{background:linear-gradient(135deg,#0d0d24,#142040);padding:16px 24px;border-bottom:2px solid var(--accent);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;position:sticky;top:0;z-index:50;backdrop-filter:blur(10px)}}
.hdr h1{{color:var(--accent);font-size:1.3em;font-weight:800;letter-spacing:-.3px}}
.hdr .upd{{color:var(--muted);font-size:.78em}}
.wrap{{max-width:1600px;margin:0 auto;padding:16px 20px}}
.kpis-action{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:16px 0 12px}}
.kpi-lg{{background:var(--card);border-radius:var(--radius);padding:20px;cursor:pointer;transition:all .2s;overflow:hidden}}
.kpi-lg:hover{{transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,0,0,.5)}}
.kpi-lg.dng{{border:2px solid var(--danger)}}.kpi-lg.exc{{border:2px solid var(--excess)}}
.kpi-lg .n{{font-size:2.8em;font-weight:900;color:#fff;line-height:1}}
.kpi-lg .l{{font-size:.82em;color:var(--dim);margin-top:4px;font-weight:600}}
.kpi-lg .s{{font-size:.75em;color:var(--muted);margin-top:2px}}
.kpi-lg .cta{{display:inline-block;margin-top:10px;padding:6px 16px;border-radius:20px;font-size:.75em;font-weight:700;text-transform:uppercase;letter-spacing:.5px}}
.kpi-lg.dng .cta{{background:var(--danger);color:#fff}}.kpi-lg.exc .cta{{background:var(--excess);color:#fff}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.7}}}}
.kpi-lg.dng .n{{animation:pulse 2s ease-in-out infinite}}
.kpis-info{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:18px}}
.kpi-sm{{background:var(--card);border-radius:12px;padding:14px 10px;text-align:center;cursor:pointer;transition:all .15s;border-top:3px solid transparent}}
.kpi-sm:hover{{transform:translateY(-1px);box-shadow:0 4px 15px rgba(0,0,0,.4)}}
.kpi-sm .n{{font-size:1.6em;font-weight:800;color:#fff;line-height:1}}
.kpi-sm .l{{font-size:.65em;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-top:3px;font-weight:600}}
.nav{{display:flex;gap:2px;background:var(--bg2);border-radius:var(--radius) var(--radius) 0 0;padding:6px 6px 0;flex-wrap:wrap}}
.nav a{{padding:12px 22px;color:var(--muted);font-size:.85em;font-weight:600;border-radius:10px 10px 0 0;cursor:pointer;transition:all .15s;display:flex;align-items:center;gap:6px;white-space:nowrap}}
.nav a:hover{{color:#ddd;background:var(--bg3)}}
.nav a.on{{color:var(--accent);background:var(--card);border-top:3px solid var(--accent)}}
.nav a .ic{{font-size:1.1em}}
.pane{{display:none;background:var(--card);border:1px solid #222;border-top:none;border-radius:0 0 var(--radius) var(--radius);padding:20px}}
.pane.on{{display:block}}
.sec{{background:var(--sec);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:16px}}
.sec-t{{font-size:1.1em;font-weight:700;color:var(--accent);margin-bottom:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.sec-t .cnt{{padding:4px 14px;border-radius:20px;font-size:.78em;font-weight:700}}
.cnt-r{{background:var(--danger);color:#fff}}.cnt-y{{background:var(--warn);color:#000}}.cnt-p{{background:var(--excess);color:#fff}}.cnt-b{{background:var(--accent);color:#000}}
.tw{{overflow-x:auto;border-radius:10px;-webkit-overflow-scrolling:touch}}
table{{width:100%;border-collapse:collapse;font-size:.88em;font-variant-numeric:tabular-nums}}
th{{background:#0c0c1c;color:var(--accent);padding:12px 10px;text-align:left;position:sticky;top:0;white-space:nowrap;user-select:none;cursor:pointer;border-bottom:2px solid var(--border);font-weight:700;font-size:.76em;text-transform:uppercase;letter-spacing:.5px}}
th:hover{{color:#fff;background:#0e0e2e}}
td{{padding:11px 10px;border-bottom:1px solid #1a1a30}}
tr:nth-child(even){{background:rgba(255,255,255,.015)}}
tr:hover{{background:rgba(79,195,247,.06)}}
tr.R{{background:rgba(255,60,60,.1)}}tr.R:hover{{background:rgba(255,60,60,.16)}}
tr.A{{background:rgba(255,170,0,.07)}}tr.A:hover{{background:rgba(255,170,0,.12)}}
tr.E{{background:rgba(200,100,255,.06)}}tr.N{{background:rgba(100,100,100,.06)}}
.b{{display:inline-flex;align-items:center;gap:4px;padding:4px 12px;border-radius:14px;font-size:.72em;font-weight:700;text-transform:uppercase;letter-spacing:.3px}}
.b-r{{background:rgba(255,68,68,.2);color:#ff6666;border:1px solid rgba(255,68,68,.3)}}
.b-a{{background:rgba(255,170,0,.15);color:#ffcc44;border:1px solid rgba(255,170,0,.25)}}
.b-o{{background:rgba(34,204,102,.12);color:var(--ok);border:1px solid rgba(34,204,102,.2)}}
.b-e{{background:rgba(204,102,255,.12);color:var(--excess);border:1px solid rgba(204,102,255,.2)}}
.b-n{{background:rgba(136,136,136,.15);color:#aaa;border:1px solid rgba(136,136,136,.2)}}
.c{{display:inline-block;padding:3px 10px;border-radius:6px;font-size:.72em;font-weight:800}}
.c-A{{background:#cc2020;color:#fff}}.c-B{{background:#b38600;color:#fff}}.c-C{{background:#2a2a40;color:#888}}
.dv{{display:inline-flex;align-items:center;gap:6px;font-weight:600}}
.dv-b{{width:55px;height:7px;background:#1a1a30;border-radius:4px;overflow:hidden}}
.dv-f{{height:100%;border-radius:4px;transition:width .3s}}
.fl{{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap;align-items:center}}
.fl select,.fl input{{background:var(--bg);color:#ddd;border:1px solid #333;padding:10px 14px;border-radius:10px;font-size:.88em;min-height:44px}}
.fl input{{min-width:240px;flex:1}}
.fl input::placeholder{{color:#666}}
.fl .btn-clear{{background:none;color:var(--muted);border:1px solid #333;padding:8px 16px;border-radius:10px;cursor:pointer;font-size:.82em;min-height:44px}}
.fl .btn-clear:hover{{color:#fff;border-color:#555}}
.cds{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
.cd{{background:var(--sec);border-radius:var(--radius);padding:18px;border:1px solid var(--border);cursor:pointer;transition:all .15s}}
.cd h3{{color:var(--accent);font-size:.95em;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center}}
.cd:hover{{border-color:var(--accent);box-shadow:0 4px 20px rgba(79,195,247,.12);transform:translateY(-1px)}}
.detail-panel{{grid-column:1/-1;background:#0a1020;border:1px solid var(--border);border-radius:0 0 12px 12px;padding:14px;margin-top:-1px}}
.cd .sts{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:8px;font-size:.82em}}
.cd .sts b{{font-weight:700}}
.cd .br{{height:6px;background:#1a1a30;border-radius:4px;display:flex;overflow:hidden;margin-top:8px}}
.cd .br div{{height:100%}}
.ped-hdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px}}
.ped-hdr h3{{color:var(--accent);font-size:1.05em;margin:0;font-weight:700}}
.ped-hdr .info{{color:var(--muted);font-size:.8em}}
.ped-sep{{border-top:2px solid var(--border);margin:24px 0;padding-top:18px}}
.btn-copy{{background:var(--bg);color:var(--accent);border:1px solid var(--accent);padding:6px 14px;border-radius:8px;cursor:pointer;font-size:.78em;font-weight:600;transition:all .15s}}
.btn-copy:hover{{background:var(--accent);color:#000}}
.btn-copy.ok{{background:var(--ok);color:#000;border-color:var(--ok)}}
.prs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}}
.pr{{background:var(--sec);border-radius:var(--radius);padding:20px;border-left:5px solid var(--accent)}}
.pr h3{{color:var(--accent);font-size:.95em;margin-bottom:10px}}.pr p{{color:#bbb;font-size:.85em;line-height:1.8}}.pr .t{{color:var(--warn);font-weight:700}}
.scroll-top{{position:fixed;bottom:80px;right:20px;width:44px;height:44px;border-radius:50%;background:var(--accent);color:#000;border:none;font-size:1.2em;cursor:pointer;display:none;align-items:center;justify-content:center;box-shadow:0 4px 15px rgba(0,0,0,.4);z-index:60}}
.scroll-top.show{{display:flex}}
@media(max-width:768px){{
body{{font-size:16px;padding-bottom:80px}}
.hdr{{padding:12px 16px}}.hdr h1{{font-size:1.15em}}
.wrap{{padding:10px 12px}}
.kpis-action{{grid-template-columns:1fr 1fr;gap:10px;margin:12px 0 10px}}
.kpi-lg{{padding:16px}}.kpi-lg .n{{font-size:2.2em}}.kpi-lg .cta{{padding:5px 12px;font-size:.7em}}
.kpis-info{{grid-template-columns:repeat(3,1fr);gap:8px}}
.kpi-sm{{padding:10px 6px}}.kpi-sm .n{{font-size:1.3em}}.kpi-sm .l{{font-size:.58em}}
.nav{{position:fixed;bottom:0;left:0;right:0;z-index:100;background:#0a0a20;border-top:2px solid var(--border);border-radius:0;padding:0;display:grid;grid-template-columns:repeat(5,1fr);gap:0;flex-wrap:nowrap}}
.nav a{{padding:6px 2px;text-align:center;font-size:.6em;border-radius:0;border-top:3px solid transparent;flex-direction:column;justify-content:center;min-height:56px}}
.nav a .ic{{font-size:1.5em;display:block;margin-bottom:1px}}
.nav a.on{{border-top-color:var(--accent);background:rgba(79,195,247,.08)}}
.nav a.hide-mobile{{display:none}}
.pane{{padding:14px 10px;border-radius:0 0 10px 10px}}
.sec{{padding:14px}}
.fl{{flex-direction:column}}.fl input,.fl select{{min-width:100%;font-size:16px}}
table.resp thead{{display:none}}
table.resp tbody tr{{display:block;margin-bottom:10px;border:1px solid var(--border);border-radius:12px;padding:14px;background:var(--sec)}}
table.resp tbody tr.R{{border-left:4px solid var(--danger)}}
table.resp tbody tr.A{{border-left:4px solid var(--warn)}}
table.resp tbody tr.E{{border-left:4px solid var(--excess)}}
table.resp tbody td{{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border:none;border-bottom:1px solid rgba(255,255,255,.04);font-size:.9em}}
table.resp tbody td:last-child{{border-bottom:none}}
table.resp tbody td::before{{content:attr(data-label);font-weight:700;color:var(--accent);font-size:.72em;text-transform:uppercase;letter-spacing:.3px;min-width:100px;flex-shrink:0}}
table.resp tbody td.td-main{{font-size:1em;font-weight:700;flex-direction:column;align-items:flex-start;gap:2px}}
table.resp tbody td.td-main::before{{font-size:.65em;margin-bottom:2px}}
.cds{{grid-template-columns:1fr}}
.scroll-top{{bottom:72px;right:12px}}
}}
@media(max-width:400px){{.kpis-action{{grid-template-columns:1fr}}.kpis-info{{grid-template-columns:repeat(3,1fr)}}}}
/* Modal */
.modal-overlay{{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);z-index:200;display:none;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(4px)}}
.modal-overlay.show{{display:flex}}
.modal{{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);width:100%;max-width:1100px;max-height:85vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.6)}}
.modal-hdr{{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--border);flex-shrink:0}}
.modal-hdr h2{{color:var(--accent);font-size:1.1em;font-weight:700}}
.modal-close{{background:none;border:none;color:var(--muted);font-size:1.5em;cursor:pointer;padding:4px 10px;border-radius:8px;transition:all .15s}}
.modal-close:hover{{color:#fff;background:rgba(255,255,255,.1)}}
.modal-body{{overflow-y:auto;padding:16px 20px;flex:1;-webkit-overflow-scrolling:touch}}
@media(max-width:768px){{
.modal{{max-height:90vh;border-radius:12px 12px 0 0;position:fixed;bottom:0;left:0;right:0;max-width:100%}}
.modal-body{{padding:12px}}
}}
/* Status buttons nos cards */
.cd .sts-btns{{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:8px}}
.cd .st-btn{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:8px 4px;border-radius:8px;cursor:pointer;font-size:.66em;font-weight:700;text-transform:uppercase;letter-spacing:.3px;transition:all .12s;user-select:none;border:1px solid transparent;text-align:center;gap:1px;line-height:1.1}}
.cd .st-btn b{{font-size:1.5em;font-weight:900;line-height:1;display:block}}
.cd .st-btn:hover{{transform:translateY(-1px);filter:brightness(1.25)}}
.cd .st-btn.st-neg{{background:rgba(100,100,100,.15);color:#bbb;border-color:rgba(150,150,150,.3)}}
.cd .st-btn.st-rupt{{background:rgba(255,68,68,.15);color:#ff7777;border-color:rgba(255,68,68,.3)}}
.cd .st-btn.st-ale{{background:rgba(255,170,0,.12);color:#ffcc55;border-color:rgba(255,170,0,.3)}}
.cd .st-btn.st-exc{{background:rgba(204,102,255,.12);color:var(--excess);border-color:rgba(204,102,255,.3)}}
.cd .st-btn.st-ok{{background:rgba(34,204,102,.12);color:var(--ok);border-color:rgba(34,204,102,.3)}}
.cd .st-btn.zero{{opacity:.3;cursor:default}}
.cd .st-btn.zero:hover{{transform:none;filter:none}}
/* Gerador de Relatorio */
.rel-form{{display:grid;grid-template-columns:2fr 1.3fr 1fr 1.5fr;gap:16px;margin-bottom:16px;align-items:start}}
.rel-group label.grp-t{{display:block;color:var(--accent);font-size:.78em;font-weight:700;text-transform:uppercase;letter-spacing:.4px;margin-bottom:8px}}
.chk-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px;max-height:180px;overflow-y:auto;padding:4px}}
.chk-grid label{{display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:.82em;transition:all .12s}}
.chk-grid label:hover{{border-color:var(--accent);background:var(--bg3)}}
.chk-grid label input{{cursor:pointer;accent-color:var(--accent);min-width:16px;min-height:16px}}
.chk-grid label:has(input:checked){{background:rgba(79,195,247,.1);border-color:var(--accent);color:#fff}}
.rel-mini{{display:flex;gap:6px;margin-top:8px}}
.rel-mini button{{background:none;color:var(--muted);border:1px solid var(--border);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:.72em}}
.rel-mini button:hover{{color:#fff;border-color:var(--accent)}}
.rel-group select{{width:100%;background:var(--bg);color:#ddd;border:1px solid #333;padding:10px 12px;border-radius:8px;font-size:.88em;min-height:40px}}
.rel-actions{{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0 20px;padding-top:16px;border-top:1px solid var(--border)}}
.rel-actions button{{padding:10px 20px;border-radius:10px;font-size:.85em;font-weight:700;cursor:pointer;transition:all .15s;border:none}}
.btn-primary{{background:var(--accent);color:#000}}
.btn-primary:hover{{background:#6fd3ff}}
.btn-secondary{{background:var(--bg);color:var(--accent);border:1px solid var(--accent)!important}}
.btn-secondary:hover:not(:disabled){{background:var(--accent);color:#000}}
.btn-secondary:disabled{{opacity:.4;cursor:not-allowed;border-color:#333!important;color:#666}}
.btn-secondary.ok{{background:var(--ok);color:#000;border-color:var(--ok)!important}}
.rel-hdr{{background:var(--sec);padding:16px 20px;border-radius:10px;margin-bottom:14px;border-left:4px solid var(--accent)}}
.rel-hdr h2{{color:var(--accent);font-size:1.15em;margin-bottom:4px}}
.rel-hdr .rel-meta{{color:var(--muted);font-size:.82em}}
.rel-setor{{background:var(--sec);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:14px}}
.rel-setor>h3{{color:#fff;font-size:1.05em;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;padding-bottom:10px;border-bottom:2px solid var(--border)}}
.rel-setor .rel-cnt{{font-size:.72em;color:var(--muted);font-weight:600}}
.rel-status{{margin:12px 0}}
.rel-status h4{{font-size:.85em;font-weight:800;text-transform:uppercase;letter-spacing:.5px;padding:6px 12px;border-radius:6px;margin-bottom:8px;display:inline-block}}
.rel-s-negativo{{background:rgba(136,136,136,.2);color:#bbb}}
.rel-s-ruptura{{background:rgba(255,68,68,.2);color:#ff7777}}
.rel-s-alerta{{background:rgba(255,170,0,.18);color:#ffcc55}}
.rel-s-excesso{{background:rgba(204,102,255,.18);color:var(--excess)}}
.rel-s-ok{{background:rgba(34,204,102,.15);color:var(--ok)}}
@media(max-width:768px){{
.rel-form{{grid-template-columns:1fr}}
.chk-grid{{grid-template-columns:1fr 1fr;max-height:220px}}
.cd .sts-btns{{grid-template-columns:repeat(5,1fr);gap:4px}}
.cd .st-btn{{padding:6px 2px;font-size:.58em}}
.cd .st-btn b{{font-size:1.25em}}
}}
/* Barra flutuante de Pedido */
.pedido-bar{{position:fixed;bottom:0;left:0;right:0;background:linear-gradient(180deg,#0d0d24,#1a1a3a);border-top:2px solid var(--accent);padding:12px 20px;z-index:90;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;box-shadow:0 -8px 30px rgba(0,0,0,.5);transform:translateY(100%);transition:transform .25s}}
.pedido-bar.on{{transform:translateY(0)}}
.pedido-bar .info{{color:#fff;font-size:.9em;font-weight:700}}
.pedido-bar .info span.accent{{color:var(--accent)}}
.pedido-bar .info .sub{{display:block;color:var(--muted);font-size:.75em;font-weight:500;margin-top:2px}}
.pedido-bar .acts{{display:flex;gap:8px}}
.pedido-bar button{{padding:10px 18px;border-radius:10px;font-size:.85em;font-weight:700;cursor:pointer;border:none;transition:all .15s}}
.pedido-bar .b-limpa{{background:transparent;color:var(--muted);border:1px solid #444}}
.pedido-bar .b-limpa:hover{{color:#fff;border-color:#888}}
.pedido-bar .b-gerar{{background:var(--accent);color:#000}}
.pedido-bar .b-gerar:hover{{background:#6fd3ff}}
/* Checkbox de selecao em tabelas */
.sel-chk{{width:18px;height:18px;cursor:pointer;accent-color:var(--accent)}}
.qt-edit{{width:68px;padding:6px 8px;background:var(--bg);color:var(--accent);border:1px solid var(--border);border-radius:6px;font-size:.92em;font-weight:700;text-align:center;font-variant-numeric:tabular-nums}}
.qt-edit:focus{{outline:2px solid var(--accent);border-color:var(--accent)}}
.qt-edit:disabled{{opacity:.4;color:#888;border-color:#333}}
@media(max-width:768px){{
.pedido-bar{{padding:10px 12px;bottom:56px;flex-direction:column;align-items:stretch;gap:8px}}
.pedido-bar .acts{{width:100%}}
.pedido-bar .acts button{{flex:1}}
.qt-edit{{width:60px;font-size:16px}}
}}
@media print{{body{{background:#fff;color:#000;padding:0}}.hdr,.nav,.fl,.scroll-top,.modal-overlay,.rel-actions,.rel-form,.rel-form *,.sec-t,.pedido-bar,.sel-chk,.qt-edit,.sel-col{{display:none!important}}.pane{{display:none!important;border:none;padding:10px 0;background:#fff}}#p-relatorio.on{{display:block!important}}#p-relatorio>.sec>*:not(#rel-output){{display:none!important}}#p-relatorio>.sec{{border:none;padding:0;background:#fff}}.rel-setor{{background:#fff!important;border:1px solid #999;page-break-inside:avoid;margin-bottom:12px}}.rel-setor>h3{{color:#000!important;border-bottom:2px solid #000}}.rel-hdr{{background:#fff!important;border-left:4px solid #000}}.rel-hdr h2{{color:#000!important}}.rel-status h4{{color:#000!important;border:1px solid #000}}table{{font-size:8pt}}th{{background:#eee;color:#000}}td{{border-color:#ddd;color:#000!important}}tr.R,tr.A,tr.E,tr.N{{background:#f8f8f8!important}}.b,.c{{border:1px solid #999;background:#f0f0f0;color:#000}}table.resp thead{{display:table-header-group!important}}table.resp tbody tr{{display:table-row!important;border:none!important;padding:0;background:#fff}}table.resp tbody td{{display:table-cell!important;padding:4px 6px;border-bottom:1px solid #eee}}table.resp tbody td::before{{display:none!important}}}}
</style>
</head>
<body>
<div class="hdr"><h1>MERKAL - Estoque</h1><div class="upd">Atualizado: {agora}</div></div>
<div class="wrap">
<div class="kpis-action">
 <div class="kpi-lg dng" onclick="go('comprar')">
  <div class="n">{precisa_comprar}</div><div class="l">Precisam de Compra</div>
  <div class="s">{rupt_curva_a} criticos Curva A + {alertas} alertas</div>
  <div class="cta">VER PEDIDOS &rarr;</div>
 </div>
 <div class="kpi-lg exc" onclick="go('excesso')">
  <div class="n">R$ {valor_excesso/1000:,.0f}k</div><div class="l">Dinheiro Parado</div>
  <div class="s">{excessos} produtos com estoque em excesso</div>
  <div class="cta">VER EXCESSOS &rarr;</div>
 </div>
</div>
<div class="kpis-info">
 <div class="kpi-sm" style="border-top-color:var(--danger)" onclick="go('comprar')"><div class="n">{rupturas+negativos}</div><div class="l">Ruptura</div></div>
 <div class="kpi-sm" style="border-top-color:var(--warn)" onclick="go('comprar')"><div class="n">{alertas}</div><div class="l">Alerta</div></div>
 <div class="kpi-sm" style="border-top-color:var(--ok)"><div class="n">{oks}</div><div class="l">OK</div></div>
 <div class="kpi-sm" style="border-top-color:#666" onclick="go('obsoletos')"><div class="n">{n_obsoletos}</div><div class="l">Obsoletos</div></div>
 <div class="kpi-sm" style="border-top-color:var(--accent)"><div class="n">R${valor_total/1000:,.0f}k</div><div class="l">Total</div></div>
</div>
<div class="nav" id="main-nav">
 <a class="on" onclick="go('comprar')"><span class="ic">&#128203;</span> Pedir Agora</a>
 <a onclick="go('todos')"><span class="ic">&#128269;</span> Consultar</a>
 <a onclick="go('setores')"><span class="ic">&#127983;</span> Setores</a>
 <a onclick="go('fornecedores')"><span class="ic">&#128666;</span> Fornecedores</a>
 <a onclick="go('relatorio')"><span class="ic">&#128196;</span> Relatorio</a>
 <a onclick="go('excesso')" class="hide-mobile"><span class="ic">&#9888;</span> Excesso</a>
 <a onclick="go('obsoletos')" class="hide-mobile"><span class="ic">&#128465;</span> Obsoletos</a>
 <a onclick="go('praticas')" class="hide-mobile"><span class="ic">&#10067;</span> Ajuda</a>
</div>
<div class="pane on" id="p-comprar">
 <div class="sec"><div class="sec-t">&#128308; Comprar Agora — Criticos Curva A <span class="cnt cnt-r">{rupt_curva_a}</span></div>
  <p style="color:var(--dim);font-size:.82em;margin-bottom:12px">Produtos que mais vendem e estao sem estoque. Pedir <b>imediatamente</b>.</p>
  <div class="tw"><table class="resp"><thead><tr><th>Cod.</th><th>Produto</th><th>Setor</th><th>Fornecedor</th><th>Estoque</th><th title="Venda media por dia">Vende/dia</th><th title="Dias que o estoque atual dura">Dias estoque</th><th>Qtd. Sugerida</th><th>Embalagem</th><th>Vendido 30d</th></tr></thead><tbody id="t-crit"></tbody></table></div></div>
 <div class="sec"><div class="sec-t">&#128992; Comprar em Breve — Alertas Curva A <span class="cnt cnt-y">{alerta_curva_a}</span></div>
  <p style="color:var(--dim);font-size:.82em;margin-bottom:12px">Estoque acabando. Incluir no <b>proximo pedido</b>.</p>
  <div class="tw"><table class="resp"><thead><tr><th>Cod.</th><th>Produto</th><th>Setor</th><th>Fornecedor</th><th>Estoque</th><th title="Venda media por dia">Vende/dia</th><th title="Dias que o estoque atual dura">Dias estoque</th><th>Qtd. Sugerida</th><th>Embalagem</th><th>Dias entrega</th></tr></thead><tbody id="t-alerta"></tbody></table></div></div>
 <div class="sec"><div class="sec-t">&#128230; Pedido por Fornecedor <span class="cnt cnt-b" id="cnt-forn-ped">0</span></div>
  <p style="color:var(--dim);font-size:.82em;margin-bottom:14px">Lista pronta para enviar ao fornecedor. Clique em <b>Copiar</b> para enviar via WhatsApp.</p>
  <div class="fl" style="position:static"><select id="filt-curva-ped" onchange="renderPedidos()"><option value="">Curva A + B</option><option value="A">Somente Curva A</option><option value="AB">Curva A + B</option><option value="ABC">Todas as Curvas</option></select></div>
  <div id="pedidos-container"></div></div>
</div>
<div class="pane" id="p-todos">
 <div class="fl"><input type="text" id="search" placeholder="&#128269; Buscar produto, codigo..." oninput="debounceFiltrar()">
  <select id="filt-setor" onchange="filtrar()"><option value="">Todos setores</option></select>
  <select id="filt-forn" onchange="filtrar()"><option value="">Todos fornecedores</option></select>
  <select id="filt-status" onchange="filtrar()"><option value="">Todos status</option><option value="ruptura">Ruptura</option><option value="alerta">Alerta</option><option value="ok">OK</option><option value="excesso">Excesso</option><option value="negativo">Negativo</option></select>
  <select id="filt-curva" onchange="filtrar()"><option value="">Todas curvas</option><option value="A">Curva A</option><option value="B">Curva B</option><option value="C">Curva C</option></select>
  <button class="btn-clear" onclick="limparFiltros()">Limpar</button></div>
 <div class="tw"><table class="resp" id="tab-todos"><thead><tr><th onclick="srt(0)">Status</th><th onclick="srt(1)">Curva</th><th onclick="srt(2)">Codigo</th><th onclick="srt(3)">Produto</th><th onclick="srt(4)">Setor</th><th onclick="srt(5)">Fornecedor</th><th onclick="srt(6)">Estoque</th><th onclick="srt(7)" title="Venda media por dia">Vende/dia</th><th onclick="srt(8)" title="Dias que o estoque atual dura">Dias estoque</th><th onclick="srt(9)">Dias entrega</th><th onclick="srt(10)">Vendido 30d</th><th onclick="srt(11)">Ult.Entrada</th></tr></thead><tbody id="t-todos"></tbody></table></div>
 <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;flex-wrap:wrap;gap:8px"><div id="cnt" style="color:var(--muted);font-size:.82em"></div><button id="btn-more" class="btn-clear" onclick="loadMore()" style="display:none">Mostrar mais 50 &#8595;</button></div>
</div>
<div class="pane" id="p-setores"><div class="cds" id="cds-set"></div></div>
<div class="pane" id="p-fornecedores"><div class="fl" style="position:static"><input type="text" id="sf" placeholder="&#128269; Buscar fornecedor..." oninput="fforn()"></div><div class="cds" id="cds-forn"></div></div>
<div class="pane" id="p-excesso">
 <div class="sec" style="border-color:rgba(204,102,255,.3)"><h3 style="color:var(--excess);margin-bottom:8px;font-size:1.15em">R$ {valor_excesso:,.2f} parados em estoque excedente</h3><p style="color:var(--dim);font-size:.85em">Produtos com DDV acima de <b>{FATOR_EXCESSO:.0f}x o ideal</b> do setor. <b style="color:var(--warn)">Nao comprar mais ate normalizar.</b></p></div>
 <div class="tw"><table class="resp"><thead><tr><th>Curva</th><th>Cod.</th><th>Produto</th><th>Setor</th><th>Fornecedor</th><th>Estoque</th><th>Vende/dia</th><th>Dias estoque</th><th>Dias ideais</th><th>Excedente</th><th>R$ Parado</th></tr></thead><tbody id="t-exc"></tbody></table></div>
</div>
<div class="pane" id="p-obsoletos">
 <div class="sec" style="border-color:rgba(136,136,136,.3)"><h3 style="color:var(--dim);margin-bottom:8px;font-size:1.15em">{n_obsoletos} produtos sem entrada nos ultimos 12 meses</h3><p style="color:var(--dim);font-size:.85em">Sem nota de entrada ha mais de 1 ano. Considerar <b style="color:var(--warn)">desativar o cadastro</b> para limpar a base.{f' R$ {valor_obsoletos:,.2f} em estoque residual.' if valor_obsoletos > 0 else ''}</p></div>
 <div class="fl" style="position:static"><input type="text" id="search-obs" placeholder="&#128269; Buscar produto obsoleto..." oninput="filtrarObs()"><select id="filt-setor-obs" onchange="filtrarObs()"><option value="">Todos setores</option></select></div>
 <div class="tw"><table class="resp"><thead><tr><th onclick="srtObs(0)">Cod.</th><th onclick="srtObs(1)">Produto</th><th onclick="srtObs(2)">Setor</th><th onclick="srtObs(3)">Fornecedor</th><th onclick="srtObs(4)">Estoque</th><th onclick="srtObs(5)">Vende/dia</th><th onclick="srtObs(6)">R$ Parado</th><th onclick="srtObs(7)">Ult. Entrada</th><th onclick="srtObs(8)">Dias s/ Entrada</th></tr></thead><tbody id="t-obs"></tbody></table></div>
 <div id="cnt-obs" style="color:var(--muted);font-size:.82em;margin-top:8px"></div>
</div>
<div class="pane" id="p-relatorio">
 <div class="sec">
  <div class="sec-t">&#128196; Gerador de Relatorio <span class="cnt cnt-b">Customizado</span></div>
  <p style="color:var(--dim);font-size:.85em;margin-bottom:16px">Escolha setores e status para gerar um relatorio agrupado. Use <b>Copiar p/ WhatsApp</b> para enviar no grupo ou <b>Imprimir/PDF</b> para salvar.</p>
  <div class="rel-form">
   <div class="rel-group">
    <label class="grp-t">Setores</label>
    <div id="rel-setores" class="chk-grid"></div>
    <div class="rel-mini"><button onclick="relSetAll(true)">Selecionar todos</button><button onclick="relSetAll(false)">Nenhum</button></div>
   </div>
   <div class="rel-group">
    <label class="grp-t">Status</label>
    <div class="chk-grid" style="max-height:none">
     <label><input type="checkbox" class="rel-st" value="negativo" checked> Negativo</label>
     <label><input type="checkbox" class="rel-st" value="ruptura" checked> Ruptura</label>
     <label><input type="checkbox" class="rel-st" value="alerta" checked> Alerta</label>
     <label><input type="checkbox" class="rel-st" value="excesso"> Excesso</label>
     <label><input type="checkbox" class="rel-st" value="ok"> OK</label>
    </div>
   </div>
   <div class="rel-group">
    <label class="grp-t">Curva</label>
    <select id="rel-curva"><option value="">Todas</option><option value="A">Somente A</option><option value="AB">A + B</option><option value="B">Somente B</option><option value="C">Somente C</option></select>
   </div>
   <div class="rel-group">
    <label class="grp-t">Fornecedor (opcional)</label>
    <select id="rel-forn"><option value="">Todos fornecedores</option></select>
   </div>
  </div>
  <div class="rel-actions">
   <button class="btn-primary" onclick="gerarRelatorio()">Gerar Relatorio</button>
   <button class="btn-secondary" id="btn-cp-rel" onclick="copiarRelatorio()" disabled>&#128203; Copiar p/ WhatsApp</button>
   <button class="btn-secondary" id="btn-pr-rel" onclick="imprimirRelatorio()" disabled>&#128424; Imprimir / PDF</button>
  </div>
 </div>
 <div id="rel-output"></div>
</div>
<div class="pane" id="p-praticas"><div class="prs">
 <div class="pr" style="border-left-color:var(--danger)"><h3>&#128308; Curva ABC</h3><p><span class="t">A</span> = 80% do faturamento — nao pode faltar!<br><span class="t">B</span> = 15% do faturamento — importante<br><span class="t">C</span> = 5% do faturamento — menor impacto</p></div>
 <div class="pr" style="border-left-color:var(--danger)"><h3>&#128680; Ruptura</h3><p>Estoque acaba <span class="t">antes do fornecedor entregar</span>. Dias de estoque &lt; Dias de entrega.<br><b>Acao:</b> Pedir imediatamente.</p></div>
 <div class="pr" style="border-left-color:var(--warn)"><h3>&#9888; Alerta</h3><p>Proximo do ponto de pedido. Margem de 1 a 3 dias.<br><b>Acao:</b> Incluir no proximo pedido.</p></div>
 <div class="pr" style="border-left-color:var(--excess)"><h3>&#8593; Excesso</h3><p>Dias de estoque <span class="t">{FATOR_EXCESSO:.0f}x acima do ideal</span> = dinheiro parado.<br><b>Acao:</b> Parar de comprar. Considerar promocao.</p></div>
 <div class="pr"><h3>&#128200; Glossario das Colunas</h3><p><span class="t">Vende/dia</span> = Quantidade vendida em media por dia (ultimos 7 dias).<br><span class="t">Dias estoque</span> = Dias que o estoque atual vai durar (Estoque / Vende/dia).<br><span class="t">Dias entrega</span> = Tempo medio entre entregas do fornecedor.<br><span class="t">Dias ideais</span> = Quanto dias o setor deveria ter em estoque.</p></div>
 <div class="pr"><h3>&#129518; Qtd. Sugerida</h3><p><span class="t">Base:</span> (Dias ideais x Vende/dia) - Estoque atual<br><span class="t">Piso historico:</span> Qtd. que o fornecedor costuma entregar (mediana dos ultimos 180d), desde que cubra o prazo de entrega. Garante que nao peca menos do que ja funciona.<br>Arredondado para a embalagem do fornecedor.</p></div>
 <div class="pr"><h3>&#128202; Apos comprar / Tipico / Dias tipico</h3><p><span class="t">Apos comprar</span> = Dias que o estoque vai durar depois de receber a qtd sugerida. Verde = bom, amarelo = curto, vermelho = ainda insuficiente.<br><span class="t">Tipico/entrega</span> = Qtd que costuma entrar por vez (mediana historica).<br><span class="t">Dias tipico</span> = Dias que essa qtd tipica cobre ao ritmo atual. Se menor que o prazo de entrega, tende a faltar.</p></div>
 <div class="pr"><h3>&#128197; Dias Ideais por Setor</h3><p>{ddv_ideal_html}<br><span class="t">Outros:</span> {DDV_IDEAL_PADRAO} dias</p></div>
 <div class="pr"><h3>&#128666; Dias de Entrega (Lead Time)</h3><p>Tempo medio entre entregas de cada fornecedor. Calculado pelas notas de entrada dos ultimos 90 dias.</p></div>
 <div class="pr" style="border-left-color:var(--accent)"><h3>&#128722; Gerar Pedido no VR Master</h3><p>Nas abas <span class="t">Setores, Fornecedores e Relatorio</span>, marque os itens que deseja comprar (coluna <span class="t">Pedir</span>). Ajuste a quantidade se precisar.<br>Quando terminar, clique em <span class="t">Gerar Pedido VR</span> na barra inferior. Um arquivo JSON sera baixado.<br>Depois execute <b>enviar_pedido.bat</b> (pasta vrmaster_agent) para criar os pedidos no VR Master com situacao <span class="t">DIGITADO</span>. Revise em <span class="t">Estoque &rarr; Consulta Pedido de Compra</span>.</p></div>
</div></div>
</div>
<!-- MODAL -->
<div class="modal-overlay" id="modal-overlay" onclick="if(event.target===this)fecharModal()">
 <div class="modal">
  <div class="modal-hdr"><h2 id="modal-title">Detalhe</h2><button class="modal-close" onclick="fecharModal()">&#10005;</button></div>
  <div class="modal-body" id="modal-body"></div>
 </div>
</div>
<!-- Barra de Pedido VR -->
<div class="pedido-bar" id="pedido-bar">
 <div class="info">
  <span id="ped-count">0 itens</span> selecionados &middot; <span class="accent" id="ped-forn">0 fornecedor(es)</span>
  <span class="sub">O arquivo sera baixado para ~/Downloads. Execute <b>enviar_pedido.bat</b> para criar no VR Master.</span>
 </div>
 <div class="acts">
  <button class="b-limpa" onclick="limparSelecaoPedido()">Limpar</button>
  <button class="b-gerar" onclick="gerarPedidoVR()">Gerar Pedido VR &#10140;</button>
 </div>
</div>
<button class="scroll-top" id="scrollTop" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">&#8593;</button>
<script>
const D={produtos_json};
const OBS={obsoletos_json};
const SET={setores_json};
const FRN={fornecedores_json};
const FE={FATOR_EXCESSO};
let _showN=50,_filteredData=D;

document.addEventListener('DOMContentLoaded',()=>{{init();setupScroll();restoreTab()}});
function init(){{rCrit();rAlt();renderPedidos();pFiltros();filtrar();rSet();rForn();rExc();rObs();pFiltrosObs();initRelatorio()}}
function setupScroll(){{const btn=document.getElementById('scrollTop');window.addEventListener('scroll',()=>{{btn.classList.toggle('show',window.scrollY>400)}})}}
function go(id){{
 document.querySelectorAll('.pane').forEach(p=>p.classList.remove('on'));
 document.querySelectorAll('.nav a').forEach(a=>a.classList.remove('on'));
 const el=document.getElementById('p-'+id);if(el)el.classList.add('on');
 document.querySelectorAll('.nav a').forEach(a=>{{if(a.getAttribute('onclick')&&a.getAttribute('onclick').includes("'"+id+"'"))a.classList.add('on')}});
 window.scrollTo({{top:0,behavior:'smooth'}});history.replaceState(null,'','#'+id)}}
function restoreTab(){{const h=location.hash.replace('#','');if(h)go(h)}}
function sb(s){{const m={{ruptura:'RUPTURA',alerta:'ALERTA',ok:'OK',excesso:'EXCESSO',negativo:'NEG'}};const i={{ruptura:'&#9679;',alerta:'&#9888;',ok:'&#10003;',excesso:'&#8593;',negativo:'&#8722;'}};const c={{ruptura:'b-r',alerta:'b-a',ok:'b-o',excesso:'b-e',negativo:'b-n'}};return'<span class="b '+(c[s]||'')+'">'+((i[s]||'')+' '+(m[s]||s))+'</span>'}}
function cb(c){{return'<span class="c c-'+c+'">'+c+'</span>'}}
function dv(ddv,ideal,lt){{if(ddv===null)return'<span style="color:var(--muted)">-</span>';let p=Math.min(100,Math.max(0,ddv/Math.max(ideal,1)*100));let cl='var(--ok)';if(ddv<=lt)cl='var(--danger)';else if(ddv<=lt+3)cl='var(--warn)';else if(ddv>ideal*FE)cl='var(--excess)';return'<span class="dv"><span style="color:'+cl+'">'+ddv.toFixed(0)+'d</span> <span class="dv-b"><span class="dv-f" style="width:'+Math.min(p,100)+'%;background:'+cl+'"></span></span></span>'}}
function R(v){{return'R$ '+v.toFixed(0).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g,'.')}}
function rCrit(){{const d=D.filter(x=>(x.status==='ruptura'||x.status==='negativo')&&x.curva==='A').sort((a,b)=>b.fat30d-a.fat30d);document.getElementById('t-crit').innerHTML=d.map(x=>'<tr class="R"><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main"><b>'+x.desc+'</b></td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque" style="color:var(--danger);font-weight:800">'+x.est.toFixed(1)+'</td><td data-label="Vende/dia">'+x.vmd.toFixed(1)+'</td><td data-label="Dias estoque">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Qtd. Comprar" style="color:var(--accent);font-weight:800;font-size:1.1em">'+(x.qtd_comprar||'-')+'</td><td data-label="Embalagem">'+(x.emb>1?x.emb+' un':'')+'</td><td data-label="Vendido 30d">'+R(x.fat30d)+'</td></tr>').join('')}}
function rAlt(){{const d=D.filter(x=>x.status==='alerta'&&x.curva==='A').sort((a,b)=>b.fat30d-a.fat30d);document.getElementById('t-alerta').innerHTML=d.map(x=>'<tr class="A"><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque" style="color:var(--warn);font-weight:700">'+x.est.toFixed(1)+'</td><td data-label="Vende/dia">'+x.vmd.toFixed(1)+'</td><td data-label="Dias estoque">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Qtd. Comprar" style="color:var(--accent);font-weight:800;font-size:1.1em">'+(x.qtd_comprar||'-')+'</td><td data-label="Embalagem">'+(x.emb>1?x.emb+' un':'')+'</td><td data-label="Dias entrega">'+x.lt+'d</td></tr>').join('')}}
function renderPedidos(){{
 const fc=document.getElementById('filt-curva-ped').value||'AB';
 let itens=D.filter(x=>x.status==='ruptura'||x.status==='alerta'||x.status==='negativo');
 if(fc==='A')itens=itens.filter(x=>x.curva==='A');
 else if(fc==='AB')itens=itens.filter(x=>x.curva==='A'||x.curva==='B');
 const grupos={{}};itens.forEach(x=>{{if(!grupos[x.forn])grupos[x.forn]=[];grupos[x.forn].push(x)}});
 const sorted=Object.entries(grupos).sort((a,b)=>{{const ra=a[1].filter(x=>x.curva==='A'&&(x.status==='ruptura'||x.status==='negativo')).length;const rb=b[1].filter(x=>x.curva==='A'&&(x.status==='ruptura'||x.status==='negativo')).length;if(rb!==ra)return rb-ra;return b[1].length-a[1].length}});
 document.getElementById('cnt-forn-ped').textContent=sorted.length+' fornecedores';
 document.getElementById('pedidos-container').innerHTML=sorted.map(([forn,prods],i)=>{{
  prods.sort((a,b)=>{{if(a.curva!==b.curva)return a.curva.localeCompare(b.curva);return(a.ddv||999)-(b.ddv||999)}});
  const nR=prods.filter(x=>x.status==='ruptura'||x.status==='negativo').length,nA=prods.filter(x=>x.status==='alerta').length,lt=prods[0].lt,fid='ped_'+i;
  return(i>0?'<div class="ped-sep"></div>':'')+
  '<div class="ped-hdr"><h3>'+forn+'</h3><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><div class="info">'+prods.length+' itens | ~'+lt+'d'+(nR?' | <b style="color:var(--danger)">'+nR+' rupt</b>':'')+(nA?' | <b style="color:var(--warn)">'+nA+' alertas</b>':'')+'</div><button class="btn-copy" id="'+fid+'" data-forn="'+forn.replace(/"/g,'&quot;')+'" onclick="copiarPedido(this.dataset.forn,this.id)">&#128203; Copiar</button></div></div>'+
  '<div class="tw"><table class="resp"><thead><tr><th>Curva</th><th>Status</th><th>Codigo</th><th>Produto</th><th>Setor</th><th>Estoque</th><th>Vende/dia</th><th>Dias estoque</th><th style="color:var(--accent)">Qtd. Comprar</th><th>Embalagem</th></tr></thead><tbody>'+
  prods.map(x=>'<tr class="'+(x.status==='ruptura'||x.status==='negativo'?'R':'A')+'"><td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Status">'+sb(x.status)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Estoque" style="font-weight:700;color:'+(x.est<=0?'var(--danger)':'var(--warn)')+'">'+x.est.toFixed(1)+'</td><td data-label="Vende/dia">'+x.vmd.toFixed(1)+'</td><td data-label="Dias estoque">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Qtd. Comprar" style="color:var(--accent);font-weight:800;font-size:1.1em">'+(x.qtd_comprar||'-')+'</td><td data-label="Embalagem">'+(x.emb>1?x.emb+' un':'un')+'</td></tr>').join('')+'</tbody></table></div>'}}).join('')}}
function copiarPedido(forn,btnId){{
 const itens=D.filter(x=>(x.status==='ruptura'||x.status==='alerta'||x.status==='negativo')&&x.forn===forn);
 let txt='*Pedido - '+forn+'*\\n'+new Date().toLocaleDateString('pt-BR')+'\\n\\n';
 itens.forEach(x=>{{txt+=x.cod+' - '+x.desc+'\\n  Qtd: '+(x.qtd_comprar||'?')+' | Estoque: '+x.est.toFixed(0)+' | Vende/dia: '+x.vmd.toFixed(1)+'\\n'}});
 txt+='\\n_Dashboard Merkal_';
 navigator.clipboard.writeText(txt).then(()=>{{const btn=document.getElementById(btnId);btn.textContent='\\u2713 Copiado!';btn.classList.add('ok');setTimeout(()=>{{btn.innerHTML='&#128203; Copiar';btn.classList.remove('ok')}},2000)}})}}
function pFiltros(){{const ss=[...new Set(D.map(x=>x.setor))].sort();const s1=document.getElementById('filt-setor');ss.forEach(s=>{{const o=document.createElement('option');o.value=s;o.textContent=s;s1.appendChild(o)}});const ff=[...new Set(D.map(x=>x.forn))].sort();const s2=document.getElementById('filt-forn');ff.forEach(f=>{{const o=document.createElement('option');o.value=f;o.textContent=f;s2.appendChild(o)}})}}
let _debounceTimer;
function debounceFiltrar(){{clearTimeout(_debounceTimer);_debounceTimer=setTimeout(filtrar,200)}}
function gF(){{const q=document.getElementById('search').value.toLowerCase(),se=document.getElementById('filt-setor').value,fo=document.getElementById('filt-forn').value,st=document.getElementById('filt-status').value,cu=document.getElementById('filt-curva').value;return D.filter(x=>{{if(q&&!x.desc.toLowerCase().includes(q)&&!x.cod.includes(q))return false;if(se&&x.setor!==se)return false;if(fo&&x.forn!==fo)return false;if(st&&x.status!==st)return false;if(cu&&x.curva!==cu)return false;return true}})}}
function filtrar(){{_showN=50;_filteredData=gF();rTodos(_filteredData)}}
function limparFiltros(){{document.getElementById('search').value='';document.getElementById('filt-setor').value='';document.getElementById('filt-forn').value='';document.getElementById('filt-status').value='';document.getElementById('filt-curva').value='';filtrar()}}
function loadMore(){{_showN+=50;rTodos(_filteredData)}}
function rTodos(data){{const t=document.getElementById('t-todos'),showing=Math.min(data.length,_showN);t.innerHTML=data.slice(0,showing).map(x=>'<tr class="'+({{ruptura:'R',alerta:'A',excesso:'E',negativo:'N'}}[x.status]||'')+'"><td data-label="Status">'+sb(x.status)+'</td><td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque">'+x.est.toFixed(1)+'</td><td data-label="Vende/dia">'+x.vmd.toFixed(1)+'</td><td data-label="Dias estoque">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Dias entrega">'+x.lt+'d</td><td data-label="Vendido 30d">'+R(x.fat30d)+'</td><td data-label="Ult.Entrada">'+x.ult_entrada+'</td></tr>').join('');document.getElementById('cnt').textContent='Mostrando '+showing+' de '+data.length;document.getElementById('btn-more').style.display=showing<data.length?'block':'none'}}
let sC=-1,sA=true;
function srt(c){{if(sC===c)sA=!sA;else{{sC=c;sA=true}};const ks=['status','curva','cod','desc','setor','forn','est','vmd','ddv','lt','fat30d','ult_entrada'];const k=ks[c];_filteredData=gF();_filteredData.sort((a,b)=>{{let va=a[k],vb=b[k];if(va===null)va=sA?999999:-999999;if(vb===null)vb=sA?999999:-999999;if(typeof va==='string')return sA?va.localeCompare(vb):vb.localeCompare(va);return sA?va-vb:vb-va}});_showN=50;rTodos(_filteredData)}}
var _setKeys=[];
function stBtn(n,cls,lbl,setor,st){{var z=n>0?'':' zero';return '<span class="st-btn '+cls+z+'" data-se="'+setor.replace(/"/g,'&quot;')+'" data-st="'+st+'"><b>'+n+'</b>'+lbl+'</span>'}}
function rSet(){{var c=document.getElementById('cds-set'),entries=Object.entries(SET);_setKeys=entries.map(e=>e[0]);c.innerHTML='';entries.forEach((e,i)=>{{var n=e[0],s=e[1],t=s.total||1;var d=document.createElement('div');d.className='cd';d.setAttribute('data-idx',i);var neg=s.negativo||0,rupt=s.ruptura||0;d.innerHTML='<h3>'+n+'</h3><div class="sts-btns">'+stBtn(neg,'st-neg','Negativo',n,'negativo')+stBtn(rupt,'st-rupt','Ruptura',n,'ruptura')+stBtn(s.alerta,'st-ale','Alerta',n,'alerta')+stBtn(s.excesso,'st-exc','Excesso',n,'excesso')+stBtn(s.ok,'st-ok','OK',n,'ok')+'</div><div style="font-size:.8em;color:var(--muted);margin-top:4px">'+s.total+' itens | '+R(s.valor_estoque)+'</div>'+(s.valor_excesso>0?'<div style="font-size:.8em;color:var(--excess)">'+R(s.valor_excesso)+' parado</div>':'')+'<div class="br"><div style="width:'+((rupt+neg)/t*100)+'%;background:var(--danger)"></div><div style="width:'+(s.alerta/t*100)+'%;background:var(--warn)"></div><div style="width:'+(s.ok/t*100)+'%;background:var(--ok)"></div><div style="width:'+(s.excesso/t*100)+'%;background:var(--excess)"></div></div>';d.querySelectorAll('.st-btn').forEach(function(btn){{btn.addEventListener('click',function(ev){{ev.stopPropagation();if(this.classList.contains('zero'))return;abrirModalFiltrado('setor',this.dataset.se,this.dataset.st)}})}});c.appendChild(d)}})}}
var _frnKeys=[];
function rForn(){{rFL(Object.entries(FRN))}}
function fforn(){{var q=document.getElementById('sf').value.toLowerCase();rFL(Object.entries(FRN).filter(e=>e[0].toLowerCase().indexOf(q)>=0))}}
function rFL(e){{var c=document.getElementById('cds-forn');_frnKeys=e.map(x=>x[0]);c.innerHTML='';e.forEach((entry,i)=>{{var n=entry[0],f=entry[1],t=f.total||1;var d=document.createElement('div');d.className='cd';d.setAttribute('data-idx',i);var neg=f.negativo||0,rupt=f.ruptura||0;d.innerHTML='<h3>'+n+'</h3><div class="sts-btns">'+stBtn(neg,'st-neg','Negativo',n,'negativo')+stBtn(rupt,'st-rupt','Ruptura',n,'ruptura')+stBtn(f.alerta,'st-ale','Alerta',n,'alerta')+stBtn(f.excesso,'st-exc','Excesso',n,'excesso')+stBtn(f.ok,'st-ok','OK',n,'ok')+'</div><div style="font-size:.8em;color:var(--muted);margin-top:4px">'+f.total+' itens | ~'+f.lead_time+'d entrega | '+R(f.valor_estoque)+'</div><div class="br"><div style="width:'+((rupt+neg)/t*100)+'%;background:var(--danger)"></div><div style="width:'+(f.alerta/t*100)+'%;background:var(--warn)"></div><div style="width:'+(f.ok/t*100)+'%;background:var(--ok)"></div><div style="width:'+(f.excesso/t*100)+'%;background:var(--excess)"></div></div>';d.querySelectorAll('.st-btn').forEach(function(btn){{btn.addEventListener('click',function(ev){{ev.stopPropagation();if(this.classList.contains('zero'))return;abrirModalFiltrado('forn',this.dataset.se,this.dataset.st)}})}});c.appendChild(d)}})}}
function abrirModal(tp,nm){{abrirModalFiltrado(tp,nm,null)}}
function abrirModalFiltrado(tp,nm,stF){{
 let prods;if(tp==='setor')prods=D.filter(x=>x.setor===nm);else prods=D.filter(x=>x.forn===nm);
 const totalSetor=prods.length;
 if(stF)prods=prods.filter(x=>x.status===stF);
 prods.sort((a,b)=>{{const o={{ruptura:0,negativo:1,alerta:2,ok:3,excesso:4}};if((o[a.status]||3)!==(o[b.status]||3))return(o[a.status]||3)-(o[b.status]||3);return a.curva.localeCompare(b.curva)||(b.fat30d-a.fat30d)}});
 const allP=tp==='setor'?D.filter(x=>x.setor===nm):D.filter(x=>x.forn===nm);
 const cR=allP.filter(x=>x.status==='ruptura').length;
 const cN=allP.filter(x=>x.status==='negativo').length;
 const cA=allP.filter(x=>x.status==='alerta').length;
 const cO=allP.filter(x=>x.status==='ok').length;
 const cE=allP.filter(x=>x.status==='excesso').length;
 const stLbl={{ruptura:'Ruptura',alerta:'Alerta',ok:'OK',excesso:'Excesso',negativo:'Negativo'}};
 const ttl=stF?(nm+' - '+stLbl[stF]+' ('+prods.length+' itens)'):(nm+' ('+prods.length+' itens)');
 document.getElementById('modal-title').textContent=ttl;
 function mBtn(n,cls,lbl,st){{var act=stF===st?' style="outline:2px solid #fff;outline-offset:2px"':'';var z=n>0?'':' zero';return '<span class="st-btn '+cls+z+'"'+act+' data-st="'+st+'" style="cursor:'+(n>0?'pointer':'default')+'"><b>'+n+'</b>'+lbl+'</span>'}}
 document.getElementById('modal-body').innerHTML=
  '<div class="sts-btns" style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:14px">'+
   mBtn(cN,'st-neg','Negativo','negativo')+mBtn(cR,'st-rupt','Ruptura','ruptura')+mBtn(cA,'st-ale','Alerta','alerta')+mBtn(cE,'st-exc','Excesso','excesso')+mBtn(cO,'st-ok','OK','ok')+
  '</div>'+
  (stF?'<div style="margin-bottom:10px"><button class="btn-clear" onclick="abrirModalFiltrado(\\''+tp+'\\',\\''+nm.replace(/\\\\/g,'\\\\\\\\').replace(/'/g,"\\\\'")+'\\',null)">Ver todos ('+totalSetor+')</button></div>':'')+
  '<div class="tw"><table class="resp"><thead><tr><th style="color:var(--accent)" title="Selecionar para gerar pedido no VR Master">Pedir</th><th>Status</th><th>Curva</th><th>Cod.</th><th>Produto</th>'+(tp==='setor'?'<th>Categoria</th><th>Fornecedor</th>':'<th>Setor</th><th>Categoria</th>')+'<th>Estoque</th><th title="Venda Media Diaria - unidades vendidas por dia (ultimos 7d)">Vende/dia</th><th title="Dias que o estoque atual dura ao ritmo atual">Dias estoque</th><th style="color:var(--accent)">Qtd. Sugerida</th><th>Embalagem</th><th style="color:var(--ok)" title="Dias que o estoque vai durar apos receber a qtd sugerida">Apos comprar</th><th title="Qtd que costuma entrar por vez - mediana dos ultimos 180d">Tipico/entrega</th><th title="Dias que a qtd tipica cobre ao ritmo atual">Dias tipico</th><th>Vendido 30d</th></tr></thead><tbody>'+
  prods.map(x=>{{var pos=(x.vmd>0&&x.qtd_comprar>0)?Math.round((x.est+x.qtd_comprar)/x.vmd):null;var posCl=pos==null?'#888':(pos<x.lt?'var(--danger)':(pos<x.ddv_ideal?'var(--warn)':'var(--ok)'));return '<tr class="'+({{ruptura:'R',alerta:'A',excesso:'E',negativo:'N'}}[x.status]||'')+'">'+chkCell(x)+'<td data-label="Status">'+sb(x.status)+'</td><td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td>'+(tp==='setor'?'<td data-label="Categoria">'+x.cat+'</td><td data-label="Fornecedor">'+x.forn+'</td>':'<td data-label="Setor">'+x.setor+'</td><td data-label="Categoria">'+x.cat+'</td>')+'<td data-label="Estoque">'+x.est.toFixed(1)+'</td><td data-label="Vende/dia">'+x.vmd.toFixed(1)+'</td><td data-label="Dias estoque">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Qtd. Sugerida" style="color:var(--accent);font-weight:800;font-size:1.05em">'+(x.qtd_comprar>0?x.qtd_comprar:'-')+'</td><td data-label="Embalagem">'+(x.emb>1?x.emb+' un':'un')+'</td><td data-label="Apos comprar" style="color:'+posCl+';font-weight:700">'+(pos!=null?pos+'d':'-')+'</td><td data-label="Tipico/entrega" style="color:#bbb">'+(x.qtd_tipica?x.qtd_tipica+' un':'-')+'</td><td data-label="Dias tipico" style="color:#bbb">'+(x.cobertura!=null?x.cobertura+'d':'-')+'</td><td data-label="Vendido 30d">'+R(x.fat30d)+'</td></tr>'}}).join('')+'</tbody></table></div>';
 // attach status switcher handlers
 document.querySelectorAll('#modal-body .sts-btns .st-btn').forEach(function(btn){{btn.addEventListener('click',function(){{if(this.classList.contains('zero'))return;var ns=this.dataset.st===stF?null:this.dataset.st;abrirModalFiltrado(tp,nm,ns)}})}});
 document.getElementById('modal-overlay').classList.add('show');document.body.style.overflow='hidden'}}
function fecharModal(){{document.getElementById('modal-overlay').classList.remove('show');document.body.style.overflow=''}}
function pFiltrosObs(){{const ss=[...new Set(OBS.map(x=>x.setor))].sort();const s1=document.getElementById('filt-setor-obs');ss.forEach(s=>{{const o=document.createElement('option');o.value=s;o.textContent=s;s1.appendChild(o)}})}}
function gFObs(){{const q=document.getElementById('search-obs').value.toLowerCase(),se=document.getElementById('filt-setor-obs').value;return OBS.filter(x=>{{if(q&&!x.desc.toLowerCase().includes(q)&&!x.cod.includes(q))return false;if(se&&x.setor!==se)return false;return true}})}}
function filtrarObs(){{rObsList(gFObs())}}
let sOC=-1,sOA=true;
function srtObs(c){{if(sOC===c)sOA=!sOA;else{{sOC=c;sOA=true}};const ks=['cod','desc','setor','forn','est','vmd','valor','ult_entrada','dias_sem_entrada'];const k=ks[c];let d=gFObs();d.sort((a,b)=>{{let va=a[k],vb=b[k];if(va===null||va===undefined)va=sOA?999999:-999999;if(vb===null||vb===undefined)vb=sOA?999999:-999999;if(typeof va==='string')return sOA?va.localeCompare(vb):vb.localeCompare(va);return sOA?va-vb:vb-va}});rObsList(d)}}
function rObs(){{rObsList(OBS)}}
function rObsList(data){{const t=document.getElementById('t-obs');t.innerHTML=data.slice(0,500).map(x=>'<tr class="N"><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque">'+x.est.toFixed(1)+'</td><td data-label="Vende/dia">'+x.vmd.toFixed(3)+'</td><td data-label="R$ Parado" style="color:var(--warn)">'+(x.valor>0?R(x.valor):'-')+'</td><td data-label="Ult. Entrada">'+x.ult_entrada+'</td><td data-label="Dias s/ Entrada" style="color:var(--muted);font-weight:700">'+(x.dias_sem_entrada!==null?x.dias_sem_entrada+'d':'Nunca')+'</td></tr>').join('');document.getElementById('cnt-obs').textContent='Mostrando '+Math.min(data.length,500)+' de '+data.length+' obsoletos'}}
function rExc(){{const d=D.filter(x=>x.status==='excesso').sort((a,b)=>{{const ea=Math.max(0,a.est-a.vmd*a.ddv_ideal)*(a.est>0?a.valor/a.est:0);const eb=Math.max(0,b.est-b.vmd*b.ddv_ideal)*(b.est>0?b.valor/b.est:0);return eb-ea}});document.getElementById('t-exc').innerHTML=d.map(x=>{{const iq=x.vmd*x.ddv_ideal,ex=Math.max(0,x.est-iq),cu=x.est>0?x.valor/x.est:0,vp=ex*cu;return'<tr class="E"><td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque">'+x.est.toFixed(0)+'</td><td data-label="Vende/dia">'+x.vmd.toFixed(1)+'</td><td data-label="Dias estoque">'+(x.ddv!==null?x.ddv.toFixed(0)+'d':'-')+'</td><td data-label="Dias ideais">'+x.ddv_ideal+'d</td><td data-label="Excedente" style="color:var(--excess);font-weight:700">'+ex.toFixed(0)+'</td><td data-label="R$ Parado" style="color:var(--excess);font-weight:700">'+R(vp)+'</td></tr>'}}).join('')}}
/* ====== GERADOR DE RELATORIO ====== */
const REL_STATUS_ORDER=['negativo','ruptura','alerta','excesso','ok'];
const REL_STATUS_LBL={{negativo:'NEGATIVO (estoque menor que zero)',ruptura:'RUPTURA (pedir imediatamente)',alerta:'ALERTA (incluir no proximo pedido)',excesso:'EXCESSO (parar de comprar)',ok:'OK'}};
const REL_STATUS_CLS={{negativo:'rel-s-negativo',ruptura:'rel-s-ruptura',alerta:'rel-s-alerta',excesso:'rel-s-excesso',ok:'rel-s-ok'}};
const REL_ROW_CLS={{ruptura:'R',alerta:'A',excesso:'E',negativo:'N'}};
var _relData=null;
function initRelatorio(){{
 var setores=[...new Set(D.map(x=>x.setor))].sort();
 document.getElementById('rel-setores').innerHTML=setores.map(function(s){{return '<label><input type="checkbox" class="rel-se" value="'+s.replace(/"/g,'&quot;')+'"> '+s+'</label>'}}).join('');
 var forns=[...new Set(D.map(x=>x.forn))].sort();
 var sel=document.getElementById('rel-forn');
 forns.forEach(function(f){{var o=document.createElement('option');o.value=f;o.textContent=f;sel.appendChild(o)}});
}}
function relSetAll(v){{document.querySelectorAll('.rel-se').forEach(function(c){{c.checked=v}})}}
function gerarRelatorio(){{
 var setores=[...document.querySelectorAll('.rel-se:checked')].map(c=>c.value);
 var statuses=[...document.querySelectorAll('.rel-st:checked')].map(c=>c.value);
 var curva=document.getElementById('rel-curva').value;
 var forn=document.getElementById('rel-forn').value;
 var out=document.getElementById('rel-output');
 if(setores.length===0){{out.innerHTML='<div class="rel-hdr"><h2 style="color:var(--warn)">Selecione pelo menos um setor</h2></div>';document.getElementById('btn-cp-rel').disabled=true;document.getElementById('btn-pr-rel').disabled=true;return}}
 if(statuses.length===0){{out.innerHTML='<div class="rel-hdr"><h2 style="color:var(--warn)">Selecione pelo menos um status</h2></div>';document.getElementById('btn-cp-rel').disabled=true;document.getElementById('btn-pr-rel').disabled=true;return}}
 var prods=D.filter(x=>setores.indexOf(x.setor)>=0&&statuses.indexOf(x.status)>=0);
 if(curva){{if(curva==='AB')prods=prods.filter(x=>x.curva==='A'||x.curva==='B');else prods=prods.filter(x=>x.curva===curva)}}
 if(forn)prods=prods.filter(x=>x.forn===forn);
 var grupos={{}};
 prods.forEach(function(p){{if(!grupos[p.setor])grupos[p.setor]={{}};if(!grupos[p.setor][p.status])grupos[p.setor][p.status]=[];grupos[p.setor][p.status].push(p)}});
 var hoje=new Date().toLocaleDateString('pt-BR');
 var hora=new Date().toLocaleTimeString('pt-BR',{{hour:'2-digit',minute:'2-digit'}});
 var html='<div class="rel-hdr"><h2>Relatorio de Estoque - '+hoje+' '+hora+'</h2><div class="rel-meta">'+prods.length+' itens | '+setores.length+' setor(es) | Status: '+statuses.map(s=>s.toUpperCase()).join(', ')+(curva?' | Curva: '+curva:'')+(forn?' | Fornecedor: '+forn:'')+'</div></div>';
 if(prods.length===0){{html+='<p style="color:var(--muted);text-align:center;padding:30px;font-size:1.05em">Nenhum produto encontrado com os filtros selecionados.</p>';out.innerHTML=html;document.getElementById('btn-cp-rel').disabled=true;document.getElementById('btn-pr-rel').disabled=true;return}}
 setores.sort().forEach(function(setor){{
  if(!grupos[setor])return;
  var statusList=REL_STATUS_ORDER.filter(s=>statuses.indexOf(s)>=0&&grupos[setor][s]&&grupos[setor][s].length>0);
  if(statusList.length===0)return;
  var totalSetor=statusList.reduce(function(sum,s){{return sum+grupos[setor][s].length}},0);
  var totalQtdSetor=0;
  statusList.forEach(function(s){{grupos[setor][s].forEach(function(p){{totalQtdSetor+=(p.qtd_comprar||0)}})}});
  html+='<div class="rel-setor"><h3>'+setor+' <span class="rel-cnt">'+totalSetor+' itens'+(totalQtdSetor>0?' &middot; <b style="color:var(--accent)">'+totalQtdSetor+' un. a comprar</b>':'')+'</span></h3>';
  statusList.forEach(function(st){{
   var items=grupos[setor][st].slice();
   items.sort(function(a,b){{if(st==='negativo')return a.est-b.est;if(st==='ruptura'||st==='alerta')return(b.qtd_comprar||0)-(a.qtd_comprar||0);if(st==='excesso')return(b.ddv||0)-(a.ddv||0);return b.fat30d-a.fat30d}});
   var qtdSt=items.reduce(function(s,p){{return s+(p.qtd_comprar||0)}},0);
   html+='<div class="rel-status"><h4 class="'+REL_STATUS_CLS[st]+'">'+REL_STATUS_LBL[st]+' ('+items.length+(qtdSt>0?' &middot; '+qtdSt+' un.':'')+')</h4>';
   html+='<div class="tw"><table class="resp"><thead><tr><th style="color:var(--accent)" title="Selecionar para gerar pedido no VR Master">Pedir</th><th>Curva</th><th>Cod.</th><th>Produto</th><th>Fornecedor</th><th>Estoque</th><th title="Venda Media Diaria">Vende/dia</th><th title="Dias de estoque atual">Dias estoque</th><th title="Prazo entre entregas do fornecedor">Dias entrega</th><th style="color:var(--accent)">Qtd. Sugerida</th><th>Embalagem</th><th style="color:var(--ok)" title="Dias de estoque apos receber a compra">Apos comprar</th><th title="Mediana historica (180d)">Tipico/entrega</th><th title="Dias que a qtd tipica cobre">Dias tipico</th><th>Vendido 30d</th></tr></thead><tbody>';
   items.forEach(function(x){{
    var ddvStr=x.ddv!==null?x.ddv.toFixed(1)+'d':'-';
    var pos=(x.vmd>0&&x.qtd_comprar>0)?Math.round((x.est+x.qtd_comprar)/x.vmd):null;
    var posCl=pos==null?'#888':(pos<x.lt?'var(--danger)':(pos<x.ddv_ideal?'var(--warn)':'var(--ok)'));
    html+='<tr class="'+(REL_ROW_CLS[x.status]||'')+'">'+chkCell(x)+'<td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque" style="font-weight:700">'+x.est.toFixed(1)+'</td><td data-label="Vende/dia">'+x.vmd.toFixed(2)+'</td><td data-label="Dias estoque">'+ddvStr+'</td><td data-label="Dias entrega">'+x.lt+'d</td><td data-label="Qtd. Sugerida" style="color:var(--accent);font-weight:800;font-size:1.05em">'+(x.qtd_comprar>0?x.qtd_comprar:'-')+'</td><td data-label="Embalagem">'+(x.emb>1?x.emb+' un':'un')+'</td><td data-label="Apos comprar" style="color:'+posCl+';font-weight:700">'+(pos!=null?pos+'d':'-')+'</td><td data-label="Tipico/entrega" style="color:#bbb">'+(x.qtd_tipica?x.qtd_tipica+' un':'-')+'</td><td data-label="Dias tipico" style="color:#bbb">'+(x.cobertura!=null?x.cobertura+'d':'-')+'</td><td data-label="Vendido 30d">'+R(x.fat30d)+'</td></tr>';
   }});
   html+='</tbody></table></div></div>';
  }});
  html+='</div>';
 }});
 out.innerHTML=html;
 _relData={{grupos:grupos,setores:setores.sort(),statuses:statuses,total:prods.length}};
 document.getElementById('btn-cp-rel').disabled=false;
 document.getElementById('btn-pr-rel').disabled=false;
}}
function copiarRelatorio(){{
 if(!_relData)return;
 var hoje=new Date().toLocaleDateString('pt-BR');
 var txt='*RELATORIO DE ESTOQUE - '+hoje+'*\\n\\n';
 _relData.setores.forEach(function(setor){{
  if(!_relData.grupos[setor])return;
  var statusList=REL_STATUS_ORDER.filter(s=>_relData.statuses.indexOf(s)>=0&&_relData.grupos[setor][s]&&_relData.grupos[setor][s].length>0);
  if(statusList.length===0)return;
  txt+='*'+setor+'*\\n';
  statusList.forEach(function(st){{
   var items=_relData.grupos[setor][st];
   txt+='_'+REL_STATUS_LBL[st]+' ('+items.length+')_\\n';
   items.slice(0,30).forEach(function(x){{
    var ddvStr=x.ddv!==null?x.ddv.toFixed(0)+'d':'-';
    var qtdStr=x.qtd_comprar>0?'\\n  *Comprar: '+x.qtd_comprar+(x.emb>1?' un (embalagem '+x.emb+')':' un')+'*':'';
    txt+=x.cod+' - '+x.desc+'\\n  Estoque: '+x.est.toFixed(0)+' | Vende/dia: '+x.vmd.toFixed(1)+' | Dura: '+ddvStr+qtdStr+'\\n';
   }});
   if(items.length>30)txt+='_... +'+(items.length-30)+' itens (ver dashboard)_\\n';
   txt+='\\n';
  }});
 }});
 txt+='_Total: '+_relData.total+' itens | Dashboard Merkal_';
 navigator.clipboard.writeText(txt).then(function(){{var btn=document.getElementById('btn-cp-rel');var old=btn.innerHTML;btn.innerHTML='\\u2713 Copiado!';btn.classList.add('ok');setTimeout(function(){{btn.innerHTML=old;btn.classList.remove('ok')}},2000)}}).catch(function(){{alert('Erro ao copiar. Selecione manualmente.')}});
}}
function imprimirRelatorio(){{window.print()}}
/* ====== SELECAO DE PEDIDO PARA VR MASTER ====== */
var _pedSel={{}}; // {{id_produto: qtd}}
function chkCell(x){{
 var checked=_pedSel[x.id]!==undefined?' checked':'';
 var qtdDefault=_pedSel[x.id]!==undefined?_pedSel[x.id]:(x.qtd_comprar>0?x.qtd_comprar:(x.emb>1?x.emb:1));
 var disabled=(_pedSel[x.id]===undefined)?' disabled':'';
 var temForn=x.id_forn?true:false;
 if(!temForn)return '<td data-label="Selecionar" class="sel-col" title="Sem fornecedor cadastrado - nao pode gerar pedido"><span style="color:#555;font-size:.7em">sem forn.</span></td>';
 return '<td data-label="Selecionar" class="sel-col" style="white-space:nowrap"><input type="checkbox" class="sel-chk" data-id="'+x.id+'"'+checked+' onchange="togglePed('+x.id+',this)"> <input type="number" min="1" class="qt-edit" data-id="'+x.id+'" value="'+qtdDefault+'"'+disabled+' onchange="updQtdPed('+x.id+',this.value)" onclick="event.stopPropagation()"></td>';
}}
function togglePed(id,cb){{
 var row=cb.closest('tr');
 var input=row.querySelector('.qt-edit[data-id="'+id+'"]');
 if(cb.checked){{
  var q=parseInt(input.value)||0;
  if(q<=0)q=1;
  _pedSel[id]=q;
  input.disabled=false;
  input.value=q;
 }}else{{
  delete _pedSel[id];
  input.disabled=true;
 }}
 // sincronizar outros checkboxes do mesmo produto (modal/relatorio podem coexistir)
 document.querySelectorAll('.sel-chk[data-id="'+id+'"]').forEach(function(c){{c.checked=cb.checked}});
 document.querySelectorAll('.qt-edit[data-id="'+id+'"]').forEach(function(i){{i.disabled=!cb.checked;if(cb.checked)i.value=_pedSel[id]}});
 atualizarBarraPedido();
}}
function updQtdPed(id,v){{
 var q=parseInt(v)||0;
 if(q<=0){{q=1;}}
 if(_pedSel[id]!==undefined){{
  _pedSel[id]=q;
  document.querySelectorAll('.qt-edit[data-id="'+id+'"]').forEach(function(i){{i.value=q}});
 }}
 atualizarBarraPedido();
}}
function atualizarBarraPedido(){{
 var ids=Object.keys(_pedSel);
 var n=ids.length;
 var bar=document.getElementById('pedido-bar');
 if(n===0){{bar.classList.remove('on');return}}
 // contar fornecedores distintos
 var forns=new Set();
 ids.forEach(function(id){{var p=D.find(x=>String(x.id)===String(id));if(p&&p.id_forn)forns.add(p.id_forn)}});
 document.getElementById('ped-count').textContent=n+' '+(n===1?'item':'itens');
 document.getElementById('ped-forn').textContent=forns.size+' '+(forns.size===1?'fornecedor':'fornecedores');
 bar.classList.add('on');
}}
function limparSelecaoPedido(){{_pedSel={{}};document.querySelectorAll('.sel-chk').forEach(function(c){{c.checked=false}});document.querySelectorAll('.qt-edit').forEach(function(i){{i.disabled=true}});atualizarBarraPedido()}}
const PEDIDO_API_URL='https://cafe-dashboard-br.vercel.app/api/pedido-novo';
function baixarPedidoLocal(payload,nome){{
 var blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}});
 var url=URL.createObjectURL(blob);
 var a=document.createElement('a');a.href=url;a.download=nome;document.body.appendChild(a);a.click();document.body.removeChild(a);
 setTimeout(function(){{URL.revokeObjectURL(url)}},1000);
}}
function gerarPedidoVR(){{
 var ids=Object.keys(_pedSel).filter(function(id){{return _pedSel[id]>0}});
 if(ids.length===0){{alert('Selecione pelo menos um item');return}}
 var porForn={{}};
 var semForn=[];
 ids.forEach(function(id){{
  var p=D.find(x=>String(x.id)===String(id));
  if(!p)return;
  if(!p.id_forn){{semForn.push(p);return}}
  if(!porForn[p.id_forn]){{porForn[p.id_forn]={{fornecedor_nome:p.forn,itens:[]}}}}
  porForn[p.id_forn].itens.push({{id_produto:parseInt(id),descricao:p.desc,quantidade:_pedSel[id]}});
 }});
 if(semForn.length>0){{alert('Atencao: '+semForn.length+' item(ns) sem fornecedor foram ignorados.')}}
 var fornsList=Object.keys(porForn);
 if(fornsList.length===0){{alert('Nenhum item com fornecedor valido.');return}}
 var resumo=fornsList.map(function(fid){{return '  - '+porForn[fid].fornecedor_nome+' ('+porForn[fid].itens.length+' itens)'}}).join('\\n');
 if(!confirm('Enviar '+fornsList.length+' pedido(s) com '+ids.length+' item(s)?\\n\\n'+resumo+'\\n\\nVai ser enviado pela nuvem e criado no VR Master pelo PC (em ate 1 min).'))return;
 var hoje=new Date();
 var yyyy=hoje.getFullYear(),mm=String(hoje.getMonth()+1).padStart(2,'0'),dd=String(hoje.getDate()).padStart(2,'0');
 var hh=String(hoje.getHours()).padStart(2,'0'),mi=String(hoje.getMinutes()).padStart(2,'0');
 var payload={{
  data_compra:yyyy+'-'+mm+'-'+dd,
  id_loja:1,
  id_comprador:1,
  id_divisaofornecedor:0,
  id_situacaopedido:1,
  id_tipofretepedido:0,
  id_tipoatendidopedido:0,
  origem:'dashboard_estoque',
  pedidos:fornsList.map(function(fid){{return {{id_fornecedor:parseInt(fid),fornecedor_nome:porForn[fid].fornecedor_nome,itens:porForn[fid].itens}}}})
 }};
 var btn=document.querySelector('.pedido-bar .b-gerar');
 var txtOrig=btn.innerHTML;btn.innerHTML='Enviando...';btn.disabled=true;
 fetch(PEDIDO_API_URL,{{
  method:'POST',
  headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify(payload)
 }}).then(function(r){{return r.json().then(function(body){{return {{status:r.status,body:body}}}})}})
 .then(function(res){{
  btn.innerHTML=txtOrig;btn.disabled=false;
  if(res.status===200&&res.body.ok){{
   limparSelecaoPedido();
   alert('Pedido enviado com sucesso!\\n\\nArquivo: '+res.body.arquivo+'\\nFornecedores: '+res.body.pedidos+'\\nItens: '+res.body.itens+'\\n\\nO PC vai criar no VR Master em ate 1 minuto.');
  }}else{{
   var erro=res.body.error||('Erro '+res.status);
   if(confirm('Falha ao enviar para a nuvem:\\n'+erro+'\\n\\nDeseja baixar o arquivo JSON para usar offline?')){{
    var nome='pedido_vrmaster_'+yyyy+mm+dd+'_'+hh+mi+'.json';
    baixarPedidoLocal(payload,nome);
   }}
  }}
 }}).catch(function(err){{
  btn.innerHTML=txtOrig;btn.disabled=false;
  if(confirm('Sem conexao com a nuvem:\\n'+err.message+'\\n\\nDeseja baixar o arquivo JSON para usar offline?')){{
   var nome='pedido_vrmaster_'+yyyy+mm+dd+'_'+hh+mi+'.json';
   baixarPedidoLocal(payload,nome);
  }}
 }});
}}
</script>
</body></html>"""

    return html


def main():
    logger.info("=" * 60)
    logger.info("GERANDO DASHBOARD DE ESTOQUE")
    logger.info("=" * 60)

    logger.info("Buscando dados...")
    produtos, obsoletos = buscar_dados()
    logger.info(f"{len(produtos)} produtos ativos | {len(obsoletos)} obsoletos")

    logger.info("Gerando estatisticas...")
    setores, fornecedores = gerar_estatisticas(produtos)

    logger.info("Gerando HTML...")
    html = gerar_html(produtos, setores, fornecedores, obsoletos)

    # Salvar na raiz do repo (para GitHub Pages) e localmente
    repo_root = os.path.dirname(BASE_DIR)
    output_path = os.path.join(repo_root, "estoque.html")
    local_path = os.path.join(BASE_DIR, "dashboard_estoque.html")

    for path in [output_path, local_path]:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)

    logger.info(f"Dashboard salvo em: {output_path}")
    logger.info(f"Copia local: {local_path}")
    logger.info(f"Tamanho: {len(html):,} bytes")
    logger.info("CONCLUIDO!")

    return output_path


def publicar():
    """Gera o dashboard e faz push para GitHub Pages."""
    import subprocess

    path = main()
    repo_root = os.path.dirname(BASE_DIR)

    logger.info("Publicando no GitHub Pages...")
    try:
        subprocess.run(["git", "add", "estoque.html"], cwd=repo_root, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Atualiza dashboard estoque"],
            cwd=repo_root, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "pull", "--rebase", "origin", "master"],
            cwd=repo_root, check=True
        )
        subprocess.run(["git", "push"], cwd=repo_root, check=True)
        logger.info("Push realizado! Dashboard disponivel em breve.")
    except subprocess.CalledProcessError as e:
        if b"nothing to commit" in (e.stdout or b""):
            logger.info("Sem alteracoes no dashboard.")
        else:
            logger.error(f"Erro no git: {e}")


if __name__ == "__main__":
    import sys as _sys
    if "--publicar" in _sys.argv:
        publicar()
    else:
        path = main()
        try:
            os.startfile(path)
        except Exception:
            pass
