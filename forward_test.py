"""過去のスクリーニング結果(output/report_*.json)をフォワードテストする。

各スナップショット時点の総合スコアと、その後N営業日の実リターンを
突き合わせ、「スコア上位群は実際にその後も上位だったか」を集計する。
過去に遡るシミュレーション(バックテスト)ではなく、実際に出力した
レポートの事後検証。スナップショットが貯まるほど集計の意味が出る。

売買の発注は一切行わない。集計結果の表示のみ。

使い方:
    python forward_test.py                 # デフォルト: 5営業日と20営業日
    python forward_test.py --horizons 10,60
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

BENCHMARK = "SPY"
MIN_CANDIDATES = 5  # これ未満のスナップショットは分位集計が無意味なので除外


def yf_symbol(candidate: dict) -> str:
    if candidate["market"] == "jp":
        return f"{candidate['code']}.T"
    return candidate["code"]


def load_snapshots(output_dir: str = "output") -> list[dict]:
    snapshots = []
    for path in sorted(Path(output_dir).glob("report_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] {path.name} を読めませんでした ({e})")
            continue
        candidates = [c for c in data.get("candidates", []) if c.get("has_price_data")]
        if len(candidates) < MIN_CANDIDATES:
            print(f"[info] {path.name}: 評価銘柄が{len(candidates)}件しかないため集計から除外")
            continue
        snapshots.append(
            {
                "file": path.name,
                "date": data["meta"]["generated_at"][:10],
                "weights": data["meta"].get("weights"),
                # score_versionが無い古いスナップショットはv1(初期ロジック)とみなす
                "score_version": data["meta"].get("score_version", 1),
                "candidates": candidates,
            }
        )
    return snapshots


def fetch_closes(symbols: list[str], start: str) -> pd.DataFrame:
    """調整後終値をまとめて取得し、銘柄を列とするDataFrameで返す。"""
    data = yf.download(symbols, start=start, auto_adjust=True, progress=False, threads=True)
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        closes = data["Close"]
    else:
        closes = data[["Close"]]
        closes.columns = [symbols[0]]
    closes.index = pd.DatetimeIndex(closes.index).tz_localize(None)
    return closes


def forward_return_pct(closes: pd.DataFrame, symbol: str, date: str, horizon: int) -> float | None:
    """スナップショット日以降の最初の営業日を起点に、horizon営業日後のリターン(%)。"""
    if symbol not in closes.columns:
        return None
    series = closes[symbol].dropna()
    idx = series.index.searchsorted(pd.Timestamp(date))
    if idx >= len(series) or idx + horizon >= len(series):
        return None  # まだhorizon分の日数が経過していない
    return float(series.iloc[idx + horizon] / series.iloc[idx] - 1) * 100


def build_observations(snapshots: list[dict], closes: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows = []
    for snap in snapshots:
        for c in snap["candidates"]:
            for h in horizons:
                ret = forward_return_pct(closes, yf_symbol(c), snap["date"], h)
                if ret is None:
                    continue
                rows.append(
                    {
                        "snapshot": snap["file"],
                        "date": snap["date"],
                        "code": c["code"],
                        "total_score": c["total_score"],
                        "horizon": h,
                        "return_pct": ret,
                    }
                )
    return pd.DataFrame(rows)


TERCILE_ORDER = ["スコア上位1/3", "中位1/3", "下位1/3"]


def _assign_terciles(sub: pd.DataFrame) -> pd.DataFrame:
    """スナップショット内のスコア順位で3分位ラベルを付ける(横断比較を避ける)。"""
    sub = sub.copy()
    sub["tercile"] = ""
    for _, g in sub.groupby("snapshot"):
        n = len(g)
        ranks = g["total_score"].rank(method="first", ascending=False)
        labels = pd.cut(ranks, bins=[0, n / 3, 2 * n / 3, n], labels=TERCILE_ORDER)
        sub.loc[g.index, "tercile"] = labels.astype(str)
    return sub


def summarize(df: pd.DataFrame, closes: pd.DataFrame, snapshots: list[dict], horizons: list[int]) -> None:
    for h in horizons:
        sub = df[df["horizon"] == h].copy()
        if sub.empty:
            print(f"\n=== {h}営業日後 === 観測なし(スナップショットが新しすぎる可能性)")
            continue

        sub = _assign_terciles(sub)

        print(f"\n=== {h}営業日後のフォワードリターン ===")
        print(f"スナップショット {sub['snapshot'].nunique()}本 / 観測 {len(sub)}件")
        agg = (
            sub.groupby("tercile", observed=True)["return_pct"]
            .agg(["mean", "median", "count"])
            .reindex(TERCILE_ORDER)
            .dropna(how="all")
        )
        for label, row in agg.iterrows():
            print(f"  {label}: 平均 {row['mean']:+.2f}% / 中央値 {row['median']:+.2f}% ({int(row['count'])}件)")

        # ベンチマーク(SPY)の同期間リターンを参考表示
        bench_rets = [
            r for r in (
                forward_return_pct(closes, BENCHMARK, snap["date"], h) for snap in snapshots
            ) if r is not None
        ]
        if bench_rets:
            print(f"  {BENCHMARK}(参考): 平均 {sum(bench_rets) / len(bench_rets):+.2f}%")

        # スコアと事後リターンの順位相関(スナップショットごとに算出して平均)
        corrs = []
        for _, g in sub.groupby("snapshot"):
            if len(g) >= MIN_CANDIDATES:
                # 順位に変換してPearson相関 = Spearman相関(scipy不要の等価計算)
                corrs.append(g["total_score"].rank().corr(g["return_pct"].rank()))
        if corrs:
            mean_corr = sum(corrs) / len(corrs)
            print(f"  スコアと事後リターンの順位相関(Spearman平均): {mean_corr:+.3f}")
            print("    (目安: +0.1超なら並べ替えに意味がある兆し、0近辺ならランダムと区別つかず)")


def main():
    parser = argparse.ArgumentParser(description="スクリーニング結果のフォワードテスト集計")
    parser.add_argument("--horizons", type=str, default="5,20", help="カンマ区切りの営業日数 (例: 5,20,60)")
    parser.add_argument("--output-dir", type=str, default="output")
    args = parser.parse_args()
    horizons = sorted({int(h) for h in args.horizons.split(",")})

    snapshots = load_snapshots(args.output_dir)
    if not snapshots:
        print("集計対象のスナップショット(output/report_*.json)がありません。")
        print("screen.py を実行するとJSONスナップショットが保存され、日を置いてから検証できます。")
        return
    print(f"スナップショット {len(snapshots)}本を読み込みました ({snapshots[0]['date']} 〜 {snapshots[-1]['date']})")

    versions = sorted({s["score_version"] for s in snapshots})
    if len(versions) > 1:
        counts = {v: sum(1 for s in snapshots if s["score_version"] == v) for v in versions}
        print(
            f"[warn] スコアリングロジックの異なるバージョンが混在しています "
            f"({', '.join(f'v{v}: {n}本' for v, n in counts.items())})。"
        )
        print("       相関の解釈時は注意してください。バージョン別に見たい場合はoutput/を分けて集計してください。")

    symbols = sorted({yf_symbol(c) for snap in snapshots for c in snap["candidates"]} | {BENCHMARK})
    start = min(snap["date"] for snap in snapshots)
    print(f"{len(symbols)}銘柄の価格履歴を取得中...")
    closes = fetch_closes(symbols, start=start)
    if closes.empty:
        print("[error] 価格データを取得できませんでした。ネットワーク接続を確認してください。")
        return

    df = build_observations(snapshots, closes, horizons)
    if df.empty:
        print("まだどのホライズンも経過日数が足りません。日を置いて再実行してください。")
        return
    summarize(df, closes, snapshots, horizons)


if __name__ == "__main__":
    main()
