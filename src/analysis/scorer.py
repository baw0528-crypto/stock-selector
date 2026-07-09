"""ファンダ・テクニカル・ニュースのスコアを重み付け合成する。"""
from __future__ import annotations

from dataclasses import dataclass, field

# スコアリングロジックのバージョン。指標の追加・解釈変更をしたら上げる。
# フォワードテストで新旧ロジックの観測が混ざったことを検知するために
# スナップショットのmetaに記録される。
#   v1: 初期実装(トレンド/RSI/出来高/クロス + PER/ROE/増収率/利益率)
#   v2: 対SPY相対強度・52週高値近接度・PEG・D/E・ニュースshrinkageを追加
#   v3: 決算サプライズ(45日以内)・ギャップ上昇+出来高急増のカタリスト検知を追加
SCORE_VERSION = 3

FUNDAMENTAL_METRICS_MAX = 6  # per(+peg)/roe/増収率/利益率/D-E/決算サプライズ


@dataclass
class CandidateScore:
    code: str
    market: str  # "jp" or "us"
    name: str = ""
    fundamental_score: float = 50.0
    technical_score: float = 50.0
    news_score: float = 50.0
    total_score: float = 0.0
    # データ充足度: 「情報がない」と「平均的」を区別するためのメタ情報。
    # has_price_data=False の銘柄はテクニカルが計算不能なのでランキング対象外にする。
    has_price_data: bool = True
    fundamental_metrics: int = 0
    news_count: int = 0
    raw: dict = field(default_factory=dict)

    def completeness_label(self) -> str:
        """レポート表示用のデータ充足度ラベル(例: "F3/5 N8")。"""
        price = "P" if self.has_price_data else "P✗"
        return f"{price} F{self.fundamental_metrics}/{FUNDAMENTAL_METRICS_MAX} N{self.news_count}"

    def compute_total(self, w_fund: float, w_tech: float, w_news: float) -> float:
        weight_sum = w_fund + w_tech + w_news
        if weight_sum == 0:
            w_fund = w_tech = w_news = 1 / 3
        else:
            w_fund, w_tech, w_news = (w / weight_sum for w in (w_fund, w_tech, w_news))
        self.total_score = round(
            self.fundamental_score * w_fund
            + self.technical_score * w_tech
            + self.news_score * w_news,
            1,
        )
        return self.total_score


def rank_candidates(candidates: list[CandidateScore], top_n: int = 10) -> list[CandidateScore]:
    return sorted(candidates, key=lambda c: c.total_score, reverse=True)[:top_n]
