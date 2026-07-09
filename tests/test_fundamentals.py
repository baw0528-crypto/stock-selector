from src.analysis.fundamentals import score_fundamentals


def test_no_data_returns_neutral_with_zero_metrics():
    result = score_fundamentals({})
    assert result == {"score": 50.0, "metrics_used": 0}


def test_negative_per_is_penalized_not_ignored():
    with_loss = score_fundamentals({"per": -5})
    without_metric = score_fundamentals({})
    assert with_loss["metrics_used"] == 1
    assert with_loss["score"] < without_metric["score"]


def test_positive_per_scores_higher_when_cheaper():
    cheap = score_fundamentals({"per": 10})
    expensive = score_fundamentals({"per": 50})
    assert cheap["score"] > expensive["score"]


def test_high_roe_and_growth_score_higher():
    strong = score_fundamentals({"roe": 20, "revenue_growth_pct": 20})
    weak = score_fundamentals({"roe": 0, "revenue_growth_pct": -10})
    assert strong["score"] > weak["score"]
    assert strong["metrics_used"] == 2


def test_peg_blend_rewards_growth_backed_high_per():
    """同じPER40でも、利益成長率が高ければ(PEGが良ければ)スコアが上がる。"""
    no_growth = score_fundamentals({"per": 40})
    with_growth = score_fundamentals({"per": 40, "earnings_growth_pct": 60})
    assert with_growth["score"] > no_growth["score"]
    # PEGはPERスコアに畳み込まれるので指標数は増えない
    assert with_growth["metrics_used"] == no_growth["metrics_used"] == 1


def test_high_debt_to_equity_is_penalized():
    healthy = score_fundamentals({"debt_to_equity_pct": 40})
    leveraged = score_fundamentals({"debt_to_equity_pct": 280})
    assert healthy["score"] > leveraged["score"]
    assert healthy["metrics_used"] == 1
