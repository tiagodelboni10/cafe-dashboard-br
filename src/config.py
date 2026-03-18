"""Configurações e constantes do projeto."""

# Feeds RSS para notícias de café — fontes relevantes (Reuters, Bloomberg, etc.)
RSS_FEEDS = {
    "robusta": [
        "https://news.google.com/rss/search?q=robusta+coffee+price+site:reuters.com+OR+site:bloomberg.com+OR+site:barchart.com&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=conilon+café+preço+site:noticiasagricolas.com.br+OR+site:reuters.com+OR+site:epbr.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://news.google.com/rss/search?q=robusta+coffee+futures+ICE+London&hl=en-US&gl=US&ceid=US:en",
    ],
    "arabica": [
        "https://news.google.com/rss/search?q=arabica+coffee+price+site:reuters.com+OR+site:bloomberg.com+OR+site:barchart.com&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=café+arábica+preço+site:noticiasagricolas.com.br+OR+site:reuters.com+OR+site:epbr.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://news.google.com/rss/search?q=arabica+coffee+futures+ICE+NYBOT&hl=en-US&gl=US&ceid=US:en",
    ],
}

# Tickers de futuros de café no Yahoo Finance
# Robusta não está disponível no yfinance — dados vêm via scraping
TICKERS = {
    "arabica": "KC=F",      # Coffee C Futures (Arábica) - ICE
}

# URL para dados de Robusta (scraping)
ROBUSTA_DATA_URL = "https://markets.businessinsider.com/commodities/coffee-robusta-price"

# Palavras-chave para análise de sentimento (português e inglês)
BULLISH_KEYWORDS = [
    "alta", "sobe", "subir", "valorização", "demanda forte", "escassez",
    "seca", "geada", "deficit", "exportações caem", "estoques baixos",
    "rally", "surge", "rise", "bullish", "shortage", "drought", "frost",
    "strong demand", "low stocks", "supply deficit", "record high",
    "quebra de safra", "produção menor", "oferta restrita",
]

BEARISH_KEYWORDS = [
    "queda", "cai", "cair", "desvalorização", "oferta forte", "excesso",
    "safra recorde", "estoques altos", "exportações sobem", "demanda fraca",
    "drop", "fall", "bearish", "surplus", "oversupply", "weak demand",
    "high stocks", "record crop", "production increase", "bumper harvest",
    "produção maior", "safra boa", "chuvas favoráveis",
]

# Configurações de exibição
MAX_NEWS_PER_TYPE = 20
HISTORICAL_DAYS = 180
DASHBOARD_TITLE = "☕ Dashboard Mercado de Café - Robusta & Arábica"
REFRESH_INTERVAL_HOURS = 6
