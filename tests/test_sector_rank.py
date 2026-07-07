from src.analysis.sector_rank import SectorStrength, select_diverse_sectors


def _s(code, name, strength):
    return SectorStrength(code=code, name=name, market="us", return_pct=strength, relative_strength_pct=strength)


CONSTITUENTS = {
    "SMH": ["NVDA", "AVGO", "TSM", "AMD", "MU", "QCOM", "TXN", "INTC", "AMAT", "LRCX"],
    "XLK": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "ACN", "IBM", "QCOM"],
    "XLF": ["JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "BLK", "SCHW", "AXP"],
    "XLY": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
}


def test_overlapping_sector_is_skipped_for_next_ranked_one():
    sectors = [_s("SMH", "半導体", 10), _s("XLK", "情報技術", 9), _s("XLF", "金融", 5)]
    selected, skipped = select_diverse_sectors(sectors, CONSTITUENTS, top_n=2)
    assert [s.code for s in selected] == ["SMH", "XLF"]
    assert [s.code for s, _ in skipped] == ["XLK"]


def test_non_overlapping_sectors_all_selected():
    sectors = [_s("XLF", "金融", 8), _s("XLY", "一般消費財", 6), _s("SMH", "半導体", 4)]
    selected, skipped = select_diverse_sectors(sectors, CONSTITUENTS, top_n=3)
    assert [s.code for s in selected] == ["XLF", "XLY", "SMH"]
    assert skipped == []


def test_top_n_respected_when_no_overlap_issue():
    sectors = [_s("XLF", "金融", 8), _s("XLY", "一般消費財", 6), _s("SMH", "半導体", 4)]
    selected, _ = select_diverse_sectors(sectors, CONSTITUENTS, top_n=1)
    assert len(selected) == 1
    assert selected[0].code == "XLF"
