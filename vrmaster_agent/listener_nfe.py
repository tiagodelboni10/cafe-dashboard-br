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

PADRAO_OK = re.compile(r"^\s*ok\s+(\d{3,})\s*$", re.IGNORECASE)
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
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    # Nao usar headless — WhatsApp Web detecta
    driver = webdriver.Chrome(options=opts)
    driver.set_window_size(1100, 800)
    return driver


def esperar_whatsapp_carregar(driver, timeout=120):
    """Espera ate o WhatsApp Web carregar a lista de chats (ou QR code)."""
    logger.info("Abrindo web.whatsapp.com...")
    driver.get("https://web.whatsapp.com")
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Se tiver QR code, aviso ao usuario
        try:
            driver.find_element(By.XPATH, "//canvas[@aria-label='Scan me!' or contains(@aria-label,'escan')]")
            logger.warning("QR code exibido — escaneie no celular (WhatsApp > Dispositivos conectados)")
            time.sleep(5)
            continue
        except NoSuchElementException:
            pass
        # UI principal carregada?
        try:
            driver.find_element(By.XPATH, "//div[@role='textbox' and contains(@aria-label,'esquisa')] | //div[contains(@aria-label,'Search input textbox')]")
            logger.info("WhatsApp Web carregado.")
            return True
        except NoSuchElementException:
            time.sleep(2)
    raise TimeoutException("WhatsApp Web nao carregou")


def abrir_grupo(driver, nome):
    """Abre o chat do grupo pelo nome."""
    logger.info(f"Abrindo grupo '{nome}'...")
    # clicar na busca
    try:
        search = driver.find_element(By.XPATH, "//div[@role='textbox' and (contains(@aria-label,'esquisa') or contains(@aria-label,'Search'))]")
    except NoSuchElementException:
        # as vezes precisa clicar num botao de busca primeiro
        driver.find_elements(By.XPATH, "//button[@aria-label='Nova conversa' or @aria-label='Pesquisar']")
        search = driver.find_element(By.XPATH, "//div[@role='textbox' and (contains(@aria-label,'esquisa') or contains(@aria-label,'Search'))]")
    search.click()
    time.sleep(0.5)
    search.send_keys(Keys.CONTROL, "a")
    search.send_keys(nome)
    time.sleep(2)
    # clicar no primeiro resultado que tem span title=nome
    try:
        el = driver.find_element(By.XPATH, f"//span[@title='{nome}']")
        el.click()
    except NoSuchElementException:
        # tentar case-insensitive / parcial
        resultados = driver.find_elements(By.XPATH, "//span[@title]")
        for r in resultados:
            if nome.lower() in (r.get_attribute("title") or "").lower():
                r.click()
                return True
        raise NoSuchElementException(f"Grupo '{nome}' nao encontrado")
    time.sleep(1)
    return True


def ler_mensagens_recentes(driver, limite=40):
    """Retorna lista das ultimas mensagens do chat atualmente aberto."""
    msgs = []
    # os contaneires de mensagens tem role='row'. Cada msg tem copyable-text
    rows = driver.find_elements(By.XPATH, "//div[@role='row']")
    for row in rows[-limite:]:
        try:
            copy_el = row.find_element(By.XPATH, ".//div[contains(@class,'copyable-text')]")
            meta = copy_el.get_attribute("data-pre-plain-text") or ""
            # texto da msg (span selectable-text)
            text = ""
            try:
                spans = copy_el.find_elements(By.XPATH, ".//span[contains(@class,'selectable-text')]")
                text = " ".join(s.text for s in spans if s.text).strip()
            except NoSuchElementException:
                pass
            if not text:
                continue
            msgs.append({"meta": meta.strip(), "text": text})
        except (NoSuchElementException, StaleElementReferenceException):
            continue
    return msgs


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


def main():
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
