"""J-Quants API クライアント。

日本株の日次株価と財務情報(概要)を取得する。
無料プランでもエンドポイントは使えるが、取得可能な期間・項目に制限がある
(株価: 直近12週間を除く過去2年分 / 財務: サマリーのみ2年分、詳細BS/PL/CFは
スタンダード以上が必要)。ライブの当日銘柄選定には使えないが、12週間より前の
期間を対象にしたバックテストなら無料プランのままで問題ない。
公式ドキュメント: https://jpx-jquants.com/
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

BASE_URL = "https://api.jquants.com/v1"
STATEMENTS_CACHE_DIR = Path("data_cache/jquants_statements")
STATEMENTS_CACHE_MAX_AGE_DAYS = 7  # 四半期開示なので短命なキャッシュで十分


class JQuantsClient:
    def __init__(self, mail: Optional[str] = None, password: Optional[str] = None):
        self.mail = mail or os.getenv("JQUANTS_MAIL")
        self.password = password or os.getenv("JQUANTS_PASSWORD")
        self._id_token: Optional[str] = None
        self._id_token_expiry: float = 0.0

    def _get_id_token(self) -> str:
        """refresh token -> id tokenの順で認証する。idトークンは約24時間有効。"""
        if self._id_token and time.time() < self._id_token_expiry:
            return self._id_token

        if not self.mail or not self.password:
            raise RuntimeError(
                "JQUANTS_MAIL / JQUANTS_PASSWORD が設定されていません。.env を確認してください。"
            )

        auth_resp = requests.post(
            f"{BASE_URL}/token/auth_user",
            json={"mailaddress": self.mail, "password": self.password},
            timeout=15,
        )
        auth_resp.raise_for_status()
        refresh_token = auth_resp.json()["refreshToken"]

        refresh_resp = requests.post(
            f"{BASE_URL}/token/auth_refresh?refreshtoken={refresh_token}",
            timeout=15,
        )
        refresh_resp.raise_for_status()
        self._id_token = refresh_resp.json()["idToken"]
        self._id_token_expiry = time.time() + 23 * 3600
        return self._id_token

    def _get(self, path: str, params: dict) -> dict:
        token = self._get_id_token()
        resp = requests.get(
            f"{BASE_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def get_daily_quotes(self, code: str, days: int = 120) -> pd.DataFrame:
        """指定銘柄の日次株価(OHLCV)を取得してDataFrameで返す。"""
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = self._get("/prices/daily_quotes", {"code": code, "from": date_from})
        quotes = data.get("daily_quotes", [])
        if not quotes:
            return pd.DataFrame()
        df = pd.DataFrame(quotes)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.rename(
            columns={
                "Open": "Open",
                "High": "High",
                "Low": "Low",
                "Close": "Close",
                "Volume": "Volume",
            }
        )
        return df.sort_values("Date").reset_index(drop=True)

    def get_all_statements(self, code: str, use_cache: bool = True) -> list[dict]:
        """開示された財務諸表を全件(開示日付き)取得する。

        先読みバイアスを避けたポイントインタイム集計(get_statements_as_of)の
        元データ。四半期ごとの開示なので短命キャッシュ(既定7日)をディスクに持つ。
        """
        cache_path = STATEMENTS_CACHE_DIR / f"{code}.json"
        if use_cache and cache_path.exists():
            cached = json.loads(cache_path.read_text())
            age_days = (time.time() - cached["fetched_at"]) / 86400
            if age_days < STATEMENTS_CACHE_MAX_AGE_DAYS:
                return cached["statements"]

        data = self._get("/fins/statements", {"code": code})
        statements = data.get("statements", [])
        statements = sorted(statements, key=lambda s: s.get("DisclosedDate", ""))

        if use_cache:
            STATEMENTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"fetched_at": time.time(), "statements": statements}, ensure_ascii=False)
            )
        return statements

    def get_statements(self, code: str) -> dict:
        """財務諸表の概要(直近開示分)を取得する。後方互換のため残す。"""
        statements = self.get_all_statements(code)
        return statements[-1] if statements else {}

    def get_statement_as_of(self, code: str, as_of_date: str) -> dict:
        """as_of_date(YYYY-MM-DD)時点で『開示済みだった』最新の財務諸表を返す。

        as_of_dateより後に開示されたものは一切見ない(先読みバイアス回避)。
        該当する開示が無ければ空dict。
        """
        statements = self.get_all_statements(code)
        disclosed = [s for s in statements if s.get("DisclosedDate", "") <= as_of_date]
        return disclosed[-1] if disclosed else {}

    @staticmethod
    def _normalize_statement(stmt: dict, code: str) -> dict:
        """財務諸表1件をスコアリング共通スキーマに正規化する(価格を含まない部分)。"""
        if not stmt:
            return {}

        def _to_float(key: str) -> Optional[float]:
            val = stmt.get(key)
            try:
                return float(val) if val not in (None, "") else None
            except (TypeError, ValueError):
                return None

        eps = _to_float("EarningsPerShare")
        bps = _to_float("BookValuePerShare")
        profit = _to_float("Profit")
        equity = _to_float("Equity")
        revenue = _to_float("NetSales")
        forecast_revenue = _to_float("ForecastNetSales")

        roe = (profit / equity * 100) if profit and equity else None
        revenue_growth = (
            (forecast_revenue / revenue - 1) * 100
            if forecast_revenue and revenue
            else None
        )

        return {
            "code": code,
            "eps": eps,
            "bps": bps,
            "roe": roe,
            "revenue_growth_pct": revenue_growth,
            "disclosed_date": stmt.get("DisclosedDate"),
        }

    def fetch_fundamentals(self, code: str) -> dict:
        """スコアリングで使う共通スキーマに正規化して返す(直近開示分、現在時点用)。"""
        return self._normalize_statement(self.get_statements(code), code)

    def fetch_fundamentals_as_of(self, code: str, as_of_date: str, price: Optional[float] = None) -> dict:
        """as_of_date時点で開示済みだった財務データをスコアリング用に正規化する。

        バックテストのポイントインタイム検証用(未来の開示を混入させない)。
        priceを渡すと、その時点の株価とeps/bpsから当時のPER/PBRも算出する
        (fundamentals.pyのscore_fundamentals()が使う指標に合わせる)。
        """
        stmt = self.get_statement_as_of(code, as_of_date)
        result = self._normalize_statement(stmt, code)
        if not result:
            return result
        if price is not None:
            eps, bps = result.get("eps"), result.get("bps")
            result["per"] = round(price / eps, 2) if eps and eps > 0 else None
            result["pbr"] = round(price / bps, 2) if bps and bps > 0 else None
        return result
