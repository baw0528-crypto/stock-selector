"""Google News RSS から銘柄関連の見出しを取得する軽量クライアント。

APIキー不要。件数や鮮度に重きを置いたシンプルな実装。
ポジティブ/ネガティブ判定はキーワードベースの簡易版で、
最終的な材料判断はFable 5側の総合判断に委ねる想定。
"""
from __future__ import annotations

import re
from urllib.parse import quote

import feedparser

# 英語の語は単語境界で一致させる("miss"が"missile"に一致する誤爆を防ぐ)。
# "raises"/"cuts"のように目的語次第で意味が反転する単独動詞は入れない。
POSITIVE_TERMS = [
    "上方修正", "増配", "好調", "最高益",
    "beat", "beats", "surge", "surges", "soar", "soars",
    "record high", "all-time high", "upgrade", "upgrades",
    "raised guidance", "strong demand",
]
NEGATIVE_TERMS = [
    "下方修正", "減配", "赤字", "急落", "不祥事",
    "miss", "misses", "plunge", "plunges", "slump", "slumps",
    "record low", "downgrade", "downgrades", "lawsuit", "recall",
    "cut guidance", "weak demand", "sell-off", "selloff",
]


def build_us_query(ticker: str, company_name: str | None) -> str:
    """ニュース検索クエリを組み立てる。

    ティッカーそのままの検索は"V"(Visa)や"SO"(Southern)のような
    短いティッカーで無関係な記事ばかり拾うため、会社名が取れていれば
    会社名ベースで検索する。
    """
    if company_name:
        return f'"{company_name}" stock'
    return f"{ticker} stock"


def fetch_headlines(query: str, lang: str = "ja", limit: int = 8) -> list[dict]:
    """queryは銘柄名やティッカーを想定。langは'ja'または'en'。"""
    if lang == "ja":
        url = f"https://news.google.com/rss/search?q={quote(query)}&hl=ja&gl=JP&ceid=JP:ja"
    else:
        url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"

    feed = feedparser.parse(url)
    headlines = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "")
        headlines.append(
            {
                "title": title,
                "link": entry.get("link"),
                "published": entry.get("published"),
                "sentiment": _rough_sentiment(title),
            }
        )
    return headlines


def _contains_term(text: str, term: str) -> bool:
    if term.isascii():
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text  # 日本語は単語境界の概念が使えないため部分一致


def _rough_sentiment(title: str) -> str:
    text = title.lower()
    pos = any(_contains_term(text, w.lower()) for w in POSITIVE_TERMS)
    neg = any(_contains_term(text, w.lower()) for w in NEGATIVE_TERMS)
    if pos and not neg:
        return "positive"
    if neg and not pos:
        return "negative"
    return "neutral"


def news_score(headlines: list[dict]) -> float:
    """見出しの簡易センチメントを0-100のスコアに変換する。"""
    if not headlines:
        return 50.0
    pos = sum(1 for h in headlines if h["sentiment"] == "positive")
    neg = sum(1 for h in headlines if h["sentiment"] == "negative")
    total = len(headlines)
    balance = (pos - neg) / total  # -1.0 ~ 1.0
    return round(50 + balance * 50, 1)
