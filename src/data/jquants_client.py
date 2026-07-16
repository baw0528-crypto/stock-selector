"""J-Quants API(V2)クライアント。

日本株の日次株価と財務情報(サマリー)を取得する。
無料プランでもエンドポイントは使えるが、取得可能な期間・項目に制限がある
(株価: 直近12週間を除く過去2年分 / 財務: サマリーのみ全期間、詳細BS/PL/CFは
スタンダード以上が必要)。ライブの当日銘柄選定には使えないが、12週間より前の
期間を対象にしたバックテストなら無料プランのままで問題ない。

2026-07時点でV2 API(x-api-key認証)を使用。V1(メール/パスワード→トークン)は
廃止済み(410 Gone)。APIキーはダッシュボード(https://jpx-jquants.com/dashboard/api-keys)
で発行する。公式ドキュメント: https://jpx-jquants.com/ja/spec
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

BASE_URL = "https://api.jquants.com/v2"
STATEMENTS_CACHE_DIR = Path("data_cache/jquants_statements")
STATEMENTS_CACHE_MAX_AGE_DAYS = 7  # 四半期開示なので短命なキャッシュで十分


class JQuantsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("JQUANTS_API_KEY")

    def _get(self, path: str, params: dict) -> list[dict]:
        """ページネーションを自動で辿り、data配列を全部連結して返す。

        無料プランは短時間の大量リクエストで429(レート制限)を返してくる
        (多銘柄を連続取得するバックテストの前処理で頻発を確認)。
        Retry-Afterヘッダがあればそれに従い、無ければ指数バックオフで
        最大5回まで再試行する。
        """
        if not self.api_key:
            raise RuntimeError(
                "JQUANTS_API_KEY が設定されていません。.env を確認してください"
                "(https://jpx-jquants.com/dashboard/api-keys でAPIキーを発行できます)。"
            )
        results: list[dict] = []
        query = dict(params)
        while True:
            for attempt in range(5):
                resp = requests.get(
                    f"{BASE_URL}{path}",
                    headers={"x-api-key": self.api_key},
                    params=query,
                    timeout=20,
                )
                if resp.status_code == 429 and attempt < 4:
                    wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            body = resp.json()
            results += body.get("data", [])
            pagination_key = body.get("pagination_key")
            if not pagination_key:
                break
            query = dict(params, pagination_key=pagination_key)
        return results

    def get_daily_quotes(self, code: str, days: int = 120) -> pd.DataFrame:
        """指定銘柄の日次株価(調整済みOHLCV)を取得してDataFrameで返す。"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self._get("/equities/bars/daily", {"code": code, "from": date_from})
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        # 調整済み四本値(AdjO/AdjH/AdjL/AdjC/AdjVo)を採用。yfinance側のauto_adjust=Trueと基準を揃える
        df = df.rename(
            columns={
                "AdjO": "Open",
                "AdjH": "High",
                "AdjL": "Low",
                "AdjC": "Close",
                "AdjVo": "Volume",
            }
        )
        return df.sort_values("Date")[["Date", "Open", "High", "Low", "Close", "Volume"]].reset_index(drop=True)

    def get_all_statements(self, code: str, use_cache: bool = True) -> list[dict]:
        """開示された財務諸表(サマリー)を全件(開示日付き)取得する。

        先読みバイアスを避けたポイントインタイム集計(get_statement_as_of)の
        元データ。四半期ごとの開示なので短命キャッシュ(既定7日)をディスクに持つ。
        """
        cache_path = STATEMENTS_CACHE_DIR / f"{code}.json"
        if use_cache and cache_path.exists():
            cached = json.loads(cache_path.read_text())
            age_days = (time.time() - cached["fetched_at"]) / 86400
            if age_days < STATEMENTS_CACHE_MAX_AGE_DAYS:
                return cached["statements"]

        statements = self._get("/fins/summary", {"code": code})
        statements = sorted(statements, key=lambda s: s.get("DiscDate", ""))

        if use_cache:
            STATEMENTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"fetched_at": time.time(), "statements": statements}, ensure_ascii=False)
            )
        return statements

    def get_statements(self, code: str) -> dict:
        """財務諸表の概要(直近開示分)を取得する。"""
        statements = self.get_all_statements(code)
        return statements[-1] if statements else {}

    def get_statement_as_of(self, code: str, as_of_date: str) -> tuple[dict, list[dict]]:
        """as_of_date(YYYY-MM-DD)時点で『開示済みだった』最新の財務諸表を返す。

        as_of_dateより後に開示されたものは一切見ない(先読みバイアス回避)。
        戻り値は (直近開示, その時点までの開示履歴全部)。履歴は増収率計算で
        直近の通期実績を探すのに使う。該当する開示が無ければ({}、[])。
        """
        statements = self.get_all_statements(code)
        disclosed = [s for s in statements if s.get("DiscDate", "") <= as_of_date]
        if not disclosed:
            return {}, []
        return disclosed[-1], disclosed

    @staticmethod
    def _normalize_statement(stmt: dict, code: str, history: list[dict] | None = None) -> dict:
        """財務諸表1件をスコアリング共通スキーマに正規化する(価格を含まない部分)。

        V2 /fins/summary のフィールドは全て文字列(空文字は欠損)で返る。

        増収率(revenue_growth_pct)は『今期予想売上高(FSales)』を、四半期累計の
        Salesではなく『直近の通期実績売上高』と比較する。FSalesは通期ベースの
        予想なので、四半期累計(例: 上期で通期の半分程度)と単純に比較すると
        分母が小さすぎて増収率が実態より大きく出てしまうため(例: 実際に約2%成長の
        ケースで計算上97%と出た実例あり)。historyを渡さない場合はこの補正はできない。
        """
        if not stmt:
            return {}

        def _to_float(key: str, source: dict = stmt) -> Optional[float]:
            val = source.get(key)
            try:
                return float(val) if val not in (None, "") else None
            except (TypeError, ValueError):
                return None

        eps = _to_float("EPS")
        bps = _to_float("BPS")
        profit = _to_float("NP")
        equity = _to_float("Eq")
        revenue = _to_float("Sales")
        forecast_revenue = _to_float("FSales")

        roe = (profit / equity * 100) if profit and equity else None
        # 利益率は同一開示内のNP/Salesなので期間基準が揃っており、増収率のような
        # 通期予想 vs 四半期累計のズレは起きない
        profit_margin = (profit / revenue * 100) if profit is not None and revenue else None

        prior_fy_revenue = None
        if history:
            for s in reversed(history):
                if s.get("CurPerType") == "FY" and s.get("DiscDate", "") <= stmt.get("DiscDate", ""):
                    prior_fy_revenue = _to_float("Sales", source=s)
                    break
        revenue_growth = (
            (forecast_revenue / prior_fy_revenue - 1) * 100
            if forecast_revenue and prior_fy_revenue
            else None
        )

        return {
            "code": code,
            "eps": eps,
            "bps": bps,
            "roe": roe,
            "revenue_growth_pct": revenue_growth,
            "profit_margin_pct": profit_margin,
            "disclosed_date": stmt.get("DiscDate"),
        }

    def fetch_fundamentals(self, code: str) -> dict:
        """スコアリングで使う共通スキーマに正規化して返す(直近開示分、現在時点用)。"""
        statements = self.get_all_statements(code)
        if not statements:
            return {}
        return self._normalize_statement(statements[-1], code, history=statements)

    def fetch_fundamentals_as_of(self, code: str, as_of_date: str, price: Optional[float] = None) -> dict:
        """as_of_date時点で開示済みだった財務データをスコアリング用に正規化する。

        バックテストのポイントインタイム検証用(未来の開示を混入させない)。
        priceを渡すと、その時点の株価とeps/bpsから当時のPER/PBRも算出する
        (fundamentals.pyのscore_fundamentals()が使う指標に合わせる)。
        """
        stmt, history = self.get_statement_as_of(code, as_of_date)
        result = self._normalize_statement(stmt, code, history=history)
        if not result:
            return result
        if price is not None:
            eps, bps = result.get("eps"), result.get("bps")
            result["per"] = round(price / eps, 2) if eps and eps > 0 else None
            result["pbr"] = round(price / bps, 2) if bps and bps > 0 else None
        return result
