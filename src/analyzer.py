"""Módulo de análise: sentimento de notícias + indicadores técnicos + recomendação."""

import pandas as pd
from src.config import BULLISH_KEYWORDS, BEARISH_KEYWORDS


def analyze_sentiment(articles: list[dict]) -> dict:
    """Analisa o sentimento das notícias (bullish/bearish)."""
    if not articles:
        return {"score": 0, "bullish": 0, "bearish": 0, "neutral": 0, "total": 0}

    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    article_sentiments = []

    for article in articles:
        text = (article.get("title", "") + " " + article.get("summary", "")).lower()

        bull_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
        bear_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in text)

        if bull_hits > bear_hits:
            sentiment = "bullish"
            bullish_count += 1
        elif bear_hits > bull_hits:
            sentiment = "bearish"
            bearish_count += 1
        else:
            sentiment = "neutral"
            neutral_count += 1

        article["sentiment"] = sentiment
        article["bull_score"] = bull_hits
        article["bear_score"] = bear_hits
        article_sentiments.append(article)

    total = len(articles)
    score = ((bullish_count - bearish_count) / total) * 100 if total > 0 else 0

    return {
        "score": round(score, 1),
        "bullish": bullish_count,
        "bearish": bearish_count,
        "neutral": neutral_count,
        "total": total,
        "articles": article_sentiments,
    }


def analyze_technicals(tech_df: pd.DataFrame) -> dict:
    """Analisa indicadores técnicos e gera sinais."""
    if tech_df.empty or len(tech_df) < 50:
        return {"signals": [], "overall": "NEUTRO", "score": 0}

    latest = tech_df.iloc[-1]
    signals = []
    score = 0

    # Sinal SMA: preço acima/abaixo da SMA 20
    if pd.notna(latest.get("SMA_20")):
        if latest["Close"] > latest["SMA_20"]:
            signals.append(("SMA 20", "ALTA", "Preço acima da média móvel de 20 dias"))
            score += 1
        else:
            signals.append(("SMA 20", "BAIXA", "Preço abaixo da média móvel de 20 dias"))
            score -= 1

    # Sinal SMA: cruzamento SMA 20/50
    if pd.notna(latest.get("SMA_20")) and pd.notna(latest.get("SMA_50")):
        if latest["SMA_20"] > latest["SMA_50"]:
            signals.append(("Cruzamento SMA", "ALTA", "SMA 20 acima da SMA 50 (Golden Cross)"))
            score += 1
        else:
            signals.append(("Cruzamento SMA", "BAIXA", "SMA 20 abaixo da SMA 50 (Death Cross)"))
            score -= 1

    # RSI
    if pd.notna(latest.get("RSI")):
        rsi = latest["RSI"]
        if rsi > 70:
            signals.append(("RSI", "BAIXA", f"RSI em {rsi:.1f} - Sobrecomprado"))
            score -= 1
        elif rsi < 30:
            signals.append(("RSI", "ALTA", f"RSI em {rsi:.1f} - Sobrevendido"))
            score += 1
        elif rsi > 50:
            signals.append(("RSI", "ALTA", f"RSI em {rsi:.1f} - Momentum positivo"))
            score += 0.5
        else:
            signals.append(("RSI", "BAIXA", f"RSI em {rsi:.1f} - Momentum negativo"))
            score -= 0.5

    # MACD
    if pd.notna(latest.get("MACD")) and pd.notna(latest.get("MACD_Signal")):
        if latest["MACD"] > latest["MACD_Signal"]:
            signals.append(("MACD", "ALTA", "MACD acima da linha de sinal"))
            score += 1
        else:
            signals.append(("MACD", "BAIXA", "MACD abaixo da linha de sinal"))
            score -= 1

    # Bollinger Bands
    if pd.notna(latest.get("BB_Upper")) and pd.notna(latest.get("BB_Lower")):
        if latest["Close"] > latest["BB_Upper"]:
            signals.append(("Bollinger", "BAIXA", "Preço acima da banda superior"))
            score -= 1
        elif latest["Close"] < latest["BB_Lower"]:
            signals.append(("Bollinger", "ALTA", "Preço abaixo da banda inferior"))
            score += 1
        else:
            signals.append(("Bollinger", "NEUTRO", "Preço dentro das bandas"))

    # Tendência de curto prazo (últimos 5 dias)
    if len(tech_df) >= 5:
        last_5 = tech_df["Close"].tail(5)
        trend = (last_5.iloc[-1] - last_5.iloc[0]) / last_5.iloc[0] * 100
        if trend > 1:
            signals.append(("Tendência 5d", "ALTA", f"Alta de {trend:.1f}% nos últimos 5 dias"))
            score += 0.5
        elif trend < -1:
            signals.append(("Tendência 5d", "BAIXA", f"Queda de {abs(trend):.1f}% nos últimos 5 dias"))
            score -= 0.5
        else:
            signals.append(("Tendência 5d", "NEUTRO", f"Variação de {trend:.1f}% nos últimos 5 dias"))

    if score >= 2:
        overall = "ALTA"
    elif score <= -2:
        overall = "BAIXA"
    else:
        overall = "NEUTRO"

    return {"signals": signals, "overall": overall, "score": round(score, 1)}


def generate_recommendation(
    sentiment: dict,
    technicals: dict,
    price_info: dict,
    season: dict | None = None,
    spread: dict | None = None,
    weather_alerts: list | None = None,
    ice_stocks: dict | None = None,
    cot: dict | None = None,
    coffee_type: str = "arabica",
) -> dict:
    """Gera recomendação final combinando todos os indicadores.

    Pesos:
        30% Técnico
        20% Sentimento de notícias
        15% Sazonalidade
        10% Spread Arábica/Robusta
        10% Clima (alertas)
        10% Estoques ICE
         5% Posição de fundos (COT)
    """
    sent_score = sentiment.get("score", 0)
    tech_score = technicals.get("score", 0)

    # ---------- score individual de cada pilar (normalizado -1 a +1) ----------

    # Técnico: score vai de ~ -5 a +5 → normaliza pra -1..+1
    s_tech = max(-1, min(1, tech_score / 5))

    # Sentimento: score vai de -100 a +100 → normaliza
    s_sent = max(-1, min(1, sent_score / 100))

    # Sazonalidade
    s_season = 0.0
    season_detail = ""
    if season:
        pressure = season.get("pressure", "")
        if "ALTISTA" in pressure:
            s_season = 0.6
            season_detail = season.get("pressure_detail", "")
        elif "BAIXISTA" in pressure:
            # Se for baixista para o tipo específico ou geral
            if coffee_type in pressure.lower() or "(" not in pressure:
                s_season = -0.6
            else:
                s_season = -0.2  # pressão baixista mas pra outro tipo
            season_detail = season.get("pressure_detail", "")

    # Spread
    s_spread = 0.0
    spread_detail = ""
    if spread:
        ratio = spread.get("ratio", 0)
        if coffee_type == "arabica":
            if ratio > 2.5:
                s_spread = -0.5  # Arábica caro → pressão de queda
            elif ratio < 1.5:
                s_spread = 0.5   # Arábica barato vs Robusta → demanda sobe
        else:  # robusta
            if ratio > 2.5:
                s_spread = 0.5   # Robusta barato → demanda por substituição sobe
            elif ratio < 1.5:
                s_spread = -0.5  # Robusta caro → pode perder demanda
        spread_detail = spread.get("signal", "")

    # Clima: alertas de geada/seca → altista; chuva excessiva durante colheita → altista
    s_weather = 0.0
    weather_detail = ""
    if weather_alerts:
        for alert in weather_alerts:
            if "GEADA SEVERA" in alert:
                s_weather += 0.8
                weather_detail = alert
            elif "GEADA" in alert:
                s_weather += 0.5
                weather_detail = alert
            elif "SECA" in alert:
                s_weather += 0.4
                if not weather_detail:
                    weather_detail = alert
            elif "CHUVA EXCESSIVA" in alert:
                s_weather += 0.3
                if not weather_detail:
                    weather_detail = alert
            elif "CALOR EXTREMO" in alert:
                s_weather += 0.3
                if not weather_detail:
                    weather_detail = alert
        s_weather = max(-1, min(1, s_weather))

    # Estoques ICE
    s_ice = 0.0
    ice_detail = ""
    if ice_stocks:
        trend = ice_stocks.get("trend", "")
        if trend == "queda":
            s_ice = 0.5  # estoques caindo → menos oferta → altista
            ice_detail = "Estoques certificados ICE em queda"
        elif trend == "alta":
            s_ice = -0.5
            ice_detail = "Estoques certificados ICE em alta"

    # COT / Fundos
    s_cot = 0.0
    cot_detail = ""
    if cot:
        pos = cot.get("position", "")
        if "comprado" in pos or "long" in pos:
            s_cot = 0.5
            cot_detail = "Fundos especulativos posicionados na compra"
        elif "vendido" in pos or "short" in pos:
            s_cot = -0.5
            cot_detail = "Fundos especulativos posicionados na venda"

    # ---------- combinar com pesos ----------
    combined = (
        s_tech    * 0.30 +
        s_sent    * 0.20 +
        s_season  * 0.15 +
        s_spread  * 0.10 +
        s_weather * 0.10 +
        s_ice     * 0.10 +
        s_cot     * 0.05
    )
    combined = max(-1, min(1, combined))

    if combined > 0.2:
        position = "COMPRA"
        direction = "ALTA"
        confidence = min(abs(combined) * 100, 95)
        icon = "🟢"
    elif combined < -0.2:
        position = "VENDA"
        direction = "BAIXA"
        confidence = min(abs(combined) * 100, 95)
        icon = "🔴"
    else:
        position = "NEUTRO"
        direction = "LATERAL"
        confidence = max(25, 50 - abs(combined) * 50)
        icon = "🟡"

    # ---------- fatores ----------
    factors = []

    if s_sent > 0.1:
        factors.append("Sentimento de notícias predominantemente positivo")
    elif s_sent < -0.1:
        factors.append("Sentimento de notícias predominantemente negativo")

    tech_overall = technicals.get("overall", "NEUTRO")
    if tech_overall == "ALTA":
        factors.append("Indicadores técnicos apontando para alta")
    elif tech_overall == "BAIXA":
        factors.append("Indicadores técnicos apontando para baixa")

    if season_detail:
        factors.append(season_detail)
    if spread_detail:
        factors.append(spread_detail)
    if weather_detail:
        factors.append(weather_detail)
    if ice_detail:
        factors.append(ice_detail)
    if cot_detail:
        factors.append(cot_detail)

    if price_info:
        price = price_info.get("price", 0)
        low_52 = price_info.get("low_52w", 0)
        high_52 = price_info.get("high_52w", 0)
        if high_52 > 0 and low_52 > 0 and (high_52 - low_52) > 0:
            range_pct = (price - low_52) / (high_52 - low_52) * 100
            if range_pct > 80:
                factors.append(f"Preço próximo da máxima de 52 semanas ({range_pct:.0f}% do range)")
            elif range_pct < 20:
                factors.append(f"Preço próximo da mínima de 52 semanas ({range_pct:.0f}% do range)")

    # breakdown de scores por pilar
    breakdown = {
        "Técnico (30%)": round(s_tech, 3),
        "Sentimento (20%)": round(s_sent, 3),
        "Sazonalidade (15%)": round(s_season, 3),
        "Spread (10%)": round(s_spread, 3),
        "Clima (10%)": round(s_weather, 3),
        "Estoques ICE (10%)": round(s_ice, 3),
        "Fundos/COT (5%)": round(s_cot, 3),
    }

    return {
        "position": position,
        "direction": direction,
        "confidence": round(confidence, 1),
        "icon": icon,
        "combined_score": round(combined, 3),
        "sentiment_score": sent_score,
        "technical_score": tech_score,
        "factors": factors,
        "breakdown": breakdown,
    }
