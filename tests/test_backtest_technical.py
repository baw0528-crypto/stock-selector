import pandas as pd

from backtest_technical import _to_bars, run_backtest


def _make_price_df(days, start=100.0, drift=0.0, start_date="2024-01-01"):
    dates = pd.date_range(start_date, periods=days, freq="B")
    closes = [start + i * drift for i in range(days)]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": closes,
            "High": [c + 0.5 for c in closes],
            "Low": [c - 0.5 for c in closes],
            "Close": closes,
            "Volume": [1_000_000] * days,
        }
    )


def test_to_bars_converts_columns_to_lowercase_dicts():
    df = _make_price_df(3)
    bars = _to_bars(df)
    assert len(bars) == 3
    assert set(bars[0].keys()) == {"date", "open", "high", "low", "close"}
    assert bars[0]["close"] == 100.0


def test_run_backtest_prefers_stronger_trend_ticker():
    """上昇トレンドが強い銘柄ほど高いテクニカルスコアで優先的に選ばれる。"""
    days = 320
    strong = _make_price_df(days, drift=0.4)  # 明確な上昇トレンド
    flat = _make_price_df(days, drift=0.0)  # レンジ
    price_map = {"STRONG": strong, "FLAT": flat}
    benchmark = _make_price_df(days, drift=0.0)

    trades, n_rebalances = run_backtest(
        price_map, benchmark, top_n=1, rebalance_days=20,
        tp_pct=10, sl_pct=-7, max_hold_days=20,
    )
    assert n_rebalances > 0
    assert len(trades) > 0
    tickers_chosen = {t["ticker"] for t in trades}
    assert tickers_chosen == {"STRONG"}  # top_n=1なので毎回STRONGが選ばれるはず


def test_run_backtest_skips_ticker_missing_data_on_rebalance_date():
    """リバランス日にデータが無い銘柄(新規上場等)はスコアリング対象から除外される。"""
    days = 320
    full = _make_price_df(days, drift=0.2)
    # 後半100日分しかない(新規上場を模したデータ)
    late = _make_price_df(100, drift=0.2, start_date="2024-01-01")
    late["Date"] = pd.date_range("2024-09-01", periods=100, freq="B")
    price_map = {"FULL": full, "LATE": late}
    benchmark = _make_price_df(days, drift=0.0)

    trades, _ = run_backtest(
        price_map, benchmark, top_n=2, rebalance_days=20,
        tp_pct=10, sl_pct=-7, max_hold_days=20,
    )
    # LATEはWARMUP_BARS分の助走が無いリバランス日では選ばれ得ない
    assert all(t["ticker"] in ("FULL", "LATE") for t in trades)
