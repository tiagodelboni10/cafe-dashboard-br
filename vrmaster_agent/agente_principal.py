"""
Agente VR Master - Verificacao de Margens
=========================================
1. Consulta vendas do dia via SQL direto no PostgreSQL
2. Compara "Margem Sb. Venda" com tabela de referencia
3. Gera relatorio PDF
4. Envia resumo no grupo MERKAL ADM do WhatsApp

Agendado para rodar todos os dias as 06:00 via Task Scheduler.
Sempre puxa as vendas do DIA ANTERIOR.
"""
import os
import sys
import logging
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"agente_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# === Configuracoes ===
GRUPO_WHATSAPP = "MERKAL ADM"
NUMERO_WHATSAPP = "5527999044729"  # fallback se grupo falhar
ENVIAR_WHATSAPP = True


def preco_ideal(custo_unit, margem_tabela):
    """Calcula preco ideal e arredonda para ,98 ou ,59 (o mais proximo acima)."""
    if margem_tabela >= 100 or custo_unit <= 0:
        return None
    preco = custo_unit / (1 - margem_tabela / 100)
    parte_inteira = int(preco)
    opcoes = []
    for base in [parte_inteira - 1, parte_inteira, parte_inteira + 1]:
        opcoes.append(base + 0.59)
        opcoes.append(base + 0.98)
    opcoes_validas = [p for p in opcoes if p >= preco]
    if opcoes_validas:
        return min(opcoes_validas)
    return min(opcoes, key=lambda x: abs(x - preco))


def main():
    logger.info("=" * 60)
    logger.info("AGENTE VR MASTER - VERIFICACAO DE MARGENS")
    logger.info(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    logger.info("=" * 60)

    # === ETAPA 1: Consulta ao banco ===
    logger.info("ETAPA 1: Consultando banco de dados...")
    try:
        from consulta_db import consultar_vendas_por_produto, consultar_vendas_pdv_realtime
        from tabela_margens import encontrar_margem_esperada, e_item_sensivel
        from config import TOLERANCIA_MARGEM

        # Sempre puxa o dia anterior (roda as 06:00)
        data_ontem = date.today() - timedelta(days=1)
        data_consulta = data_ontem
        caixa_nao_fechado = False

        # Tentar dados do fechamento de caixa (mais preciso)
        produtos, totais = consultar_vendas_por_produto(data_consulta)

        if not produtos:
            # Caixa nao fechado — usar logestoque em tempo real
            logger.warning(f"Caixa nao fechado {data_consulta.strftime('%d/%m/%Y')}. Usando Venda PDV (tempo real)...")
            caixa_nao_fechado = True
            produtos, totais = consultar_vendas_pdv_realtime(data_consulta)
            if produtos:
                logger.info(f"Venda PDV (logestoque): {totais['total_produtos']} produtos")

        if not produtos:
            logger.error("Nenhum dado de venda encontrado!")
            return False

        logger.info(f"Dados: {totais['total_produtos']} produtos, "
                     f"R$ {totais['total_venda_bruta']:,.2f} ({data_consulta.strftime('%d/%m/%Y')})"
                     f"{' [via PDV real-time]' if caixa_nao_fechado else ''}")

    except Exception as e:
        logger.error(f"ERRO na consulta: {e}", exc_info=True)
        return False

    # === ETAPA 2: Analise de margens ===
    logger.info("ETAPA 2: Analisando margens...")
    try:
        itens_abaixo = []
        itens_sensiveis = []

        for prod in produtos:
            desc = str(prod.get('descricao', ''))
            margem_real = float(prod.get('margem_sb_venda', 0))
            cod = str(prod.get('id_produto', ''))
            preco = float(prod.get('preco_venda', 0))
            custo = float(prod.get('venda_bruta', 0))
            qtd = float(prod.get('quantidade', 0))

            # Calcular custo unitario
            if qtd > 0 and preco > 0:
                custo_unit = preco * (1 - margem_real / 100)
            else:
                continue

            ref = encontrar_margem_esperada(desc)
            sensivel = e_item_sensivel(desc)

            if ref:
                mg_min = ref[0]
                if margem_real < (mg_min - TOLERANCIA_MARGEM):
                    pi = preco_ideal(custo_unit, mg_min)
                    item = (cod, desc, margem_real, mg_min, preco, pi)
                    if sensivel:
                        itens_sensiveis.append(item)
                    else:
                        itens_abaixo.append(item)

        # Ordenar por diferenca (maior gap primeiro)
        itens_abaixo.sort(key=lambda x: x[2] - x[3])
        itens_sensiveis.sort(key=lambda x: x[2] - x[3])

        logger.info(f"Resultados: {len(itens_abaixo)} SUBIR PRECO | "
                     f"{len(itens_sensiveis)} SENSIVEIS")

    except Exception as e:
        logger.error(f"ERRO na analise: {e}", exc_info=True)
        return False

    # === ETAPA 3: Gerar PDF ===
    logger.info("ETAPA 3: Gerando PDF...")
    try:
        from analisar_margens import analisar_dados, gerar_relatorio_pdf
        analise = analisar_dados(produtos)
        pdf_path = gerar_relatorio_pdf(*analise, data_consulta=data_consulta)
        logger.info(f"PDF: {pdf_path}")
    except Exception as e:
        logger.error(f"ERRO no PDF: {e}", exc_info=True)
        pdf_path = None

    # === ETAPA 4: Montar e enviar WhatsApp ===
    if ENVIAR_WHATSAPP and (itens_abaixo or itens_sensiveis):
        logger.info("ETAPA 4: Enviando WhatsApp...")
        try:
            linhas = []
            if caixa_nao_fechado:
                linhas += [f'*CAIXA NAO FECHADO - {data_ontem.strftime("%d/%m/%Y")}*',
                           f'_Dados via Venda PDV (preco de cadastro)_', '']
            linhas += [f'*MARGENS ABAIXO DA TABELA - {data_consulta.strftime("%d/%m/%Y")}*',
                      f'{len(itens_abaixo) + len(itens_sensiveis)} itens no total', '']

            if itens_abaixo:
                linhas += [f'*SUBIR PRECO ({len(itens_abaixo)} itens):*', '']
                for cod, desc, prat, exig, pa, pi in itens_abaixo:
                    pis = f'R$ {pi:,.2f}'.replace('.', ',') if pi else '-'
                    pas = f'R$ {pa:,.2f}'.replace('.', ',')
                    linhas += [f'*{cod}* - {desc}',
                               f'Praticada: *{prat:.1f}%* | Tabela: *{exig}%*',
                               f'Preco atual: {pas} | Preco ideal: *{pis}*', '']

            if itens_sensiveis:
                linhas += [f'*ITENS SENSIVEIS - NAO SUBIR PRECO ({len(itens_sensiveis)} itens):*',
                           '_Manter igual ou mais barato que concorrencia_', '']
                for cod, desc, prat, exig, pa, pi in itens_sensiveis:
                    pas = f'R$ {pa:,.2f}'.replace('.', ',')
                    linhas += [f'*{cod}* - {desc}',
                               f'Praticada: *{prat:.1f}%* | Tabela: *{exig}%*',
                               f'Preco atual: {pas}', '']

            linhas.append('_Agente VR Master_')
            msg = '\n'.join(linhas)

            from enviar_whatsapp import enviar_para_grupo
            enviar_para_grupo(msg, GRUPO_WHATSAPP)
            logger.info("WhatsApp enviado!")

        except Exception as e:
            logger.error(f"ERRO no WhatsApp: {e}", exc_info=True)

    elif not itens_abaixo and not itens_sensiveis:
        logger.info("Todos os itens dentro da margem. Nenhum alerta enviado.")

    # Abrir PDF
    if pdf_path:
        try:
            os.startfile(pdf_path)
        except Exception:
            pass

    logger.info("=" * 60)
    logger.info("AGENTE CONCLUIDO!")
    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    sucesso = main()
    sys.exit(0 if sucesso else 1)
