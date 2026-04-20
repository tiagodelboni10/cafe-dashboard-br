"""
listener_nfe.py
===============
Escuta o grupo "MERKAL NOTAS" do WhatsApp via Selenium.
Quando alguem manda "OK <numero>", escreve um arquivo em nfe_fila/
que sera processado pelo agente_nfe.py.

Primeira execucao: vai abrir Chrome com um profile dedicado,
voce precisa escanear o QR code do WhatsApp Web. Depois fica logado.

Roda em loop continuo. Ao receber SIGINT ou se der erro, tenta reabrir.
"""
import os
import re
import sys
import json
import time
import hashlib
import logging
import signal
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
    StaleElementReferenceException,
)

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

GRUPO_NOME = os.environ.get("MERKAL_NOTAS_GRUPO", "MERKAL NOTAS")
FILA_DIR = BASE_DIR / "nfe_fila"
STATE_FILE = BASE_DIR / "listener_nfe_state.json"
PROFILE_DIR = BASE_DIR / "chrome_profile_whatsapp"
LOGS_DIR = BASE_DIR / "logs"

FILA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

PADRAO_OK = re.compile(r"^\s*ok\s+(\d{3,})\b", re.IGNORECASE)
POLL_SECONDS = 20

log_file = LOGS_DIR / f"listener_nfe_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def load_state():
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("processed", []))
        except Exception:
            return set()
    return set()


def save_state(processed):
    # manter ultimos 500 hashes para nao crescer indefinidamente
    lst = list(processed)[-500:]
    STATE_FILE.write_text(json.dumps({"processed": lst}), encoding="utf-8")


def msg_hash(meta, text):
    return hashlib.sha256(f"{meta}|{text}".encode("utf-8")).hexdigest()[:16]


def enqueue(numero, meta, text):
    """Grava arquivo na fila para o agente processar."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    arq = FILA_DIR / f"nfe_{numero}_{ts}.json"
    arq.write_text(
        json.dumps({
            "numero_nota": numero,
            "mensagem_origem": text,
            "meta": meta,
            "recebido_em": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Nota {numero} enfileirada: {arq.name}")
    return arq


def criar_driver():
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-features=VizDisplayCompositor")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    # Nao usar headless — WhatsApp Web detecta
    driver = webdriver.Chrome(options=opts)
    driver.set_window_size(1100, 800)
    return driver


def esperar_whatsapp_carregar(driver, timeout=600):
    """Espera ate o WhatsApp Web carregar (logado). Se tiver QR, avisa e espera scan."""
    logger.info("Abrindo web.whatsapp.com...")
    driver.get("https://web.whatsapp.com")

    deadline = time.time() + timeout
    qr_avisado = False
    while time.time() < deadline:
        # LOGADO: sidebar do chat sempre existe
        for sel in ("div#pane-side", "div#side", "div[aria-label='Lista de conversas']",
                    "div[aria-label='Chat list']"):
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    logger.info(f"WhatsApp Web carregado (seletor: {sel}).")
                    return True
            except NoSuchElementException:
                continue
            except Exception:
                continue

        # QR visivel?
        qr_visivel = False
        for sel in ("canvas[aria-label]", "div[data-ref]", "div._akau canvas",
                    "div[data-testid='qrcode']"):
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    qr_visivel = True
                    break
            except NoSuchElementException:
                continue
            except Exception:
                continue

        if qr_visivel and not qr_avisado:
            logger.warning("=" * 60)
            logger.warning("QR CODE visivel no Chrome.")
            logger.warning("WhatsApp no celular > Menu > Dispositivos conectados >")
            logger.warning("Conectar dispositivo > Escaneie o QR da janela do Chrome.")
            logger.warning("=" * 60)
            qr_avisado = True

        time.sleep(3)

    # timeout — tentar dump do estado atual para debug
    try:
        title = driver.title
        url = driver.current_url
        body_snip = (driver.find_element(By.TAG_NAME, "body").text or "")[:200]
        logger.error(f"Timeout. Title='{title}' URL='{url}'")
        logger.error(f"Body snippet: {body_snip!r}")
    except Exception:
        pass
    raise TimeoutException(f"WhatsApp Web nao carregou em {timeout}s")


def abrir_grupo(driver, nome):
    """Abre o chat do grupo pelo nome. JS-based — resistente a mudancas de HTML."""
    logger.info(f"Abrindo grupo '{nome}'...")
    time.sleep(2)

    # Estrategia 1: buscar + clicar direto no span[title=nome] em qualquer lugar
    script_click = """
        const target = arguments[0].toLowerCase().trim();
        const spans = document.querySelectorAll('span[title]');
        // priorizar match exato primeiro
        let match = null;
        for (const s of spans) {
            const t = (s.getAttribute('title') || '').toLowerCase().trim();
            if (t === target) { match = s; break; }
        }
        if (!match) {
            for (const s of spans) {
                const t = (s.getAttribute('title') || '').toLowerCase().trim();
                if (t && t.includes(target)) { match = s; break; }
            }
        }
        if (!match) return {ok: false, titles: Array.from(spans).slice(0, 30).map(s => s.getAttribute('title')).filter(x => x)};
        // subir ate achar um ancestral clicavel (listitem ou role=row)
        let el = match;
        for (let i = 0; i < 8 && el; i++) {
            const r = el.getAttribute && (el.getAttribute('role') || '');
            if (r === 'listitem' || r === 'row' || r === 'button') {
                el.click();
                return {ok: true, title: match.getAttribute('title'), clicked: r};
            }
            el = el.parentElement;
        }
        // fallback: clicar no proprio span
        match.click();
        return {ok: true, title: match.getAttribute('title'), clicked: 'span'};
    """
    resultado = driver.execute_script(script_click, nome)
    if resultado and resultado.get("ok"):
        time.sleep(1.5)
        logger.info(f"Grupo aberto: '{resultado.get('title')}' (via {resultado.get('clicked')})")
        return True

    titulos_visiveis = resultado.get("titles", []) if isinstance(resultado, dict) else []
    logger.warning(f"Grupo nao visivel na sidebar. Titulos: {titulos_visiveis[:15]}")

    # Estrategia 2: usar atalho de teclado pra focar busca e procurar
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        body = driver.find_element(By.TAG_NAME, "body")
        # Ctrl+Alt+/ foca a busca no WhatsApp Web
        ActionChains(driver).key_down(Keys.CONTROL).key_down(Keys.ALT).send_keys("/").key_up(Keys.ALT).key_up(Keys.CONTROL).perform()
        time.sleep(1)
        active = driver.switch_to.active_element
        if active and active.get_attribute("contenteditable") == "true":
            active.send_keys(nome)
            time.sleep(2)
            # re-tentar clicar
            resultado = driver.execute_script(script_click, nome)
            if resultado and resultado.get("ok"):
                time.sleep(1)
                logger.info(f"Grupo aberto via busca: '{resultado.get('title')}'")
                return True
    except Exception as e:
        logger.warning(f"Atalho Ctrl+Alt+/ falhou: {e}")

    raise NoSuchElementException(
        f"Grupo '{nome}' nao encontrado. Confira o nome exato e se ele esta na sua lista de conversas."
    )


_JS_LER_MSGS = r"""
    const limite = arguments[0] || 40;
    const diag = { pre: 0, copyable: 0, span_sel: 0, msg_in: 0, data_id: 0, main: false };
    const main = document.querySelector('#main');
    diag.main = !!main;
    const root = main || document;
    diag.pre = root.querySelectorAll('[data-pre-plain-text]').length;
    diag.copyable = root.querySelectorAll('div.copyable-text, [data-copyable-text]').length;
    diag.span_sel = root.querySelectorAll('span.selectable-text, span[class*="selectable-text"]').length;
    diag.msg_in = root.querySelectorAll('div.message-in, div.message-out, div[class*="message-in"], div[class*="message-out"]').length;
    diag.data_id = root.querySelectorAll('div[data-id]').length;

    // Estrategia 1: containers com data-pre-plain-text
    let result = [];
    const containers = root.querySelectorAll('[data-pre-plain-text]');
    for (const c of containers) {
        const meta = c.getAttribute('data-pre-plain-text') || '';
        let text = '';
        const spans = c.querySelectorAll('span.selectable-text, span[class*="selectable-text"]');
        if (spans.length > 0) {
            text = Array.from(spans).map(s => s.innerText || s.textContent || '').join(' ').trim();
        } else {
            text = (c.innerText || c.textContent || '').trim();
        }
        if (text) result.push({meta: meta.trim(), text: text});
    }

    // Estrategia 2: se nada achou, varrer spans selectable-text dentro de bubbles
    if (result.length === 0 && main) {
        const bubbles = main.querySelectorAll('div[data-id], div[class*="message-in"], div[class*="message-out"]');
        for (const b of bubbles) {
            const spans = b.querySelectorAll('span.selectable-text, span[class*="selectable-text"]');
            if (spans.length === 0) continue;
            const text = Array.from(spans).map(s => s.innerText || s.textContent || '').join(' ').trim();
            if (!text) continue;
            const did = b.getAttribute('data-id') || '';
            result.push({meta: did, text: text});
        }
    }

    return {diag: diag, msgs: result.slice(-limite)};
"""


def ler_mensagens_recentes(driver, limite=40):
    """Retorna lista das ultimas mensagens do chat atualmente aberto (via JS)."""
    try:
        out = driver.execute_script(_JS_LER_MSGS, limite)
        diag = (out or {}).get("diag", {})
        msgs = (out or {}).get("msgs", []) or []
        # log diagnostico uma vez por ciclo
        logger.info(
            f"DOM: main={diag.get('main')} pre={diag.get('pre')} copyable={diag.get('copyable')}"
            f" spanSel={diag.get('span_sel')} msgIO={diag.get('msg_in')} dataId={diag.get('data_id')}"
            f" -> msgs={len(msgs)}"
        )
        return msgs
    except Exception as e:
        logger.warning(f"Erro ao ler mensagens via JS: {e}")
        return []


def ciclo_leitura(driver, processed):
    msgs = ler_mensagens_recentes(driver)
    novos = 0
    for m in msgs:
        h = msg_hash(m["meta"], m["text"])
        if h in processed:
            continue
        match = PADRAO_OK.match(m["text"])
        if match:
            numero = match.group(1)
            try:
                enqueue(numero, m["meta"], m["text"])
                novos += 1
            except Exception as e:
                logger.error(f"Falha ao enfileirar: {e}")
        processed.add(h)
    if novos:
        save_state(processed)
    return novos


_parar = False


def handler_sinal(signum, frame):
    global _parar
    _parar = True
    logger.info(f"Sinal {signum} recebido, encerrando...")


def _verificar_instancia_unica():
    """Evita 2 listeners rodando ao mesmo tempo (trava o profile)."""
    lock = BASE_DIR / "listener_nfe.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text().strip())
            # checar se processo existe
            import psutil  # type: ignore
            if psutil.pid_exists(pid):
                logger.error(f"Listener ja esta rodando (PID {pid}). Abortando.")
                sys.exit(0)
        except Exception:
            pass  # se psutil nao tiver, segue em frente
    try:
        lock.write_text(str(os.getpid()))
    except Exception:
        pass
    import atexit
    atexit.register(lambda: lock.unlink(missing_ok=True) if lock.exists() else None)


def main():
    _verificar_instancia_unica()
    signal.signal(signal.SIGINT, handler_sinal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handler_sinal)

    while not _parar:
        driver = None
        try:
            driver = criar_driver()
            esperar_whatsapp_carregar(driver)
            abrir_grupo(driver, GRUPO_NOME)
            processed = load_state()
            logger.info(f"Listener ativo. Polling a cada {POLL_SECONDS}s.")
            while not _parar:
                try:
                    n = ciclo_leitura(driver, processed)
                    if n > 0:
                        logger.info(f"{n} mensagem(ns) enfileirada(s).")
                except Exception as e:
                    logger.error(f"Erro no ciclo: {e}")
                for _ in range(POLL_SECONDS):
                    if _parar:
                        break
                    time.sleep(1)
        except WebDriverException as e:
            logger.error(f"Erro no driver: {e}. Reabrindo em 30s...")
            time.sleep(30)
        except Exception as e:
            logger.error(f"Erro inesperado: {e}. Reabrindo em 30s...")
            time.sleep(30)
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
