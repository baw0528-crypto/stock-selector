"""セクター/テーマ単位でのローテーション判定に使うマッピング定義。

代表銘柄リストは「土台」として少数だけ用意した仮のものなので、
運用しながら各自のウォッチリストに合わせて拡充してください。
"""

# 米国: State Street系セクターETF(SPDR)+ 半導体はテーマ性が強いので別建て
US_SECTOR_ETFS = {
    "XLK": "情報技術",
    "XLF": "金融",
    "XLE": "エネルギー",
    "XLV": "ヘルスケア",
    "XLY": "一般消費財",
    "XLP": "生活必需品",
    "XLI": "資本財",
    "XLB": "素材",
    "XLU": "公益事業",
    "XLRE": "不動産",
    "XLC": "コミュニケーション",
    "SMH": "半導体(テーマ)",
}
US_BENCHMARK = "SPY"

# セクターETFごとの代表構成銘柄(時価総額上位中心の静的リスト)。
# ETFの構成銘柄は入替えがあるため、これはあくまでスナップショット。
# 将来的にはSPDRが日次公開している保有銘柄CSVからの動的取得に置き換え可能。
US_SECTOR_CONSTITUENTS = {
    "XLK": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "ACN", "IBM", "QCOM"],
    "XLF": ["JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "BLK", "SCHW", "AXP", "C", "SPGI"],
    "XLE": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "WMB"],
    "XLV": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "AMGN", "PFE", "DHR", "ISRG", "GILD"],
    "XLY": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "BKNG", "TJX", "CMG"],
    "XLP": ["PG", "KO", "PEP", "COST", "WMT", "PM", "MDLZ", "MO", "CL", "KMB"],
    "XLI": ["GE", "CAT", "RTX", "HON", "UNP", "BA", "DE", "LMT", "UPS", "ETN"],
    "XLB": ["LIN", "SHW", "APD", "ECL", "NEM", "FCX", "CTVA", "DOW", "DD", "NUE"],
    "XLU": ["NEE", "SO", "DUK", "AEP", "EXC", "SRE", "D", "XEL", "PEG", "ED"],
    "XLRE": ["PLD", "AMT", "EQIX", "PSA", "O", "WELL", "SPG", "CCI", "DLR", "VICI"],
    "XLC": ["META", "GOOGL", "NFLX", "DIS", "TMUS", "CMCSA", "VZ", "T", "EA", "CHTR"],
    "SMH": ["NVDA", "AVGO", "TSM", "AMD", "MU", "QCOM", "TXN", "INTC", "AMAT", "LRCX"],
}

# 日本: NEXT FUNDS TOPIX-17シリーズETF(野村AM)。証券コードは要検証。
# 銘柄コードは変更・上場廃止の可能性があるため、運用前に最新のコードを確認してください。
JP_SECTOR_ETFS = {
    "1617.T": "食品",
    "1618.T": "エネルギー資源",
    "1619.T": "建設・資材",
    "1620.T": "素材・化学",
    "1621.T": "医薬品",
    "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄",
    "1624.T": "機械",
    "1625.T": "電機・精密",
    "1626.T": "情報通信・サービスその他",
    "1627.T": "電力・ガス",
    "1628.T": "運輸・物流",
    "1629.T": "商社・卸売",
    "1630.T": "小売",
    "1631.T": "銀行",
    "1632.T": "金融(除く銀行)",
    "1633.T": "不動産",
}
JP_BENCHMARK = "1306.T"  # TOPIX連動ETF

# セクター名(日本語) -> 代表銘柄コード(仮の少数リスト)
JP_SECTOR_CONSTITUENTS = {
    "電機・精密": ["6758", "6501", "6702", "285A"],  # ソニーG/日立/富士通/キオクシア
    "自動車・輸送機": ["7203", "7267", "7261"],  # トヨタ/ホンダ/マツダ
    "銀行": ["8306", "8316", "8411"],  # MUFG/三井住友FG/みずほFG
    "商社・卸売": ["8058", "8031", "8001"],  # 三菱商事/三井物産/伊藤忠
    "情報通信・サービスその他": ["9984", "9432", "9433"],  # SBG/NTT/KDDI
}
