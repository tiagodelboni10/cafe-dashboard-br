"""
agente_nfe.py
=============
Le arquivos da fila nfe_fila/ e executa no VR Master:
  1. Abre Repositorio de NF-e Entrada (se nao estiver)
  2. Busca a nota pelo numero
  3. Seleciona, clica Conferir NF-e, marca Consultar autenticidade, Conferir
  4. Na janela de divergencia, clica Conferir
  5. Clica Carregar NF-e, escolhe Tipo (baseado no historico do fornecedor)
  6. Se aparecer dialog de CFOP divergente, clica Sim
  7. Espera validar e move arquivo para nfe_processadas/

Roda a cada 1 min. Processa 1 nota por execucao (para dar intervalo).

Requisitos:
  - VR Master aberto e logado (pode ficar minimizado)
  - pywinauto instalado

Responde no WhatsApp via enviar_whatsapp.py (best effort).
"""
import os
import sys
import json
import time
import logging
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS, ID_LOJA

GRUPO_RESPOSTA = os.environ.get("MERKAL_NOTAS_GRUPO", "MERKAL NOTAS")

FILA_DIR = BASE_DIR / "nfe_fila"
PROCESSADAS_DIR = BASE_DIR / "nfe_processadas"
ERROS_DIR = BASE_DIR / "nfe_erros"
LOGS_DIR = BASE_DIR / "logs"
for d in (FILA_DIR, PROCESSADAS_DIR, ERROS_DIR, LOGS_DIR):
    d.mkdir(exist_ok=True)

log_file = LOGS_DIR / f"agente_nfe_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def conectar_db():
    import psycopg2
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS, connect_timeout=15
    )


def tipo_entrada_mais_usado(id_fornecedor, id_loja=ID_LOJA, limite=10):
    """Busca o id_tipoentrada mais usado nas ultimas N notas desse fornecedor."""
    conn = conectar_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH ultimas AS (
                SELECT id_tipoentrada
                FROM notaentrada
                WHERE id_fornecedor = %s AND id_loja = %s
                  AND id_tipoentrada IS NOT NULL
                ORDER BY dataentrada DESC NULLS LAST
                LIMIT %s
            )
            SELECT id_tipoentrada, COUNT(*) c
            FROM ultimas
            GROUP BY 1
            ORDER BY c DESC, id_tipoentrada ASC
            LIMIT 1
        """, (id_fornecedor, id_loja, limite))
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def buscar_dados_nota(numero_nota, id_loja=ID_LOJA):
    """Busca dados da nota no repositorio (para log e validacao)."""
    conn = conectar_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT nne.id, nne.id_fornecedor, f.razaosocial, nne.conferido, nne.carregado,
                   nne.datahorarecebimento, nne.valortotal
            FROM notaentradanfe nne
            JOIN fornecedor f ON nne.id_fornecedor = f.id
            WHERE nne.numeronota = %s AND nne.id_loja = %s
            ORDER BY nne.datahorarecebimento DESC
            LIMIT 1
        """, (int(numero_nota), id_loja))
        return cur.fetchone()
    finally:
        conn.close()


def responder_whatsapp(msg):
    """Envia resposta no grupo Merkal NOTAS (best effort — nao bloqueia se falhar)."""
    try:
        from enviar_whatsapp import enviar_para_grupo
        enviar_para_grupo(msg, GRUPO_RESPOSTA)
        logger.info(f"WhatsApp enviado ({GRUPO_RESPOSTA}): {msg[:80]}")
    except Exception as e:
        logger.warning(f"Falha WhatsApp (segue): {e}")


# =========================================================
# AUTOMACAO VR MASTER via pywinauto
# =========================================================

def _conectar_app():
    """Conecta no VR Master. Tenta UIA (melhor para Java Swing) e fallback win32."""
    from pywinauto import Application
    from pywinauto.findwindows import ElementNotFoundError
    ultimo_erro = None
    for backend in ("uia", "win32"):
        try:
            app = Application(backend=backend).connect(title_re="VR Master.*", timeout=5)
            return app, backend
        except ElementNotFoundError as e:
            ultimo_erro = e
    raise RuntimeError(
        f"VR Master nao esta aberto (verificado UIA+win32). Ultimo erro: {ultimo_erro}"
    )


def _forcar_foreground(hwnd):
    """Traz janela para frente bypassando focus-lock do Windows."""
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return
    cur_thread = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    try:
        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, fg_thread, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, fg_thread, False)


def focar_vr_master():
    """Conecta + traz VR Master para o frente agressivamente."""
    app, backend = _conectar_app()
    logger.info(f"VR Master conectado (backend {backend}).")
    w = app.window(title_re="VR Master.*")
    try:
        w.restore()
    except Exception:
        pass
    # foco agressivo via Win32
    try:
        hwnd = w.handle if hasattr(w, "handle") else w.wrapper_object().handle
        _forcar_foreground(hwnd)
    except Exception as e:
        logger.warning(f"Forcar foreground falhou: {e}. Tentando set_focus().")
        try:
            w.set_focus()
        except Exception as e2:
            logger.warning(f"set_focus tambem falhou: {e2}")
    time.sleep(0.6)
    return app, w


def abrir_repositorio_nfe(app, main_win):
    """
    Caminho no VR:
      Nota Fiscal > Repositorio > NF-e > Entrada
    Navega via teclado (pyautogui) porque Delphi nao expoe menu nativo
    confiavelmente via pywinauto.

    Sequencia:
      Alt+N          -> abre menu Nota Fiscal
      R, R           -> cicla entre 'Recebimento' e 'Repositorio'
      Right          -> abre submenu Repositorio
      N, N           -> cicla entre 'NFC-e' e 'NF-e'
      Right          -> abre submenu NF-e
      Enter          -> ativa 'Entrada' (primeiro item)
    """
    import pyautogui
    logger.info("Abrindo Repositorio de NF-e Entrada (menu 4 niveis)...")

    existentes = app.windows(title_re="Repositorio de NF-?e Entrada.*")
    if existentes:
        w = existentes[0]
        try:
            w.set_focus()
        except Exception:
            pass
        logger.info("Repositorio ja estava aberto.")
        return w

    # Re-focar (caso o foco tenha perdido desde focar_vr_master)
    try:
        hwnd = main_win.handle if hasattr(main_win, "handle") else main_win.wrapper_object().handle
        _forcar_foreground(hwnd)
    except Exception as e:
        logger.warning(f"Falha re-focar VR: {e}")
    time.sleep(0.6)

    # Usar pyautogui com delays maiores pra Java Swing
    pyautogui.PAUSE = 0.2
    # Alt+N -> Nota Fiscal
    pyautogui.keyDown("alt")
    time.sleep(0.1)
    pyautogui.press("n")
    time.sleep(0.05)
    pyautogui.keyUp("alt")
    time.sleep(0.6)
    # R, R -> Repositorio (pula Recebimento)
    pyautogui.press("r")
    time.sleep(0.25)
    pyautogui.press("r")
    time.sleep(0.4)
    # abrir submenu Repositorio
    pyautogui.press("right")
    time.sleep(0.5)
    # N, N -> NF-e (pula NFC-e)
    pyautogui.press("n")
    time.sleep(0.25)
    pyautogui.press("n")
    time.sleep(0.4)
    # abrir submenu NF-e
    pyautogui.press("right")
    time.sleep(0.5)
    # Enter -> Entrada (primeiro item)
    pyautogui.press("enter")
    time.sleep(2.0)

    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            win = app.window(title_re="Repositorio de NF-?e Entrada.*")
            win.wait("exists visible ready", timeout=1)
            return win
        except Exception:
            time.sleep(0.5)

    # Fechar qualquer menu aberto antes de retornar erro
    try:
        pyautogui.press("escape")
        pyautogui.press("escape")
        pyautogui.press("escape")
    except Exception:
        pass
    raise RuntimeError(
        "Nao consegui abrir Repositorio de NF-e. "
        "Caminho testado: Nota Fiscal > Repositorio > NF-e > Entrada. "
        "Verifique se o VR Master esta em primeiro plano."
    )


def buscar_nota(repo_win, numero_nota):
    """Preenche o filtro Nº Nota e clica Consultar."""
    logger.info(f"Buscando nota {numero_nota}...")
    # Encontrar campo de Nº Nota. Em Delphi/VR geralmente sao TEdits ordenados.
    # Estrategia robusta: buscar por controle Edit que esteja proximo do label "No Nota"
    edits = repo_win.descendants(control_type="Edit")
    # Heuristica: o campo N Nota costuma ser o 4o ou 5o edit da tela, mas varia.
    # Vamos preencher atraves de tab keys e inserir manualmente se nao achar por nome.
    # Primeira tentativa: children filtrados por texto proximo
    focou = False
    for e in edits:
        try:
            rect = e.rectangle()
        except Exception:
            continue
        # heuristica simples: campos no topo da janela
        if rect.top < 200:
            # tentar o campo com texto ''; pular se for combobox-like
            try:
                e.set_focus()
                e.type_keys("^a{DEL}", with_spaces=False, set_foreground=False)
                e.type_keys(str(int(numero_nota)), set_foreground=False)
                # avaliar visualmente depois clicando Consultar
                focou = True
                # Nao sabemos qual edit eh — vamos usar outro metodo melhor
                break
            except Exception:
                continue

    if not focou:
        raise RuntimeError("Nao encontrei o campo Numero da Nota.")

    time.sleep(0.3)
    # Clicar Consultar (botao com texto "Consultar")
    try:
        btn = repo_win.child_window(title="Consultar", control_type="Button")
        btn.click_input()
    except Exception:
        repo_win.type_keys("{F7}")
    time.sleep(1.5)


def selecionar_unica_linha(repo_win):
    """Marca o checkbox 'Selecionado' da primeira linha do grid."""
    logger.info("Selecionando linha...")
    # O grid parece ser um TDBGrid. Com pywinauto backend=win32 nao conseguimos
    # interagir com celulas facilmente. Estrategia: clicar na primeira linha
    # e usar espaco para marcar.
    # Abordagem por coordenadas relativas (primeira linha, coluna 'Selecionado')
    # Como nao sei exatamente onde, vou enviar: Home (primeira linha), Space (toggle)
    repo_win.type_keys("^{HOME}")
    time.sleep(0.3)
    repo_win.type_keys(" ")
    time.sleep(0.3)


def clicar_toolbar_por_tooltip(win, tooltip_contains):
    """Busca um botao de toolbar pelo tooltip/title."""
    for b in win.descendants(control_type="Button"):
        try:
            nome = (b.window_text() or "")
            if tooltip_contains.lower() in nome.lower():
                b.click_input()
                return True
        except Exception:
            continue
    return False


def conferir_nota(app, repo_win):
    """Clica Conferir NF-e (toolbar) -> marca autenticidade -> Conferir.
    Depois na janela de Divergencia clica Conferir de novo.
    """
    logger.info("Etapa Conferir...")
    # toolbar: idealmente buscar icone. Tentar atalho alternativo:
    # Nao sei o atalho. Vou tentar encontrar um botao titulado "Conferir".
    # A tela do repositorio tem menu de icones — vamos tentar pelo nome do botao.
    # Se nao achar, levanta excecao para sinalizar.
    if not clicar_toolbar_por_tooltip(repo_win, "Conferir"):
        raise RuntimeError("Nao encontrei botao 'Conferir NF-e' na toolbar do Repositorio.")
    time.sleep(1.5)

    # Dialog "Conferencia de NF-e Entrada"
    win_conf = app.window(title_re="Conferencia de NF-?e Entrada.*")
    win_conf.wait("exists visible ready", timeout=10)

    # garantir que "Consultar autenticidade" esta marcado
    try:
        chk = win_conf.child_window(title_re=".*autenticidade.*", control_type="CheckBox")
        if not chk.get_toggle_state():
            chk.toggle()
    except Exception:
        pass

    # Clicar Conferir (Alt+O)
    win_conf.type_keys("%o")
    time.sleep(2)

    # Dialog "Divergencia de Importacao NF-e"
    try:
        win_div = app.window(title_re="Divergencia de Importacao NF-?e.*")
        win_div.wait("exists visible ready", timeout=15)
        # Clicar Conferir
        win_div.child_window(title="Conferir", control_type="Button").click_input()
        time.sleep(2)
    except Exception as e:
        logger.info(f"Sem dialog de divergencia (ou ja fechou): {e}")


def carregar_nota(app, repo_win, id_tipoentrada):
    """Clica Carregar NF-e -> seta Tipo -> Carregar. Se CFOP divergente, Sim."""
    logger.info(f"Etapa Carregar (tipo={id_tipoentrada})...")
    if not clicar_toolbar_por_tooltip(repo_win, "Carregar"):
        raise RuntimeError("Nao encontrei botao 'Carregar NF-e' na toolbar do Repositorio.")
    time.sleep(1.5)

    win_car = app.window(title_re="Carregar NF-?e Entrada.*")
    win_car.wait("exists visible ready", timeout=10)

    # Setar campo Tipo (codigo de tipoentrada)
    try:
        # o campo Tipo eh um Edit com numero formatado (ex: 0001)
        # Assumindo que esta proximo ao label "Tipo"
        edits = win_car.descendants(control_type="Edit")
        # heuristica: pegar primeiro edit numerico apos o combo NORMAL
        setou = False
        codigo = f"{id_tipoentrada:04d}"
        for e in edits:
            try:
                cls = e.friendly_class_name().lower()
                if "edit" in cls:
                    cur = e.window_text() or ""
                    # pular o combobox tipo nota (nao eh editavel direto)
                    e.set_focus()
                    e.type_keys("^a{DEL}" + codigo + "{TAB}", with_spaces=False, set_foreground=False)
                    setou = True
                    break
            except Exception:
                continue
        if not setou:
            raise RuntimeError("Nao consegui preencher campo Tipo")
    except Exception as e:
        raise RuntimeError(f"Falha ao preencher Tipo: {e}")

    time.sleep(0.5)
    # garantir radio "Entrada"
    try:
        rb_ent = win_car.child_window(title="Entrada", control_type="RadioButton")
        rb_ent.select()
    except Exception:
        pass
    # garantir Consultar autenticidade ligado
    try:
        chk = win_car.child_window(title_re=".*autenticidade.*", control_type="CheckBox")
        if not chk.get_toggle_state():
            chk.toggle()
    except Exception:
        pass

    # clicar Carregar
    try:
        win_car.child_window(title="Carregar", control_type="Button").click_input()
    except Exception:
        win_car.type_keys("%c")
    time.sleep(2)

    # Possivel dialog CFOP divergente — clicar Sim
    try:
        cfop_dlg = app.window(title_re="Importacao de NFe Entrada.*")
        cfop_dlg.wait("exists visible ready", timeout=5)
        cfop_dlg.child_window(title="Sim", control_type="Button").click_input()
        logger.info("Dialog CFOP divergente: cliquei Sim.")
        time.sleep(1)
    except Exception:
        pass

    # Esperar validando
    logger.info("Aguardando validacao do VR...")
    tempo_max = 60
    t0 = time.time()
    while time.time() - t0 < tempo_max:
        try:
            validando = app.window(title_re="Validando.*")
            if validando.exists():
                time.sleep(1)
                continue
        except Exception:
            pass
        break
    time.sleep(1)


def processar_nota_no_vr(numero_nota, id_fornecedor):
    """Executa todo o fluxo para uma nota. Retorna (True, info) ou (False, erro)."""
    tipo = tipo_entrada_mais_usado(id_fornecedor)
    if tipo is None:
        return False, f"fornecedor sem historico para inferir Tipo de entrada"

    app, main_win = focar_vr_master()
    repo_win = abrir_repositorio_nfe(app, main_win)
    buscar_nota(repo_win, numero_nota)
    selecionar_unica_linha(repo_win)
    conferir_nota(app, repo_win)
    # re-selecionar depois de conferir (VR deseleciona as vezes)
    try:
        selecionar_unica_linha(repo_win)
    except Exception:
        pass
    carregar_nota(app, repo_win, tipo)

    # Verificar no banco se ficou conferido + carregado
    dados = buscar_dados_nota(numero_nota)
    if dados and dados[3] and dados[4]:
        return True, f"nota {numero_nota} conferida e carregada (tipo={tipo})"
    if dados and dados[3] and not dados[4]:
        return False, f"nota {numero_nota} conferida mas NAO carregada"
    return False, f"nao foi possivel confirmar no banco"


def processar_arquivo(path):
    nome = path.name
    logger.info(f"Processando {nome}...")
    dados_fila = json.loads(path.read_text(encoding="utf-8"))
    numero = dados_fila["numero_nota"]

    info_nota = buscar_dados_nota(numero)
    if not info_nota:
        return False, f"nota {numero} nao encontrada no Repositorio do VR"

    id_nne, id_forn, razao, conferido, carregado, dt_receb, vt = info_nota
    if carregado:
        return True, f"nota {numero} ja estava carregada (ignorando)"

    logger.info(f"Nota {numero} - {razao} - R$ {vt or 0:.2f}")
    return processar_nota_no_vr(numero, id_forn)


def main():
    # processa 1 arquivo por execucao para dar intervalo entre notas
    arquivos = sorted(FILA_DIR.glob("nfe_*.json"))
    if not arquivos:
        logger.info("Fila vazia.")
        return 0

    arq = arquivos[0]
    try:
        ok, info = processar_arquivo(arq)
    except Exception as e:
        ok, info = False, f"excecao: {e}"
        logger.exception("Erro inesperado")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if ok:
        dest = PROCESSADAS_DIR / arq.name
        shutil.move(str(arq), str(dest))
        logger.info(f"OK: {info}")
        numero = arq.stem.split("_")[1] if "_" in arq.stem else "??"
        responder_whatsapp(f"Nota {numero} carregada no VR Master ({info}).")
    else:
        dest = ERROS_DIR / f"{arq.stem}_erro_{timestamp}.json"
        # anexar erro
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
            d["erro"] = info
            d["erro_em"] = datetime.now().isoformat(timespec="seconds")
            dest.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            arq.unlink()
        except Exception:
            shutil.move(str(arq), str(dest))
        logger.error(f"ERRO: {info}")
        numero = arq.stem.split("_")[1] if "_" in arq.stem else "??"
        responder_whatsapp(f"Erro ao processar nota {numero}: {info}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
