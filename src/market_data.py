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
    """Busca preço do DIA do Robusta via Barchart (USD/ton).

    Extrai lastPrice do JSON embutido no data-ng-init da página,
    que contém o preço mais recente (não média).
    """
    import re
    import json as _json
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

        # 1) Extrair lastPrice do JSON no data-ng-init (preço do dia)
        price = 0.0
        change = 0.0
        change_pct = 0.0
        prev_price = 0.0
        high_52w = 0.0
        low_52w = 0.0

        for tag in soup.find_all(True, attrs={"data-ng-init": True}):
            init_val = tag.get("data-ng-init", "")
            # JSON com dados do quote: init({"symbol":"RMU25","lastPrice":"4,382s",...})
            m = re.search(r'init\((\{"symbol".*?\})', init_val, re.DOTALL)
            if m:
                # Limpar e parsear
                raw = m.group(1)
                try:
                    data = _json.loads(raw)
                except _json.JSONDecodeError:
                    continue

                # lastPrice vem como "4,382s" ou "4,382" — remover letras e vírgulas
                lp = data.get("lastPrice", "0")
                lp_clean = re.sub(r"[^\d.]", "", lp.replace(",", ""))
                if lp_clean:
                    price = float(lp_clean)

                # priceChange e percentChange
                pc = data.get("priceChange", "0")
                if pc not in ("unch", "N/A", "-"):
                    pc_clean = re.sub(r"[^\d.+-]", "", pc.replace(",", ""))
                    if pc_clean:
                        change = float(pc_clean)

                pct = data.get("percentChange", "0")
                if pct not in ("unch", "N/A", "-"):
                    pct_clean = re.sub(r"[^\d.+-]", "", pct.replace(",", ""))
                    if pct_clean:
                        change_pct = float(pct_clean)

                pp = data.get("previousPrice", "0")
                pp_clean = re.sub(r"[^\d.]", "", pp.replace(",", ""))
                if pp_clean:
                    prev_price = float(pp_clean)

                break

            # JSON com overview: init("RMU25",{...},{...},{"previousPrice":"4,382",...})
            m2 = re.search(
                r'init\("RMU25".*?"previousPrice":"([\d,]+)".*?"volume":"([\d,]+)"',
                init_val,
            )
            if m2 and not prev_price:
                prev_price = float(m2.group(1).replace(",", ""))

        # 2) Se não achou change mas temos prev_price, calcular
        if price and prev_price and change == 0 and price != prev_price:
            change = price - prev_price
            change_pct = (change / prev_price) * 100 if prev_price else 0

        # 3) 52-week via tabela "Last Price / 52-Week High/Low"
        for tag in soup.find_all("td"):
            text = tag.get_text(strip=True)
            next_td = tag.find_next_sibling("td")
            if not next_td:
                continue
            val_text = next_td.get_text(strip=True)
            val_clean = re.sub(r"[^\d.]", "", val_text.replace(",", ""))
            if not val_clean:
                continue
            val = float(val_clean)
            if "52-Week High" in text and val > 1000:
                high_52w = val
            elif "52-Week Low" in text and val > 1000:
                low_52w = val

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
