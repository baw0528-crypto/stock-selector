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

# S&P各指数の構成銘柄リスト(Wikipedia)。sp500=大型 / sp400=中型 / sp600=小型
INDEX_SOURCES = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}


def get_price_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """1銘柄の価格履歴を取得する。52週高値近接度の計算に1年分が要るためデフォルト1y。

    auto_adjust=Trueを明示(一括取得get_price_historiesと調整基準を揃える。
    yfinanceのデフォルト変更に依存しない)。
    """
    df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
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


def get_index_tickers(index: str, max_age_days: int = 30) -> list[str]:
    """指定したS&P指数の構成銘柄ティッカーを取得する(ローカルキャッシュ付き)。

    構成銘柄は入替えがあるため、キャッシュが古くなったらWikipediaの
    一覧から再取得する。オフライン時はキャッシュが古くてもそのまま使う。
    """
    if index not in INDEX_SOURCES:
        raise ValueError(f"未対応の指数です: {index} (対応: {', '.join(INDEX_SOURCES)})")
    cache_path = Path(f"data_cache/{index}_tickers.json")

    cached = None
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        age_days = (time.time() - cached["fetched_at"]) / 86400
        if age_days < max_age_days:
            return cached["tickers"]

    try:
        # pd.read_htmlに直接URLを渡すとデフォルトUAがWikipediaに403で弾かれる
        resp = requests.get(
            INDEX_SOURCES[index], headers={"User-Agent": "stock-selector/1.0"}, timeout=30
        )
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        # 構成銘柄テーブルは通常最初だが、Symbol列を持つ最初のテーブルを探す
        table = next(t for t in tables if "Symbol" in t.columns)
        # yfinanceはクラス株の区切りにドットではなくハイフンを使う(BRK.B -> BRK-B)
        tickers = [str(t).replace(".", "-") for t in table["Symbol"].tolist()]
    except Exception as e:  # noqa: BLE001
        if cached:
            print(f"[warn] {index}リストの更新に失敗。古いキャッシュを使います ({e})")
            return cached["tickers"]
        raise RuntimeError(f"{index}構成銘柄リストの取得に失敗しました: {e}") from e

    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps({"fetched_at": time.time(), "tickers": tickers}))
    return tickers


def get_universe_tickers(universe: str) -> list[str]:
    """ユニバース名からティッカーリストを解決する。sp1500 = 500+400+600の合算。"""
    if universe == "sp1500":
        tickers: list[str] = []
        for index in ("sp500", "sp400", "sp600"):
            tickers += get_index_tickers(index)
        return list(dict.fromkeys(tickers))  # 重複除去(指数間の入替え過渡期対策)
    return get_index_tickers(universe)


def get_sp500_tickers(max_age_days: int = 30) -> list[str]:
    """後方互換のためのエイリアス。"""
    return get_index_tickers("sp500", max_age_days=max_age_days)


def fetch_earnings_surprise(ticker: str) -> Optional[dict]:
    """直近の発表済み決算のEPSサプライズを取得する。

    「好材料発表直後の銘柄」を捉えるカタリスト系の指標。
    発表済み(Reported EPSが存在する)最新の四半期について、
    サプライズ率(%)と発表からの経過日数を返す。取得不能ならNone。
    """
    try:
        df = yf.Ticker(ticker).earnings_dates
    except Exception:  # noqa: BLE001
        return None
    if df is None or df.empty or "Surprise(%)" not in df.columns:
        return None
    reported = df.dropna(subset=["Reported EPS", "Surprise(%)"])
    if reported.empty:
        return None
    latest_date = reported.index.max()
    row = reported.loc[latest_date]
    if isinstance(row, pd.DataFrame):  # 同日に複数行ある場合
        row = row.iloc[0]
    now = pd.Timestamp.now(tz=latest_date.tz) if latest_date.tz else pd.Timestamp.now()
    days_since = (now - latest_date).days
    if days_since < 0:
        return None
    return {
        "surprise_pct": float(row["Surprise(%)"]),
        "days_since": int(days_since),
    }


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
