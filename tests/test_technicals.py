import numpy as np
import pandas as pd

from src.analysis.technicals import score_technicals


def _make_df(closes, volume=1_000_000):
    closes = list(closes)
    # Openは前日終値と同じ(ギャップなし)をデフォルトにする
    opens = [closes[0]] + closes[:-1]
    return pd.DataFrame({"Open": opens, "Close": closes, "Volume": [volume] * len(closes)})


def test_insufficient_data_returns_neutral():
    df = _make_df([100.0] * 10)
    result = score_technicals(df)
    assert result == {"score": 50.0, "detail": "価格データ不足"}


def test_none_or_empty_returns_neutral():
    assert score_technicals(None)["score"] == 50.0
    assert score_technicals(pd.DataFrame())["score"] == 50.0


def test_steady_uptrend_scores_above_neutral():
    closes = [100 + i * 0.5 for i in range(90)]
    result = score_technicals(_make_df(closes))
    assert result["score"] > 50.0


def test_steady_downtrend_scores_below_neutral():
    closes = [100 - i * 0.5 for i in range(90)]
    result = score_technicals(_make_df(closes))
    assert result["score"] < 50.0


def test_rsi_rewards_strength_instead_of_penalizing_overbought():
    """モメンタム方針との整合性: 強い上昇トレンド(高RSI)がRSI要因で
    減点されず、trend/rsiの両方が同じ方向(高スコア)を向くこと。"""
    closes = [100 + i * 0.5 for i in range(90)]
    result = score_technicals(_make_df(closes))
    detail = result["detail"]
    trend = float(detail.split("trend=")[1].split(" ")[0])
    rsi = float(detail.split("rsi=")[1].split(" ")[0])
    assert trend > 50
    assert rsi > 50


def test_relative_strength_rewards_outperformance():
    """同じ銘柄でも、ベンチマークが弱いほど相対強度スコアが高くなる。"""
    stock = _make_df([100 + i * 0.5 for i in range(90)])  # 強い上昇
    flat_bench = _make_df([100.0] * 90)
    strong_bench = _make_df([100 + i * 0.8 for i in range(90)])
    vs_flat = score_technicals(stock, benchmark_df=flat_bench)
    vs_strong = score_technicals(stock, benchmark_df=strong_bench)
    assert vs_flat["score"] > vs_strong["score"]


def test_relative_strength_neutral_without_benchmark():
    closes = [100 + i * 0.5 for i in range(90)]
    result = score_technicals(_make_df(closes))
    assert "rs=50(中立)" in result["detail"]


def test_gap_up_with_volume_spike_gets_catalyst_bonus():
    """直近のギャップ上昇+出来高急増(材料が出た形)はgap_bonusが付く。"""
    n = 60
    closes = [100.0] * (n - 3) + [106.0, 107.0, 108.0]  # 3日前に+6%ギャップ
    opens = [100.0] * (n - 3) + [106.0, 106.5, 107.5]
    volumes = [1_000_000] * (n - 3) + [3_000_000, 1_500_000, 1_200_000]
    df = pd.DataFrame({"Open": opens, "Close": closes, "Volume": volumes})
    result = score_technicals(df)
    assert "gap_bonus=+15" in result["detail"]

    quiet = score_technicals(_make_df([100.0] * n))
    assert "gap_bonus=+0" in quiet["detail"]


def test_52w_high_proximity_favors_stocks_near_high():
    """高値圏の銘柄は、高値から大きく崩れた銘柄よりhi52スコアが高い。"""
    near_high = [100 + i * 0.2 for i in range(120)]  # 単調上昇=常に高値圏
    # 前半で高値を付けて後半で40%下落
    off_high = [100 + i for i in range(60)] + [160 - i * 1.1 for i in range(60)]
    near = score_technicals(_make_df(near_high))
    off = score_technicals(_make_df(off_high))
    hi_near = float(near["detail"].split("hi52=")[1].split(" ")[0])
    hi_off = float(off["detail"].split("hi52=")[1].split(" ")[0])
    assert hi_near > hi_off
    assert hi_off == 0  # -30%超の下落は0点
