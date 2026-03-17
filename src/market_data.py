"""Módulo para busca de dados de mercado de futuros de café."""

import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from src.config import TICKERS, HISTORICAL_DAYS


def fetch_coffee_futures(coffee_type: str, period_days: int = HISTORICAL_DAYS) -> pd.DataFrame:
    """Busca dados históricos de futuros de café."""
    ticker = TICKERS.get(coffee_type)
    if not ticker:
        # Para robusta, tentamos gerar dados a partir do preço atual
        return pd.DataFrame()

    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        data = yf.download(
            ticker,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            progress=False,
        )
        if data.empty:
            return pd.DataFrame()

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = data.reset_index()
        return data
    except Exception as e:
        print(f"Erro ao buscar dados de {coffee_type} ({ticker}): {e}")
        return pd.DataFrame()


def _scrape_robusta_price() -> dict:
    """Busca preço atual do Robusta via Barchart (USD/ton)."""
    import re
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(
            "https://www.barchart.com/futures/quotes/RMU25/overview",
            headers=headers, timeout=15,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text()

        # Extrair dados da seção "Price Performance"
        idx = text.find("Price Performance")
        if idx < 0:
            raise ValueError("Secao Price Performance nao encontrada")

        chunk = text[idx:idx + 600]
        numbers = re.findall(r"[\d,]+\.?\d*", chunk)
        # numbers[1] = 1-month low (aprox preço atual), numbers[6] = 52-week low, etc.

        # Layout: "1-Month <low> +X% on MM/DD/YY <high> -X% on MM/DD/YY <change> (<pct>%) since ..."
        #         "52-Week <low> ... <high> ... <change> (<pct>%) since ..."

        def parse_number(s):
            return float(s.replace(",", ""))

        # Preço atual: primeiro número grande na seção 1-Month
        price = 0.0
        m = re.search(r"1-Month\s+([\d,]+)", chunk)
        if m:
            price = parse_number(m.group(1))

        # 52-Week: extrair low e high
        low_52w = 0.0
        high_52w = 0.0
        m52 = re.search(
            r"52-Week\s+([\d,]+)\s+.*?\s+([\d,]+)\s+", chunk
        )
        if m52:
            v1 = parse_number(m52.group(1))
            v2 = parse_number(m52.group(2))
            low_52w = min(v1, v2)
            high_52w = max(v1, v2)

        # Variação do 1-Month: "<change> (<pct>%) since"
        change = 0.0
        change_pct = 0.0
        m_1m = re.search(
            r"1-Month.*?([-+][\d,]+)\s+\(([-+]?\d+\.?\d*)%\)\s+since",
            chunk, re.DOTALL,
        )
        if m_1m:
            change = parse_number(m_1m.group(1))
            change_pct = float(m_1m.group(2))

        return {
            "price": round(price, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "currency": "USD/ton",
            "name": "Robusta Coffee Futures (ICE London)",
        }
    except Exception as e:
        print(f"Erro ao buscar preco Robusta via scraping: {e}")
        return {}


def get_current_price(coffee_type: str) -> dict:
    """Retorna o preço atual e variações do futuro de café."""
    if coffee_type == "robusta":
        return _scrape_robusta_price()

    ticker = TICKERS.get(coffee_type)
    if not ticker:
        return {}

    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="5d")

        if hist.empty:
            return {}

        current_price = hist["Close"].iloc[-1]
        prev_price = hist["Close"].iloc[-2] if len(hist) > 1 else current_price

        change = current_price - prev_price
        change_pct = (change / prev_price) * 100 if prev_price != 0 else 0

        return {
            "price": round(float(current_price), 2),
            "change": round(float(change), 2),
            "change_pct": round(float(change_pct), 2),
            "high_52w": round(float(info.get("fiftyTwoWeekHigh", 0)), 2),
            "low_52w": round(float(info.get("fiftyTwoWeekLow", 0)), 2),
            "currency": info.get("currency", "USD"),
            "name": info.get("shortName", coffee_type.capitalize()),
        }
    except Exception as e:
        print(f"Erro ao buscar preço atual de {coffee_type}: {e}")
        return {}


def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula indicadores técnicos sobre os dados de preço."""
    if df.empty or "Close" not in df.columns:
        return df

    df = df.copy()

    # Médias Móveis
    df["SMA_20"] = df["Close"].rolling(window=20).mean()
    df["SMA_50"] = df["Close"].rolling(window=50).mean()
    df["EMA_12"] = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA_26"] = df["Close"].ewm(span=26, adjust=False).mean()

    # MACD
    df["MACD"] = df["EMA_12"] - df["EMA_26"]
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    # RSI (14 períodos)
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # Bollinger Bands
    df["BB_Mid"] = df["Close"].rolling(window=20).mean()
    bb_std = df["Close"].rolling(window=20).std()
    df["BB_Upper"] = df["BB_Mid"] + (bb_std * 2)
    df["BB_Lower"] = df["BB_Mid"] - (bb_std * 2)

    if "Volume" in df.columns:
        df["Vol_SMA_20"] = df["Volume"].rolling(window=20).mean()

    return df


def get_market_summary() -> dict:
    """Retorna resumo do mercado para ambos os tipos de café."""
    summary = {}
    for coffee_type in ["arabica", "robusta"]:
        price_info = get_current_price(coffee_type)
        hist_data = fetch_coffee_futures(coffee_type)
        tech_data = calculate_technical_indicators(hist_data)

        summary[coffee_type] = {
            "price_info": price_info,
            "historical": hist_data,
            "technical": tech_data,
        }
    return summary
