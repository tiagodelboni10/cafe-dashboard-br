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


# =========================================================
# MODO DE OPERACAO (C3 diurno / D noturno)
# =========================================================
# C3: dia — bot abre Repositorio, filtra, seleciona, faz Conferir completo,
#     abre dialog Carregar com Tipo preenchido e PARA. Usuario clica Carregar.
# D:  noite (20h-6h) — bot faz tudo inclusive Carregar + CFOP Sim. Em caso de
#     dialog inesperado, pula a nota e notifica no WhatsApp (D-prudente).

HORA_INICIO_NOITE = 20  # 20:00
HORA_FIM_NOITE = 6      # 06:00


def modo_atual():
    h = datetime.now().hour
    return "D" if (h >= HORA_INICIO_NOITE or h < HORA_FIM_NOITE) else "C3"


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


RESPOSTAS_DIR = BASE_DIR / "nfe_respostas"
RESPOSTAS_DIR.mkdir(exist_ok=True)


def responder_whatsapp(msg):
    """
    Escreve resposta num arquivo. O listener_nfe.py (Selenium) le essa pasta a
    cada ciclo e envia no grupo Merkal NOTAS via a mesma sessao de WhatsApp Web
    (mais robusto que pyautogui em PC dedicado).
    """
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        arq = RESPOSTAS_DIR / f"resp_{ts}.txt"
        arq.write_text(msg, encoding="utf-8")
        logger.info(f"Resposta enfileirada: {arq.name} | {msg[:80]}")
    except Exception as e:
        logger.warning(f"Falha ao enfileirar resposta: {e}")


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
    """Traz janela para frente bypassando focus-lock do Windows. NAO redimensiona."""
    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

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


def _maximizar_se_pequeno(w, hwnd):
    """Maximiza a janela se a altura estiver menor que 400px."""
    import ctypes
    from ctypes.wintypes import RECT
    try:
        rect = RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        altura = rect.bottom - rect.top
        logger.info(f"Altura atual VR: {altura}px")
        if altura < 400:
            logger.info("Janela pequena — maximizando.")
            try:
                w.maximize()
            except Exception:
                ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            time.sleep(0.8)
            # confirmar
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            logger.info(f"Nova altura: {rect.bottom - rect.top}px")
    except Exception as e:
        logger.warning(f"Erro ao maximizar: {e}")


def focar_vr_master():
    """Conecta + traz VR Master para frente. Maximiza se estiver muito pequeno."""
    app, backend = _conectar_app()
    logger.info(f"VR Master conectado (backend {backend}).")
    w = app.window(title_re="VR Master.*")
    hwnd = None
    try:
        hwnd = w.handle if hasattr(w, "handle") else w.wrapper_object().handle
    except Exception as e:
        logger.warning(f"Nao obtive hwnd: {e}")

    if hwnd:
        # Maximizar primeiro se estiver pequeno
        _maximizar_se_pequeno(w, hwnd)
        _forcar_foreground(hwnd)
    else:
        try:
            w.set_focus()
        except Exception as e:
            logger.warning(f"set_focus falhou: {e}")
    time.sleep(0.8)
    try:
        r = w.rectangle()
        logger.info(f"VR rect: {r.left},{r.top} {r.right-r.left}x{r.bottom-r.top}")
    except Exception:
        pass
    return app, w, backend


def _aguardar_janela_repositorio(app, timeout=12):
    """Espera a janela 'Repositorio de NF-e Entrada' abrir. Retorna janela ou None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            win = app.window(title_re="Repositorio de NF-?e Entrada.*")
            win.wait("exists visible ready", timeout=1)
            return win
        except Exception:
            time.sleep(0.5)
    return None


def _fechar_dialogs_e_menus():
    """Fecha qualquer menu/popup aberto (ate 5 Esc)."""
    import pyautogui
    for _ in range(5):
        try:
            pyautogui.press("escape")
        except Exception:
            pass
        time.sleep(0.1)


def _estrategia_menu_select_uia(app, main_win):
    """Usa pywinauto.menu_select - funciona se o menu estiver exposto via UIA."""
    logger.info("Tentativa 1: menu_select UIA 'Nota Fiscal->Repositorio->NF-e->Entrada'")
    for sep in ("->", " -> "):
        try:
            main_win.menu_select(f"Nota Fiscal{sep}Repositório{sep}NF-e{sep}Entrada")
            win = _aguardar_janela_repositorio(app, timeout=10)
            if win:
                return win
        except Exception as e:
            logger.info(f"  menu_select('{sep}') falhou: {e}")
    return None


def _estrategia_click_uia(app, main_win):
    """Encontra os itens de menu via UIA e clica em cada um."""
    logger.info("Tentativa 2: clique UIA item a item no menu.")
    try:
        # menu bar principal
        main_win.child_window(title="Nota Fiscal", control_type="MenuItem").click_input()
        time.sleep(0.5)
        main_win.child_window(title_re="Reposit[oó]rio", control_type="MenuItem").click_input()
        time.sleep(0.5)
        main_win.child_window(title="NF-e", control_type="MenuItem").click_input()
        time.sleep(0.5)
        main_win.child_window(title="Entrada", control_type="MenuItem").click_input()
        win = _aguardar_janela_repositorio(app, timeout=10)
        if win:
            return win
    except Exception as e:
        logger.info(f"  clique UIA falhou: {e}")
    return None


_DEBUG_DIR = BASE_DIR / "debug_nfe"
_DEBUG_DIR.mkdir(exist_ok=True)


def _refocar(main_win):
    """Re-forca foco no VR Master."""
    try:
        hwnd = main_win.handle if hasattr(main_win, "handle") else main_win.wrapper_object().handle
        _forcar_foreground(hwnd)
    except Exception:
        pass
    time.sleep(0.5)


def _screenshot(nome):
    """Salva screenshot pra debug em debug_nfe/."""
    try:
        import pyautogui
        path = _DEBUG_DIR / f"{datetime.now().strftime('%H%M%S')}_{nome}.png"
        pyautogui.screenshot(str(path))
        logger.info(f"Screenshot: {path.name}")
    except Exception as e:
        logger.warning(f"Screenshot falhou: {e}")


def _obter_rect_vr(main_win):
    """Retorna (x, y, largura, altura) da janela VR."""
    try:
        r = main_win.rectangle()
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    except Exception:
        try:
            r = main_win.wrapper_object().rectangle()
            return r.left, r.top, r.right - r.left, r.bottom - r.top
        except Exception:
            return None


def _estrategia_click_coordenadas(main_win):
    """
    Clica em coordenadas do menu baseadas na posicao da janela.
    Calcula x de cada item do menu bar a partir de medicoes tipicas.
    """
    import pyautogui
    logger.info("Tentativa 6: clique em coordenadas do menu.")
    _refocar(main_win)

    rect = _obter_rect_vr(main_win)
    if not rect:
        logger.info("  Nao consegui obter rect da janela VR.")
        return

    x, y, w, h = rect
    logger.info(f"  VR rect: x={x} y={y} w={w} h={h}")

    # Menu bar eh a linha y+38 aproximadamente
    # Ordem dos menus (medidos na largura): Administrativo, Ativo Imobilizado,
    # Cadastro, Contabilidade, CRM, Estoque, Fechamento, Financeiro, Fiscal,
    # Interface, Logistica, Nota Fiscal, PDV, Utilitario, Sistema, Janela, Ajuda
    # Posicoes X aproximadas (a partir do x do frame):
    offset_nota_fiscal_x = x + 720
    menu_y = y + 38

    _screenshot("00_antes_click")
    # Clicar em "Nota Fiscal"
    pyautogui.click(offset_nota_fiscal_x, menu_y)
    time.sleep(0.8)
    _screenshot("01_apos_click_nf")

    # Submenu aparece abaixo. "Repositorio" eh item 9.
    # Cada item ~20px de altura. Submenu comeca ~y+45 da clicada.
    # Item 9 = Repositorio. Uso setas:
    for _ in range(9):
        pyautogui.press("down"); time.sleep(0.08)
    time.sleep(0.3)
    _screenshot("02_apos_9_downs")
    pyautogui.press("right"); time.sleep(0.5)
    _screenshot("03_apos_right")

    # Submenu Repositorio: CF-e ja vem selecionado. 2 downs = NF-e
    for _ in range(2):
        pyautogui.press("down"); time.sleep(0.08)
    time.sleep(0.3)
    _screenshot("04_apos_2_downs")
    pyautogui.press("right"); time.sleep(0.5)
    _screenshot("05_apos_right2")

    pyautogui.press("enter"); time.sleep(1.5)
    _screenshot("06_apos_enter")


def _estrategia_pywinauto_typekeys(main_win):
    """Usa pywinauto type_keys que envia ao handle especifico (melhor que pyautogui)."""
    logger.info("Tentativa 3: pywinauto type_keys (setas).")
    _refocar(main_win)
    # Alt+N abre Nota Fiscal
    # depois 9 setas pra baixo ate Repositorio -> Right -> 3 baixo -> Right -> Enter
    try:
        main_win.type_keys("%n", set_foreground=True, pause=0.05)
        time.sleep(0.7)
        main_win.type_keys("{DOWN 9}", set_foreground=False, pause=0.08)
        time.sleep(0.3)
        main_win.type_keys("{RIGHT}", set_foreground=False)
        time.sleep(0.5)
        main_win.type_keys("{DOWN 2}", set_foreground=False, pause=0.08)
        time.sleep(0.3)
        main_win.type_keys("{RIGHT}", set_foreground=False)
        time.sleep(0.5)
        main_win.type_keys("{ENTER}", set_foreground=False)
        time.sleep(1.5)
    except Exception as e:
        logger.info(f"  type_keys falhou: {e}")


def _estrategia_pyautogui_setas(main_win):
    """Fallback: pyautogui com setas."""
    import pyautogui
    logger.info("Tentativa 4: pyautogui setas (9 downs, right, 2 downs, right, enter).")
    _refocar(main_win)
    pyautogui.keyDown("alt"); time.sleep(0.1)
    pyautogui.press("n"); time.sleep(0.05)
    pyautogui.keyUp("alt")
    time.sleep(0.8)
    for _ in range(9):
        pyautogui.press("down"); time.sleep(0.1)
    time.sleep(0.3)
    pyautogui.press("right"); time.sleep(0.5)
    for _ in range(2):  # submenu ja vem com 1o item selecionado
        pyautogui.press("down"); time.sleep(0.1)
    time.sleep(0.3)
    pyautogui.press("right"); time.sleep(0.5)
    pyautogui.press("enter"); time.sleep(1.5)


def _estrategia_pyautogui_hotkeys(main_win):
    """pyautogui com hotkeys letters (R, N) — assumindo hotkeys do Delphi/Swing."""
    import pyautogui
    logger.info("Tentativa 5: pyautogui letras (R,R,Right,N,N,Right,Enter).")
    _refocar(main_win)
    pyautogui.keyDown("alt"); time.sleep(0.1)
    pyautogui.press("n"); time.sleep(0.05)
    pyautogui.keyUp("alt")
    time.sleep(0.8)
    pyautogui.press("r"); time.sleep(0.3)
    pyautogui.press("r"); time.sleep(0.4)
    pyautogui.press("right"); time.sleep(0.5)
    pyautogui.press("n"); time.sleep(0.3)
    pyautogui.press("n"); time.sleep(0.4)
    pyautogui.press("right"); time.sleep(0.5)
    pyautogui.press("enter"); time.sleep(1.5)


def abrir_repositorio_nfe(app, main_win, backend="uia"):
    """
    Caminho VR Master: Nota Fiscal > Repositorio > NF-e > Entrada
    Tenta varias estrategias ate uma funcionar.
    """
    logger.info("Abrindo Repositorio de NF-e Entrada...")

    existentes = app.windows(title_re="Repositorio de NF-?e Entrada.*")
    if existentes:
        w = existentes[0]
        try:
            w.set_focus()
        except Exception:
            pass
        logger.info("Repositorio ja estava aberto.")
        return w

    # Garantir foco sem mexer no tamanho
    try:
        hwnd = main_win.handle if hasattr(main_win, "handle") else main_win.wrapper_object().handle
        _forcar_foreground(hwnd)
    except Exception as e:
        logger.warning(f"Falha re-focar VR: {e}")
    time.sleep(0.6)

    estrategias = [
        ("menu_select UIA", _estrategia_menu_select_uia, True),
        ("click UIA items", _estrategia_click_uia, True),
        ("pywinauto type_keys setas", _estrategia_pywinauto_typekeys, False),
        ("pyautogui setas", _estrategia_pyautogui_setas, False),
        ("pyautogui letras", _estrategia_pyautogui_hotkeys, False),
        ("click coordenadas", _estrategia_click_coordenadas, False),
    ]

    for nome, fn, precisa_app in estrategias:
        _fechar_dialogs_e_menus()
        time.sleep(0.5)
        try:
            if precisa_app:
                res = fn(app, main_win)
            else:
                fn(main_win)
                res = _aguardar_janela_repositorio(app, timeout=10)
            if res:
                logger.info(f"Sucesso com estrategia: {nome}")
                return res
        except Exception as e:
            logger.info(f"Estrategia '{nome}' falhou com excecao: {e}")

    _fechar_dialogs_e_menus()
    raise RuntimeError(
        "Nao consegui abrir Repositorio de NF-e com nenhuma estrategia "
        "(menu_select UIA, click UIA, teclado setas)."
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


def carregar_nota(app, repo_win, id_tipoentrada, modo="D"):
    """
    Abre dialog Carregar, preenche Tipo, radio Entrada, checkbox autenticidade.
    modo='C3': PARA aqui. Usuario finaliza clicando Carregar manualmente.
    modo='D':  clica Carregar + trata CFOP Sim + aguarda validacao.
    """
    logger.info(f"Etapa Carregar (tipo={id_tipoentrada}, modo={modo})...")
    if not clicar_toolbar_por_tooltip(repo_win, "Carregar"):
        raise RuntimeError("Nao encontrei botao 'Carregar NF-e' na toolbar do Repositorio.")
    time.sleep(1.5)

    win_car = app.window(title_re="Carregar NF-?e Entrada.*")
    win_car.wait("exists visible ready", timeout=10)

    # Setar campo Tipo (codigo de tipoentrada)
    try:
        edits = win_car.descendants(control_type="Edit")
        setou = False
        codigo = f"{id_tipoentrada:04d}"
        for e in edits:
            try:
                cls = e.friendly_class_name().lower()
                if "edit" in cls:
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
    try:
        rb_ent = win_car.child_window(title="Entrada", control_type="RadioButton")
        rb_ent.select()
    except Exception:
        pass
    try:
        chk = win_car.child_window(title_re=".*autenticidade.*", control_type="CheckBox")
        if not chk.get_toggle_state():
            chk.toggle()
    except Exception:
        pass

    # ======== MODO C3: PARA aqui ========
    if modo == "C3":
        logger.info("Modo C3: dialog Carregar aberto com Tipo preenchido. Aguardando clique manual do usuario.")
        return

    # ======== MODO D: clicar Carregar automatico ========
    try:
        win_car.child_window(title="Carregar", control_type="Button").click_input()
    except Exception:
        win_car.type_keys("%c")
    time.sleep(2)

    # Dialog CFOP divergente — clicar Sim
    try:
        cfop_dlg = app.window(title_re="Importacao de NFe Entrada.*")
        cfop_dlg.wait("exists visible ready", timeout=5)
        cfop_dlg.child_window(title="Sim", control_type="Button").click_input()
        logger.info("Dialog CFOP divergente: cliquei Sim.")
        time.sleep(1)
    except Exception:
        pass

    # D-prudente: detectar dialogs INESPERADOS (erro, divergencia critica, etc)
    # Se aparecer qualquer janela que nao seja "Validando" nem o repositorio,
    # tratar como erro e abortar (sem clicar).
    time.sleep(1.5)
    try:
        janelas_abertas = [w.window_text() for w in app.windows() if w.is_visible()]
        logger.info(f"Janelas abertas apos Carregar: {janelas_abertas}")
        # dialogs com nome "Atencao", "Erro", "Aviso", etc. sao suspeitos
        for w in app.windows():
            try:
                titulo = (w.window_text() or "").lower()
                if any(kw in titulo for kw in ("erro", "aviso", "atencao", "divergencia", "bloqueio")):
                    if "repositorio" not in titulo and "validando" not in titulo:
                        raise RuntimeError(f"Dialog inesperado apareceu: '{w.window_text()}'. Pulando.")
            except RuntimeError:
                raise
            except Exception:
                continue
    except RuntimeError:
        raise
    except Exception:
        pass

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


def processar_nota_no_vr(numero_nota, id_fornecedor, modo):
    """Executa todo o fluxo para uma nota. Retorna (True, info) ou (False, erro)."""
    tipo = tipo_entrada_mais_usado(id_fornecedor)
    if tipo is None:
        return False, "fornecedor sem historico para inferir Tipo de entrada"

    app, main_win, backend = focar_vr_master()

    # Limpeza preventiva: Esc pra fechar qualquer dialog que ficou aberto
    _fechar_dialogs_e_menus()
    time.sleep(0.5)

    repo_win = abrir_repositorio_nfe(app, main_win, backend)
    buscar_nota(repo_win, numero_nota)
    selecionar_unica_linha(repo_win)
    conferir_nota(app, repo_win)
    # re-selecionar depois de conferir (VR as vezes deseleciona)
    try:
        selecionar_unica_linha(repo_win)
    except Exception:
        pass
    carregar_nota(app, repo_win, tipo, modo=modo)

    # Verificacao no banco difere por modo
    dados = buscar_dados_nota(numero_nota)
    if dados and dados[3] and dados[4]:
        return True, f"nota {numero_nota} conferida e carregada (tipo={tipo}, modo={modo})"
    if modo == "C3" and dados and dados[3] and not dados[4]:
        # C3 eh esperado terminar com conferido=True, carregado=False
        return True, f"nota {numero_nota} conferida + dialog Carregar aberto (modo C3 — aguardando clique manual)"
    if dados and dados[3] and not dados[4]:
        return False, f"nota {numero_nota} conferida mas NAO carregada"
    return False, "nao foi possivel confirmar no banco"


def processar_arquivo(path, modo):
    nome = path.name
    logger.info(f"Processando {nome} no modo {modo}...")
    dados_fila = json.loads(path.read_text(encoding="utf-8"))
    numero = dados_fila["numero_nota"]

    info_nota = buscar_dados_nota(numero)
    if not info_nota:
        return False, f"nota {numero} nao encontrada no Repositorio do VR"

    id_nne, id_forn, razao, conferido, carregado, dt_receb, vt = info_nota
    if carregado:
        return True, f"nota {numero} ja estava carregada (ignorando)"

    logger.info(f"Nota {numero} - {razao} - R$ {vt or 0:.2f}")
    return processar_nota_no_vr(numero, id_forn, modo)


def main():
    modo = modo_atual()

    # processa 1 arquivo por execucao para dar intervalo entre notas
    todos = sorted(FILA_DIR.glob("nfe_*.json"))
    # filtrar os que ja foram processados em C3 e estao aguardando o clique manual
    # (tem um irmao com sufixo .aguardando)
    if modo == "C3":
        arquivos = [a for a in todos if not (a.parent / (a.stem + ".aguardando")).exists()]
    else:
        # modo D: processa TUDO, inclusive os que ficaram aguardando desde o dia.
        # Antes, remove todos os markers .aguardando pra reprocessar do zero.
        for a in todos:
            flag = a.parent / (a.stem + ".aguardando")
            if flag.exists():
                flag.unlink()
        arquivos = todos

    if not arquivos:
        logger.info(f"Fila vazia (modo {modo}, {len(todos)} total, 0 processaveis agora).")
        return 0

    logger.info(f"Modo de operacao: {modo} "
                f"({'Noturno full-auto' if modo == 'D' else 'Diurno semi-auto'}) "
                f"- {len(arquivos)} nota(s) a processar.")

    arq = arquivos[0]
    numero = arq.stem.split("_")[1] if "_" in arq.stem else "??"
    try:
        ok, info = processar_arquivo(arq, modo)
    except Exception as e:
        ok, info = False, f"excecao: {e}"
        logger.exception("Erro inesperado")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if ok:
        if modo == "C3" and "aguardando clique manual" in info.lower():
            # C3: deixar arquivo na fila como "em_espera" pra nao reprocessar
            # varias vezes enquanto usuario nao clica. Marca com .aguardando
            novo = arq.parent / (arq.stem + ".aguardando")
            if not novo.exists():
                novo.touch()
            logger.info(f"C3 OK: {info}")
            responder_whatsapp(f"Nota {numero}: tela Carregar aberta no VR — clique Carregar pra finalizar.")
        else:
            dest = PROCESSADAS_DIR / arq.name
            shutil.move(str(arq), str(dest))
            # limpar flag .aguardando se existia
            flag = arq.parent / (arq.stem + ".aguardando")
            if flag.exists():
                flag.unlink()
            logger.info(f"OK: {info}")
            responder_whatsapp(f"Nota {numero} carregada no VR Master ({info}).")
    else:
        # em modo D-prudente, se foi dialog inesperado, notificar e mover pra erros
        dest = ERROS_DIR / f"{arq.stem}_erro_{timestamp}.json"
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
            d["erro"] = info
            d["erro_em"] = datetime.now().isoformat(timespec="seconds")
            d["modo"] = modo
            dest.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            arq.unlink()
        except Exception:
            shutil.move(str(arq), str(dest))
        # limpar flag .aguardando se existia
        flag = arq.parent / (arq.stem + ".aguardando")
        if flag.exists():
            flag.unlink()
        logger.error(f"ERRO: {info}")
        responder_whatsapp(
            f"ERRO na nota {numero} (modo {modo}): {info}. "
            f"Precisa tratar manualmente no VR."
        )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
