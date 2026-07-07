"""ファンダ・テクニカル・ニュースのスコアを重み付け合成する。"""
from __future__ import annotations

from dataclasses import dataclass, field


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
        """レポート表示用のデータ充足度ラベル(例: "F3/4 N8")。"""
        price = "P" if self.has_price_data else "P✗"
        return f"{price} F{self.fundamental_metrics}/4 N{self.news_count}"

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
