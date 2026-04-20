"""
worker_pedidos.py
=================
Puxa pedidos pendentes do repositorio GitHub (enviados pelo dashboard) e
cria no VR Master. Roda a cada 1 min via Task Scheduler.

Fluxo por execucao:
  1. git pull no repo
  2. Para cada arquivo .json em pedidos_pendentes/:
     a. Cria pedido(s) no VR Master via enviar_pedido.py
     b. Move arquivo para pedidos_processados/ (ou pedidos_com_erro/ se falhar)
  3. git add + commit + push (se houve mudanca)

Idempotente: mesmo rodando de minuto em minuto, nao cria pedidos duplicados
(cada arquivo eh movido apos processar).
"""
import os
import sys
import json
import shutil
import logging
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
PENDENTES = os.path.join(REPO_ROOT, "pedidos_pendentes")
PROCESSADOS = os.path.join(REPO_ROOT, "pedidos_processados")
COM_ERRO = os.path.join(REPO_ROOT, "pedidos_com_erro")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

for d in (PENDENTES, PROCESSADOS, COM_ERRO, LOGS_DIR):
    os.makedirs(d, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"worker_pedidos_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

sys.path.insert(0, BASE_DIR)
from enviar_pedido import conectar, inserir_pedido  # reusa a logica ja testada


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


def git(*args, check=True):
    """Roda git no repo root. Retorna stdout. Sem janela de console no Windows."""
    r = subprocess.run(
        ["git"] + list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=_NO_WINDOW,
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} falhou: {r.stderr.strip()}")
    return r.stdout.strip()


def sincronizar_repo():
    """git pull com rebase. Tolera conflito local simples."""
    try:
        git("pull", "--rebase", "--autostash")
        logger.info("git pull ok")
    except RuntimeError as e:
        logger.warning(f"git pull falhou: {e}. Tentando fetch + reset...")
        git("fetch", "origin", "master")
        # Nao fazemos reset --hard aqui por seguranca — se tiver conflito, alerta
        raise


def listar_pendentes():
    arquivos = []
    for nome in os.listdir(PENDENTES):
        if nome.endswith(".json") and not nome.startswith("."):
            arquivos.append(os.path.join(PENDENTES, nome))
    return sorted(arquivos)  # FIFO


def processar_arquivo(conn, path):
    """Processa um arquivo de pedido. Retorna (sucesso, resumo, erro_msg)."""
    nome = os.path.basename(path)
    logger.info(f"Processando {nome}...")
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        return False, None, f"erro ao ler JSON: {e}"

    cur = conn.cursor()
    try:
        pedidos_criados = []
        for pedido in payload["pedidos"]:
            id_pedido, valor = inserir_pedido(cur, pedido, payload)
            pedidos_criados.append((id_pedido, pedido["fornecedor_nome"],
                                    len(pedido["itens"]), valor))
        conn.commit()
        resumo = "; ".join(f"#{p[0]} {p[1]} ({p[2]} itens R${p[3]:.2f})"
                            for p in pedidos_criados)
        logger.info(f"  Criado no VR: {resumo}")
        return True, resumo, None
    except Exception as e:
        conn.rollback()
        logger.error(f"  Falha ao inserir no VR: {e}")
        return False, None, str(e)


def mover_arquivo(path, dest_dir, sufixo=None, info=None):
    """Move arquivo para pasta dest. Opcionalmente anexa info de erro."""
    nome = os.path.basename(path)
    if sufixo:
        base, ext = os.path.splitext(nome)
        nome = f"{base}_{sufixo}{ext}"
    dest = os.path.join(dest_dir, nome)

    if info:
        # Acrescentar info ao JSON antes de mover
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("_meta", {}).update(info)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    shutil.move(path, dest)
    return dest


def commit_e_push(mensagens):
    """Commit arquivos movidos e faz push. Tolera 'nothing to commit'."""
    git("add", "pedidos_pendentes/", "pedidos_processados/", "pedidos_com_erro/")
    status = git("status", "--porcelain")
    if not status:
        logger.info("Sem mudancas para commitar")
        return
    msg = f"Worker pedidos: {'; '.join(mensagens)}"
    try:
        git("commit", "-m", msg)
    except RuntimeError as e:
        logger.warning(f"commit falhou: {e}")
        return
    try:
        git("push")
        logger.info("Push realizado")
    except RuntimeError as e:
        logger.warning(f"push falhou (tentara de novo na proxima): {e}")


def main():
    logger.info("=" * 50)
    logger.info("Worker pedidos iniciando")

    try:
        sincronizar_repo()
    except Exception as e:
        logger.error(f"Sync falhou, abortando: {e}")
        return 1

    pendentes = listar_pendentes()
    if not pendentes:
        logger.info("Nenhum pedido pendente.")
        return 0

    logger.info(f"{len(pendentes)} arquivo(s) pendente(s)")

    conn = conectar()
    sumario = []
    try:
        for path in pendentes:
            nome = os.path.basename(path)
            ok, resumo, erro = processar_arquivo(conn, path)
            if ok:
                mover_arquivo(path, PROCESSADOS, info={
                    "processado_em": datetime.now().isoformat(timespec="seconds"),
                    "pedidos_criados": resumo,
                })
                sumario.append(f"OK {nome}: {resumo}")
            else:
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                mover_arquivo(path, COM_ERRO, sufixo=f"erro_{ts}", info={
                    "erro_em": datetime.now().isoformat(timespec="seconds"),
                    "erro_msg": erro,
                })
                sumario.append(f"ERRO {nome}: {erro}")
    finally:
        conn.close()

    commit_e_push(sumario)
    logger.info("Worker concluido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
