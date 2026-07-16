import pytest

from track_positions import evaluate_exit, evaluate_exit_trailing, compute_stats


def _bar(date, o, h, l, c):
    return {"date": date, "open": o, "high": h, "low": l, "close": c}


def test_take_profit_hit_intraday():
    bars = [_bar("2026-01-02", 100, 112, 99, 111)]
    result = evaluate_exit(100.0, bars, tp_pct=10, sl_pct=-7)
    assert result["exit_reason"] == "tp"
    assert result["exit_price"] == pytest.approx(110.0)  # 閾値ちょうどで約定したとみなす


def test_stop_loss_hit_intraday():
    bars = [_bar("2026-01-02", 100, 101, 90, 91)]
    result = evaluate_exit(100.0, bars, tp_pct=10, sl_pct=-7)
    assert result["exit_reason"] == "sl"
    assert result["exit_price"] == 93.0


def test_same_day_both_hit_is_conservative_stop_loss():
    """同日に高値がTP・安値がSLの両方に触れた場合は損切り優先。"""
    bars = [_bar("2026-01-02", 100, 115, 90, 100)]
    result = evaluate_exit(100.0, bars, tp_pct=10, sl_pct=-7)
    assert result["exit_reason"] == "sl"


def test_gap_down_exits_at_open_not_sl_price():
    """SLを飛び越えて寄った場合、SL価格ではなく寄り値(より悪い値)で約定。"""
    bars = [_bar("2026-01-02", 85, 88, 84, 86)]
    result = evaluate_exit(100.0, bars, tp_pct=10, sl_pct=-7)
    assert result["exit_reason"] == "sl"
    assert result["exit_price"] == 85


def test_time_exit_at_max_hold_close():
    bars = [_bar(f"2026-01-{d:02d}", 100, 101, 99, 100.5) for d in range(2, 25)]
    result = evaluate_exit(100.0, bars, tp_pct=10, sl_pct=-7, max_hold_days=5)
    assert result["exit_reason"] == "time"
    assert result["days_held"] == 5
    assert result["exit_price"] == 100.5


def test_no_exit_returns_none():
    bars = [_bar("2026-01-02", 100, 102, 98, 101)]
    assert evaluate_exit(100.0, bars, tp_pct=10, sl_pct=-7) is None


def test_compute_stats_win_rate_and_profit_factor():
    closed = [
        {"pnl_pct": 10.0, "days_held": 3, "exit_reason": "tp"},
        {"pnl_pct": 10.0, "days_held": 5, "exit_reason": "tp"},
        {"pnl_pct": -7.0, "days_held": 2, "exit_reason": "sl"},
        {"pnl_pct": 2.0, "days_held": 20, "exit_reason": "time"},
    ]
    s = compute_stats(closed)
    assert s["trades"] == 4
    assert s["win_rate_pct"] == 75.0
    assert s["avg_pnl_pct"] == 3.75
    assert s["profit_factor"] == round(22.0 / 7.0, 2)
    assert s["exit_reasons"] == {"tp": 2, "sl": 1, "time": 1}


def test_compute_stats_empty():
    assert compute_stats([]) == {"trades": 0}


def test_trailing_exit_uses_initial_sl_before_reaching_profit_lock():
    """含み益がtrail_start_pctに届く前は、固定の初期損切りだけで判定する。"""
    bars = [_bar("2026-01-02", 100, 100.5, 92, 93)]  # SL -7%=93、寄りは変化なし
    result = evaluate_exit_trailing(100.0, bars, trail_start_pct=1, trail_pct=5, initial_sl_pct=-7)
    assert result["exit_reason"] == "sl"
    assert result["exit_price"] == 93.0


def test_trailing_exit_activates_after_profit_lock_and_trails_the_peak():
    """+1%(101)に到達後は高値からtrail_pct%下がったら手仕舞う。固定TPは無い。"""
    bars = [
        _bar("2026-01-02", 100, 110, 100, 108),  # 高値110で+1%通過、トレーリング開始
        _bar("2026-01-05", 108, 112, 107, 112),  # さらに高値更新112
        _bar("2026-01-06", 112, 112, 105, 106),  # 高値112の-5%=106.4を下回り手仕舞い
    ]
    result = evaluate_exit_trailing(100.0, bars, trail_start_pct=1, trail_pct=5, initial_sl_pct=-7)
    assert result["exit_reason"] == "trail"
    assert result["exit_price"] == pytest.approx(112 * 0.95)
    assert result["days_held"] == 3


def test_trailing_exit_lets_winner_run_beyond_old_fixed_tp():
    """固定+10%を超えても、トレーリングに触れなければ持ち続けられる。"""
    bars = [_bar("2026-01-02", 100, 130, 128, 129)]  # +30%でもトレーリング未接触
    result = evaluate_exit_trailing(100.0, bars, trail_start_pct=1, trail_pct=5, initial_sl_pct=-7)
    assert result is None  # 保有継続(まだクローズしない)


def test_trailing_exit_time_exit_still_applies():
    bars = [_bar(f"2026-01-{d:02d}", 101, 102, 100.5, 101.5) for d in range(2, 25)]
    result = evaluate_exit_trailing(100.0, bars, trail_start_pct=1, trail_pct=5, max_hold_days=5)
    assert result["exit_reason"] == "time"
    assert result["days_held"] == 5


def test_enter_position_uses_snapshot_price_without_fetching():
    """as_of_close/as_of_dateが渡された場合、ネットワーク取得せずその価格で建玉する。"""
    from track_positions import enter_position

    state = {"positions": [], "closed": []}
    ok = enter_position(
        state, "TEST", "Test Co", 70.0, "report-ts",
        entry_price=123.45, entered_at="2026-07-09",
    )
    assert ok
    assert state["positions"][0]["entry_price"] == 123.45
    assert state["positions"][0]["entered_at"] == "2026-07-09"


def test_enter_position_skips_duplicate_ticker():
    from track_positions import enter_position

    state = {"positions": [{"ticker": "TEST"}], "closed": []}
    ok = enter_position(
        state, "TEST", "Test Co", 70.0, "report-ts",
        entry_price=123.45, entered_at="2026-07-09",
    )
    assert not ok
    assert len(state["positions"]) == 1
