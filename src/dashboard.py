"""Dashboard Streamlit para o mercado de café."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

from src.config import DASHBOARD_TITLE
from src.news_fetcher import get_all_coffee_news
from src.market_data import (
    fetch_coffee_futures,
    get_current_price,
    calculate_technical_indicators,
)
from src.analyzer import analyze_sentiment, analyze_technicals, generate_recommendation


def setup_page():
    """Configura a página do Streamlit."""
    st.set_page_config(
        page_title="Dashboard Café",
        page_icon="☕",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title(DASHBOARD_TITLE)
    st.caption(f"Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M')}")


def render_price_card(coffee_type: str, label: str, price_info: dict):
    """Renderiza card de preço."""
    if not price_info:
        st.warning(f"Dados de preço indisponíveis para {label}")
        return

    price = price_info.get("price", 0)
    change = price_info.get("change", 0)
    change_pct = price_info.get("change_pct", 0)
    currency = price_info.get("currency", "USD")

    color = "green" if change >= 0 else "red"
    arrow = "▲" if change >= 0 else "▼"

    st.metric(
        label=f"{label} ({currency})",
        value=f"{price:.2f}",
        delta=f"{arrow} {abs(change):.2f} ({abs(change_pct):.2f}%)",
        delta_color="normal" if change >= 0 else "inverse",
    )

    col1, col2 = st.columns(2)
    col1.caption(f"Mín 52s: {price_info.get('low_52w', 'N/A')}")
    col2.caption(f"Máx 52s: {price_info.get('high_52w', 'N/A')}")


def render_price_chart(tech_df: pd.DataFrame, coffee_label: str):
    """Renderiza gráfico de preço com indicadores técnicos."""
    if tech_df.empty:
        st.info("Dados históricos indisponíveis")
        return

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=(f"Preço {coffee_label}", "MACD", "RSI"),
    )

    # Candlestick
    if all(col in tech_df.columns for col in ["Open", "High", "Low", "Close"]):
        fig.add_trace(
            go.Candlestick(
                x=tech_df["Date"],
                open=tech_df["Open"],
                high=tech_df["High"],
                low=tech_df["Low"],
                close=tech_df["Close"],
                name="Preço",
            ),
            row=1, col=1,
        )

    # Médias móveis
    if "SMA_20" in tech_df.columns:
        fig.add_trace(
            go.Scatter(x=tech_df["Date"], y=tech_df["SMA_20"],
                       name="SMA 20", line=dict(color="orange", width=1)),
            row=1, col=1,
        )
    if "SMA_50" in tech_df.columns:
        fig.add_trace(
            go.Scatter(x=tech_df["Date"], y=tech_df["SMA_50"],
                       name="SMA 50", line=dict(color="blue", width=1)),
            row=1, col=1,
        )

    # Bollinger Bands
    if "BB_Upper" in tech_df.columns:
        fig.add_trace(
            go.Scatter(x=tech_df["Date"], y=tech_df["BB_Upper"],
                       name="BB Superior", line=dict(color="gray", width=0.5, dash="dot")),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(x=tech_df["Date"], y=tech_df["BB_Lower"],
                       name="BB Inferior", line=dict(color="gray", width=0.5, dash="dot"),
                       fill="tonexty", fillcolor="rgba(128,128,128,0.1)"),
            row=1, col=1,
        )

    # MACD
    if "MACD" in tech_df.columns:
        colors = ["green" if v >= 0 else "red" for v in tech_df["MACD_Hist"].fillna(0)]
        fig.add_trace(
            go.Bar(x=tech_df["Date"], y=tech_df["MACD_Hist"],
                   name="MACD Hist", marker_color=colors),
            row=2, col=1,
        )
        fig.add_trace(
            go.Scatter(x=tech_df["Date"], y=tech_df["MACD"],
                       name="MACD", line=dict(color="blue", width=1)),
            row=2, col=1,
        )
        fig.add_trace(
            go.Scatter(x=tech_df["Date"], y=tech_df["MACD_Signal"],
                       name="Sinal", line=dict(color="red", width=1)),
            row=2, col=1,
        )

    # RSI
    if "RSI" in tech_df.columns:
        fig.add_trace(
            go.Scatter(x=tech_df["Date"], y=tech_df["RSI"],
                       name="RSI", line=dict(color="purple", width=1)),
            row=3, col=1,
        )
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

    fig.update_layout(
        height=700,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_recommendation(rec: dict, label: str):
    """Renderiza a recomendação de posição."""
    icon = rec.get("icon", "🟡")
    position = rec.get("position", "NEUTRO")
    direction = rec.get("direction", "LATERAL")
    confidence = rec.get("confidence", 0)

    st.subheader(f"{icon} Posição {label}: **{position}**")
    st.write(f"Direção esperada: **{direction}** | Confiança: **{confidence:.0f}%**")

    # Barra de score
    score = rec.get("combined_score", 0)
    normalized = (score + 1) / 2  # mapeia [-1, 1] para [0, 1]
    st.progress(normalized, text=f"Score combinado: {score:.3f}")

    # Fatores
    factors = rec.get("factors", [])
    if factors:
        st.write("**Fatores:**")
        for f in factors:
            st.write(f"  - {f}")

    # Scores detalhados
    col1, col2 = st.columns(2)
    col1.metric("Score Sentimento", f"{rec.get('sentiment_score', 0):.1f}")
    col2.metric("Score Técnico", f"{rec.get('technical_score', 0):.1f}")


def render_signals_table(signals: list):
    """Renderiza tabela de sinais técnicos."""
    if not signals:
        st.info("Sinais técnicos indisponíveis")
        return

    df = pd.DataFrame(signals, columns=["Indicador", "Sinal", "Descrição"])

    def color_signal(val):
        if val == "ALTA":
            return "background-color: #d4edda; color: #155724"
        elif val == "BAIXA":
            return "background-color: #f8d7da; color: #721c24"
        return "background-color: #fff3cd; color: #856404"

    styled = df.style.map(color_signal, subset=["Sinal"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render_news_section(articles: list[dict], label: str):
    """Renderiza seção de notícias."""
    if not articles:
        st.info(f"Nenhuma notícia encontrada para {label}")
        return

    for article in articles:
        sentiment = article.get("sentiment", "neutral")
        if sentiment == "bullish":
            emoji = "🟢"
        elif sentiment == "bearish":
            emoji = "🔴"
        else:
            emoji = "⚪"

        with st.expander(f"{emoji} {article['title']}", expanded=False):
            st.caption(
                f"📅 {article.get('published', 'N/A')} | "
                f"📰 {article.get('source', 'N/A')}"
            )
            if article.get("summary"):
                st.write(article["summary"])
            if article.get("link"):
                st.markdown(f"[Ler notícia completa]({article['link']})")


def render_sentiment_gauge(sentiment: dict, label: str):
    """Renderiza gauge de sentimento."""
    score = sentiment.get("score", 0)
    bullish = sentiment.get("bullish", 0)
    bearish = sentiment.get("bearish", 0)
    neutral = sentiment.get("neutral", 0)

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        domain=dict(x=[0, 1], y=[0, 1]),
        title=dict(text=f"Sentimento {label}"),
        gauge=dict(
            axis=dict(range=[-100, 100]),
            bar=dict(color="darkblue"),
            steps=[
                dict(range=[-100, -30], color="#f8d7da"),
                dict(range=[-30, 30], color="#fff3cd"),
                dict(range=[30, 100], color="#d4edda"),
            ],
            threshold=dict(
                line=dict(color="black", width=2),
                thickness=0.75,
                value=score,
            ),
        ),
    ))
    fig.update_layout(height=250, margin=dict(t=50, b=0, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True)

    cols = st.columns(3)
    cols[0].metric("Alta 🟢", bullish)
    cols[1].metric("Neutra ⚪", neutral)
    cols[2].metric("Baixa 🔴", bearish)


def run_dashboard():
    """Função principal do dashboard."""
    setup_page()

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configurações")
        if st.button("🔄 Atualizar Dados", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.divider()
        st.markdown("""
        **Fontes de dados:**
        - Preços: Yahoo Finance (Futuros ICE)
        - Notícias: Google News RSS
        - Análise: Sentimento + Técnica

        **Indicadores técnicos:**
        - SMA 20 / SMA 50
        - MACD
        - RSI (14)
        - Bollinger Bands

        **Disclaimer:**
        Este dashboard é apenas para fins
        informativos. Não constitui conselho
        financeiro ou recomendação de
        investimento.
        """)

    # Carregar dados
    with st.spinner("Carregando dados do mercado..."):
        arabica_price = get_current_price("arabica")
        robusta_price = get_current_price("robusta")
        arabica_hist = fetch_coffee_futures("arabica")
        robusta_hist = fetch_coffee_futures("robusta")
        arabica_tech = calculate_technical_indicators(arabica_hist)
        robusta_tech = calculate_technical_indicators(robusta_hist)

    with st.spinner("Buscando notícias..."):
        news = get_all_coffee_news()

    # Análise
    arabica_sentiment = analyze_sentiment(news.get("arabica", []))
    robusta_sentiment = analyze_sentiment(news.get("robusta", []))
    arabica_technicals = analyze_technicals(arabica_tech)
    robusta_technicals = analyze_technicals(robusta_tech)
    arabica_rec = generate_recommendation(arabica_sentiment, arabica_technicals, arabica_price)
    robusta_rec = generate_recommendation(robusta_sentiment, robusta_technicals, robusta_price)

    # === PAINEL DE PREÇOS ===
    st.header("📊 Preços Atuais")
    col1, col2 = st.columns(2)
    with col1:
        render_price_card("arabica", "Café Arábica (KC)", arabica_price)
    with col2:
        render_price_card("robusta", "Café Robusta (RC)", robusta_price)

    st.divider()

    # === RECOMENDAÇÕES ===
    st.header("🎯 Posição Recomendada")
    col1, col2 = st.columns(2)
    with col1:
        render_recommendation(arabica_rec, "Arábica")
    with col2:
        render_recommendation(robusta_rec, "Robusta")

    st.divider()

    # === TABS PARA CADA CAFÉ ===
    tab_arabica, tab_robusta, tab_news = st.tabs([
        "☕ Arábica", "☕ Robusta (Conilon)", "📰 Notícias"
    ])

    with tab_arabica:
        st.subheader("Análise Técnica - Arábica")
        render_price_chart(arabica_tech, "Arábica")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Sinais Técnicos")
            render_signals_table(arabica_technicals.get("signals", []))
        with col2:
            st.subheader("Sentimento de Mercado")
            render_sentiment_gauge(arabica_sentiment, "Arábica")

    with tab_robusta:
        st.subheader("Análise Técnica - Robusta (Conilon)")
        render_price_chart(robusta_tech, "Robusta")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Sinais Técnicos")
            render_signals_table(robusta_technicals.get("signals", []))
        with col2:
            st.subheader("Sentimento de Mercado")
            render_sentiment_gauge(robusta_sentiment, "Robusta")

    with tab_news:
        st.subheader("📰 Notícias do Mercado de Café")

        col1, col2 = st.columns(2)
        with col1:
            st.write("### Arábica")
            render_news_section(
                arabica_sentiment.get("articles", news.get("arabica", [])),
                "Arábica",
            )
        with col2:
            st.write("### Robusta / Conilon")
            render_news_section(
                robusta_sentiment.get("articles", news.get("robusta", [])),
                "Robusta",
            )

        st.divider()
        st.write("### Mercado Geral")
        render_news_section(news.get("geral", []), "Mercado Geral")
