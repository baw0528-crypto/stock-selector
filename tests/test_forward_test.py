from forward_test import strategy_key, strategy_label


def _meta(**overrides):
    meta = {
        "score_version": 3,
        "market": "us",
        "universe": "sp1500",
        "sector_first": False,
        "weights": {"fundamental": 0.34, "technical": 0.33, "news": 0.33},
    }
    meta.update(overrides)
    return meta


def test_same_conditions_share_a_key():
    assert strategy_key(_meta()) == strategy_key(_meta())


def test_different_universe_or_weights_get_different_keys():
    base = strategy_key(_meta())
    assert strategy_key(_meta(universe="sp600")) != base
    assert (
        strategy_key(_meta(weights={"fundamental": 0.25, "technical": 0.6, "news": 0.15}))
        != base
    )
    assert strategy_key(_meta(score_version=2)) != base


def test_old_snapshot_without_fields_still_produces_key():
    key = strategy_key({})
    assert "default" in key  # universe未記録はdefault扱い
    assert strategy_key({}) == key  # 決定的であること


def test_strategy_label_is_human_readable():
    label = strategy_label(_meta())
    assert "sp1500" in label
    assert "0.34/0.33/0.33" in label
    assert "v3" in label
