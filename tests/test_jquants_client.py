import pytest

from src.data.jquants_client import JQuantsClient


def _stmt(disclosed, per_type="2Q", eps=100.0, bps=1000.0, profit=5_000_000, equity=50_000_000,
          revenue=100_000_000, forecast_revenue=110_000_000):
    """J-Quants V2 /fins/summary 形式のスタブ(値は本来すべて文字列だが数値のままでも動く)。"""
    return {
        "DiscDate": disclosed,
        "CurPerType": per_type,
        "EPS": eps,
        "BPS": bps,
        "NP": profit,
        "Eq": equity,
        "Sales": revenue,
        "FSales": forecast_revenue,
    }


def test_get_statement_as_of_excludes_future_disclosures():
    """先読みバイアス回避の核心: as_of_dateより後の開示は絶対に見ない。"""
    client = JQuantsClient(api_key="test-key")
    statements = [_stmt("2025-05-10", eps=80), _stmt("2025-08-08", eps=100), _stmt("2025-11-07", eps=120)]
    client.get_all_statements = lambda code, use_cache=True: statements

    stmt, history = client.get_statement_as_of("1234", "2025-01-01")
    assert stmt == {} and history == []

    stmt, history = client.get_statement_as_of("1234", "2025-09-01")
    assert stmt["EPS"] == 100  # 8/8開示のみ知り得る、11/7はまだ
    assert [s["DiscDate"] for s in history] == ["2025-05-10", "2025-08-08"]

    stmt, _ = client.get_statement_as_of("1234", "2025-12-01")
    assert stmt["EPS"] == 120


def test_revenue_growth_compares_forecast_to_prior_full_year_actual():
    """回帰テスト: FSales(通期予想)を四半期累計Salesと比べると水増しされるバグの修正確認。

    実例(トヨタ実データ)で発生: 2Qの累計売上高23兆に対し通期予想46兆を単純に
    割ると『+97%成長』という非現実的な値になっていた。正しくは直近の通期実績
    (前期のSales)と比較すべき。
    """
    client = JQuantsClient(api_key="test-key")
    history = [
        _stmt("2024-05-08", per_type="FY", revenue=45_000_000_000, forecast_revenue=None),
        _stmt("2024-08-01", per_type="1Q", revenue=11_800_000_000, forecast_revenue=46_000_000_000),
        _stmt("2024-11-06", per_type="2Q", revenue=23_300_000_000, forecast_revenue=46_000_000_000),
    ]
    result = client._normalize_statement(history[-1], "7203", history=history)
    # 46,000 / 45,000 - 1 ≈ +2.2%(前期通期実績比)。四半期累計比なら+97%になり誤り
    assert result["revenue_growth_pct"] == pytest.approx((46_000_000_000 / 45_000_000_000 - 1) * 100)
    assert result["revenue_growth_pct"] < 10  # 明らかにおかしい90%超にはならない


def test_revenue_growth_none_without_prior_fy_actual_in_history():
    """通期実績がまだ履歴に無い(上場直後等)場合は増収率を無理に計算せずNoneにする。"""
    client = JQuantsClient(api_key="test-key")
    history = [_stmt("2024-08-01", per_type="1Q", revenue=11_800_000_000, forecast_revenue=46_000_000_000)]
    result = client._normalize_statement(history[-1], "7203", history=history)
    assert result["revenue_growth_pct"] is None


def test_normalize_statement_computes_roe():
    client = JQuantsClient(api_key="test-key")
    result = client._normalize_statement(_stmt("2025-08-08"), "1234")
    assert result["roe"] == 10.0  # 5,000,000 / 50,000,000 * 100
    assert result["disclosed_date"] == "2025-08-08"


def test_normalize_statement_empty_input_returns_empty():
    client = JQuantsClient(api_key="test-key")
    assert client._normalize_statement({}, "1234") == {}


def test_fetch_fundamentals_as_of_adds_point_in_time_per_pbr():
    client = JQuantsClient(api_key="test-key")
    client.get_all_statements = lambda code, use_cache=True: [_stmt("2025-08-08", eps=100, bps=1000)]

    result = client.fetch_fundamentals_as_of("1234", "2025-09-01", price=1500.0)
    assert result["per"] == 15.0   # 1500/100
    assert result["pbr"] == 1.5    # 1500/1000


def test_fetch_fundamentals_as_of_without_price_omits_per_pbr():
    client = JQuantsClient(api_key="test-key")
    client.get_all_statements = lambda code, use_cache=True: [_stmt("2025-08-08")]

    result = client.fetch_fundamentals_as_of("1234", "2025-09-01")
    assert "per" not in result
    assert "pbr" not in result


def test_fetch_fundamentals_as_of_no_disclosure_yet_returns_empty():
    client = JQuantsClient(api_key="test-key")
    client.get_all_statements = lambda code, use_cache=True: [_stmt("2025-08-08")]

    result = client.fetch_fundamentals_as_of("1234", "2025-01-01", price=1500.0)
    assert result == {}
