"""Gera dashboard como HTML estático auto-contido com todos os indicadores."""

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
from src.macro_data import (
    fetch_usdbrl,
    get_usdbrl_current,
    calculate_spread,
    fetch_all_weather,
    fetch_ice_stocks_news,
    fetch_cot_news,
    get_current_season_context,
    fetch_correlated_commodities,
    fetch_fertilizer_prices,
    analyze_fertilizer_impact,
    fetch_fertilizer_news,
    fetch_brazilian_physical_prices,
    CROP_CALENDAR,
    COFFEE_FERTILIZATION,
)

PLOTLY_THEME = dict(
    template="plotly_dark",
    paper_bgcolor="#1a1a2e",
    plot_bgcolor="#16213e",
)


# ──────────────────────────────────────────────────────────────────
# Gráficos Plotly → HTML fragment
# ──────────────────────────────────────────────────────────────────

def _chart(fig, height=500):
    fig.update_layout(height=height, **PLOTLY_THEME,
                      margin=dict(l=50, r=20, t=60, b=30))
    return fig.to_html(full_html=False, include_plotlyjs=False)


def build_price_chart(tech_df: pd.DataFrame, label: str) -> str:
    if tech_df.empty:
        return "<p class='muted'>Dados historicos indisponiveis</p>"
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05, row_heights=[.55, .25, .20],
                        subplot_titles=(f"Preco {label}", "MACD", "RSI"))
    if all(c in tech_df.columns for c in ["Open","High","Low","Close"]):
        fig.add_trace(go.Candlestick(x=tech_df["Date"], open=tech_df["Open"],
            high=tech_df["High"], low=tech_df["Low"], close=tech_df["Close"],
            name="Preco"), row=1, col=1)
    for col, color, name in [("SMA_20","orange","SMA 20"),("SMA_50","#4fc3f7","SMA 50")]:
        if col in tech_df.columns:
            fig.add_trace(go.Scatter(x=tech_df["Date"], y=tech_df[col],
                name=name, line=dict(color=color, width=1)), row=1, col=1)
    if "BB_Upper" in tech_df.columns:
        fig.add_trace(go.Scatter(x=tech_df["Date"], y=tech_df["BB_Upper"],
            name="BB Sup", line=dict(color="gray", width=.5, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=tech_df["Date"], y=tech_df["BB_Lower"],
            name="BB Inf", line=dict(color="gray", width=.5, dash="dot"),
            fill="tonexty", fillcolor="rgba(128,128,128,0.1)"), row=1, col=1)
    if "MACD" in tech_df.columns:
        clrs = ["#26a69a" if v>=0 else "#ef5350" for v in tech_df["MACD_Hist"].fillna(0)]
        fig.add_trace(go.Bar(x=tech_df["Date"], y=tech_df["MACD_Hist"],
            name="MACD Hist", marker_color=clrs), row=2, col=1)
        fig.add_trace(go.Scatter(x=tech_df["Date"], y=tech_df["MACD"],
            name="MACD", line=dict(color="blue", width=1)), row=2, col=1)
        fig.add_trace(go.Scatter(x=tech_df["Date"], y=tech_df["MACD_Signal"],
            name="Sinal", line=dict(color="red", width=1)), row=2, col=1)
    if "RSI" in tech_df.columns:
        fig.add_trace(go.Scatter(x=tech_df["Date"], y=tech_df["RSI"],
            name="RSI", line=dict(color="purple", width=1)), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)
    fig.update_layout(xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return _chart(fig, 650)


def build_gauge(value, title, lo=-100, hi=100):
    fig = go.Figure(go.Indicator(mode="gauge+number", value=value,
        title=dict(text=title, font=dict(color="white")),
        number=dict(font=dict(color="white")),
        gauge=dict(axis=dict(range=[lo, hi], tickfont=dict(color="white")),
            bar=dict(color="#4fc3f7"), bgcolor="#16213e",
            steps=[dict(range=[lo, lo+(hi-lo)*0.35], color="#ef5350"),
                   dict(range=[lo+(hi-lo)*0.35, lo+(hi-lo)*0.65], color="#ffa726"),
                   dict(range=[lo+(hi-lo)*0.65, hi], color="#26a69a")])))
    return _chart(fig, 260)


def build_usdbrl_chart(df: pd.DataFrame) -> str:
    if df.empty:
        return "<p class='muted'>Dados USD/BRL indisponiveis</p>"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Date"], y=df["Close"],
        name="USD/BRL", line=dict(color="#ffa726", width=2), fill="tozeroy",
        fillcolor="rgba(255,167,38,0.1)"))
    fig.update_layout(title="Dolar (USD/BRL)", showlegend=False,
        yaxis_title="R$")
    return _chart(fig, 350)


def build_weather_chart(weather: dict) -> str:
    if not weather:
        return "<p class='muted'>Dados climaticos indisponiveis</p>"
    # Pick a key region to chart
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Precipitacao 7d (mm)", "Temperatura 7d (C)"))
    colors = ["#4fc3f7", "#26a69a", "#ffa726", "#ef5350", "#ab47bc", "#78909c"]
    for i, (region, data) in enumerate(weather.items()):
        if not data or not data.get("daily_dates"):
            continue
        c = colors[i % len(colors)]
        fig.add_trace(go.Bar(x=data["daily_dates"], y=data["daily_precip"],
            name=region.split("(")[0].strip(), marker_color=c, opacity=0.7), row=1, col=1)
        fig.add_trace(go.Scatter(x=data["daily_dates"], y=data["daily_max"],
            name=region.split("(")[0].strip(), line=dict(color=c, width=1),
            showlegend=False), row=1, col=2)
    fig.update_layout(barmode="group", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1))
    return _chart(fig, 380)


def build_breakdown_chart(breakdown: dict, label: str) -> str:
    names = list(breakdown.keys())
    values = list(breakdown.values())
    colors = ["#26a69a" if v >= 0 else "#ef5350" for v in values]
    fig = go.Figure(go.Bar(x=values, y=names, orientation="h",
        marker_color=colors, text=[f"{v:+.2f}" for v in values], textposition="auto"))
    fig.update_layout(title=f"Breakdown — {label}", xaxis=dict(range=[-1, 1]),
        yaxis=dict(autorange="reversed"))
    return _chart(fig, 300)


def build_season_chart(season: dict) -> str:
    """Gera gráfico de Gantt simplificado do calendário de safra."""
    cal = season.get("calendar", CROP_CALENDAR)
    month_now = season.get("month", datetime.now().month)
    months = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]

    fig = go.Figure()
    countries = list(cal.keys())
    for i, (country, info) in enumerate(cal.items()):
        harvest_months = info["meses_colheita"]
        for m in harvest_months:
            fig.add_trace(go.Bar(x=[1], y=[country], orientation="h",
                base=[m - 1], marker_color="#26a69a" if m != month_now else "#ffa726",
                showlegend=False, hovertext=f"{country}: colheita em {months[m-1]}"))
    # Mark current month
    fig.add_vline(x=month_now - 0.5, line_dash="dash", line_color="#ef5350", line_width=2)
    fig.update_layout(
        title="Calendario de Safra (verde = colheita, linha vermelha = mes atual)",
        xaxis=dict(tickmode="array", tickvals=list(range(12)),
                   ticktext=months, range=[-0.5, 11.5]),
        yaxis=dict(autorange="reversed"),
        barmode="stack", showlegend=False,
    )
    return _chart(fig, 320)


def build_fertilizer_chart(fert_data: dict) -> str:
    """Gera gráfico de barras dos preços e variações de fertilizantes."""
    if not fert_data:
        return "<p class='muted'>Dados de fertilizantes indisponiveis</p>"

    names = list(fert_data.keys())
    changes_1d = [fert_data[n].get("change_pct", 0) for n in names]
    changes_30d = [fert_data[n].get("change_30d", 0) for n in names]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=names, x=changes_1d, orientation="h", name="Variacao 1d (%)",
        marker_color=["#26a69a" if v >= 0 else "#ef5350" for v in changes_1d],
        text=[f"{v:+.1f}%" for v in changes_1d], textposition="auto",
    ))
    fig.add_trace(go.Bar(
        y=names, x=changes_30d, orientation="h", name="Variacao 30d (%)",
        marker_color=["#4fc3f7" if v >= 0 else "#ffa726" for v in changes_30d],
        text=[f"{v:+.1f}%" for v in changes_30d], textposition="auto",
        opacity=0.7,
    ))
    fig.update_layout(
        title="Fertilizantes — Variacao de Preco",
        barmode="group", yaxis=dict(autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return _chart(fig, 350)


# ──────────────────────────────────────────────────────────────────
# HTML helpers
# ──────────────────────────────────────────────────────────────────

def _price_card(label, info):
    if not info:
        return f'<div class="card center"><h3>{label}</h3><p class="muted">Dados indisponiveis</p></div>'
    p = info.get("price", 0)
    ch = info.get("change", 0)
    pct = info.get("change_pct", 0)
    cur = info.get("currency", "USD")
    color = "#26a69a" if ch >= 0 else "#ef5350"
    arrow = "&#9650;" if ch >= 0 else "&#9660;"
    return f'''<div class="card center">
        <h3>{label}</h3>
        <div class="big-num">{cur} {p:,.2f}</div>
        <div style="color:{color}; font-size:1.2em; font-weight:600">
            {arrow} {abs(ch):,.2f} ({abs(pct):.2f}%)</div>
        <div class="row muted" style="justify-content:space-between; margin-top:12px">
            <span>Min 52s: {info.get("low_52w","N/A")}</span>
            <span>Max 52s: {info.get("high_52w","N/A")}</span></div></div>'''


def _rec_card(label, rec):
    pos = rec.get("position", "NEUTRO")
    bg = {"COMPRA": "#1b5e20", "VENDA": "#b71c1c"}.get(pos, "#e65100")
    bar_pct = (rec.get("combined_score", 0) + 1) / 2 * 100
    factors = "".join(f"<li>{f}</li>" for f in rec.get("factors", []))
    return f'''<div class="card" style="border-left:4px solid {bg}">
        <div class="row" style="align-items:center; gap:12px; margin-bottom:12px">
            <span style="font-size:2em">{rec.get("icon","")}</span>
            <span style="font-size:1.2em; color:#ccc">{label}</span></div>
        <div style="display:inline-block; padding:8px 24px; border-radius:8px;
            font-size:1.5em; font-weight:700; color:#fff; background:{bg}; margin-bottom:12px">{pos}</div>
        <div class="row muted" style="gap:24px; margin-bottom:8px">
            <span>Direcao: <strong style="color:#fff">{rec.get("direction","")}</strong></span>
            <span>Confianca: <strong style="color:#fff">{rec.get("confidence",0):.0f}%</strong></span></div>
        <div class="bar-bg"><div class="bar-fill" style="width:{bar_pct:.0f}%"></div></div>
        <div class="muted small">Score combinado: {rec.get("combined_score",0):.3f}</div>
        {'<ul class="factors">' + factors + '</ul>' if factors else ''}</div>'''


def _signals_table(signals):
    if not signals:
        return "<p class='muted'>Sinais indisponiveis</p>"
    rows = ""
    for ind, sinal, desc in signals:
        cls = {"ALTA": "bull", "BAIXA": "bear"}.get(sinal, "neut")
        rows += f'<tr><td>{ind}</td><td class="sg-{cls}">{sinal}</td><td>{desc}</td></tr>'
    return f'''<table class="tbl">
        <thead><tr><th>Indicador</th><th>Sinal</th><th>Descricao</th></tr></thead>
        <tbody>{rows}</tbody></table>'''


def _news_list(articles, label):
    if not articles:
        return f"<p class='muted'>Nenhuma noticia para {label}</p>"
    items = ""
    for a in articles:
        dot = {"bullish":"🟢","bearish":"🔴"}.get(a.get("sentiment",""), "⚪")
        items += f'''<div class="news-item">
            <div class="news-title">{dot} <a href="{a.get("link","#")}" target="_blank">{a.get("title","")}</a></div>
            <div class="muted small">{a.get("published","N/A")} &middot; {a.get("source","")}</div>
            <div class="muted small">{a.get("summary","")[:200]}</div></div>'''
    return items


def _weather_cards(weather: dict) -> str:
    if not weather:
        return "<p class='muted'>Dados climaticos indisponiveis</p>"
    cards = ""
    for region, data in weather.items():
        if not data:
            continue
        alerts_html = ""
        for alert in data.get("alerts", []):
            alerts_html += f'<div class="alert">{alert}</div>'
        cards += f'''<div class="card small-card">
            <h4>{region}</h4>
            <div class="row" style="gap:16px; flex-wrap:wrap">
                <span>🌡️ {data.get("temp",0):.1f}°C</span>
                <span>💧 {data.get("humidity",0)}%</span>
                <span>🌧️ 7d: {data.get("precip_7d",0):.0f}mm</span>
                <span>📊 {data.get("temp_min_7d",0):.0f}–{data.get("temp_max_7d",0):.0f}°C</span>
            </div>
            {alerts_html}</div>'''
    return cards


def _commodity_row(commodities: dict) -> str:
    if not commodities:
        return ""
    items = ""
    for name, info in commodities.items():
        p = info.get("price", 0)
        pct = info.get("change_pct", 0)
        color = "#26a69a" if pct >= 0 else "#ef5350"
        arrow = "&#9650;" if pct >= 0 else "&#9660;"
        items += f'''<div class="mini-card">
            <div class="muted small">{name}</div>
            <div style="font-size:1.1em; font-weight:600">{p:,.2f}</div>
            <div style="color:{color}; font-size:0.85em">{arrow} {abs(pct):.2f}%</div></div>'''
    return f'<div class="row" style="gap:12px; flex-wrap:wrap">{items}</div>'


def _spread_card(spread: dict, spread_brl: dict | None = None) -> str:
    if not spread:
        return "<p class='muted'>Spread indisponivel</p>"
    brl_row = ""
    if spread_brl:
        brl_row = f'''<div class="row" style="gap:24px; margin:12px 0; padding:12px; background:#16213e; border-radius:8px">
            <div><div class="muted small">Arabica (R$/saca)</div><div class="med-num" style="color:#26a69a">R$ {spread_brl.get("arabica_brl_saca",0):,.2f}</div></div>
            <div><div class="muted small">Robusta (R$/saca)</div><div class="med-num" style="color:#ffa726">R$ {spread_brl.get("robusta_brl_saca",0):,.2f}</div></div>
            <div><div class="muted small">Spread (R$/saca)</div><div class="med-num">R$ {spread_brl.get("spread_brl_saca",0):,.2f}</div></div>
        </div>'''
    return f'''<div class="card">
        <h4>Spread Arabica / Robusta</h4>
        {brl_row}
        <div class="row" style="gap:24px; margin:12px 0">
            <div><div class="muted small">Arabica (USD/lb)</div><div class="med-num">{spread.get("arabica_usd_lb",0):.4f}</div></div>
            <div><div class="muted small">Robusta (USD/lb)</div><div class="med-num">{spread.get("robusta_usd_lb",0):.4f}</div></div>
            <div><div class="muted small">Spread (USD/lb)</div><div class="med-num">{spread.get("spread_usd_lb",0):.4f}</div></div>
            <div><div class="muted small">Ratio</div><div class="med-num">{spread.get("ratio",0):.2f}x</div></div>
        </div>
        <div class="muted">{spread.get("signal","")}</div></div>'''


def _season_card(season: dict) -> str:
    pressure = season.get("pressure", "NEUTRA")
    detail = season.get("pressure_detail", "")
    harvesting = ", ".join(season.get("harvesting", [])) or "Nenhum"
    bg = "#1b5e20" if "ALTISTA" in pressure else "#b71c1c" if "BAIXISTA" in pressure else "#e65100"
    return f'''<div class="card" style="border-left:4px solid {bg}">
        <h4>Pressao Sazonal: <span style="color:{bg}">{pressure}</span></h4>
        <div class="muted" style="margin:8px 0">{detail}</div>
        <div class="muted small">Em colheita agora: {harvesting}</div></div>'''


def _ice_cot_card(ice: dict, cot: dict) -> str:
    ice_trend = ice.get("trend", "indefinido") if ice else "indefinido"
    cot_pos = cot.get("position", "indefinido") if cot else "indefinido"
    ice_color = {"queda": "#26a69a", "alta": "#ef5350"}.get(ice_trend, "#ffa726")
    cot_color = "#26a69a" if "comprado" in cot_pos else "#ef5350" if "vendido" in cot_pos else "#ffa726"

    ice_news = ""
    for a in (ice or {}).get("articles", [])[:3]:
        ice_news += f'<div class="news-item"><div class="news-title"><a href="{a.get("link","#")}" target="_blank">{a.get("title","")}</a></div><div class="muted small">{a.get("published","")}</div></div>'

    cot_news = ""
    for a in (cot or {}).get("articles", [])[:3]:
        cot_news += f'<div class="news-item"><div class="news-title"><a href="{a.get("link","#")}" target="_blank">{a.get("title","")}</a></div><div class="muted small">{a.get("published","")}</div></div>'

    return f'''<div class="grid-2">
        <div class="card">
            <h4>Estoques Certificados ICE</h4>
            <div style="font-size:1.2em; font-weight:600; color:{ice_color}; margin:8px 0">
                Tendencia: {ice_trend.upper()}</div>
            {ice_news}
        </div>
        <div class="card">
            <h4>Posicao de Fundos (COT)</h4>
            <div style="font-size:1.2em; font-weight:600; color:{cot_color}; margin:8px 0">
                {cot_pos.upper()}</div>
            {cot_news}
        </div></div>'''


def _physical_prices_section(phys: dict) -> str:
    """Gera seção de preços do mercado físico brasileiro (CEPEA + praças)."""
    if not phys:
        return "<p class='muted'>Dados do mercado fisico indisponiveis</p>"

    # CEPEA indicators
    cepea_cards = ""
    arabica_cepea = phys.get("arabica_cepea")
    robusta_cepea = phys.get("robusta_cepea")

    for label, data, color in [
        ("Arabica — CEPEA/Esalq", arabica_cepea, "#26a69a"),
        ("Robusta/Conilon — CEPEA/Esalq", robusta_cepea, "#ffa726"),
    ]:
        if data:
            var_text = data.get("variation", "")
            var_num = 0.0
            try:
                var_num = float(var_text.replace(",", ".").replace("%", "").strip())
            except (ValueError, AttributeError):
                pass
            var_color = "#26a69a" if var_num >= 0 else "#ef5350"
            arrow = "&#9650;" if var_num >= 0 else "&#9660;"
            cepea_cards += f'''<div class="card center">
                <h3>{label}</h3>
                <div class="muted small">Referencia oficial — {data.get("date","")}</div>
                <div class="big-num" style="color:{color}">R$ {data.get("price",0):,.2f}</div>
                <div class="muted small">por saca de 60kg</div>
                <div style="color:{var_color}; font-size:1.1em; font-weight:600; margin-top:8px">
                    {arrow} {var_text}</div></div>'''
        else:
            cepea_cards += f'''<div class="card center">
                <h3>{label}</h3>
                <p class="muted">Indisponivel</p></div>'''

    # Physical market prices by city (praças)
    arabica_fisico = phys.get("arabica_fisico", [])
    conilon_fisico = phys.get("conilon_fisico", [])

    def _pracas_table(rows, title):
        if not rows:
            return f"<p class='muted'>{title}: sem dados</p>"
        trs = ""
        for r in rows[:10]:
            var = r.get("variation", "")
            try:
                vn = float(var.replace(",", ".").replace("%", "").strip())
                vc = "#26a69a" if vn >= 0 else "#ef5350"
            except (ValueError, AttributeError):
                vc = "#888"
            trs += f'<tr><td>{r.get("city", r.get("type",""))}</td><td style="font-weight:600">R$ {r.get("price",0):,.2f}</td><td style="color:{vc}">{var}</td></tr>'
        return f'''<div class="card">
            <h4>{title}</h4>
            <table class="tbl">
                <thead><tr><th>Praca / Tipo</th><th>R$/saca 60kg</th><th>Variacao</th></tr></thead>
                <tbody>{trs}</tbody></table></div>'''

    pracas_html = f'''<div class="grid-2" style="margin-top:16px">
        {_pracas_table(arabica_fisico, "Mercado Fisico — Arabica Tipo 6/7")}
        {_pracas_table(conilon_fisico, "Mercado Fisico — Conilon")}
    </div>'''

    # NYBOT futures in BRL
    nybot = phys.get("nybot", [])
    nybot_html = ""
    if nybot:
        nybot_rows = ""
        for n in nybot[:5]:
            nybot_rows += f'<tr><td>{n.get("contract","")}</td><td>{n.get("usx_lb","")}</td><td style="font-weight:600">R$ {n.get("brl_saca",0):,.2f}</td><td>{n.get("variation","")}</td></tr>'
        nybot_html = f'''<div class="card" style="margin-top:16px">
            <h4>Futuros NYBOT em R$/saca</h4>
            <table class="tbl">
                <thead><tr><th>Contrato</th><th>USX/lb</th><th>R$/saca</th><th>Variacao</th></tr></thead>
                <tbody>{nybot_rows}</tbody></table></div>'''

    updated = phys.get("updated", "")
    updated_html = f'<div class="muted small" style="text-align:right; margin-top:8px">Fonte: Noticias Agricolas / CEPEA-Esalq{" — " + updated if updated else ""}</div>'

    return f'''<div class="grid-2">{cepea_cards}</div>
        {pracas_html}
        {nybot_html}
        {updated_html}'''


def _fertilizer_section(fert_data: dict, fert_impact: dict, fert_news: list) -> str:
    """Gera seção completa de fertilizantes."""
    if not fert_data:
        return "<p class='muted'>Dados de fertilizantes indisponiveis</p>"

    # Cards de preço
    cards = ""
    for name, info in fert_data.items():
        p = info.get("price", 0)
        pct = info.get("change_pct", 0)
        pct30 = info.get("change_30d", 0)
        color = "#26a69a" if pct >= 0 else "#ef5350"
        color30 = "#4fc3f7" if pct30 >= 0 else "#ffa726"
        arrow = "&#9650;" if pct >= 0 else "&#9660;"
        tipo = "&#128200;" if info.get("tipo") == "commodity" else "&#127970;"
        cards += f'''<div class="mini-card">
            <div class="muted small">{tipo} {name}</div>
            <div style="font-size:1.1em; font-weight:600">{p:,.2f}</div>
            <div style="color:{color}; font-size:.85em">{arrow} {abs(pct):.2f}% (1d)</div>
            <div style="color:{color30}; font-size:.8em">30d: {pct30:+.1f}%</div>
            <div class="muted small" style="margin-top:4px">{info.get("relevancia","")}</div></div>'''

    # Impacto
    impact_html = ""
    if fert_impact:
        trend = fert_impact.get("trend", "")
        sig = fert_impact.get("signal", "")
        t_color = "#26a69a" if "ALTA" in trend else "#ef5350" if "QUEDA" in trend else "#ffa726"
        impact_html = f'''<div class="card" style="border-left:4px solid {t_color}; margin-top:16px">
            <h4>Impacto no Cafe: <span style="color:{t_color}">{trend}</span></h4>
            <div class="muted" style="margin:8px 0">{sig}</div>
            <div class="muted small" style="margin-top:8px; padding:12px; background:#16213e; border-radius:8px">
                <strong>Contexto:</strong> {COFFEE_FERTILIZATION["custo_pct"]}<br>
                {COFFEE_FERTILIZATION["impacto"]}</div></div>'''

    # Notícias
    news_html = ""
    if fert_news:
        for a in fert_news[:5]:
            news_html += f'''<div class="news-item">
                <div class="news-title"><a href="{a.get("link","#")}" target="_blank">{a.get("title","")}</a></div>
                <div class="muted small">{a.get("published","")} &middot; {a.get("summary","")[:150]}</div></div>'''

    return f'''<div class="row" style="gap:12px; flex-wrap:wrap; margin-bottom:16px">{cards}</div>
        {impact_html}
        {f'<h4 style="margin-top:16px">Noticias de Insumos</h4>' + news_html if news_html else ''}'''


# ──────────────────────────────────────────────────────────────────
# Main generator
# ──────────────────────────────────────────────────────────────────

def generate_html_dashboard(output_path: str = "dashboard.html"):
    """Gera o dashboard completo como arquivo HTML."""

    # ── Fetch all data ──
    print("Buscando precos...")
    arabica_price = get_current_price("arabica")
    robusta_price = get_current_price("robusta")

    print("Buscando historicos...")
    arabica_hist = fetch_coffee_futures("arabica")
    arabica_tech = calculate_technical_indicators(arabica_hist)

    print("Buscando USD/BRL...")
    usdbrl = get_usdbrl_current()
    usdbrl_hist = fetch_usdbrl()

    print("Buscando noticias...")
    news = get_all_coffee_news()

    print("Buscando clima...")
    weather = fetch_all_weather()

    print("Buscando estoques ICE e COT...")
    ice_stocks = fetch_ice_stocks_news()
    cot = fetch_cot_news()

    print("Buscando commodities correlacionadas...")
    commodities = fetch_correlated_commodities()

    print("Buscando precos do mercado fisico brasileiro...")
    physical_prices = fetch_brazilian_physical_prices()

    print("Buscando fertilizantes e insumos...")
    fert_data = fetch_fertilizer_prices()
    fert_impact = analyze_fertilizer_impact(fert_data)
    fert_news = fetch_fertilizer_news()

    # ── Analyze ──
    print("Analisando...")
    arabica_sentiment = analyze_sentiment(news.get("arabica", []))
    robusta_sentiment = analyze_sentiment(news.get("robusta", []))
    arabica_technicals = analyze_technicals(arabica_tech)
    robusta_technicals = analyze_technicals(pd.DataFrame())  # sem dados historicos do robusta

    spread = calculate_spread(
        arabica_price.get("price", 0),
        robusta_price.get("price", 0),
    )
    season = get_current_season_context()

    # Coletar alertas climáticos
    all_weather_alerts = []
    for region, data in weather.items():
        all_weather_alerts.extend(data.get("alerts", []))

    arabica_rec = generate_recommendation(
        arabica_sentiment, arabica_technicals, arabica_price,
        season=season, spread=spread, weather_alerts=all_weather_alerts,
        ice_stocks=ice_stocks, cot=cot, fertilizer_impact=fert_impact,
        coffee_type="arabica",
    )
    robusta_rec = generate_recommendation(
        robusta_sentiment, robusta_technicals, robusta_price,
        season=season, spread=spread, weather_alerts=all_weather_alerts,
        ice_stocks=ice_stocks, cot=cot, fertilizer_impact=fert_impact,
        coffee_type="robusta",
    )

    # ── Build charts ──
    print("Gerando graficos...")
    usdbrl_chart = build_usdbrl_chart(usdbrl_hist)
    weather_chart = build_weather_chart(weather)
    season_chart = build_season_chart(season)
    fert_chart = build_fertilizer_chart(fert_data)
    arabica_gauge = build_gauge(arabica_sentiment.get("score", 0), "Sentimento Arabica")
    robusta_gauge = build_gauge(robusta_sentiment.get("score", 0), "Sentimento Robusta")
    arabica_breakdown = build_breakdown_chart(arabica_rec.get("breakdown", {}), "Arabica")
    robusta_breakdown = build_breakdown_chart(robusta_rec.get("breakdown", {}), "Robusta")

    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # ── Conversão para BRL/saca 60kg ──
    usd_rate = usdbrl.get("price", 5.20) or 5.20

    def to_brl_saca(price_info: dict, coffee_type: str) -> dict:
        """Converte preço para BRL por saca de 60kg."""
        p = price_info.get("price", 0)
        if not p:
            return price_info
        info = dict(price_info)
        if coffee_type == "arabica":
            # Arábica: centavos USD/lb → USD/saca (1 saca=60kg=132.277 lb) → BRL/saca
            factor = 132.277 / 100 * usd_rate
        else:
            # Robusta: USD/ton → USD/saca (1 saca=60kg → 60/1000 ton) → BRL/saca
            factor = 60 / 1000 * usd_rate
        info["price"] = round(p * factor, 2)
        info["change"] = round(info.get("change", 0) * factor, 2)
        h52 = info.get("high_52w", 0)
        l52 = info.get("low_52w", 0)
        if h52:
            info["high_52w"] = round(h52 * factor, 2)
        if l52:
            info["low_52w"] = round(l52 * factor, 2)
        info["currency"] = "R$"
        info["unit"] = "saca 60kg"
        return info

    arabica_brl = to_brl_saca(arabica_price, "arabica")
    robusta_brl = to_brl_saca(robusta_price, "robusta")

    # Converter historico Arabica para BRL/saca no grafico
    if not arabica_tech.empty and "Close" in arabica_tech.columns:
        brl_tech = arabica_tech.copy()
        brl_factor = 132.277 / 100 * usd_rate
        for col in ["Open", "High", "Low", "Close", "SMA_20", "SMA_50",
                     "EMA_12", "EMA_26", "BB_Mid", "BB_Upper", "BB_Lower"]:
            if col in brl_tech.columns:
                brl_tech[col] = brl_tech[col] * brl_factor
        # MACD e derivados também
        for col in ["MACD", "MACD_Signal", "MACD_Hist"]:
            if col in brl_tech.columns:
                brl_tech[col] = brl_tech[col] * brl_factor
        arabica_chart = build_price_chart(brl_tech, "Arabica (R$/saca 60kg)")
    else:
        arabica_chart = build_price_chart(arabica_tech, "Arabica")

    # Spread em BRL/saca
    spread_brl = None
    if spread:
        spread_brl = dict(spread)
        spread_brl["arabica_brl_saca"] = round(arabica_brl.get("price", 0), 2)
        spread_brl["robusta_brl_saca"] = round(robusta_brl.get("price", 0), 2)
        spread_brl["spread_brl_saca"] = round(
            arabica_brl.get("price", 0) - robusta_brl.get("price", 0), 2)

    # ── Compose HTML ──
    arabica_signals_html = _signals_table(arabica_technicals.get("signals", []))
    arabica_news_html = _news_list(arabica_sentiment.get("articles", []), "Arabica")
    robusta_news_html = _news_list(robusta_sentiment.get("articles", []), "Robusta")
    general_news_html = _news_list(news.get("geral", []), "Geral")
    weather_cards_html = _weather_cards(weather)
    commodity_html = _commodity_row(commodities)
    physical_html = _physical_prices_section(physical_prices)
    spread_html = _spread_card(spread, spread_brl)
    season_card_html = _season_card(season)
    ice_cot_html = _ice_cot_card(ice_stocks, cot)
    fert_section_html = _fertilizer_section(fert_data, fert_impact, fert_news)

    sent_stats = lambda s: f'''<div class="row center" style="gap:20px; padding:8px">
        <span class="bull">Alta: {s.get("bullish",0)}</span>
        <span class="neut">Neutra: {s.get("neutral",0)}</span>
        <span class="bear">Baixa: {s.get("bearish",0)}</span></div>'''

    # USD/BRL card
    usd_ch = usdbrl.get("change", 0)
    usd_color = "#26a69a" if usd_ch >= 0 else "#ef5350"
    usd_arrow = "&#9650;" if usd_ch >= 0 else "&#9660;"
    usdbrl_card = f'''<div class="card center">
        <h3>Dolar (USD/BRL)</h3>
        <div class="big-num">R$ {usdbrl.get("price",0):.4f}</div>
        <div style="color:{usd_color}; font-size:1.1em; font-weight:600">
            {usd_arrow} {abs(usd_ch):.4f} ({abs(usdbrl.get("change_pct",0)):.2f}%)</div></div>'''

    html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Mercado de Cafe</title>
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f0f23;color:#e0e0e0;line-height:1.6}}
.container{{max-width:1440px;margin:0 auto;padding:20px}}
header{{text-align:center;padding:30px 20px;background:linear-gradient(135deg,#1a1a2e,#16213e);
    border-bottom:2px solid #4fc3f7;margin-bottom:24px}}
header h1{{font-size:2em;color:#4fc3f7}}
header .sub{{color:#888;margin-top:8px;font-size:.9em}}
h2.sec{{font-size:1.4em;color:#4fc3f7;margin:32px 0 16px;padding-bottom:8px;border-bottom:1px solid #2a2a4a}}
h3{{color:#4fc3f7;margin-bottom:12px;font-size:1.1em}}
h4{{color:#4fc3f7;margin-bottom:8px}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}}
.grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:20px}}
.card{{background:#1a1a2e;border-radius:12px;padding:24px;border:1px solid #2a2a4a}}
.small-card{{padding:16px}}
.center{{text-align:center}}
.row{{display:flex;align-items:center}}
.big-num{{font-size:2.2em;font-weight:700;color:#fff}}
.med-num{{font-size:1.3em;font-weight:600;color:#fff}}
.muted{{color:#888}}.small{{font-size:.85em}}
.bull{{color:#26a69a;font-weight:600}}
.bear{{color:#ef5350;font-weight:600}}
.neut{{color:#ffa726;font-weight:600}}
.bar-bg{{height:8px;background:#2a2a4a;border-radius:4px;overflow:hidden;margin:8px 0}}
.bar-fill{{height:100%;background:linear-gradient(90deg,#ef5350,#ffa726,#26a69a);border-radius:4px}}
.factors{{margin-top:12px;padding-left:20px;color:#aaa;font-size:.9em}}
.factors li{{margin-bottom:4px}}
.tbl{{width:100%;border-collapse:collapse;margin:12px 0;background:#1a1a2e;border-radius:8px;overflow:hidden}}
.tbl th{{background:#16213e;padding:10px 14px;text-align:left;color:#4fc3f7;font-size:.9em}}
.tbl td{{padding:8px 14px;border-bottom:1px solid #2a2a4a}}
.sg-bull{{color:#26a69a;font-weight:700}}.sg-bear{{color:#ef5350;font-weight:700}}.sg-neut{{color:#ffa726;font-weight:700}}
.tabs{{display:flex;gap:4px;border-bottom:2px solid #2a2a4a;flex-wrap:wrap}}
.tab-btn{{padding:10px 22px;cursor:pointer;background:#1a1a2e;border:1px solid #2a2a4a;
    border-bottom:none;border-radius:8px 8px 0 0;color:#888;font-size:.95em;transition:all .2s}}
.tab-btn.active{{background:#16213e;color:#4fc3f7;border-color:#4fc3f7}}
.tab-btn:hover{{color:#4fc3f7}}
.tab-content{{display:none;padding:20px 0}}.tab-content.active{{display:block}}
.news-item{{background:#1a1a2e;border-radius:8px;padding:14px;margin-bottom:10px;
    border:1px solid #2a2a4a;transition:border-color .2s}}
.news-item:hover{{border-color:#4fc3f7}}
.news-title{{margin-bottom:4px}}.news-title a{{color:#e0e0e0;text-decoration:none}}
.news-title a:hover{{color:#4fc3f7}}
.news-grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
.mini-card{{background:#1a1a2e;border-radius:8px;padding:14px 18px;border:1px solid #2a2a4a;min-width:140px}}
.alert{{background:#b71c1c33;border:1px solid #ef5350;border-radius:6px;padding:8px 12px;
    margin-top:8px;font-size:.9em;color:#ef5350}}
footer{{text-align:center;padding:24px;color:#555;font-size:.8em;margin-top:40px;border-top:1px solid #2a2a4a}}
@media(max-width:768px){{
    .grid-2,.grid-3,.news-grid{{grid-template-columns:1fr}}
    .big-num{{font-size:1.6em}}header h1{{font-size:1.3em}}
    .tab-btn{{padding:8px 14px;font-size:.85em}}
}}
</style>
</head>
<body>
<header>
    <h1>&#9749; Dashboard Mercado de Cafe</h1>
    <div class="sub">Robusta (Conilon) &amp; Arabica &mdash; Atualizado em {now}</div>
</header>
<div class="container">

    <!-- PRECOS MERCADO FISICO (referencia) -->
    <h2 class="sec">&#128200; Precos do Dia — Mercado Fisico (R$/saca 60kg)</h2>
    {physical_html}

    <!-- PRECOS FUTUROS + DOLAR -->
    <h2 class="sec">&#128202; Precos Futuros (convertidos) e Cambio</h2>
    <div class="grid-3">
        {_price_card("Arabica Futuros (NYBOT) — R$/saca", arabica_brl)}
        {_price_card("Robusta Futuros (ICE) — R$/saca", robusta_brl)}
        {usdbrl_card}
    </div>

    <!-- COMMODITIES CORRELACIONADAS -->
    <h2 class="sec">&#128279; Commodities Correlacionadas</h2>
    {commodity_html}

    <!-- SPREAD -->
    <h2 class="sec">&#8646; Spread Arabica / Robusta</h2>
    {spread_html}

    <!-- RECOMENDACOES -->
    <h2 class="sec">&#127919; Posicao Recomendada</h2>
    <div class="grid-2">
        {_rec_card("Arabica", arabica_rec)}
        {_rec_card("Robusta / Conilon", robusta_rec)}
    </div>
    <div class="grid-2">
        {arabica_breakdown}
        {robusta_breakdown}
    </div>

    <!-- SAZONALIDADE -->
    <h2 class="sec">&#128197; Sazonalidade e Safra</h2>
    {season_card_html}
    {season_chart}

    <!-- ESTOQUES + COT -->
    <h2 class="sec">&#128230; Estoques ICE &amp; Posicoes de Fundos</h2>
    {ice_cot_html}

    <!-- FERTILIZANTES -->
    <h2 class="sec">&#129716; Fertilizantes e Insumos Agricolas</h2>
    {fert_section_html}
    {fert_chart}

    <!-- CLIMA -->
    <h2 class="sec">&#127782;&#65039; Clima nas Regioes Produtoras</h2>
    {weather_cards_html}
    {weather_chart}

    <!-- TABS ANALISE -->
    <h2 class="sec">&#128202; Analise Detalhada</h2>
    <div class="tabs">
        <div class="tab-btn active" onclick="switchTab('arabica')">&#9749; Arabica</div>
        <div class="tab-btn" onclick="switchTab('robusta')">&#9749; Robusta</div>
        <div class="tab-btn" onclick="switchTab('usdbrl')">&#128181; USD/BRL</div>
        <div class="tab-btn" onclick="switchTab('news')">&#128240; Noticias</div>
    </div>

    <div id="tab-arabica" class="tab-content active">
        {arabica_chart}
        <div class="grid-2">
            <div><h4>Sinais Tecnicos</h4>{arabica_signals_html}</div>
            <div><h4>Sentimento de Mercado</h4>{arabica_gauge}{sent_stats(arabica_sentiment)}</div>
        </div>
    </div>

    <div id="tab-robusta" class="tab-content">
        <div class="card center" style="padding:40px">
            <h3>Robusta — Dados de Futuros</h3>
            <p class="muted">Graficos historicos do Robusta nao estao disponiveis via fontes gratuitas.
            A analise utiliza preco atual (Barchart), noticias, clima, sazonalidade e spread.</p>
            {robusta_gauge}{sent_stats(robusta_sentiment)}
        </div>
    </div>

    <div id="tab-usdbrl" class="tab-content">
        {usdbrl_chart}
        <div class="card" style="margin-top:16px">
            <h4>Impacto do Dolar no Cafe</h4>
            <p class="muted">Dolar forte (alta) tende a pressionar precos de commodities para baixo em USD,
            mas beneficia exportadores brasileiros em BRL. Dolar fraco tem efeito inverso.</p>
        </div>
    </div>

    <div id="tab-news" class="tab-content">
        <div class="news-grid">
            <div><h3>&#9749; Noticias Arabica</h3>{arabica_news_html}</div>
            <div><h3>&#9749; Noticias Robusta / Conilon</h3>{robusta_news_html}</div>
        </div>
        <h3 style="margin-top:24px">&#127758; Mercado Geral</h3>
        {general_news_html}
    </div>

</div>

<footer>
    Este dashboard e apenas para fins informativos. Nao constitui conselho financeiro.<br>
    Fontes: CEPEA/Esalq &middot; Noticias Agricolas &middot; Yahoo Finance &middot; Barchart &middot; Google News RSS &middot; Open-Meteo &middot;
    Analise: Tecnica + Sentimento + Sazonalidade + Clima + Spread + Estoques + Fertilizantes + COT
</footer>

<script>
function switchTab(name){{
    document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    document.getElementById('tab-'+name).classList.add('active');
    const tabs=['arabica','robusta','usdbrl','news'];
    document.querySelectorAll('.tab-btn')[tabs.indexOf(name)].classList.add('active');
    window.dispatchEvent(new Event('resize'));
}}
</script>
</body>
</html>'''

    out = Path(output_path)
    out.write_text(html, encoding="utf-8")
    print(f"\nDashboard gerado: {out.resolve()}")
    return str(out.resolve())
