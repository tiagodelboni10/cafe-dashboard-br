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

        # Embalagem e quantidade sugerida de compra
        id_forn = f.get('id_forn')
        emb = embalagens.get((p['id'], id_forn), 1) if id_forn else 1
        p['embalagem'] = emb

        # Qtd sugerida = (DDV ideal * VMD) - estoque atual, arredondado para cima em embalagens
        if p['vmd'] > 0 and p['status'] in ('ruptura', 'alerta', 'negativo'):
            qtd_ideal = ddv_ideal * p['vmd']
            qtd_comprar = max(0, qtd_ideal - max(0, p['est']))
            if emb > 1:
                qtd_comprar = -(-int(qtd_comprar) // emb) * emb  # ceil division
            else:
                qtd_comprar = max(1, int(qtd_comprar + 0.99))
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
        'setor': p['setor'], 'cat': p['cat'], 'forn': p['forn_curto'],
        'est': round(p['est'], 1), 'vmd': round(p['vmd'], 3),
        'ddv': round(p['ddv'], 1) if p['ddv'] is not None else None,
        'ddv_ideal': p['ddv_ideal'], 'lt': p['lead_time'], 'status': p['status'],
        'valor': round(p['valor_estoque'], 2), 'ult_entrada': p['ult_entrada'],
        'curva': p.get('curva', 'C'), 'fat30d': round(p.get('fat30d', 0), 2),
        'emb': p.get('embalagem', 1), 'qtd_comprar': p.get('qtd_comprar', 0),
    } for p in produtos], ensure_ascii=False)

    obsoletos_json = json.dumps([{
        'cod': str(p['id']).zfill(6), 'id': p['id'], 'desc': p['desc'][:55],
        'setor': p['setor'], 'cat': p['cat'],
        'forn': p.get('forn_curto', p.get('forn', 'SEM FORNECEDOR')[:30]),
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
@media print{{body{{background:#fff;color:#000;padding:0}}.hdr,.nav,.fl,.scroll-top{{display:none}}.pane{{display:block!important;border:none;padding:10px 0;background:#fff}}table{{font-size:9pt}}th{{background:#eee;color:#000}}td{{border-color:#ddd}}.b{{border:1px solid #999;background:#f0f0f0;color:#000}}}}
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
 <a onclick="go('excesso')" class="hide-mobile"><span class="ic">&#9888;</span> Excesso</a>
 <a onclick="go('obsoletos')" class="hide-mobile"><span class="ic">&#128465;</span> Obsoletos</a>
 <a onclick="go('praticas')" class="hide-mobile"><span class="ic">&#10067;</span> Ajuda</a>
</div>
<div class="pane on" id="p-comprar">
 <div class="sec"><div class="sec-t">&#128308; Comprar Agora — Criticos Curva A <span class="cnt cnt-r">{rupt_curva_a}</span></div>
  <p style="color:var(--dim);font-size:.82em;margin-bottom:12px">Produtos que mais vendem e estao sem estoque. Pedir <b>imediatamente</b>.</p>
  <div class="tw"><table class="resp"><thead><tr><th>Cod.</th><th>Produto</th><th>Setor</th><th>Fornecedor</th><th>Estoque</th><th>VMD</th><th>DDV</th><th>Qtd. Sugerida</th><th>Emb.</th><th>Fat. 30d</th></tr></thead><tbody id="t-crit"></tbody></table></div></div>
 <div class="sec"><div class="sec-t">&#128992; Comprar em Breve — Alertas Curva A <span class="cnt cnt-y">{alerta_curva_a}</span></div>
  <p style="color:var(--dim);font-size:.82em;margin-bottom:12px">Estoque acabando. Incluir no <b>proximo pedido</b>.</p>
  <div class="tw"><table class="resp"><thead><tr><th>Cod.</th><th>Produto</th><th>Setor</th><th>Fornecedor</th><th>Estoque</th><th>VMD</th><th>DDV</th><th>Qtd. Sugerida</th><th>Emb.</th><th>Lead Time</th></tr></thead><tbody id="t-alerta"></tbody></table></div></div>
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
 <div class="tw"><table class="resp" id="tab-todos"><thead><tr><th onclick="srt(0)">Status</th><th onclick="srt(1)">Curva</th><th onclick="srt(2)">Codigo</th><th onclick="srt(3)">Produto</th><th onclick="srt(4)">Setor</th><th onclick="srt(5)">Fornecedor</th><th onclick="srt(6)">Estoque</th><th onclick="srt(7)">VMD</th><th onclick="srt(8)">DDV</th><th onclick="srt(9)">Lead Time</th><th onclick="srt(10)">Fat. 30d</th><th onclick="srt(11)">Ult.Entrada</th></tr></thead><tbody id="t-todos"></tbody></table></div>
 <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;flex-wrap:wrap;gap:8px"><div id="cnt" style="color:var(--muted);font-size:.82em"></div><button id="btn-more" class="btn-clear" onclick="loadMore()" style="display:none">Mostrar mais 50 &#8595;</button></div>
</div>
<div class="pane" id="p-setores"><div class="cds" id="cds-set"></div></div>
<div class="pane" id="p-fornecedores"><div class="fl" style="position:static"><input type="text" id="sf" placeholder="&#128269; Buscar fornecedor..." oninput="fforn()"></div><div class="cds" id="cds-forn"></div></div>
<div class="pane" id="p-excesso">
 <div class="sec" style="border-color:rgba(204,102,255,.3)"><h3 style="color:var(--excess);margin-bottom:8px;font-size:1.15em">R$ {valor_excesso:,.2f} parados em estoque excedente</h3><p style="color:var(--dim);font-size:.85em">Produtos com DDV acima de <b>{FATOR_EXCESSO:.0f}x o ideal</b> do setor. <b style="color:var(--warn)">Nao comprar mais ate normalizar.</b></p></div>
 <div class="tw"><table class="resp"><thead><tr><th>Curva</th><th>Cod.</th><th>Produto</th><th>Setor</th><th>Fornecedor</th><th>Estoque</th><th>VMD</th><th>DDV</th><th>DDV Ideal</th><th>Excedente</th><th>R$ Parado</th></tr></thead><tbody id="t-exc"></tbody></table></div>
</div>
<div class="pane" id="p-obsoletos">
 <div class="sec" style="border-color:rgba(136,136,136,.3)"><h3 style="color:var(--dim);margin-bottom:8px;font-size:1.15em">{n_obsoletos} produtos sem entrada nos ultimos 12 meses</h3><p style="color:var(--dim);font-size:.85em">Sem nota de entrada ha mais de 1 ano. Considerar <b style="color:var(--warn)">desativar o cadastro</b> para limpar a base.{f' R$ {valor_obsoletos:,.2f} em estoque residual.' if valor_obsoletos > 0 else ''}</p></div>
 <div class="fl" style="position:static"><input type="text" id="search-obs" placeholder="&#128269; Buscar produto obsoleto..." oninput="filtrarObs()"><select id="filt-setor-obs" onchange="filtrarObs()"><option value="">Todos setores</option></select></div>
 <div class="tw"><table class="resp"><thead><tr><th onclick="srtObs(0)">Cod.</th><th onclick="srtObs(1)">Produto</th><th onclick="srtObs(2)">Setor</th><th onclick="srtObs(3)">Fornecedor</th><th onclick="srtObs(4)">Estoque</th><th onclick="srtObs(5)">VMD</th><th onclick="srtObs(6)">R$ Parado</th><th onclick="srtObs(7)">Ult. Entrada</th><th onclick="srtObs(8)">Dias s/ Entrada</th></tr></thead><tbody id="t-obs"></tbody></table></div>
 <div id="cnt-obs" style="color:var(--muted);font-size:.82em;margin-top:8px"></div>
</div>
<div class="pane" id="p-praticas"><div class="prs">
 <div class="pr" style="border-left-color:var(--danger)"><h3>&#128308; Curva ABC</h3><p><span class="t">A</span> = 80% do faturamento — nao pode faltar!<br><span class="t">B</span> = 15% do faturamento — importante<br><span class="t">C</span> = 5% do faturamento — menor impacto</p></div>
 <div class="pr" style="border-left-color:var(--danger)"><h3>&#128680; Ruptura</h3><p>Estoque acaba <span class="t">antes do fornecedor entregar</span>. DDV &lt; Lead Time.<br><b>Acao:</b> Pedir imediatamente.</p></div>
 <div class="pr" style="border-left-color:var(--warn)"><h3>&#9888; Alerta</h3><p>Proximo do ponto de pedido. Margem de 1 a 3 dias.<br><b>Acao:</b> Incluir no proximo pedido.</p></div>
 <div class="pr" style="border-left-color:var(--excess)"><h3>&#8593; Excesso</h3><p>DDV <span class="t">{FATOR_EXCESSO:.0f}x acima do ideal</span> = dinheiro parado.<br><b>Acao:</b> Parar de comprar. Considerar promocao.</p></div>
 <div class="pr"><h3>&#128200; DDV e VMD</h3><p><span class="t">VMD</span> = Venda Media Diaria (ultimos 7 dias)<br><span class="t">DDV</span> = Estoque / VMD (dias que dura)<br>DDV=5 e lead time=7 → estoque acaba antes da entrega.</p></div>
 <div class="pr"><h3>&#129518; Quantidade Sugerida</h3><p><span class="t">Formula:</span> (DDV ideal x VMD) - Estoque atual<br>Arredondado para a embalagem do fornecedor.</p></div>
 <div class="pr"><h3>&#128197; DDV Ideal por Setor</h3><p>{ddv_ideal_html}<br><span class="t">Outros:</span> {DDV_IDEAL_PADRAO} dias</p></div>
 <div class="pr"><h3>&#128666; Lead Time</h3><p>Tempo medio entre entregas de cada fornecedor. Calculado pelas notas de entrada dos ultimos 90 dias.</p></div>
</div></div>
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
function init(){{rCrit();rAlt();renderPedidos();pFiltros();filtrar();rSet();rForn();rExc();rObs();pFiltrosObs()}}
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
function rCrit(){{const d=D.filter(x=>(x.status==='ruptura'||x.status==='negativo')&&x.curva==='A').sort((a,b)=>b.fat30d-a.fat30d);document.getElementById('t-crit').innerHTML=d.map(x=>'<tr class="R"><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main"><b>'+x.desc+'</b></td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque" style="color:var(--danger);font-weight:800">'+x.est.toFixed(1)+'</td><td data-label="VMD">'+x.vmd.toFixed(1)+'</td><td data-label="DDV">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Qtd." style="color:var(--accent);font-weight:800;font-size:1.1em">'+(x.qtd_comprar||'-')+'</td><td data-label="Emb.">'+(x.emb>1?x.emb+'un':'')+'</td><td data-label="Fat.30d">'+R(x.fat30d)+'</td></tr>').join('')}}
function rAlt(){{const d=D.filter(x=>x.status==='alerta'&&x.curva==='A').sort((a,b)=>b.fat30d-a.fat30d);document.getElementById('t-alerta').innerHTML=d.map(x=>'<tr class="A"><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque" style="color:var(--warn);font-weight:700">'+x.est.toFixed(1)+'</td><td data-label="VMD">'+x.vmd.toFixed(1)+'</td><td data-label="DDV">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Qtd." style="color:var(--accent);font-weight:800;font-size:1.1em">'+(x.qtd_comprar||'-')+'</td><td data-label="Emb.">'+(x.emb>1?x.emb+'un':'')+'</td><td data-label="Lead Time">'+x.lt+'d</td></tr>').join('')}}
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
  '<div class="ped-hdr"><h3>'+forn+'</h3><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><div class="info">'+prods.length+' itens | ~'+lt+'d'+(nR?' | <b style="color:var(--danger)">'+nR+' rupt</b>':'')+(nA?' | <b style="color:var(--warn)">'+nA+' alertas</b>':'')+'</div><button class="btn-copy" id="'+fid+'" onclick="copiarPedido(\''+forn.replace(/'/g,"\\\\'")+'\',\''+fid+'\')">&#128203; Copiar</button></div></div>'+
  '<div class="tw"><table class="resp"><thead><tr><th>Curva</th><th>Status</th><th>Codigo</th><th>Produto</th><th>Setor</th><th>Estoque</th><th>VMD</th><th>DDV</th><th style="color:var(--accent)">Qtd. Comprar</th><th>Emb.</th></tr></thead><tbody>'+
  prods.map(x=>'<tr class="'+(x.status==='ruptura'||x.status==='negativo'?'R':'A')+'"><td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Status">'+sb(x.status)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Estoque" style="font-weight:700;color:'+(x.est<=0?'var(--danger)':'var(--warn)')+'">'+x.est.toFixed(1)+'</td><td data-label="VMD">'+x.vmd.toFixed(1)+'</td><td data-label="DDV">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Qtd." style="color:var(--accent);font-weight:800;font-size:1.1em">'+(x.qtd_comprar||'-')+'</td><td data-label="Emb.">'+(x.emb>1?x.emb+'un':'un')+'</td></tr>').join('')+'</tbody></table></div>'}}).join('')}}
function copiarPedido(forn,btnId){{
 const itens=D.filter(x=>(x.status==='ruptura'||x.status==='alerta'||x.status==='negativo')&&x.forn===forn);
 let txt='*Pedido - '+forn+'*\\n'+new Date().toLocaleDateString('pt-BR')+'\\n\\n';
 itens.forEach(x=>{{txt+=x.cod+' - '+x.desc+'\\n  Qtd: '+(x.qtd_comprar||'?')+' | Est: '+x.est.toFixed(0)+' | VMD: '+x.vmd.toFixed(1)+'\\n'}});
 txt+='\\n_Dashboard Merkal_';
 navigator.clipboard.writeText(txt).then(()=>{{const btn=document.getElementById(btnId);btn.textContent='\\u2713 Copiado!';btn.classList.add('ok');setTimeout(()=>{{btn.innerHTML='&#128203; Copiar';btn.classList.remove('ok')}},2000)}})}}
function pFiltros(){{const ss=[...new Set(D.map(x=>x.setor))].sort();const s1=document.getElementById('filt-setor');ss.forEach(s=>{{const o=document.createElement('option');o.value=s;o.textContent=s;s1.appendChild(o)}});const ff=[...new Set(D.map(x=>x.forn))].sort();const s2=document.getElementById('filt-forn');ff.forEach(f=>{{const o=document.createElement('option');o.value=f;o.textContent=f;s2.appendChild(o)}})}}
let _debounceTimer;
function debounceFiltrar(){{clearTimeout(_debounceTimer);_debounceTimer=setTimeout(filtrar,200)}}
function gF(){{const q=document.getElementById('search').value.toLowerCase(),se=document.getElementById('filt-setor').value,fo=document.getElementById('filt-forn').value,st=document.getElementById('filt-status').value,cu=document.getElementById('filt-curva').value;return D.filter(x=>{{if(q&&!x.desc.toLowerCase().includes(q)&&!x.cod.includes(q))return false;if(se&&x.setor!==se)return false;if(fo&&x.forn!==fo)return false;if(st&&x.status!==st)return false;if(cu&&x.curva!==cu)return false;return true}})}}
function filtrar(){{_showN=50;_filteredData=gF();rTodos(_filteredData)}}
function limparFiltros(){{document.getElementById('search').value='';document.getElementById('filt-setor').value='';document.getElementById('filt-forn').value='';document.getElementById('filt-status').value='';document.getElementById('filt-curva').value='';filtrar()}}
function loadMore(){{_showN+=50;rTodos(_filteredData)}}
function rTodos(data){{const t=document.getElementById('t-todos'),showing=Math.min(data.length,_showN);t.innerHTML=data.slice(0,showing).map(x=>'<tr class="'+({{ruptura:'R',alerta:'A',excesso:'E',negativo:'N'}}[x.status]||'')+'"><td data-label="Status">'+sb(x.status)+'</td><td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque">'+x.est.toFixed(1)+'</td><td data-label="VMD">'+x.vmd.toFixed(1)+'</td><td data-label="DDV">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Lead Time">'+x.lt+'d</td><td data-label="Fat.30d">'+R(x.fat30d)+'</td><td data-label="Ult.Entrada">'+x.ult_entrada+'</td></tr>').join('');document.getElementById('cnt').textContent='Mostrando '+showing+' de '+data.length;document.getElementById('btn-more').style.display=showing<data.length?'block':'none'}}
let sC=-1,sA=true;
function srt(c){{if(sC===c)sA=!sA;else{{sC=c;sA=true}};const ks=['status','curva','cod','desc','setor','forn','est','vmd','ddv','lt','fat30d','ult_entrada'];const k=ks[c];_filteredData=gF();_filteredData.sort((a,b)=>{{let va=a[k],vb=b[k];if(va===null)va=sA?999999:-999999;if(vb===null)vb=sA?999999:-999999;if(typeof va==='string')return sA?va.localeCompare(vb):vb.localeCompare(va);return sA?va-vb:vb-va}});_showN=50;rTodos(_filteredData)}}
var _setKeys=[];
function rSet(){{var c=document.getElementById('cds-set'),entries=Object.entries(SET);_setKeys=entries.map(e=>e[0]);c.innerHTML='';entries.forEach((e,i)=>{{var n=e[0],s=e[1],t=s.total||1;var d=document.createElement('div');d.className='cd';d.setAttribute('data-idx',i);d.innerHTML='<h3>'+n+' <span style="font-size:.7em;color:#666">&#9660;</span></h3><div class="sts"><span><b style="color:var(--danger)">'+s.ruptura+'</b> rupt</span><span><b style="color:var(--warn)">'+s.alerta+'</b> alerta</span><span><b style="color:var(--ok)">'+s.ok+'</b> ok</span><span><b style="color:var(--excess)">'+s.excesso+'</b> exc</span></div><div style="font-size:.8em;color:var(--muted)">'+s.total+' itens | '+R(s.valor_estoque)+'</div>'+(s.valor_excesso>0?'<div style="font-size:.8em;color:var(--excess)">'+R(s.valor_excesso)+' excesso</div>':'')+'<div class="br"><div style="width:'+(s.ruptura/t*100)+'%;background:var(--danger)"></div><div style="width:'+(s.alerta/t*100)+'%;background:var(--warn)"></div><div style="width:'+(s.ok/t*100)+'%;background:var(--ok)"></div><div style="width:'+(s.excesso/t*100)+'%;background:var(--excess)"></div></div><div class="detail-panel" style="display:none"></div>';d.addEventListener('click',function(){{toggleDetail(this.querySelector('.detail-panel'),'setor',_setKeys[this.getAttribute('data-idx')])}});c.appendChild(d)}})}}
var _frnKeys=[];
function rForn(){{rFL(Object.entries(FRN))}}
function fforn(){{var q=document.getElementById('sf').value.toLowerCase();rFL(Object.entries(FRN).filter(e=>e[0].toLowerCase().indexOf(q)>=0))}}
function rFL(e){{var c=document.getElementById('cds-forn');_frnKeys=e.map(x=>x[0]);c.innerHTML='';e.forEach((entry,i)=>{{var n=entry[0],f=entry[1],t=f.total||1;var d=document.createElement('div');d.className='cd';d.setAttribute('data-idx',i);d.innerHTML='<h3>'+n+' <span style="font-size:.7em;color:#666">&#9660;</span></h3><div class="sts"><span><b style="color:var(--danger)">'+f.ruptura+'</b> rupt</span><span><b style="color:var(--warn)">'+f.alerta+'</b> alerta</span><span><b style="color:var(--ok)">'+f.ok+'</b> ok</span><span><b style="color:var(--excess)">'+f.excesso+'</b> exc</span></div><div style="font-size:.8em;color:var(--muted)">'+f.total+' itens | ~'+f.lead_time+'d entrega | '+R(f.valor_estoque)+'</div><div class="br"><div style="width:'+(f.ruptura/t*100)+'%;background:var(--danger)"></div><div style="width:'+(f.alerta/t*100)+'%;background:var(--warn)"></div><div style="width:'+(f.ok/t*100)+'%;background:var(--ok)"></div><div style="width:'+(f.excesso/t*100)+'%;background:var(--excess)"></div></div><div class="detail-panel" style="display:none"></div>';d.addEventListener('click',function(){{toggleDetail(this.querySelector('.detail-panel'),'forn',_frnKeys[this.getAttribute('data-idx')])}});c.appendChild(d)}})}}
function toggleDetail(el,tp,nm){{if(!el)return;event.stopPropagation();if(el.style.display!=='none'){{el.style.display='none';return}};if(!el.dataset.loaded){{let prods;if(tp==='setor')prods=D.filter(x=>x.setor===nm);else prods=D.filter(x=>x.forn===nm);prods.sort((a,b)=>{{const o={{ruptura:0,negativo:1,alerta:2,ok:3,excesso:4}};if((o[a.status]||3)!==(o[b.status]||3))return(o[a.status]||3)-(o[b.status]||3);return a.curva.localeCompare(b.curva)||(b.fat30d-a.fat30d)}});el.innerHTML='<div class="tw" style="margin-top:10px"><table class="resp"><thead><tr><th>Status</th><th>Curva</th><th>Cod.</th><th>Produto</th>'+(tp==='setor'?'<th>Categoria</th><th>Fornecedor</th>':'<th>Setor</th><th>Categoria</th>')+'<th>Estoque</th><th>VMD</th><th>DDV</th><th>Fat.30d</th><th>Ult.Entrada</th></tr></thead><tbody>'+prods.map(x=>'<tr class="'+({{ruptura:'R',alerta:'A',excesso:'E',negativo:'N'}}[x.status]||'')+'"><td data-label="Status">'+sb(x.status)+'</td><td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td>'+(tp==='setor'?'<td data-label="Categoria">'+x.cat+'</td><td data-label="Fornecedor">'+x.forn+'</td>':'<td data-label="Setor">'+x.setor+'</td><td data-label="Categoria">'+x.cat+'</td>')+'<td data-label="Estoque">'+x.est.toFixed(1)+'</td><td data-label="VMD">'+x.vmd.toFixed(1)+'</td><td data-label="DDV">'+dv(x.ddv,x.ddv_ideal,x.lt)+'</td><td data-label="Fat.30d">'+R(x.fat30d)+'</td><td data-label="Ult.Entrada">'+x.ult_entrada+'</td></tr>').join('')+'</tbody></table></div>';el.dataset.loaded='1'}};el.style.display='block'}}
function pFiltrosObs(){{const ss=[...new Set(OBS.map(x=>x.setor))].sort();const s1=document.getElementById('filt-setor-obs');ss.forEach(s=>{{const o=document.createElement('option');o.value=s;o.textContent=s;s1.appendChild(o)}})}}
function gFObs(){{const q=document.getElementById('search-obs').value.toLowerCase(),se=document.getElementById('filt-setor-obs').value;return OBS.filter(x=>{{if(q&&!x.desc.toLowerCase().includes(q)&&!x.cod.includes(q))return false;if(se&&x.setor!==se)return false;return true}})}}
function filtrarObs(){{rObsList(gFObs())}}
let sOC=-1,sOA=true;
function srtObs(c){{if(sOC===c)sOA=!sOA;else{{sOC=c;sOA=true}};const ks=['cod','desc','setor','forn','est','vmd','valor','ult_entrada','dias_sem_entrada'];const k=ks[c];let d=gFObs();d.sort((a,b)=>{{let va=a[k],vb=b[k];if(va===null||va===undefined)va=sOA?999999:-999999;if(vb===null||vb===undefined)vb=sOA?999999:-999999;if(typeof va==='string')return sOA?va.localeCompare(vb):vb.localeCompare(va);return sOA?va-vb:vb-va}});rObsList(d)}}
function rObs(){{rObsList(OBS)}}
function rObsList(data){{const t=document.getElementById('t-obs');t.innerHTML=data.slice(0,500).map(x=>'<tr class="N"><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque">'+x.est.toFixed(1)+'</td><td data-label="VMD">'+x.vmd.toFixed(3)+'</td><td data-label="R$ Parado" style="color:var(--warn)">'+(x.valor>0?R(x.valor):'-')+'</td><td data-label="Ult. Entrada">'+x.ult_entrada+'</td><td data-label="Dias s/ Entrada" style="color:var(--muted);font-weight:700">'+(x.dias_sem_entrada!==null?x.dias_sem_entrada+'d':'Nunca')+'</td></tr>').join('');document.getElementById('cnt-obs').textContent='Mostrando '+Math.min(data.length,500)+' de '+data.length+' obsoletos'}}
function rExc(){{const d=D.filter(x=>x.status==='excesso').sort((a,b)=>{{const ea=Math.max(0,a.est-a.vmd*a.ddv_ideal)*(a.est>0?a.valor/a.est:0);const eb=Math.max(0,b.est-b.vmd*b.ddv_ideal)*(b.est>0?b.valor/b.est:0);return eb-ea}});document.getElementById('t-exc').innerHTML=d.map(x=>{{const iq=x.vmd*x.ddv_ideal,ex=Math.max(0,x.est-iq),cu=x.est>0?x.valor/x.est:0,vp=ex*cu;return'<tr class="E"><td data-label="Curva">'+cb(x.curva)+'</td><td data-label="Codigo">'+x.cod+'</td><td data-label="Produto" class="td-main">'+x.desc+'</td><td data-label="Setor">'+x.setor+'</td><td data-label="Fornecedor">'+x.forn+'</td><td data-label="Estoque">'+x.est.toFixed(0)+'</td><td data-label="VMD">'+x.vmd.toFixed(1)+'</td><td data-label="DDV">'+(x.ddv!==null?x.ddv.toFixed(0)+'d':'-')+'</td><td data-label="DDV Ideal">'+x.ddv_ideal+'d</td><td data-label="Excedente" style="color:var(--excess);font-weight:700">'+ex.toFixed(0)+'</td><td data-label="R$ Parado" style="color:var(--excess);font-weight:700">'+R(vp)+'</td></tr>'}}).join('')}}
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
