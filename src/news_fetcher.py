"""Módulo para busca de notícias do mercado de café."""

import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Optional
from src.config import RSS_FEEDS, MAX_NEWS_PER_TYPE


def fetch_rss_news(feed_url: str, max_items: int = 10) -> list[dict]:
    """Busca notícias de um feed RSS."""
    articles = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:max_items]:
            published = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
            elif hasattr(entry, "published"):
                published = entry.published

            articles.append({
                "title": entry.get("title", "Sem título"),
                "link": entry.get("link", ""),
                "published": published,
                "source": entry.get("source", {}).get("title", "Google News"),
                "summary": BeautifulSoup(
                    entry.get("summary", ""), "html.parser"
                ).get_text()[:300],
            })
    except Exception as e:
        print(f"Erro ao buscar feed {feed_url}: {e}")
    return articles


def fetch_all_news(coffee_type: str) -> list[dict]:
    """Busca todas as notícias para um tipo de café (robusta ou arabica)."""
    feeds = RSS_FEEDS.get(coffee_type, [])
    all_articles = []
    seen_titles = set()

    for feed_url in feeds:
        articles = fetch_rss_news(feed_url, max_items=MAX_NEWS_PER_TYPE)
        for article in articles:
            title_lower = article["title"].lower()
            if title_lower not in seen_titles:
                seen_titles.add(title_lower)
                article["coffee_type"] = coffee_type
                all_articles.append(article)

    all_articles.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_articles[:MAX_NEWS_PER_TYPE]


def fetch_additional_market_news() -> list[dict]:
    """Busca notícias gerais do mercado de café via Google News RSS."""
    general_feeds = [
        "https://news.google.com/rss/search?q=coffee+market+commodity+site:reuters.com+OR+site:bloomberg.com+OR+site:ft.com+OR+site:barchart.com&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=mercado+café+commodity+brasil+site:noticiasagricolas.com.br+OR+site:reuters.com+OR+site:valor.globo.com+OR+site:infomoney.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://news.google.com/rss/search?q=coffee+supply+demand+crop+harvest+site:reuters.com+OR+site:bloomberg.com&hl=en-US&gl=US&ceid=US:en",
    ]
    all_articles = []
    seen_titles = set()

    for feed_url in general_feeds:
        articles = fetch_rss_news(feed_url, max_items=10)
        for article in articles:
            title_lower = article["title"].lower()
            if title_lower not in seen_titles:
                seen_titles.add(title_lower)
                article["coffee_type"] = "geral"
                all_articles.append(article)

    all_articles.sort(key=lambda x: x.get("published", ""), reverse=True)
    return all_articles[:15]


def get_all_coffee_news() -> dict:
    """Retorna todas as notícias organizadas por tipo de café."""
    return {
        "robusta": fetch_all_news("robusta"),
        "arabica": fetch_all_news("arabica"),
        "geral": fetch_additional_market_news(),
    }
