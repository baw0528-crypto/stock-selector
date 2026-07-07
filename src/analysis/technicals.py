"""価格データからテクニカル指標を計算し0-100のスコアに変換する。

入力は Date/Open/High/Low/Close/Volume を持つDataFrame。
移動平均のトレンド・RSI・出来高の勢いを組み合わせたシンプルな設計。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss == 0 or np.isnan(avg_loss):
        return 100.0 if avg_gain and avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def score_technicals(df: pd.DataFrame) -> dict:
    """スコアと内訳を返す。データ不足時はニュートラル(50)を返す。"""
    if df is None or df.empty or len(df) < 30:
        return {"score": 50.0, "detail": "価格データ不足"}

    close = df["Close"]
    volume = df["Volume"]

    ma25 = close.rolling(25).mean()
    ma75 = close.rolling(75).mean() if len(close) >= 75 else None

    last_close = close.iloc[-1]
    last_ma25 = ma25.iloc[-1]

    trend_score = 50.0
    if not np.isnan(last_ma25):
        # 終値がMA25より何%上にあるかでトレンドを評価
        gap_pct = (last_close / last_ma25 - 1) * 100
        trend_score = 50 + gap_pct * 4
        trend_score = max(0, min(100, trend_score))

    golden_cross_bonus = 0.0
    if ma75 is not None and not np.isnan(ma75.iloc[-1]) and not np.isnan(ma25.iloc[-1]):
        if ma25.iloc[-1] > ma75.iloc[-1] and ma25.iloc[-5] <= ma75.iloc[-5]:
            golden_cross_bonus = 10.0
        elif ma25.iloc[-1] < ma75.iloc[-1] and ma25.iloc[-5] >= ma75.iloc[-5]:
            golden_cross_bonus = -10.0

    rsi_value = _rsi(close)
    # trend_score/golden_cross_bonus/volume_scoreはいずれもモメンタム(強い銘柄ほど加点)方針。
    # RSIを従来の逆張り解釈(過熱=減点、売られすぎ=加点)のままにすると、
    # 強い上昇トレンド銘柄がtrend_scoreで加点されつつRSIで減点される矛盾が生じるため、
    # ここもモメンタム方向(RSIが高い=強い=加点)に合わせる。ただし極端な過熱(85超)は
    # 反落リスクとしてやや頭打ちにする。
    if rsi_value <= 30:
        rsi_score = rsi_value  # 下落基調での売られすぎは反発期待ではなく弱さの表れとして評価
    elif rsi_value <= 70:
        rsi_score = 30 + (rsi_value - 30) * 1.25  # 30→30点、70→80点
    elif rsi_value <= 85:
        rsi_score = 80 + (rsi_value - 70) * (10 / 15)  # 70→80点、85→90点
    else:
        rsi_score = 90 - (rsi_value - 85) * 2  # 85超はブローオフ(過熱の反落)リスクを反映

    recent_vol = volume.tail(5).mean()
    base_vol = volume.tail(30).mean()
    volume_score = 50.0
    if base_vol and base_vol > 0:
        vol_ratio = recent_vol / base_vol
        volume_score = max(0, min(100, 50 + (vol_ratio - 1) * 50))

    total = (
        trend_score * 0.4
        + rsi_score * 0.25
        + volume_score * 0.2
        + (50 + golden_cross_bonus) * 0.15
    )
    total = round(max(0, min(100, total)), 1)

    return {
        "score": total,
        "detail": (
            f"trend={trend_score:.0f} rsi={rsi_value:.0f} "
            f"volume={volume_score:.0f} cross_bonus={golden_cross_bonus:+.0f}"
        ),
    }
