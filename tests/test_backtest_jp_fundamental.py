import pandas as pd
import pytest

from backtest_jp_fundamental import fundamentals_as_of, run_backtest
from src.data.jquants_client import JQuantsClient


def _stmt(disclosed, per_type="FY", eps=100.0, bps=1000.0, profit=5_000_000, equity=50_000_000,
          revenue=100_000_000, forecast_revenue=110_000_000):
    return {
        "DiscDate": disclosed, "CurPerType": per_type, "EPS": eps, "BPS": bps,
        "NP": profit, "Eq": equity, "Sales": revenue, "FSales": forecast_revenue,
    }


def test_fundamentals_as_of_uses_only_prefetched_history_no_api_call():
    """prefetch済みhistoryだけで判定し、クライアント経由の再取得(get_all_statements)は呼ばない。"""
    client = JQuantsClient(api_key="test-key")

    def _boom(*args, **kwargs):
        raise AssertionError("get_all_statements を再度呼んではいけない(prefetch結果を使い回すのが目的)")

    client.get_all_statements = _boom
    history = [_stmt("2025-08-08", eps=100, bps=1000)]

    result = fundamentals_as_of(client, "1234", history, "2025-09-01", price=1500.0)
    assert result["per"] == 15.0
    assert result["pbr"] == 1.5


def test_fundamentals_as_of_excludes_future_disclosures():
    """as_of_dateより後の開示は見ない(先読みバイアス回避)。合成バックテスト側でも守られていることの確認。"""
    client = JQuantsClient(api_key="test-key")
    history = [_stmt("2025-05-10", eps=80), _stmt("2025-11-07", eps=120)]

    result = fundamentals_as_of(client, "1234", history, "2025-09-01", price=1000.0)
    assert result["eps"] == 80  # 11/7開示はまだ見えない


def test_fundamentals_as_of_no_disclosure_yet_returns_empty():
    client = JQuantsClient(api_key="test-key")
    history = [_stmt("2025-08-08")]

    result = fundamentals_as_of(client, "1234", history, "2025-01-01", price=1000.0)
    assert result == {}


def _make_price_df(n_days: int, start_price: float, daily_return_pct: float) -> pd.DataFrame:
    dates = pd.date_range("2023-01-02", periods=n_days, freq="B")
    prices = [start_price * (1 + daily_return_pct / 100) ** i for i in range(n_days)]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
            "Volume": [1_000_000] * n_days,
        }
    )


def test_run_backtest_weight_zero_fundamental_matches_technical_only_ranking():
    """weight_fundamental=0なら、ファンダデータの有無に関わらずテクニカルのみのランキングと同じ選定になる。"""
    n_days = 320
    price_map = {
        "AAAA.T": _make_price_df(n_days, 1000, 0.30),  # 上昇トレンド
        "BBBB.T": _make_price_df(n_days, 1000, -0.10),  # 下落トレンド
    }
    benchmark_df = _make_price_df(n_days, 1000, 0.0)
    statements = {"AAAA": [], "BBBB": []}  # ファンダデータなし(常に中立50点)
    client = JQuantsClient(api_key="test-key")

    trades, n_rebalances = run_backtest(
        price_map, benchmark_df, statements, client,
        top_n=1, rebalance_days=20, weight_fundamental=0.0, weight_technical=1.0,
        tp_pct=999, sl_pct=-999, max_hold_days=15,
    )

    assert n_rebalances > 0
    assert trades  # 上昇トレンド銘柄がテクニカル優位で選ばれるはず
    assert all(t["ticker"] == "AAAA.T" for t in trades)
