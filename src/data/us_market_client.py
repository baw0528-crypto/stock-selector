"""yfinanceを使った米国株の株価・ファンダメンタルズ取得。

APIキー不要で使えるが、非公式データソースのため遅延・欠損があり得る。
本番判断に使う前に必ず数値の妥当性を確認すること。
"""
from __future__ import annotations

import json
import time
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

SP500_CACHE = Path("data_cache/sp500_tickers.json")
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def get_price_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """1銘柄の価格履歴を取得する。52週高値近接度の計算に1年分が要るためデフォルト1y。"""
    df = yf.Ticker(ticker).history(period=period)
    if df.empty:
        return df
    df = df.reset_index().rename(columns={"Date": "Date"})
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


def get_price_histories(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """複数銘柄の価格履歴を一括ダウンロードする。

    広いユニバース(S&P 500等)を1銘柄ずつ取得するとレート制限と
    実行時間の両方で破綻するため、yf.downloadでまとめて取る。
    取得できなかった銘柄は結果に含まれない。
    """
    if not tickers:
        return {}
    data = yf.download(
        tickers,
        period=period,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            # yfinanceのバージョン・銘柄数によってMultiIndex有無が変わる
            df = data[ticker] if isinstance(data.columns, pd.MultiIndex) else data
        except KeyError:
            continue
        df = df.dropna(subset=["Close"])
        if df.empty:
            continue
        df = df.reset_index()
        result[ticker] = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    return result


def get_sp500_tickers(max_age_days: int = 30) -> list[str]:
    """S&P 500構成銘柄のティッカーを取得する(ローカルキャッシュ付き)。

    構成銘柄は入替えがあるため、キャッシュが古くなったらWikipediaの
    一覧から再取得する。オフライン時はキャッシュが古くてもそのまま使う。
    """
    if SP500_CACHE.exists():
        cached = json.loads(SP500_CACHE.read_text())
        age_days = (time.time() - cached["fetched_at"]) / 86400
        if age_days < max_age_days:
            return cached["tickers"]
    else:
        cached = None

    try:
        # pd.read_htmlに直接URLを渡すとデフォルトUAがWikipediaに403で弾かれる
        resp = requests.get(SP500_URL, headers={"User-Agent": "stock-selector/1.0"}, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        # yfinanceはクラス株の区切りにドットではなくハイフンを使う(BRK.B -> BRK-B)
        tickers = [t.replace(".", "-") for t in tables[0]["Symbol"].tolist()]
    except Exception as e:  # noqa: BLE001
        if cached:
            print(f"[warn] S&P 500リストの更新に失敗。古いキャッシュを使います ({e})")
            return cached["tickers"]
        raise RuntimeError(f"S&P 500構成銘柄リストの取得に失敗しました: {e}") from e

    SP500_CACHE.parent.mkdir(exist_ok=True)
    SP500_CACHE.write_text(json.dumps({"fetched_at": time.time(), "tickers": tickers}))
    return tickers


def fetch_fundamentals(ticker: str) -> dict:
    """スコアリングで使う共通スキーマに正規化して返す。"""
    info = yf.Ticker(ticker).info or {}

    def _get(key: str) -> Optional[float]:
        val = info.get(key)
        return float(val) if isinstance(val, (int, float)) else None

    roe = _get("returnOnEquity")
    revenue_growth = _get("revenueGrowth")
    earnings_growth = _get("earningsGrowth")

    return {
        "code": ticker,
        "per": _get("trailingPE"),
        "pbr": _get("priceToBook"),
        "roe": roe * 100 if roe is not None else None,
        "revenue_growth_pct": revenue_growth * 100 if revenue_growth is not None else None,
        "earnings_growth_pct": earnings_growth * 100 if earnings_growth is not None else None,
        "profit_margin_pct": (
            _get("profitMargins") * 100 if _get("profitMargins") is not None else None
        ),
        # yfinanceのdebtToEquityは%表記(例: 150.0 = 負債が自己資本の1.5倍)
        "debt_to_equity_pct": _get("debtToEquity"),
        "market_cap": _get("marketCap"),
        "short_name": info.get("shortName"),
    }
