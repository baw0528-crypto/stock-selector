"""J-Quants API クライアント。

日本株の日次株価と財務情報(概要)を取得する。
無料プランでもエンドポイントは使えるが、取得可能な期間・項目に制限がある。
公式ドキュメント: https://jpx-jquants.com/
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
import pandas as pd

BASE_URL = "https://api.jquants.com/v1"


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

    def get_statements(self, code: str) -> dict:
        """財務諸表の概要(直近開示分)を取得する。"""
        data = self._get("/fins/statements", {"code": code})
        statements = data.get("statements", [])
        if not statements:
            return {}
        latest = sorted(statements, key=lambda s: s.get("DisclosedDate", ""))[-1]
        return latest

    def fetch_fundamentals(self, code: str) -> dict:
        """スコアリングで使う共通スキーマに正規化して返す。"""
        stmt = self.get_statements(code)
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
