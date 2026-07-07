import numpy as np
import pandas as pd

from src.analysis.technicals import score_technicals


def _make_df(closes, volume=1_000_000):
    return pd.DataFrame({"Close": closes, "Volume": [volume] * len(closes)})


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
