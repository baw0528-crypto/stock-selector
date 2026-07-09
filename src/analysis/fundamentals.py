"""ファンダメンタルズ指標を0-100のスコアに変換する。

JP(J-Quants)とUS(yfinance)でフィールドが少し異なるため、
共通して使える roe / revenue_growth_pct を中心にスコア化し、
per/pbr が取れる場合(主にUS)は割安度も加味する。
"""
from __future__ import annotations

from typing import Optional


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score_fundamentals(data: dict) -> dict:
    """スコアと、算出に使えた指標数を返す。

    指標数0(データなし)は中立50点だが、「情報がない」ことを
    呼び出し側が区別できるよう metrics_used を必ず添える。
    """
    if not data:
        return {"score": 50.0, "metrics_used": 0}

    scores = []

    roe = data.get("roe")
    if roe is not None:
        # ROE 0%→30点、10%→60点、20%以上→90点 の目安で線形補間
        scores.append(_clip(30 + roe * 3, 0, 95))

    growth = data.get("revenue_growth_pct")
    if growth is not None:
        # 減収-10%→20点、横ばい0%→50点、+20%成長→90点の目安
        scores.append(_clip(50 + growth * 2, 0, 95))

    per = data.get("per")
    if per is not None:
        if per > 0:
            # PERが低いほど割安。15倍前後を中立、40倍超で減点。
            per_score = _clip(100 - (per - 10) * 2.5, 10, 90)
            # 利益成長率が取れる場合はPEG(成長調整後PER)を加味する。
            # 高成長銘柄は絶対PERだけ見ると一律「割高」になるが、
            # 成長率対比では正当化されるケースがあるため半々でブレンドする。
            eps_growth = data.get("earnings_growth_pct")
            if eps_growth is not None and eps_growth > 0:
                peg = per / eps_growth
                # PEG 1.0前後を妥当、2.0で減速、3.0超で明確に割高の目安
                peg_score = _clip(100 - (peg - 0.5) * 30, 10, 90)
                per_score = (per_score + peg_score) / 2
            scores.append(per_score)
        else:
            # PERがマイナス = 赤字企業。単に指標を無視すると
            # 「データが少ないだけ」の中位スコアに紛れてしまうため、
            # 赤字であること自体を低スコアとして明示的に反映する。
            scores.append(15.0)

    margin = data.get("profit_margin_pct")
    if margin is not None:
        scores.append(_clip(40 + margin * 1.5, 0, 90))

    dte = data.get("debt_to_equity_pct")
    if dte is not None and dte >= 0:
        # 負債資本倍率(%)。50%以下は健全(80点)、100%で65点、200%で35点、
        # 300%超は財務リスク大として頭打ちの低評価。
        scores.append(_clip(95 - dte * 0.3, 5, 90))

    if not scores:
        return {"score": 50.0, "metrics_used": 0}

    return {"score": round(sum(scores) / len(scores), 1), "metrics_used": len(scores)}
