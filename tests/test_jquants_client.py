import pytest

from src.data.jquants_client import JQuantsClient


def _stmt(disclosed, eps=100.0, bps=1000.0, profit=5_000_000, equity=50_000_000,
          revenue=100_000_000, forecast_revenue=110_000_000):
    return {
        "DisclosedDate": disclosed,
        "EarningsPerShare": eps,
        "BookValuePerShare": bps,
        "Profit": profit,
        "Equity": equity,
        "NetSales": revenue,
        "ForecastNetSales": forecast_revenue,
    }


def test_get_statement_as_of_excludes_future_disclosures():
    """先読みバイアス回避の核心: as_of_dateより後の開示は絶対に見ない。"""
    client = JQuantsClient(mail="x", password="y")
    statements = [_stmt("2025-05-10", eps=80), _stmt("2025-08-08", eps=100), _stmt("2025-11-07", eps=120)]
    client.get_all_statements = lambda code, use_cache=True: statements

    as_of_before_all = client.get_statement_as_of("1234", "2025-01-01")
    assert as_of_before_all == {}

    as_of_between = client.get_statement_as_of("1234", "2025-09-01")
    assert as_of_between["EarningsPerShare"] == 100  # 8/8開示のみ知り得る、11/7はまだ

    as_of_after_all = client.get_statement_as_of("1234", "2025-12-01")
    assert as_of_after_all["EarningsPerShare"] == 120


def test_normalize_statement_computes_roe_and_revenue_growth():
    client = JQuantsClient(mail="x", password="y")
    result = client._normalize_statement(_stmt("2025-08-08"), "1234")
    assert result["roe"] == 10.0  # 5,000,000 / 50,000,000 * 100
    assert result["revenue_growth_pct"] == pytest.approx(10.0)  # 110M/100M - 1) * 100
    assert result["disclosed_date"] == "2025-08-08"


def test_normalize_statement_empty_input_returns_empty():
    client = JQuantsClient(mail="x", password="y")
    assert client._normalize_statement({}, "1234") == {}


def test_fetch_fundamentals_as_of_adds_point_in_time_per_pbr():
    client = JQuantsClient(mail="x", password="y")
    client.get_all_statements = lambda code, use_cache=True: [_stmt("2025-08-08", eps=100, bps=1000)]

    result = client.fetch_fundamentals_as_of("1234", "2025-09-01", price=1500.0)
    assert result["per"] == 15.0   # 1500/100
    assert result["pbr"] == 1.5    # 1500/1000


def test_fetch_fundamentals_as_of_without_price_omits_per_pbr():
    client = JQuantsClient(mail="x", password="y")
    client.get_all_statements = lambda code, use_cache=True: [_stmt("2025-08-08")]

    result = client.fetch_fundamentals_as_of("1234", "2025-09-01")
    assert "per" not in result
    assert "pbr" not in result


def test_fetch_fundamentals_as_of_no_disclosure_yet_returns_empty():
    client = JQuantsClient(mail="x", password="y")
    client.get_all_statements = lambda code, use_cache=True: [_stmt("2025-08-08")]

    result = client.fetch_fundamentals_as_of("1234", "2025-01-01", price=1500.0)
    assert result == {}
