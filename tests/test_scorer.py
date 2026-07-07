from src.analysis.scorer import CandidateScore, rank_candidates


def test_compute_total_weighted_average():
    c = CandidateScore(code="AAA", market="us", fundamental_score=80, technical_score=60, news_score=40)
    total = c.compute_total(w_fund=0.5, w_tech=0.3, w_news=0.2)
    assert total == 66.0
    assert c.total_score == 66.0


def test_compute_total_normalizes_weights_not_summing_to_one():
    c = CandidateScore(code="AAA", market="us", fundamental_score=100, technical_score=100, news_score=0)
    total = c.compute_total(w_fund=1, w_tech=1, w_news=1)
    assert total == round(200 / 3, 1)


def test_compute_total_falls_back_to_equal_weights_when_all_zero():
    c = CandidateScore(code="AAA", market="us", fundamental_score=90, technical_score=60, news_score=30)
    total = c.compute_total(w_fund=0, w_tech=0, w_news=0)
    assert total == 60.0


def test_rank_candidates_sorts_descending_and_limits():
    candidates = [
        CandidateScore(code="A", market="us", total_score=50),
        CandidateScore(code="B", market="us", total_score=90),
        CandidateScore(code="C", market="us", total_score=70),
    ]
    ranked = rank_candidates(candidates, top_n=2)
    assert [c.code for c in ranked] == ["B", "C"]


def test_completeness_label_reflects_missing_price_data():
    c = CandidateScore(code="A", market="us", has_price_data=False, fundamental_metrics=2, news_count=5)
    assert c.completeness_label() == "P✗ F2/4 N5"
