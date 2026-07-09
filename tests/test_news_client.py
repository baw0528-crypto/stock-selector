from src.data.news_client import build_us_query, news_score, _rough_sentiment


def test_build_us_query_prefers_company_name_over_ticker():
    assert build_us_query("V", "Visa Inc.") == '"Visa Inc." stock'


def test_build_us_query_falls_back_to_ticker_when_no_company_name():
    assert build_us_query("V", None) == "V stock"


def test_sentiment_word_boundary_avoids_false_positive():
    # "miss" が "missile" に誤爆しないこと(センチメント誤爆修正の回帰テスト)
    assert _rough_sentiment("Missile defense system unveiled") == "neutral"


def test_sentiment_detects_positive_and_negative_terms():
    assert _rough_sentiment("Company beats earnings estimates, stock at record high") == "positive"
    assert _rough_sentiment("Company misses estimates amid lawsuit") == "negative"


def test_news_score_neutral_when_no_headlines():
    assert news_score([]) == 50.0


def test_news_score_reflects_positive_negative_balance():
    headlines = [
        {"sentiment": "positive"},
        {"sentiment": "positive"},
        {"sentiment": "negative"},
        {"sentiment": "neutral"},
    ]
    # shrinkage: (2 - 1) / (4 + 4) = 0.125 -> 50 + 0.125*50 = 56.2
    assert news_score(headlines) == 56.2


def test_news_score_shrinks_small_samples_toward_neutral():
    """同じ「全部ポジティブ」でも、見出しが少ないほど中立寄りになる。"""
    few = [{"sentiment": "positive"}] * 2
    many = [{"sentiment": "positive"}] * 16
    assert 50.0 < news_score(few) < news_score(many)
