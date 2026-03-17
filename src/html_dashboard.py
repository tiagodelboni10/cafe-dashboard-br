"""Gera dashboard como HTML estático auto-contido."""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.news_fetcher import get_all_coffee_news
from src.market_data import (
    fetch_coffee_futures,
    get_current_price,
    calculate_technical_indicators,
)
from src.analyzer import analyze_sentiment, analyze_technicals, generate_recommendation


def build_price_chart_html(tech_df: pd.DataFrame, label: str) -> str:
    """Gera HTML de gráfico de preço com indicadores."""
    if tech_df.empty:
        return "<p>Dados históricos indisponíveis</p>"

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=(f"Preço {label}", "MACD", "RSI"),
    )

    if all(c in tech_df.columns for c in ["Open", "High", "Low", "Close"]):
        fig.add_trace(go.Candlestick(
            x=tech_df["Date"], open=tech_df["Open"],
            high=tech_df["High"], low=tech_df["Low"],
            close=tech_df["Close"], name="Preço",
        ), row=1, col=1)

    if "SMA_20" in tech_df.columns:
        fig.add_trace(go.Scatter(
            x=tech_df["Date"], y=tech_df["SMA_20"],
            name="SMA 20", line=dict(color="orange", width=1),
        ), row=1, col=1)
    if "SMA_50" in tech_df.columns:
        fig.add_trace(go.Scatter(
            x=tech_df["Date"], y=tech_df["SMA_50"],
            name="SMA 50", line=dict(color="blue", width=1),
        ), row=1, col=1)

    if "BB_Upper" in tech_df.columns:
        fig.add_trace(go.Scatter(
            x=tech_df["Date"], y=tech_df["BB_Upper"],
            name="BB Superior", line=dict(color="gray", width=0.5, dash="dot"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=tech_df["Date"], y=tech_df["BB_Lower"],
            name="BB Inferior", line=dict(color="gray", width=0.5, dash="dot"),
            fill="tonexty", fillcolor="rgba(128,128,128,0.1)",
        ), row=1, col=1)

    if "MACD" in tech_df.columns:
        colors = ["#26a69a" if v >= 0 else "#ef5350" for v in tech_df["MACD_Hist"].fillna(0)]
        fig.add_trace(go.Bar(
            x=tech_df["Date"], y=tech_df["MACD_Hist"],
            name="MACD Hist", marker_color=colors,
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=tech_df["Date"], y=tech_df["MACD"],
            name="MACD", line=dict(color="blue", width=1),
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=tech_df["Date"], y=tech_df["MACD_Signal"],
            name="Sinal", line=dict(color="red", width=1),
        ), row=2, col=1)

    if "RSI" in tech_df.columns:
        fig.add_trace(go.Scatter(
            x=tech_df["Date"], y=tech_df["RSI"],
            name="RSI", line=dict(color="purple", width=1),
        ), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

    fig.update_layout(
        height=650, xaxis_rangeslider_visible=False,
        showlegend=True, template="plotly_dark",
        paper_bgcolor="#1a1a2e", plot_bgcolor="#16213e",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=60, b=30),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def build_sentiment_gauge_html(sentiment: dict, label: str) -> str:
    """Gera HTML de gauge de sentimento."""
    score = sentiment.get("score", 0)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title=dict(text=f"Sentimento {label}", font=dict(color="white")),
        number=dict(font=dict(color="white")),
        gauge=dict(
            axis=dict(range=[-100, 100], tickfont=dict(color="white")),
            bar=dict(color="#4fc3f7"),
            bgcolor="#16213e",
            steps=[
                dict(range=[-100, -30], color="#ef5350"),
                dict(range=[-30, 30], color="#ffa726"),
                dict(range=[30, 100], color="#26a69a"),
            ],
        ),
    ))
    fig.update_layout(
        height=280, paper_bgcolor="#1a1a2e",
        margin=dict(l=30, r=30, t=60, b=10),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def generate_html_dashboard(output_path: str = "dashboard.html"):
    """Gera o dashboard completo como arquivo HTML."""
    print("Buscando precos do mercado...")
    arabica_price = get_current_price("arabica")
    robusta_price = get_current_price("robusta")

    print("Buscando dados historicos...")
    arabica_hist = fetch_coffee_futures("arabica")
    robusta_hist = fetch_coffee_futures("robusta")
    arabica_tech = calculate_technical_indicators(arabica_hist)
    robusta_tech = calculate_technical_indicators(robusta_hist)

    print("Buscando noticias...")
    news = get_all_coffee_news()

    print("Analisando sentimento e indicadores...")
    arabica_sentiment = analyze_sentiment(news.get("arabica", []))
    robusta_sentiment = analyze_sentiment(news.get("robusta", []))
    arabica_technicals = analyze_technicals(arabica_tech)
    robusta_technicals = analyze_technicals(robusta_tech)
    arabica_rec = generate_recommendation(arabica_sentiment, arabica_technicals, arabica_price)
    robusta_rec = generate_recommendation(robusta_sentiment, robusta_technicals, robusta_price)

    print("Gerando graficos...")
    arabica_chart = build_price_chart_html(arabica_tech, "Arabica")
    robusta_chart = build_price_chart_html(robusta_tech, "Robusta")
    arabica_gauge = build_sentiment_gauge_html(arabica_sentiment, "Arabica")
    robusta_gauge = build_sentiment_gauge_html(robusta_sentiment, "Robusta")

    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    def price_card(label, info):
        if not info:
            return f'<div class="price-card"><h3>{label}</h3><p>Dados indisponiveis</p></div>'
        p = info.get("price", 0)
        ch = info.get("change", 0)
        pct = info.get("change_pct", 0)
        cur = info.get("currency", "USD")
        color = "#26a69a" if ch >= 0 else "#ef5350"
        arrow = "&#9650;" if ch >= 0 else "&#9660;"
        return f'''<div class="price-card">
            <h3>{label}</h3>
            <div class="price-value">{cur} {p:.2f}</div>
            <div class="price-change" style="color:{color}">
                {arrow} {abs(ch):.2f} ({abs(pct):.2f}%)
            </div>
            <div class="price-range">
                <span>Min 52s: {info.get("low_52w", "N/A")}</span>
                <span>Max 52s: {info.get("high_52w", "N/A")}</span>
            </div>
        </div>'''

    def rec_card(label, rec):
        icon = rec.get("icon", "")
        pos = rec.get("position", "NEUTRO")
        direction = rec.get("direction", "LATERAL")
        conf = rec.get("confidence", 0)
        score = rec.get("combined_score", 0)
        bar_pct = (score + 1) / 2 * 100

        if pos == "COMPRA":
            bg = "#1b5e20"
        elif pos == "VENDA":
            bg = "#b71c1c"
        else:
            bg = "#e65100"

        factors_html = ""
        for f in rec.get("factors", []):
            factors_html += f"<li>{f}</li>"

        return f'''<div class="rec-card" style="border-left: 4px solid {bg}">
            <div class="rec-header">
                <span class="rec-icon">{icon}</span>
                <span class="rec-label">{label}</span>
            </div>
            <div class="rec-position" style="background:{bg}">{pos}</div>
            <div class="rec-details">
                <span>Direcao: <strong>{direction}</strong></span>
                <span>Confianca: <strong>{conf:.0f}%</strong></span>
            </div>
            <div class="score-bar-container">
                <div class="score-bar" style="width:{bar_pct:.0f}%"></div>
            </div>
            <div class="rec-score">Score: {score:.3f}</div>
            <div class="rec-scores-row">
                <div>Sentimento: {rec.get("sentiment_score", 0):.1f}</div>
                <div>Tecnico: {rec.get("technical_score", 0):.1f}</div>
            </div>
            {f'<ul class="rec-factors">{factors_html}</ul>' if factors_html else ''}
        </div>'''

    def signals_table(signals):
        if not signals:
            return "<p>Sinais indisponiveis</p>"
        rows = ""
        for ind, sinal, desc in signals:
            if sinal == "ALTA":
                cls = "signal-bull"
            elif sinal == "BAIXA":
                cls = "signal-bear"
            else:
                cls = "signal-neutral"
            rows += f'<tr><td>{ind}</td><td class="{cls}">{sinal}</td><td>{desc}</td></tr>'
        return f'''<table class="signals-table">
            <thead><tr><th>Indicador</th><th>Sinal</th><th>Descricao</th></tr></thead>
            <tbody>{rows}</tbody></table>'''

    def news_list(articles, label):
        if not articles:
            return f"<p>Nenhuma noticia para {label}</p>"
        items = ""
        for a in articles:
            s = a.get("sentiment", "neutral")
            dot = {"bullish": "🟢", "bearish": "🔴"}.get(s, "⚪")
            link = a.get("link", "#")
            items += f'''<div class="news-item">
                <div class="news-title">{dot} <a href="{link}" target="_blank">{a.get("title","")}</a></div>
                <div class="news-meta">{a.get("published","N/A")} &middot; {a.get("source","")}</div>
                <div class="news-summary">{a.get("summary","")[:200]}</div>
            </div>'''
        return items

    arabica_signals = signals_table(arabica_technicals.get("signals", []))
    robusta_signals = signals_table(robusta_technicals.get("signals", []))

    arabica_news_html = news_list(
        arabica_sentiment.get("articles", news.get("arabica", [])), "Arabica")
    robusta_news_html = news_list(
        robusta_sentiment.get("articles", news.get("robusta", [])), "Robusta")
    general_news_html = news_list(news.get("geral", []), "Geral")

    sent_stats = lambda s: f'''<div class="sent-stats">
        <span class="stat-bull">Alta: {s.get("bullish",0)}</span>
        <span class="stat-neut">Neutra: {s.get("neutral",0)}</span>
        <span class="stat-bear">Baixa: {s.get("bearish",0)}</span>
    </div>'''

    html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Mercado de Cafe</title>
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #0f0f23;
    color: #e0e0e0;
    line-height: 1.6;
}}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
header {{
    text-align: center;
    padding: 30px 20px;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border-bottom: 2px solid #4fc3f7;
    margin-bottom: 24px;
}}
header h1 {{ font-size: 2em; color: #4fc3f7; }}
header .subtitle {{ color: #888; margin-top: 8px; font-size: 0.9em; }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
.price-card {{
    background: #1a1a2e; border-radius: 12px; padding: 24px;
    border: 1px solid #2a2a4a; text-align: center;
}}
.price-card h3 {{ color: #4fc3f7; margin-bottom: 12px; font-size: 1.1em; }}
.price-value {{ font-size: 2.4em; font-weight: 700; color: #fff; }}
.price-change {{ font-size: 1.2em; margin: 8px 0; font-weight: 600; }}
.price-range {{ display: flex; justify-content: space-between; color: #888; font-size: 0.85em; margin-top: 12px; }}
.section-title {{
    font-size: 1.4em; color: #4fc3f7; margin: 32px 0 16px 0;
    padding-bottom: 8px; border-bottom: 1px solid #2a2a4a;
}}
.rec-card {{
    background: #1a1a2e; border-radius: 12px; padding: 24px;
    border: 1px solid #2a2a4a;
}}
.rec-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }}
.rec-icon {{ font-size: 2em; }}
.rec-label {{ font-size: 1.2em; color: #ccc; }}
.rec-position {{
    display: inline-block; padding: 8px 24px; border-radius: 8px;
    font-size: 1.5em; font-weight: 700; color: #fff; margin-bottom: 16px;
}}
.rec-details {{ display: flex; gap: 24px; margin-bottom: 12px; color: #bbb; }}
.score-bar-container {{
    height: 8px; background: #2a2a4a; border-radius: 4px;
    overflow: hidden; margin-bottom: 8px;
}}
.score-bar {{
    height: 100%;
    background: linear-gradient(90deg, #ef5350, #ffa726, #26a69a);
    border-radius: 4px;
}}
.rec-score {{ color: #888; font-size: 0.85em; margin-bottom: 8px; }}
.rec-scores-row {{ display: flex; gap: 24px; color: #aaa; font-size: 0.9em; }}
.rec-factors {{ margin-top: 12px; padding-left: 20px; color: #aaa; font-size: 0.9em; }}
.rec-factors li {{ margin-bottom: 4px; }}
.tabs {{
    display: flex; gap: 4px; margin-bottom: 0;
    border-bottom: 2px solid #2a2a4a;
}}
.tab-btn {{
    padding: 12px 28px; cursor: pointer; background: #1a1a2e;
    border: 1px solid #2a2a4a; border-bottom: none; border-radius: 8px 8px 0 0;
    color: #888; font-size: 1em; transition: all 0.2s;
}}
.tab-btn.active {{ background: #16213e; color: #4fc3f7; border-color: #4fc3f7; }}
.tab-btn:hover {{ color: #4fc3f7; }}
.tab-content {{ display: none; padding: 24px 0; }}
.tab-content.active {{ display: block; }}
.signals-table {{
    width: 100%; border-collapse: collapse; margin: 16px 0;
    background: #1a1a2e; border-radius: 8px; overflow: hidden;
}}
.signals-table th {{
    background: #16213e; padding: 12px 16px; text-align: left;
    color: #4fc3f7; font-size: 0.9em;
}}
.signals-table td {{ padding: 10px 16px; border-bottom: 1px solid #2a2a4a; }}
.signal-bull {{ color: #26a69a; font-weight: 700; }}
.signal-bear {{ color: #ef5350; font-weight: 700; }}
.signal-neutral {{ color: #ffa726; font-weight: 700; }}
.analysis-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
.sent-stats {{
    display: flex; gap: 20px; justify-content: center;
    padding: 12px; margin-top: 8px;
}}
.stat-bull {{ color: #26a69a; font-weight: 600; }}
.stat-neut {{ color: #ffa726; font-weight: 600; }}
.stat-bear {{ color: #ef5350; font-weight: 600; }}
.news-item {{
    background: #1a1a2e; border-radius: 8px; padding: 16px;
    margin-bottom: 12px; border: 1px solid #2a2a4a;
    transition: border-color 0.2s;
}}
.news-item:hover {{ border-color: #4fc3f7; }}
.news-title {{ font-size: 1em; margin-bottom: 6px; }}
.news-title a {{ color: #e0e0e0; text-decoration: none; }}
.news-title a:hover {{ color: #4fc3f7; }}
.news-meta {{ font-size: 0.8em; color: #888; margin-bottom: 6px; }}
.news-summary {{ font-size: 0.85em; color: #aaa; }}
.news-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
footer {{
    text-align: center; padding: 24px; color: #555;
    font-size: 0.8em; margin-top: 40px;
    border-top: 1px solid #2a2a4a;
}}
@media (max-width: 768px) {{
    .grid-2, .analysis-grid, .news-grid {{ grid-template-columns: 1fr; }}
    .price-value {{ font-size: 1.8em; }}
    header h1 {{ font-size: 1.4em; }}
}}
</style>
</head>
<body>

<header>
    <h1>&#9749; Dashboard Mercado de Cafe</h1>
    <div class="subtitle">Robusta (Conilon) &amp; Arabica &mdash; Atualizado em {now}</div>
</header>

<div class="container">

    <!-- PRECOS -->
    <h2 class="section-title">&#128200; Precos Atuais</h2>
    <div class="grid-2">
        {price_card("Cafe Arabica (KC) - ICE", arabica_price)}
        {price_card("Cafe Robusta (RC) - ICE", robusta_price)}
    </div>

    <!-- RECOMENDACOES -->
    <h2 class="section-title">&#127919; Posicao Recomendada</h2>
    <div class="grid-2">
        {rec_card("Arabica", arabica_rec)}
        {rec_card("Robusta / Conilon", robusta_rec)}
    </div>

    <!-- TABS -->
    <h2 class="section-title">&#128202; Analise Detalhada</h2>
    <div class="tabs">
        <div class="tab-btn active" onclick="switchTab('arabica')">&#9749; Arabica</div>
        <div class="tab-btn" onclick="switchTab('robusta')">&#9749; Robusta (Conilon)</div>
        <div class="tab-btn" onclick="switchTab('news')">&#128240; Noticias</div>
    </div>

    <div id="tab-arabica" class="tab-content active">
        <h3 style="color:#4fc3f7; margin-bottom:16px;">Analise Tecnica - Arabica</h3>
        {arabica_chart}
        <div class="analysis-grid">
            <div>
                <h4 style="color:#4fc3f7; margin:16px 0 8px;">Sinais Tecnicos</h4>
                {arabica_signals}
            </div>
            <div>
                <h4 style="color:#4fc3f7; margin:16px 0 8px;">Sentimento de Mercado</h4>
                {arabica_gauge}
                {sent_stats(arabica_sentiment)}
            </div>
        </div>
    </div>

    <div id="tab-robusta" class="tab-content">
        <h3 style="color:#4fc3f7; margin-bottom:16px;">Analise Tecnica - Robusta (Conilon)</h3>
        {robusta_chart}
        <div class="analysis-grid">
            <div>
                <h4 style="color:#4fc3f7; margin:16px 0 8px;">Sinais Tecnicos</h4>
                {robusta_signals}
            </div>
            <div>
                <h4 style="color:#4fc3f7; margin:16px 0 8px;">Sentimento de Mercado</h4>
                {robusta_gauge}
                {sent_stats(robusta_sentiment)}
            </div>
        </div>
    </div>

    <div id="tab-news" class="tab-content">
        <div class="news-grid">
            <div>
                <h3 style="color:#4fc3f7; margin-bottom:16px;">&#9749; Noticias Arabica</h3>
                {arabica_news_html}
            </div>
            <div>
                <h3 style="color:#4fc3f7; margin-bottom:16px;">&#9749; Noticias Robusta / Conilon</h3>
                {robusta_news_html}
            </div>
        </div>
        <h3 style="color:#4fc3f7; margin:24px 0 16px;">&#127758; Mercado Geral de Cafe</h3>
        {general_news_html}
    </div>

</div>

<footer>
    Este dashboard e apenas para fins informativos. Nao constitui conselho financeiro.<br>
    Fontes: Yahoo Finance (futuros ICE) &middot; Google News RSS &middot; Analise automatizada por sentimento + indicadores tecnicos
</footer>

<script>
function switchTab(name) {{
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    const tabs = ['arabica','robusta','news'];
    const btns = document.querySelectorAll('.tab-btn');
    btns[tabs.indexOf(name)].classList.add('active');
    window.dispatchEvent(new Event('resize'));
}}
</script>
</body>
</html>'''

    out = Path(output_path)
    out.write_text(html, encoding="utf-8")
    print(f"\nDashboard gerado: {out.resolve()}")
    return str(out.resolve())
