"""過去データでテクニカル因子のみをバックテストする。

なぜテクニカルだけか: ファンダメンタルズ(PER/ROE等)とニュースは
「その時点で実際どういう値だったか」を無料API(yfinance等)では取得できず、
過去日付に現在の値を当てはめると未来の情報が過去に漏れる「先読みバイアス」に
なるため、検証として無効になる。テクニカルは価格履歴からその日時点で
再現計算できるので、過去の任意の時点をエントリー日として遡って
何度もシミュレーションできる。

やっていること: 過去N年の株価データを使い、一定間隔(既定5営業日=週次)の
リバランス日ごとに、その時点までの価格データだけでテクニカルスコアを計算し
(未来のデータは一切参照しない)、上位num_ticker銘柄を仮想エントリー。
その後の値動きに track_positions.py と全く同じ利確/損切り/時間切れルール
(evaluate_exit)を適用してクローズを判定する。ライブのペーパートレードと
同じ物差しで、はるかに多いトレード数を素早く集められる。

売買は一切行わない。集計結果の表示のみ。

使い方:
    python backtest_technical.py --universe sp600 --years 2
    python backtest_technical.py --universe sp600 --max-tickers 50  # 動作確認用に絞る
"""
from __future__ import annotations

import argparse

import pandas as pd

from src.analysis.technicals import score_technicals
from src.data import us_market_client
from track_positions import compute_stats, evaluate_exit, DEFAULT_TP_PCT, DEFAULT_SL_PCT, DEFAULT_MAX_HOLD_DAYS

WARMUP_BARS = 252  # 52週高値・MA75を安定させるための最低助走期間(約1年)


def _to_bars(df: pd.DataFrame) -> list[dict]:
    """DataFrame(Date/Open/High/Low/Close)をevaluate_exit()が読める形式に変換する。"""
    return [
        {
            "date": str(row["Date"])[:10],
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        }
        for _, row in df.iterrows()
    ]


def run_backtest(
    price_map: dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame,
    top_n: int,
    rebalance_days: int,
    tp_pct: float,
    sl_pct: float,
    max_hold_days: int,
) -> tuple[list[dict], int]:
    """リバランス日ごとに上位top_n銘柄を仮想エントリーし、クローズ済みトレード一覧を返す。"""
    bench_dates = benchmark_df["Date"].tolist()
    n_dates = len(bench_dates)

    rebalance_range = range(WARMUP_BARS, n_dates - max_hold_days - 1, rebalance_days)
    trades: list[dict] = []

    for step, idx in enumerate(rebalance_range, start=1):
        as_of_date = bench_dates[idx]
        bench_upto = benchmark_df.iloc[: idx + 1]

        scored = []
        for ticker, df in price_map.items():
            pos = df["Date"].searchsorted(as_of_date, side="right") - 1
            if pos < WARMUP_BARS or pos >= len(df) - max_hold_days:
                continue
            if df["Date"].iloc[pos] != as_of_date:
                continue  # この銘柄はこの日に取引データが無い(新規上場/欠損等)
            df_upto = df.iloc[: pos + 1]
            score = score_technicals(df_upto, benchmark_df=bench_upto)["score"]
            scored.append((ticker, pos, score))

        scored.sort(key=lambda x: x[2], reverse=True)
        for ticker, pos, score in scored[:top_n]:
            df = price_map[ticker]
            entry_price = float(df["Close"].iloc[pos])
            future_bars = _to_bars(df.iloc[pos + 1 : pos + 1 + max_hold_days + 5])
            exit_info = evaluate_exit(entry_price, future_bars, tp_pct, sl_pct, max_hold_days)
            if exit_info is None:
                continue  # データ不足で判定できなかった(まれ)
            pnl = (exit_info["exit_price"] / entry_price - 1) * 100
            trades.append(
                {
                    "ticker": ticker,
                    "entered_at": str(as_of_date)[:10],
                    "entry_price": round(entry_price, 4),
                    "score": round(score, 1),
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
    parser.add_argument(
        "--universe", choices=["sp500", "sp400", "sp600", "sp1500"], default="sp600",
        help="対象ユニバース(デフォルト: sp600、アグレッシブ戦略と同じ小型株)",
    )
    parser.add_argument("--years", type=int, default=2, help="遡る年数(デフォルト2年)")
    parser.add_argument("--top-n", type=int, default=3, help="リバランス日ごとに仮想エントリーする銘柄数")
    parser.add_argument("--rebalance-days", type=int, default=5, help="リバランス間隔(営業日、デフォルト5=週次)")
    parser.add_argument("--tp", type=float, default=DEFAULT_TP_PCT, help="利確ライン%%")
    parser.add_argument("--sl", type=float, default=DEFAULT_SL_PCT, help="損切りライン%%")
    parser.add_argument("--max-hold", type=int, default=DEFAULT_MAX_HOLD_DAYS, help="最大保有営業日数")
    parser.add_argument("--max-tickers", type=int, default=None, help="動作確認用にユニバースを先頭N銘柄に絞る")
    args = parser.parse_args()

    tickers = us_market_client.get_universe_tickers(args.universe)
    if args.max_tickers:
        tickers = tickers[: args.max_tickers]
    print(f"ユニバース: {args.universe} ({len(tickers)}銘柄) / 期間: 過去{args.years}年")

    print("価格データを一括取得中(数分かかることがあります)...")
    price_map = us_market_client.get_price_histories(tickers, period=f"{args.years}y")
    benchmark_df = us_market_client.get_price_history("SPY", period=f"{args.years}y")
    print(f"取得成功: {len(price_map)}/{len(tickers)}銘柄")

    # 取得元(単一/一括)でtzの有無が揺れることがあるため、日付比較の前にtz-naiveへ統一する
    def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        dates = pd.to_datetime(df["Date"])
        df["Date"] = dates.dt.tz_localize(None) if dates.dt.tz is not None else dates
        return df

    benchmark_df = _strip_tz(benchmark_df)
    price_map = {ticker: _strip_tz(df) for ticker, df in price_map.items()}

    if benchmark_df.empty or len(benchmark_df) < WARMUP_BARS + args.max_hold + 10:
        print("[error] ベンチマーク(SPY)のデータが不足しています。--yearsを増やしてください。")
        return

    print(
        f"バックテスト実行中(リバランス間隔{args.rebalance_days}営業日、"
        f"毎回上位{args.top_n}銘柄をエントリー)..."
    )
    trades, n_rebalances = run_backtest(
        price_map, benchmark_df, args.top_n, args.rebalance_days, args.tp, args.sl, args.max_hold
    )

    print(f"\nリバランス {n_rebalances}回 / トレード {len(trades)}件")
    print(
        f"ルール: 利確{args.tp:+.0f}% / 損切り{args.sl:+.0f}% / 最大{args.max_hold}営業日"
        f"(track_positions.pyと同一ロジック)"
    )
    print("※ テクニカル因子のみのバックテスト。ファンダ・ニュースは含まない(先読みバイアス回避のため)")

    stats = compute_stats(trades)
    if stats["trades"] == 0:
        print("\nトレードが発生しませんでした。--years を増やすか --max-tickers を確認してください。")
        return

    print(f"\n=== 成績 ===")
    print(f"トレード数: {stats['trades']} / 勝率: {stats['win_rate_pct']}%")
    print(
        f"平均損益: {stats['avg_pnl_pct']:+.2f}% "
        f"(勝ち平均 {stats['avg_win_pct']}% / 負け平均 {stats['avg_loss_pct']}%)"
    )
    if stats["profit_factor"] is not None:
        print(f"プロフィットファクター: {stats['profit_factor']}")
    print(f"平均保有: {stats['avg_days_held']}営業日 / 決済内訳: {stats['exit_reasons']}")


if __name__ == "__main__":
    main()
