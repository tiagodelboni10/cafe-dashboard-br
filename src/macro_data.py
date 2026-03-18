"""Dados macroeconômicos e indicadores complementares para o mercado de café."""

import re
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# 1. Câmbio USD/BRL
# ---------------------------------------------------------------------------

def fetch_usdbrl(period_days: int = 180) -> pd.DataFrame:
    """Busca histórico USD/BRL via yfinance."""
    try:
        end = datetime.now()
        start = end - timedelta(days=period_days)
        data = yf.download(
            "USDBRL=X",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
        )
        if data.empty:
            return pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return data.reset_index()
    except Exception as e:
        print(f"Erro ao buscar USD/BRL: {e}")
        return pd.DataFrame()


def get_usdbrl_current() -> dict:
    """Retorna cotação atual do USD/BRL."""
    try:
        tk = yf.Ticker("USDBRL=X")
        hist = tk.history(period="5d")
        if hist.empty:
            return {}
        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
        change = price - prev
        change_pct = (change / prev) * 100 if prev else 0
        return {
            "price": round(price, 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 2),
        }
    except Exception as e:
        print(f"Erro USD/BRL atual: {e}")
        return {}


# ---------------------------------------------------------------------------
# 2. Spread Arábica / Robusta
# ---------------------------------------------------------------------------

def calculate_spread(arabica_price: float, robusta_price: float) -> dict:
    """Calcula o spread (diferença de preço) entre Arábica e Robusta.

    Arábica é cotado em USX/lb (centavos de dólar por libra).
    Robusta é cotado em USD/ton.
    Converte ambos para USD/lb para comparação justa.
    """
    if not arabica_price or not robusta_price:
        return {}

    # Arábica: centavos/lb -> dólares/lb
    arabica_usd_lb = arabica_price / 100

    # Robusta: USD/ton -> USD/lb (1 ton = 2204.62 lb)
    robusta_usd_lb = robusta_price / 2204.62

    spread = arabica_usd_lb - robusta_usd_lb
    ratio = arabica_usd_lb / robusta_usd_lb if robusta_usd_lb > 0 else 0

    # Ratio histórico médio fica entre 1.5 e 2.5
    if ratio > 2.5:
        spread_signal = "Arábica muito caro vs Robusta — possível pressão de queda no Arábica"
    elif ratio > 2.0:
        spread_signal = "Spread acima da média — favorece substituição por Robusta"
    elif ratio > 1.5:
        spread_signal = "Spread na faixa normal"
    elif ratio > 1.0:
        spread_signal = "Spread apertado — demanda forte por Arábica ou excesso de Robusta"
    else:
        spread_signal = "Spread invertido — situação atípica"

    return {
        "arabica_usd_lb": round(arabica_usd_lb, 4),
        "robusta_usd_lb": round(robusta_usd_lb, 4),
        "spread_usd_lb": round(spread, 4),
        "ratio": round(ratio, 2),
        "signal": spread_signal,
    }


# ---------------------------------------------------------------------------
# 3. Clima nas regiões produtoras
# ---------------------------------------------------------------------------

# Coordenadas das principais regiões produtoras
WEATHER_REGIONS = {
    "Minas Gerais (Arábica BR)": {"lat": -21.25, "lon": -44.99},
    "São Paulo (Arábica BR)": {"lat": -22.30, "lon": -47.05},
    "Espírito Santo (Conilon BR)": {"lat": -19.83, "lon": -40.30},
    "Rondônia (Conilon BR)": {"lat": -10.89, "lon": -61.95},
    "Vietnam Central Highlands": {"lat": 14.35, "lon": 108.00},
    "Colombia (Eje Cafetero)": {"lat": 4.81, "lon": -75.68},
}


def fetch_weather(lat: float, lon: float) -> dict:
    """Busca dados climáticos via Open-Meteo (API gratuita, sem chave)."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max"
            f"&timezone=auto&forecast_days=7"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()

        current = data.get("current", {})
        daily = data.get("daily", {})

        # Calcular precipitação acumulada dos próximos 7 dias
        precip_7d = sum(daily.get("precipitation_sum", []) or [0])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])

        # Alertas
        alerts = []
        if min_temps and min(min_temps) < 3:
            alerts.append("⚠️ RISCO DE GEADA — mínima prevista abaixo de 3°C")
        if min_temps and min(min_temps) < 0:
            alerts.append("🚨 GEADA SEVERA — mínima prevista abaixo de 0°C")
        if precip_7d < 5:
            alerts.append("⚠️ SECA — precipitação menor que 5mm nos próximos 7 dias")
        if precip_7d > 100:
            alerts.append("⚠️ CHUVA EXCESSIVA — acima de 100mm nos próximos 7 dias")
        if max_temps and max(max_temps) > 38:
            alerts.append("⚠️ CALOR EXTREMO — máxima acima de 38°C")

        return {
            "temp": current.get("temperature_2m", 0),
            "humidity": current.get("relative_humidity_2m", 0),
            "precip_now": current.get("precipitation", 0),
            "wind": current.get("wind_speed_10m", 0),
            "precip_7d": round(precip_7d, 1),
            "temp_max_7d": round(max(max_temps), 1) if max_temps else 0,
            "temp_min_7d": round(min(min_temps), 1) if min_temps else 0,
            "daily_precip": daily.get("precipitation_sum", []),
            "daily_dates": daily.get("time", []),
            "daily_max": max_temps,
            "daily_min": min_temps,
            "alerts": alerts,
        }
    except Exception as e:
        print(f"Erro clima ({lat},{lon}): {e}")
        return {}


def fetch_all_weather() -> dict:
    """Busca clima de todas as regiões produtoras."""
    results = {}
    for region, coords in WEATHER_REGIONS.items():
        results[region] = fetch_weather(coords["lat"], coords["lon"])
    return results


# ---------------------------------------------------------------------------
# 4. Estoques certificados ICE (via notícias/scraping)
# ---------------------------------------------------------------------------

def fetch_ice_stocks_news() -> dict:
    """Busca dados de estoques certificados ICE via Google News."""
    import feedparser

    feeds = [
        "https://news.google.com/rss/search?q=ICE+certified+coffee+stocks&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=estoques+certificados+cafe+ICE&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    ]
    articles = []
    seen = set()
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                if title.lower() not in seen:
                    seen.add(title.lower())
                    published = ""
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                    articles.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "published": published,
                        "summary": BeautifulSoup(
                            entry.get("summary", ""), "html.parser"
                        ).get_text()[:200],
                    })
        except Exception:
            pass

    # Análise simples de tendência dos estoques
    trend = "indefinido"
    for a in articles:
        text = (a.get("title", "") + " " + a.get("summary", "")).lower()
        if any(w in text for w in ["drop", "fell", "decline", "queda", "caiu", "lower", "decrease"]):
            trend = "queda"
            break
        if any(w in text for w in ["rise", "rose", "increase", "alta", "subiu", "higher", "grew"]):
            trend = "alta"
            break

    return {
        "articles": articles[:5],
        "trend": trend,
    }


# ---------------------------------------------------------------------------
# 5. COT Report — Posições de fundos (via notícias/scraping)
# ---------------------------------------------------------------------------

def fetch_cot_news() -> dict:
    """Busca notícias sobre posições de fundos no mercado de café."""
    import feedparser

    feeds = [
        "https://news.google.com/rss/search?q=coffee+futures+speculative+positions+CFTC&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=coffee+COT+report+funds&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=cafe+futuros+posicoes+fundos&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    ]
    articles = []
    seen = set()
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                if title.lower() not in seen:
                    seen.add(title.lower())
                    published = ""
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                    articles.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "published": published,
                        "summary": BeautifulSoup(
                            entry.get("summary", ""), "html.parser"
                        ).get_text()[:200],
                    })
        except Exception:
            pass

    # Análise de posição dos fundos
    position = "indefinido"
    for a in articles:
        text = (a.get("title", "") + " " + a.get("summary", "")).lower()
        if any(w in text for w in ["net long", "buying", "comprados", "increased long", "bullish position"]):
            position = "comprado (net long)"
            break
        if any(w in text for w in ["net short", "selling", "vendidos", "increased short", "bearish position"]):
            position = "vendido (net short)"
            break

    return {
        "articles": articles[:5],
        "position": position,
    }


# ---------------------------------------------------------------------------
# 6. Calendário de safra / Sazonalidade
# ---------------------------------------------------------------------------

CROP_CALENDAR = {
    "Brasil (Arábica)": {
        "colheita": "Mai–Set",
        "florada": "Set–Nov",
        "maturação": "Jan–Abr",
        "meses_colheita": [5, 6, 7, 8, 9],
        "impacto": "Maior produtor mundial. Safra entra = pressão vendedora.",
    },
    "Brasil (Conilon)": {
        "colheita": "Abr–Ago",
        "florada": "Ago–Out",
        "maturação": "Dez–Mar",
        "meses_colheita": [4, 5, 6, 7, 8],
        "impacto": "Maior produtor de Robusta. Safra forte no ES e RO.",
    },
    "Vietnam": {
        "colheita": "Nov–Mar",
        "florada": "Mar–Mai",
        "maturação": "Jun–Out",
        "meses_colheita": [11, 12, 1, 2, 3],
        "impacto": "2º maior produtor (Robusta). Safra na entressafra do Brasil.",
    },
    "Colômbia": {
        "colheita": "Out–Fev / Abr–Jun",
        "florada": "Mar / Ago",
        "maturação": "Jun–Set / Dez–Mar",
        "meses_colheita": [10, 11, 12, 1, 2, 4, 5, 6],
        "impacto": "3º em Arábica. Duas safras por ano = oferta mais estável.",
    },
    "Indonésia": {
        "colheita": "Jun–Set",
        "florada": "Mar–Mai",
        "maturação": "Set–Mai",
        "meses_colheita": [6, 7, 8, 9],
        "impacto": "Robusta de Sumatra. Safra pode afetar preço do Robusta.",
    },
    "Etiópia": {
        "colheita": "Out–Dez",
        "florada": "Abr–Jun",
        "maturação": "Jul–Set",
        "meses_colheita": [10, 11, 12],
        "impacto": "Berço do café. Arábicas especiais e exóticos.",
    },
}


def get_current_season_context() -> dict:
    """Retorna contexto sazonal atual com base no mês."""
    month = datetime.now().month
    month_name = [
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez",
    ][month - 1]

    harvesting = []
    not_harvesting = []
    for country, info in CROP_CALENDAR.items():
        if month in info["meses_colheita"]:
            harvesting.append(country)
        else:
            not_harvesting.append(country)

    # Pressão sazonal
    br_arabica_harvest = month in CROP_CALENDAR["Brasil (Arábica)"]["meses_colheita"]
    br_conilon_harvest = month in CROP_CALENDAR["Brasil (Conilon)"]["meses_colheita"]
    vietnam_harvest = month in CROP_CALENDAR["Vietnam"]["meses_colheita"]

    pressure = "NEUTRA"
    pressure_detail = ""
    if br_arabica_harvest and br_conilon_harvest:
        pressure = "BAIXISTA"
        pressure_detail = "Brasil em plena colheita de Arábica e Conilon — forte pressão de oferta"
    elif br_arabica_harvest:
        pressure = "BAIXISTA (Arábica)"
        pressure_detail = "Safra brasileira de Arábica — pressão vendedora sobre KC"
    elif br_conilon_harvest:
        pressure = "BAIXISTA (Robusta)"
        pressure_detail = "Safra de Conilon no Brasil — pressão vendedora sobre Robusta"
    elif vietnam_harvest:
        pressure = "BAIXISTA (Robusta)"
        pressure_detail = "Safra do Vietnam entrando — oferta de Robusta aumenta"
    else:
        pressure = "ALTISTA"
        pressure_detail = "Entressafra nos principais produtores — oferta mais restrita"

    return {
        "month": month,
        "month_name": month_name,
        "harvesting": harvesting,
        "not_harvesting": not_harvesting,
        "pressure": pressure,
        "pressure_detail": pressure_detail,
        "calendar": CROP_CALENDAR,
    }


# ---------------------------------------------------------------------------
# 7. Commodities correlacionadas
# ---------------------------------------------------------------------------

def fetch_correlated_commodities() -> dict:
    """Busca preços de commodities correlacionadas ao café."""
    tickers = {
        "Petróleo (WTI)": "CL=F",
        "Açúcar": "SB=F",
        "Cacau": "CC=F",
        "DXY (Índice Dólar)": "DX-Y.NYB",
    }
    results = {}
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty:
                continue
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            change_pct = ((price - prev) / prev) * 100 if prev else 0
            results[name] = {
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
            }
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# 8. Fertilizantes e insumos agrícolas
# ---------------------------------------------------------------------------

# Tickers: empresas líderes de fertilizantes + gás natural (matéria-prima da uréia)
FERTILIZER_TICKERS = {
    "Gás Natural (uréia)": {"ticker": "NG=F", "tipo": "commodity",
        "relevancia": "Matéria-prima para produção de uréia (N). Alta no gás = adubo mais caro."},
    "Mosaic (P+K)": {"ticker": "MOS", "tipo": "acao",
        "relevancia": "Maior produtora de fosfato e potássio. Proxy de preço de MAP/DAP/KCl."},
    "Nutrien (NPK)": {"ticker": "NTR", "tipo": "acao",
        "relevancia": "Maior empresa de fertilizantes do mundo. Produz N, P e K."},
    "CF Industries (N)": {"ticker": "CF", "tipo": "acao",
        "relevancia": "Líder em nitrogênio/uréia. Proxy para custo de adubação nitrogenada."},
    "ICL Group (K+P)": {"ticker": "ICL", "tipo": "acao",
        "relevancia": "Produtora de potássio e fosfato especializado."},
    "Intrepid Potash (K)": {"ticker": "IPI", "tipo": "acao",
        "relevancia": "Produtora de potássio (KCl). Potássio é crítico para qualidade do café."},
}

# Adubação típica do café (kg/ha/ano) — para contextualização
COFFEE_FERTILIZATION = {
    "info": "O café é uma cultura exigente em nutrientes. Uma lavoura adulta de arábica "
            "consome em média 300-450 kg/ha de N, 60-100 kg/ha de P2O5 e 200-350 kg/ha de K2O por ano.",
    "npk_ratio": "A formulação mais comum para café é 20-05-20, aplicada em 3-4 parcelas.",
    "custo_pct": "Fertilizantes representam 25-35% do custo total de produção do café.",
    "impacto": "Alta no preço de fertilizantes pressiona o custo de produção, "
               "o que pode sustentar preços do café (produtor repassa custo) "
               "ou reduzir a adubação (menos produtividade na safra seguinte = menos oferta).",
}


# ---------------------------------------------------------------------------
# Conhecimento — Guia do Cafeicultor
# ---------------------------------------------------------------------------

COFFEE_KNOWLEDGE = {
    "umidade_solo": {
        "title": "Umidade Ideal do Solo",
        "intro": "A capacidade de campo (CC) e o principal parametro para manejo de irrigacao. "
                 "O monitoramento com tensiometros e fundamental para evitar estresse hidrico ou encharcamento.",
        "arabica": {
            "faixa_ideal": "60–70% da capacidade de campo",
            "ponto_murcha": "Abaixo de 40% CC causa estresse hidrico severo",
            "excesso": "Acima de 80% CC favorece fungos (cercospora, ferrugem) e asfixia radicular",
            "fases": [
                ("Florada", "70–80% CC", "Fase critica — deficit causa abortamento floral"),
                ("Enchimento de grao", "60–70% CC", "Necessidade moderada a alta"),
                ("Maturacao", "50–60% CC", "Leve estresse favorece maturacao uniforme"),
                ("Pos-colheita / Vegetativo", "60–70% CC", "Recuperacao da planta e preparacao para florada"),
            ],
        },
        "conilon": {
            "faixa_ideal": "65–75% da capacidade de campo",
            "nota": "Conilon e mais tolerante a seca que Arabica mas responde muito bem a irrigacao",
            "fases": [
                ("Florada", "75–85% CC", "Uniformidade de florada depende de estresse hidrico previo controlado"),
                ("Enchimento de grao", "65–75% CC", "Fase de maior demanda hidrica"),
                ("Maturacao", "55–65% CC", "Reducao gradual favorece qualidade"),
            ],
        },
    },
    "adubacao": {
        "title": "Guia de Adubacao e Fertilizacao",
        "calagem": "Manter pH entre 5.5 e 6.5. Aplicar calcario dolomitico 60–90 dias antes do plantio. "
                   "Quantidade tipica: 2–4 ton/ha, conforme analise de solo.",
        "macronutrientes": [
            ("Nitrogenio (N)", "300–450 kg/ha/ano", "Parcelado em 3–4 aplicacoes (Out–Mar). Essencial para crescimento vegetativo e producao."),
            ("Fosforo (P2O5)", "60–100 kg/ha/ano", "Aplicar no sulco de plantio e em cobertura anual. Fundamental para enraizamento."),
            ("Potassio (K2O)", "200–350 kg/ha/ano", "Parcelado junto com N. Essencial para qualidade do grao e resistencia a seca."),
        ],
        "micronutrientes": [
            ("Boro (B)", "Aplicacao foliar: 0.3–0.5% acido borico", "Critico para florada e frutificacao"),
            ("Zinco (Zn)", "Sulfato de zinco 0.3–0.5% foliar", "Essencial para crescimento de ramos novos"),
            ("Manganes (Mn)", "Sulfato de manganes 0.3% foliar", "Importante em solos com pH > 6.0"),
        ],
        "organica": "Palha de cafe (3–5 ton/ha) ou esterco curtido (10–20 ton/ha) melhoram "
                    "estrutura do solo e retencao hidrica. Compostagem da casca do cafe e excelente opcao.",
        "formulacoes": [
            ("20-05-20", "Lavoura em producao — formulacao mais comum"),
            ("20-10-10", "Lavoura em formacao (ate 3 anos)"),
            ("25-00-25", "Cobertura em solos com P adequado"),
        ],
        "epoca": "Iniciar apos as primeiras chuvas (outubro). Parcelar em 3–4 vezes: Out, Dez, Fev (e Mar se necessario).",
    },
    "irrigacao": {
        "title": "Boas Praticas de Irrigacao",
        "sistemas": [
            ("Gotejamento", "90–95% eficiencia", "Ideal para terrenos declivosos. Economia de 30–40% de agua vs aspersao. Permite fertirrigacao."),
            ("Microaspersao", "80–90% eficiencia", "Boa uniformidade. Cobre mais area que gotejo. Pode auxiliar em geadas leves."),
            ("Pivo central", "75–85% eficiencia", "Para areas planas e grandes (>50ha). Menor custo por hectare em escala."),
            ("Aspersao convencional", "60–70% eficiencia", "Menor eficiencia, mais barato. Aceitavel para areas sem restricao hidrica."),
        ],
        "manejo": [
            ("Tensiometros", "Irrigar quando tensao > 40 kPa (arabica) ou 60 kPa (conilon)"),
            ("Turno de rega", "Definir pelo balanco hidrico: KC x ETo. KC varia de 0.8 (vegetativo) a 1.1 (frutificacao)"),
            ("Horario ideal", "Final da tarde ou inicio da noite para reduzir evaporacao"),
            ("Estresse controlado", "Suspender irrigacao 30–60 dias antes da florada esperada para uniformizar"),
            ("Lamina de agua", "Calcular pela evapotranspiracao da cultura (ETc) e pela capacidade de retencao do solo"),
        ],
    },
    "boas_praticas": {
        "title": "Boas Praticas de Cultivo",
        "podas": [
            ("Decote", "Corte a 1.8–2.0m de altura", "Facilita colheita e renova copa. Fazer apos a colheita."),
            ("Esqueletamento", "Corte de ramos a 30cm do tronco", "Ciclo de 4–5 anos. Estimula brotacao lateral."),
            ("Recepa", "Corte total a 30–40cm do solo", "Para lavouras improdutivas. Recuperacao em 2 safras."),
            ("Desbrota", "Eliminar brotos excessivos", "Manter 2–3 brotos por no, apos poda ou recepa."),
        ],
        "pragas_doencas": [
            ("Broca-do-cafe", "Monitorar com armadilhas. Controle biologico com Beauveria bassiana. Nivel de controle: >3% de frutos brocados."),
            ("Bicho-mineiro", "Monitorar folhas — nivel de controle: >30% de folhas minadas. Neonicotinoides sistemicos ou biologico."),
            ("Ferrugem (Hemileia)", "Fungicidas cupricos preventivos (Jun–Ago). Variedades resistentes: Obata, Catucai, Paraiso."),
            ("Cercospora", "Adubacao equilibrada em K e B reduz incidencia. Fungicidas foliares em areas com historico."),
            ("Nematoides", "Usar variedades tolerantes (Apoata como porta-enxerto). Rotacao com Crotalaria."),
        ],
        "colheita": [
            ("Ponto ideal", "70–80% dos frutos no estagio cereja. Evitar colher com menos de 50% cereja."),
            ("Metodos", "Derrica manual (qualidade), derricadeira mecanica (mista), colheitadeira automotriz (terrenos planos)."),
            ("Pos-colheita", "Secar ate 11–12% de umidade. Terreiro suspenso, secador mecanico ou secagem em leira."),
            ("Armazenamento", "Tulhas ventiladas com umidade <12%. Separar lotes por qualidade e talhao."),
        ],
        "espacamento": [
            ("Arabica convencional", "3.5–4.0m entre ruas x 0.5–1.0m entre plantas", "3.000–5.500 plantas/ha"),
            ("Arabica adensado", "2.5–3.0m x 0.5–0.7m", "5.500–8.000 plantas/ha — exige mais manejo"),
            ("Conilon", "3.0–3.5m x 1.0–1.5m", "2.000–3.500 plantas/ha"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Marketplace — Servicos e Equipamentos
# ---------------------------------------------------------------------------

MARKETPLACE_SERVICES = [
    {
        "title": "Drone de Pulverizacao",
        "category": "Pulverizacao Aerea",
        "icon": "&#128681;",
        "tag": "Servico",
        "tag_color": "#26a69a",
        "description": "Servico de pulverizacao com drone para aplicacao de defensivos "
                       "e fertilizantes foliares em lavouras de cafe. Precisao e economia.",
        "specs": [
            "Capacidade: 20–30L por voo",
            "Cobertura: 8–15 ha/dia",
            "Precisao GPS RTK centimetrica",
            "Reducao de 30–40% no uso de defensivos",
            "Sem compactacao do solo",
        ],
        "contact_label": "Solicitar orcamento",
    },
    {
        "title": "Escavadeira Hidraulica",
        "category": "Mecanizacao",
        "icon": "&#128679;",
        "tag": "Aluguel",
        "tag_color": "#ffa726",
        "description": "Locacao de escavadeira hidraulica para preparo de terreno, "
                       "abertura de curvas de nivel, terraplanagem e construcao de estradas internas.",
        "specs": [
            "Cat 320 / Komatsu PC200",
            "Disponivel por hora ou diaria",
            "Operador incluso",
            "Ideal para abertura de novas areas",
        ],
        "contact_label": "Consultar disponibilidade",
    },
    {
        "title": "Colheitadeira de Cafe",
        "category": "Colheita Mecanizada",
        "icon": "&#127811;",
        "tag": "Aluguel / Servico",
        "tag_color": "#4fc3f7",
        "description": "Colheitadeira automotriz para colheita mecanizada de cafe. "
                       "Ideal para terrenos planos e lavouras com espacamento adequado.",
        "specs": [
            "Colhedora automotriz ou tratorizada",
            "Rendimento: 30–60 sacas/hora",
            "Disponivel por diaria ou safra",
            "Assistencia tecnica inclusa",
        ],
        "contact_label": "Reservar para safra",
    },
    {
        "title": "Analise de Solo e Foliar",
        "category": "Laboratorio",
        "icon": "&#128300;",
        "tag": "Servico",
        "tag_color": "#26a69a",
        "description": "Analise completa de solo e tecido foliar com laudo e recomendacao "
                       "de adubacao personalizada para sua lavoura de cafe.",
        "specs": [
            "Analise quimica completa do solo",
            "Analise de micronutrientes",
            "Analise foliar (macro + micro)",
            "Laudo com recomendacao de adubacao",
            "Resultado em 7–10 dias uteis",
        ],
        "contact_label": "Solicitar coleta",
    },
    {
        "title": "Consultoria Agronomica",
        "category": "Consultoria",
        "icon": "&#127793;",
        "tag": "Servico",
        "tag_color": "#26a69a",
        "description": "Consultoria especializada em cafeicultura. Planejamento de safra, "
                       "manejo integrado de pragas, nutricao e irrigacao.",
        "specs": [
            "Visita tecnica mensal ou quinzenal",
            "Planejamento de safra completo",
            "Manejo integrado de pragas e doencas",
            "Recomendacao de adubacao e irrigacao",
        ],
        "contact_label": "Agendar visita",
    },
    {
        "title": "Mudas de Cafe",
        "category": "Insumos",
        "icon": "&#127807;",
        "tag": "Venda",
        "tag_color": "#ef5350",
        "description": "Mudas de cafe arabica e conilon de alta qualidade. "
                       "Variedades resistentes a ferrugem e nematoides.",
        "specs": [
            "Arabica: Obata, Catucai, Paraiso, Arara",
            "Conilon: clones recomendados Incaper",
            "Mudas de 4–6 meses (prontas para plantio)",
            "Entrega em todo ES, MG, SP e RJ",
        ],
        "contact_label": "Consultar precos",
    },
]


# ---------------------------------------------------------------------------
# 9. Preços do mercado físico brasileiro (CEPEA/Esalq + praças)
# ---------------------------------------------------------------------------

def fetch_paineldocafe() -> dict:
    """Busca preços do Painel do Café (paineldocafe.com.br) via API.

    Retorna Conilon 7/8, Arábica Rio, Dólar, Londres e N.York — preço do dia.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    result = {
        "conilon": None,
        "arabica_rio": None,
        "dolar": None,
        "londres": None,
        "nyork": None,
    }
    try:
        resp = requests.get(
            "https://api.coffee-panel.mitrix.online/api/home/information",
            headers=headers, timeout=15,
        )
        data = resp.json()

        # Values: Conilon 7/8, Arábica RIO
        for v in data.get("values", []):
            name = v.get("name", "").lower()
            val = v.get("value", 0)
            if "conilon" in name:
                result["conilon"] = {"name": v.get("name", ""), "price": round(val, 2)}
            elif "bica" in name or "rio" in name:
                result["arabica_rio"] = {"name": v.get("name", ""), "price": round(val, 2)}

        # Stocks: Dólar, Londres, N.York
        for s in data.get("stocks", []):
            name = s.get("name", "").lower()
            info = {
                "name": s.get("name", ""),
                "price": s.get("price", 0),
                "change": s.get("change", 0),
                "movement": s.get("movement", ""),
                "last_update": s.get("last_update", ""),
                "market_strip": s.get("market_strip", ""),
            }
            if "lar" in name or "usd" in name:
                result["dolar"] = info
            elif "londres" in name or "london" in name:
                result["londres"] = info
            elif "york" in name or name == "kc":
                result["nyork"] = info

    except Exception as e:
        print(f"Erro ao buscar Painel do Cafe: {e}")

    return result


def fetch_brazilian_physical_prices() -> dict:
    """Busca preços do mercado físico brasileiro via Notícias Agrícolas.

    Retorna preços CEPEA/Esalq (referência) e praças do mercado físico
    em R$/saca de 60kg — preço do dia.
    """
    import feedparser

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    result = {
        "arabica_cepea": None,
        "robusta_cepea": None,
        "arabica_fisico": [],
        "conilon_fisico": [],
        "nybot": [],
        "updated": "",
    }

    try:
        resp = requests.get(
            "https://www.noticiasagricolas.com.br/cotacoes/cafe",
            headers=headers, timeout=15,
        )
        soup = BeautifulSoup(resp.text, "html.parser")

        for div in soup.select("div.cotacao"):
            title = div.get_text()[:100]

            # ── CEPEA/Esalq Arábica ──
            if "Indicador" in title and "bica" in title and "Robusta" not in title:
                table = div.find("table")
                if table:
                    cells = [td.get_text(strip=True) for td in table.find_all("td")]
                    # cells: [date, value, variation, ...]
                    if len(cells) >= 3:
                        val = cells[1].replace(".", "").replace(",", ".")
                        try:
                            result["arabica_cepea"] = {
                                "price": float(val),
                                "variation": cells[2],
                                "date": cells[0],
                            }
                        except ValueError:
                            pass

            # ── CEPEA/Esalq Robusta ──
            elif "Indicador" in title and "Robusta" in title:
                table = div.find("table")
                if table:
                    cells = [td.get_text(strip=True) for td in table.find_all("td")]
                    if len(cells) >= 3:
                        val = cells[1].replace(".", "").replace(",", ".")
                        try:
                            result["robusta_cepea"] = {
                                "price": float(val),
                                "variation": cells[2],
                                "date": cells[0],
                            }
                        except ValueError:
                            pass

            # ── NYBOT (futuros em R$/saca) ──
            elif "Nova Iorque" in title or "NYBOT" in title:
                table = div.find("table")
                if table:
                    rows = table.find_all("tr")[1:]  # skip header
                    for row in rows:
                        cells = [td.get_text(strip=True) for td in row.find_all("td")]
                        if len(cells) >= 3:
                            try:
                                brl_val = cells[2].replace(".", "").replace(",", ".")
                                result["nybot"].append({
                                    "contract": cells[0],
                                    "usx_lb": cells[1],
                                    "brl_saca": float(brl_val),
                                    "variation": cells[3] if len(cells) > 3 else "",
                                })
                            except (ValueError, IndexError):
                                pass

            # ── Mercado Físico Arábica (praças) ──
            elif "sico" in title and ("Tipo 6/7" in title or "Tipo 6 " in title):
                table = div.find("table")
                if table:
                    rows = table.find_all("tr")[1:]
                    for row in rows:
                        cells = [td.get_text(strip=True) for td in row.find_all("td")]
                        if len(cells) >= 3:
                            try:
                                val = cells[1].replace(".", "").replace(",", ".")
                                result["arabica_fisico"].append({
                                    "city": cells[0],
                                    "price": float(val),
                                    "variation": cells[2],
                                })
                            except (ValueError, IndexError):
                                pass

            # ── Conilon ES ──
            elif "Conilon" in title:
                table = div.find("table")
                if table:
                    rows = table.find_all("tr")[1:]
                    for row in rows:
                        cells = [td.get_text(strip=True) for td in row.find_all("td")]
                        if len(cells) >= 3:
                            try:
                                val = cells[1].replace(".", "").replace(",", ".")
                                price = float(val)
                                if price > 100:  # filtrar headers
                                    result["conilon_fisico"].append({
                                        "type": cells[0],
                                        "price": price,
                                        "variation": cells[2],
                                    })
                            except (ValueError, IndexError):
                                pass

        # Data de atualização
        update_el = soup.find(string=re.compile(r"Atualizado em"))
        if update_el:
            m = re.search(r"Atualizado em:\s*(\S+)", update_el)
            if m:
                result["updated"] = m.group(1)

    except Exception as e:
        print(f"Erro ao buscar precos fisicos: {e}")

    return result


def fetch_fertilizer_prices() -> dict:
    """Busca preços de fertilizantes e insumos via yfinance."""
    results = {}
    for name, info in FERTILIZER_TICKERS.items():
        try:
            hist = yf.Ticker(info["ticker"]).history(period="5d")
            if hist.empty:
                continue
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            change_pct = ((price - prev) / prev) * 100 if prev else 0

            # Buscar variação de 30 dias
            hist_30 = yf.Ticker(info["ticker"]).history(period="1mo")
            change_30d = 0
            if len(hist_30) > 1:
                first = float(hist_30["Close"].iloc[0])
                change_30d = ((price - first) / first) * 100 if first else 0

            results[name] = {
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "change_30d": round(change_30d, 2),
                "tipo": info["tipo"],
                "relevancia": info["relevancia"],
            }
        except Exception:
            pass
    return results


def analyze_fertilizer_impact(fert_data: dict) -> dict:
    """Analisa o impacto dos preços de fertilizantes no café."""
    if not fert_data:
        return {"trend": "indefinido", "signal": "", "score": 0}

    # Calcular tendência média dos fertilizantes
    changes_30d = [v["change_30d"] for v in fert_data.values() if "change_30d" in v]
    avg_change = sum(changes_30d) / len(changes_30d) if changes_30d else 0

    if avg_change > 10:
        trend = "FORTE ALTA"
        signal = (
            "Fertilizantes em forte alta (+{:.1f}% em 30d) — custo de produção subindo "
            "significativamente. Pode sustentar preços do café e reduzir investimento "
            "em adubação na próxima safra."
        ).format(avg_change)
        score = 0.6  # altista para preço do café
    elif avg_change > 3:
        trend = "ALTA"
        signal = (
            "Fertilizantes em alta moderada (+{:.1f}% em 30d) — pressão no custo "
            "de produção. Tendência de sustentação dos preços do café."
        ).format(avg_change)
        score = 0.3
    elif avg_change < -10:
        trend = "FORTE QUEDA"
        signal = (
            "Fertilizantes em forte queda ({:.1f}% em 30d) — custo de produção caindo. "
            "Produtores podem investir mais em adubação = maior produtividade futura."
        ).format(avg_change)
        score = -0.4  # baixista para preço do café (mais oferta futura)
    elif avg_change < -3:
        trend = "QUEDA"
        signal = (
            "Fertilizantes em queda ({:.1f}% em 30d) — alívio no custo de produção."
        ).format(avg_change)
        score = -0.2
    else:
        trend = "ESTÁVEL"
        signal = "Preços de fertilizantes estáveis ({:+.1f}% em 30d).".format(avg_change)
        score = 0

    return {
        "trend": trend,
        "signal": signal,
        "score": round(score, 2),
        "avg_change_30d": round(avg_change, 2),
        "info": COFFEE_FERTILIZATION,
    }


def fetch_fertilizer_news() -> list[dict]:
    """Busca notícias sobre fertilizantes e custo de produção do café."""
    import feedparser

    feeds = [
        "https://news.google.com/rss/search?q=fertilizante+café+custo+produção&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://news.google.com/rss/search?q=adubo+café+preço+insumo&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://news.google.com/rss/search?q=coffee+fertilizer+cost+production&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=ureia+potassio+fosfato+preço+agrícola&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    ]
    articles = []
    seen = set()
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                if title.lower() not in seen:
                    seen.add(title.lower())
                    published = ""
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                    articles.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "published": published,
                        "summary": BeautifulSoup(
                            entry.get("summary", ""), "html.parser"
                        ).get_text()[:200],
                    })
        except Exception:
            pass
    return articles[:10]
