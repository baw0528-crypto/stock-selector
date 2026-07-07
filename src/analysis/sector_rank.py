"""セクターETF/指数の相対強度(ベンチマーク比の騰落率)でランキングする。

「セクターの勢い」を数値化する最もオーソドックスな方法として、
一定期間のリターンをベンチマーク(SPY/TOPIX)と比較する。
"""
from __future__ import annotations

from dataclasses import dataclass

from src.data import us_market_client
from src.data.sector_data import (
    US_SECTOR_ETFS,
    US_BENCHMARK,
    JP_SECTOR_ETFS,
    JP_BENCHMARK,
)


@dataclass
class SectorStrength:
    code: str
    name: str
    market: str
    return_pct: float
    relative_strength_pct: float  # ベンチマーク比の超過リターン


def _period_return(df, days: int) -> float | None:
    if df is None or df.empty or len(df) < days + 1:
        return None
    recent = df["Close"].iloc[-1]
    past = df["Close"].iloc[-(days + 1)]
    if past == 0:
        return None
    return (recent / past - 1) * 100


def rank_us_sectors(days: int = 20) -> list[SectorStrength]:
    """SPY比の相対強度で米国セクターETFをランキングする。days=20は約1ヶ月。"""
    bench_df = us_market_client.get_price_history(US_BENCHMARK, period="3mo")
    bench_return = _period_return(bench_df, days)
    if bench_return is None:
        bench_return = 0.0

    results = []
    for etf, name in US_SECTOR_ETFS.items():
        df = us_market_client.get_price_history(etf, period="3mo")
        ret = _period_return(df, days)
        if ret is None:
            continue
        results.append(
            SectorStrength(
                code=etf,
                name=name,
                market="us",
                return_pct=round(ret, 2),
                relative_strength_pct=round(ret - bench_return, 2),
            )
        )
    return sorted(results, key=lambda s: s.relative_strength_pct, reverse=True)


def select_diverse_sectors(
    sectors: list[SectorStrength],
    constituents: dict[str, list[str]],
    top_n: int,
    overlap_threshold: float = 0.35,
) -> tuple[list[SectorStrength], list[tuple[SectorStrength, float]]]:
    """上位からtop_n件選ぶが、既選択セクターと代表銘柄が大きく重複するセクターは
    スキップして順位が下のセクターで埋める(例: SMHはXLKと同じ半導体大型株を含むため、
    両方選ぶと実質1テーマを2枠使うだけで分散にならない)。

    戻り値は (採用セクター, スキップされた(セクター, 重複率)) のタプル。
    """
    selected: list[SectorStrength] = []
    selected_tickers: set[str] = set()
    skipped: list[tuple[SectorStrength, float]] = []
    for s in sectors:
        if len(selected) >= top_n:
            break
        tickers = set(constituents.get(s.code, []))
        if tickers and selected_tickers:
            # 銘柄数が少ない方の集合を基準に重複率を見る(片方が大きいリストでも
            # 「小さい方がほぼ丸ごと重複」というケースを見逃さないため)。
            denom = min(len(tickers), len(selected_tickers))
            overlap = len(tickers & selected_tickers) / denom
            if overlap >= overlap_threshold:
                skipped.append((s, overlap))
                continue
        selected.append(s)
        selected_tickers |= tickers
    return selected, skipped


def rank_jp_sectors(days: int = 20) -> list[SectorStrength]:
    """TOPIX比の相対強度で日本の業種別ETFをランキングする。

    注意: JP_SECTOR_ETFSの証券コードは要検証(上場廃止・変更の可能性あり)。
    現状はyfinanceのグローバルティッカー経由で取得しているため、
    日本のETFで正しく値が取れない場合はJ-Quants側の日次データに
    切り替えることを検討してください。
    """
    bench_df = us_market_client.get_price_history(JP_BENCHMARK, period="3mo")
    bench_return = _period_return(bench_df, days)
    if bench_return is None:
        bench_return = 0.0

    results = []
    for etf, name in JP_SECTOR_ETFS.items():
        df = us_market_client.get_price_history(etf, period="3mo")
        ret = _period_return(df, days)
        if ret is None:
            continue
        results.append(
            SectorStrength(
                code=etf,
                name=name,
                market="jp",
                return_pct=round(ret, 2),
                relative_strength_pct=round(ret - bench_return, 2),
            )
        )
    return sorted(results, key=lambda s: s.relative_strength_pct, reverse=True)
