"""日本株:テクニカル+ファンダメンタルズを合成したバックテスト。

backtest_technical.py(米国株、テクニカルのみ)との違い: J-Quantsは開示日
(DiscDate)付きで財務データを返すため、米国株(yfinanceは現在のスナップショット
のみ)と違って日本株はファンダメンタルズも先読みバイアス無しで過去に遡って
検証できる。ニュースは(Google News RSSに履歴が無く先読みバイアスになるため)
引き続き対象外。テクニカル判定は米国株と同じscore_technicals()、エントリー/
エグジットの判定もtrack_positions.pyのevaluate_exit()と完全に同一ロジック。

売買は一切行わない。集計結果の表示のみ。

使い方:
    python backtest_jp_fundamental.py --market jp --years 2
    python backtest_jp_fundamental.py --market jp-growth --max-tickers 30  # 動作確認用
"""
from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
from dotenv import load_dotenv

from backtest_technical import WARMUP_BARS, _to_bars, analyze_quality
from src.analysis.fundamentals import score_fundamentals
from src.analysis.technicals import score_technicals
from src.data import us_market_client
from src.data.jquants_client import JQuantsClient, STATEMENTS_CACHE_DIR
from track_positions import (
    compute_stats,
    evaluate_exit,
    evaluate_exit_trailing,
    DEFAULT_TP_PCT,
    DEFAULT_SL_PCT,
    DEFAULT_MAX_HOLD_DAYS,
    DEFAULT_TRAIL_START_PCT,
    DEFAULT_TRAIL_PCT,
)

load_dotenv()


def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    dates = pd.to_datetime(df["Date"])
    df["Date"] = dates.dt.tz_localize(None) if dates.dt.tz is not None else dates
    return df


def prefetch_statements(client: JQuantsClient, codes: list[str]) -> dict[str, list[dict]]:
    """全銘柄の財務開示履歴を先に(1銘柄1回だけ)取得しておく。

    リバランス日ごとに叩くと同じ銘柄に何十回もAPIリクエストすることになるため、
    先に全履歴をキャッシュ付きで取得し、以後はメモリ内でas_of_dateによる
    絞り込みだけを行う。
    """
    history: dict[str, list[dict]] = {}
    for i, code in enumerate(codes, start=1):
        was_cached = (STATEMENTS_CACHE_DIR / f"{code}.json").exists()
        try:
            history[code] = client.get_all_statements(code)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] {code}: 財務データ取得失敗 ({e})")
            history[code] = []
        if not was_cached:
            time.sleep(0.5)  # 無料プランのレート制限対策(429頻発を確認済み)
        if i % 50 == 0 or i == len(codes):
            print(f"  財務データ取得中... {i}/{len(codes)}")
    return history


def fundamentals_as_of(
    client: JQuantsClient, code: str, history: list[dict], as_of_date: str, price: float | None
) -> dict:
    """prefetch済みhistoryからas_of_date時点の財務をその場で正規化する(API通信なし)。"""
    disclosed = [s for s in history if s.get("DiscDate", "") <= as_of_date]
    if not disclosed:
        return {}
    stmt = disclosed[-1]
    result = client._normalize_statement(stmt, code, history=disclosed)
    if not result:
        return result
    if price is not None:
        eps, bps = result.get("eps"), result.get("bps")
        result["per"] = round(price / eps, 2) if eps and eps > 0 else None
        result["pbr"] = round(price / bps, 2) if bps and bps > 0 else None
    return result


def run_backtest(
    price_map: dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame,
    statements: dict[str, list[dict]],
    client: JQuantsClient,
    top_n: int,
    rebalance_days: int,
    weight_fundamental: float,
    weight_technical: float,
    tp_pct: float,
    sl_pct: float,
    max_hold_days: int,
    exit_style: str = "fixed",
    trail_start_pct: float = DEFAULT_TRAIL_START_PCT,
    trail_pct: float = DEFAULT_TRAIL_PCT,
) -> tuple[list[dict], int]:
    bench_dates = benchmark_df["Date"].tolist()
    n_dates = len(bench_dates)
    rebalance_range = range(WARMUP_BARS, n_dates - max_hold_days - 1, rebalance_days)
    trades: list[dict] = []

    w_sum = weight_fundamental + weight_technical
    w_fund, w_tech = weight_fundamental / w_sum, weight_technical / w_sum

    for idx in rebalance_range:
        as_of_date = bench_dates[idx]
        as_of_str = str(as_of_date)[:10]
        bench_upto = benchmark_df.iloc[: idx + 1]

        scored = []
        for ticker, df in price_map.items():
            code = ticker.replace(".T", "")
            pos = df["Date"].searchsorted(as_of_date, side="right") - 1
            if pos < WARMUP_BARS or pos >= len(df) - max_hold_days:
                continue
            if df["Date"].iloc[pos] != as_of_date:
                continue
            df_upto = df.iloc[: pos + 1]
            tech_score = score_technicals(df_upto, benchmark_df=bench_upto)["score"]
            price = float(df_upto["Close"].iloc[-1])
            fund_data = fundamentals_as_of(client, code, statements.get(code, []), as_of_str, price)
            fund_score = score_fundamentals(fund_data)["score"]
            composite = w_tech * tech_score + w_fund * fund_score
            scored.append((ticker, pos, composite, tech_score, fund_score))

        scored.sort(key=lambda x: x[2], reverse=True)

        for rank, (ticker, pos, composite, tech_score, fund_score) in enumerate(scored[:top_n], start=1):
            df = price_map[ticker]
            entry_price = float(df["Close"].iloc[pos])
            future_bars = _to_bars(df.iloc[pos + 1 : pos + 1 + max_hold_days + 5])
            if exit_style == "trailing":
                exit_info = evaluate_exit_trailing(
                    entry_price, future_bars, trail_start_pct, trail_pct, sl_pct, max_hold_days
                )
            else:
                exit_info = evaluate_exit(entry_price, future_bars, tp_pct, sl_pct, max_hold_days)
            if exit_info is None:
                continue
            pnl = (exit_info["exit_price"] / entry_price - 1) * 100
            trades.append(
                {
                    "ticker": ticker,
                    "entered_at": as_of_str,
                    "entry_price": round(entry_price, 4),
                    "entry_rank": rank,
                    "composite_score": round(composite, 1),
                    "day_top_score": round(scored[0][2], 1) if scored else None,
                    "tech_score": round(tech_score, 1),
                    "fund_score": round(fund_score, 1),
                    "closed_at": exit_info["exit_date"],
                    "exit_price": round(exit_info["exit_price"], 4),
                    "exit_reason": exit_info["exit_reason"],
                    "pnl_pct": round(pnl, 2),
                    "days_held": exit_info["days_held"],
                }
            )

    return trades, len(list(rebalance_range))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=["jp", "jp-growth"], default="jp", help="jp=日経225 / jp-growth=東証グロース250")
    parser.add_argument("--years", type=int, default=2, help="遡る年数(J-Quants無料プランの実質上限は2年)")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--rebalance-days", type=int, default=5)
    parser.add_argument("--weight-fundamental", type=float, default=0.5)
    parser.add_argument("--weight-technical", type=float, default=0.5)
    parser.add_argument("--tp", type=float, default=DEFAULT_TP_PCT)
    parser.add_argument("--sl", type=float, default=DEFAULT_SL_PCT)
    parser.add_argument("--max-hold", type=int, default=DEFAULT_MAX_HOLD_DAYS)
    parser.add_argument("--exit-style", choices=["fixed", "trailing"], default="fixed")
    parser.add_argument("--trail-start", type=float, default=DEFAULT_TRAIL_START_PCT)
    parser.add_argument("--trail-pct", type=float, default=DEFAULT_TRAIL_PCT)
    parser.add_argument("--max-tickers", type=int, default=None, help="動作確認用にユニバースを先頭N銘柄に絞る")
    args = parser.parse_args()

    client = JQuantsClient()
    if not client.api_key:
        print("[error] JQUANTS_API_KEY が設定されていません。.env を確認してください。")
        sys.exit(1)

    if args.market == "jp":
        codes = us_market_client.get_nikkei225_tickers()
        universe_label = "nikkei225"
    else:
        codes = us_market_client.get_tse_growth250_tickers()
        universe_label = "tse-growth250"
    if args.max_tickers:
        codes = codes[: args.max_tickers]
    tickers = [f"{c}.T" for c in codes]
    print(f"ユニバース: {universe_label} ({len(tickers)}銘柄) / 期間: 過去{args.years}年")

    print("価格データを一括取得中(yfinance)...")
    price_map = us_market_client.get_price_histories(tickers, period=f"{args.years}y")
    benchmark_df = us_market_client.get_price_history("1321.T", period=f"{args.years}y")
    print(f"取得成功: {len(price_map)}/{len(tickers)}銘柄")

    price_map = {t: _strip_tz(df) for t, df in price_map.items()}
    benchmark_df = _strip_tz(benchmark_df)

    if benchmark_df.empty or len(benchmark_df) < WARMUP_BARS + args.max_hold + 10:
        print("[error] ベンチマークのデータが不足しています。--yearsを増やしてください。")
        return

    print(f"財務データを取得中(J-Quants、{len(codes)}銘柄・キャッシュ7日)...")
    statements = prefetch_statements(client, codes)
    n_with_data = sum(1 for h in statements.values() if h)
    print(f"財務データ取得成功: {n_with_data}/{len(codes)}銘柄")

    print(
        f"バックテスト実行中(リバランス間隔{args.rebalance_days}営業日、"
        f"毎回上位{args.top_n}銘柄、重み ファンダ{args.weight_fundamental}/テクニカル{args.weight_technical})..."
    )
    trades, n_rebalances = run_backtest(
        price_map, benchmark_df, statements, client,
        args.top_n, args.rebalance_days, args.weight_fundamental, args.weight_technical,
        args.tp, args.sl, args.max_hold,
        exit_style=args.exit_style, trail_start_pct=args.trail_start, trail_pct=args.trail_pct,
    )

    print(f"\nリバランス {n_rebalances}回 / トレード {len(trades)}件")
    if args.exit_style == "trailing":
        print(f"ルール: 含み益+{args.trail_start:.0f}%でトレーリング開始(高値から-{args.trail_pct:.0f}%で手仕舞い) / 初期損切り{args.sl:+.0f}% / 最大{args.max_hold}営業日")
    else:
        print(f"ルール: 利確{args.tp:+.0f}% / 損切り{args.sl:+.0f}% / 最大{args.max_hold}営業日")
    print("※ テクニカル+ファンダメンタルズ合成(ニュースは対象外・先読みバイアス回避のため)")

    stats = compute_stats(trades)
    if stats["trades"] == 0:
        print("\nトレードが発生しませんでした。")
        return

    print("\n=== 成績 ===")
    print(f"トレード数: {stats['trades']} / 勝率: {stats['win_rate_pct']}%")
    print(f"平均損益: {stats['avg_pnl_pct']:+.2f}% (勝ち平均 {stats['avg_win_pct']}% / 負け平均 {stats['avg_loss_pct']}%)")
    if stats["profit_factor"] is not None:
        print(f"プロフィットファクター: {stats['profit_factor']}")
    print(f"平均保有: {stats['avg_days_held']}営業日 / 決済内訳: {stats['exit_reasons']}")

    print("\n=== ファンダ寄与の検証(テクニカルのみとの比較用) ===")
    analyze_quality(trades, "fund_score", "ファンダスコア")
    analyze_quality(trades, "tech_score", "テクニカルスコア")
    analyze_quality(trades, "composite_score", "合成スコア")


if __name__ == "__main__":
    main()
