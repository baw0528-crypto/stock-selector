"""スクリーニング上位銘柄の仮想エントリーと利確/損切り監視(ペーパートレード)。

実際の発注は一切行わない。スクリーニングの選定が「実際に買っていたら
どうだったか」を検証するための仮想ポジション管理と成績集計のみ。

ルール(デフォルト、引数で変更可):
- エントリー: 最新レポートの上位N銘柄を前日終値で仮想購入(同銘柄の重複保有はしない)
- 利確: +10% / 損切り: -7% / 時間切れ: 20営業日で終値クローズ
- 日次OHLCで判定。同日に利確・損切り両方に触れた場合は損切り優先(保守的)。
  ギャップで閾値を飛び越えた場合は寄り値で約定したとみなす(現実に近い側に倒す)

使い方:
    python track_positions.py                     # 保有中の監視・クローズ判定・成績表示
    python track_positions.py --auto-enter 3      # 最新レポート上位3銘柄を仮想エントリー
    python track_positions.py --enter NVDA        # 手動で1銘柄エントリー
    python track_positions.py --close NVDA        # 手動クローズ(現値)
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("output")
REPORT_RE = re.compile(r"^report_(\d{8}_\d{4})\.json$")


def state_file(portfolio_name: str) -> Path:
    """戦略別の状態ファイル。defaultは従来のportfolio.jsonを使う。"""
    if portfolio_name == "default":
        return OUTPUT_DIR / "portfolio.json"
    return OUTPUT_DIR / f"portfolio_{portfolio_name}.json"

DEFAULT_TP_PCT = 10.0
DEFAULT_SL_PCT = -7.0
DEFAULT_MAX_HOLD_DAYS = 20  # 営業日(価格バー数で近似)


# ---------------- 純粋ロジック(テスト対象) ----------------

def evaluate_exit(
    entry_price: float,
    bars: list[dict],
    tp_pct: float = DEFAULT_TP_PCT,
    sl_pct: float = DEFAULT_SL_PCT,
    max_hold_days: int = DEFAULT_MAX_HOLD_DAYS,
) -> dict | None:
    """エントリー後の日次バー(古い順、date/open/high/low/close)からクローズ判定する。

    クローズ条件に達していれば {exit_price, exit_reason, exit_date, days_held} を返す。
    達していなければ None(保有継続)。
    """
    tp_price = entry_price * (1 + tp_pct / 100)
    sl_price = entry_price * (1 + sl_pct / 100)

    for i, bar in enumerate(bars, start=1):
        # 寄り付きで既に閾値を飛び越えているケース(ギャップ)を先に判定
        if bar["open"] <= sl_price:
            return {"exit_price": bar["open"], "exit_reason": "sl", "exit_date": bar["date"], "days_held": i}
        if bar["open"] >= tp_price:
            return {"exit_price": bar["open"], "exit_reason": "tp", "exit_date": bar["date"], "days_held": i}
        # ザラ場中の判定。同日に両方触れた場合はどちらが先か分からないため損切り優先
        if bar["low"] <= sl_price:
            return {"exit_price": sl_price, "exit_reason": "sl", "exit_date": bar["date"], "days_held": i}
        if bar["high"] >= tp_price:
            return {"exit_price": tp_price, "exit_reason": "tp", "exit_date": bar["date"], "days_held": i}
        if i >= max_hold_days:
            return {"exit_price": bar["close"], "exit_reason": "time", "exit_date": bar["date"], "days_held": i}
    return None


DEFAULT_TRAIL_START_PCT = 1.0  # ここまで含み益が乗ったらトレーリング開始(元記事の最低利益目標)
DEFAULT_TRAIL_PCT = 5.0  # 高値からの許容下落幅(元記事のSL -5〜7%の中間)


def evaluate_exit_trailing(
    entry_price: float,
    bars: list[dict],
    trail_start_pct: float = DEFAULT_TRAIL_START_PCT,
    trail_pct: float = DEFAULT_TRAIL_PCT,
    initial_sl_pct: float = DEFAULT_SL_PCT,
    max_hold_days: int = DEFAULT_MAX_HOLD_DAYS,
) -> dict | None:
    """固定利確ではなく「最低利益を確保したらトレーリングストップで伸ばす」方式。

    参考記事(souzai.net)の設計を模したエグジット:
    - 含み益がtrail_start_pct(既定+1%)に達するまでは、初期損切りinitial_sl_pct(既定-7%)のみで守る
    - 達した後は、そこまでの高値からtrail_pct(既定5%)下落したら手仕舞う(利益を伸ばす)
    - 上限(固定TP)は設けない。トレーリングに引っかかるか、時間切れまで持ち続ける

    evaluate_exit()と同様、ギャップは寄り値で約定したとみなす。
    """
    initial_sl_price = entry_price * (1 + initial_sl_pct / 100)
    trail_start_price = entry_price * (1 + trail_start_pct / 100)
    peak_price = entry_price
    trailing_active = False

    for i, bar in enumerate(bars, start=1):
        if not trailing_active:
            # トレーリング開始前: 初期損切りのみで守る
            if bar["open"] <= initial_sl_price:
                return {
                    "exit_price": bar["open"], "exit_reason": "sl",
                    "exit_date": bar["date"], "days_held": i,
                }
            if bar["low"] <= initial_sl_price:
                return {
                    "exit_price": initial_sl_price, "exit_reason": "sl",
                    "exit_date": bar["date"], "days_held": i,
                }
            peak_price = max(peak_price, bar["high"])
            if peak_price >= trail_start_price:
                trailing_active = True
        else:
            peak_price = max(peak_price, bar["high"])
            stop_price = peak_price * (1 - trail_pct / 100)
            if bar["open"] <= stop_price:
                return {
                    "exit_price": bar["open"], "exit_reason": "trail",
                    "exit_date": bar["date"], "days_held": i,
                }
            if bar["low"] <= stop_price:
                return {
                    "exit_price": stop_price, "exit_reason": "trail",
                    "exit_date": bar["date"], "days_held": i,
                }

        if i >= max_hold_days:
            return {"exit_price": bar["close"], "exit_reason": "time", "exit_date": bar["date"], "days_held": i}
    return None


def compute_stats(closed: list[dict]) -> dict:
    """クローズ済みトレードから勝率などの成績を集計する。"""
    if not closed:
        return {"trades": 0}
    pnls = [t["pnl_pct"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    reasons = {}
    for t in closed:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    total_win = sum(wins)
    total_loss = abs(sum(losses))
    return {
        "trades": len(closed),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1),
        "avg_pnl_pct": round(sum(pnls) / len(pnls), 2),
        "avg_win_pct": round(total_win / len(wins), 2) if wins else None,
        "avg_loss_pct": round(-total_loss / len(losses), 2) if losses else None,
        "profit_factor": round(total_win / total_loss, 2) if total_loss > 0 else None,
        "avg_days_held": round(sum(t["days_held"] for t in closed) / len(closed), 1),
        "exit_reasons": reasons,
    }


# ---------------- 状態管理・データ取得 ----------------

def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"positions": [], "closed": [], "settings": {}}


def save_state(state: dict, path: Path, name: str, tp_pct: float, sl_pct: float, max_hold: int) -> None:
    state["name"] = name
    state["settings"] = {"tp_pct": tp_pct, "sl_pct": sl_pct, "max_hold_days": max_hold}
    state["stats"] = compute_stats(state["closed"])
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def latest_report() -> dict | None:
    reports = sorted(p for p in OUTPUT_DIR.glob("report_*.json") if REPORT_RE.match(p.name))
    if not reports:
        return None
    return json.loads(reports[-1].read_text(encoding="utf-8"))


def fetch_bars_since(ticker: str, since: str) -> list[dict]:
    """エントリー日より後の日次OHLCバーを古い順で返す。"""
    import pandas as pd
    from src.data import us_market_client

    df = us_market_client.get_price_history(ticker, period="6mo")
    if df is None or df.empty:
        return []
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    df = df[df["Date"] > pd.Timestamp(since)]
    return [
        {
            "date": row["Date"].strftime("%Y-%m-%d"),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        }
        for _, row in df.iterrows()
    ]


def fetch_last_close(ticker: str) -> tuple[float, str] | None:
    from src.data import us_market_client

    df = us_market_client.get_price_history(ticker, period="1mo")
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    date = str(row["Date"])[:10]
    return float(row["Close"]), date


# ---------------- 操作 ----------------

def enter_position(
    state: dict,
    ticker: str,
    name: str,
    score: float | None,
    source: str,
    entry_price: float | None = None,
    entered_at: str | None = None,
    next_earnings_date: str | None = None,
) -> bool:
    if any(p["ticker"] == ticker for p in state["positions"]):
        print(f"[skip] {ticker}: すでに保有中のためエントリーしません")
        return False
    if entry_price is None or entered_at is None:
        fetched = fetch_last_close(ticker)
        if not fetched:
            print(f"[warn] {ticker}: 価格を取得できずエントリーできません")
            return False
        entry_price, entered_at = fetched
    state["positions"].append(
        {
            "ticker": ticker,
            "name": name,
            "entry_price": round(entry_price, 4),
            "entered_at": entered_at,
            "score": score,
            "source": source,
            # 保有中に決算発表をまたぐリスクの警告用(ダッシュボードで表示)
            "next_earnings_date": next_earnings_date,
        }
    )
    print(f"[entry] {ticker} {name} @ {entry_price:.2f} ({entered_at})")
    return True


def auto_enter(state: dict, top_n: int) -> None:
    report = latest_report()
    if not report:
        print("[warn] output/ にレポートがありません。先に screen.py を実行してください。")
        return
    ts = report["meta"]["generated_at"]
    candidates = [c for c in report.get("candidates", []) if c.get("market") == "us"]
    for c in candidates[:top_n]:
        # スナップショットに記録されたシグナル時点の終値でエントリーする。
        # 古い形式のスナップショット(as_of_close無し)は最新終値にフォールバック
        enter_position(
            state,
            c["code"],
            c.get("name", c["code"]),
            c.get("total_score"),
            ts,
            entry_price=c.get("as_of_close"),
            entered_at=c.get("as_of_date"),
            next_earnings_date=c.get("next_earnings_date"),
        )


def update_positions(state: dict, tp_pct: float, sl_pct: float, max_hold: int) -> None:
    still_open = []
    for pos in state["positions"]:
        bars = fetch_bars_since(pos["ticker"], pos["entered_at"])
        exit_info = evaluate_exit(pos["entry_price"], bars, tp_pct, sl_pct, max_hold)
        if exit_info:
            pnl = (exit_info["exit_price"] / pos["entry_price"] - 1) * 100
            state["closed"].append(
                {
                    **pos,
                    "closed_at": exit_info["exit_date"],
                    "exit_price": round(exit_info["exit_price"], 4),
                    "exit_reason": exit_info["exit_reason"],
                    "pnl_pct": round(pnl, 2),
                    "days_held": exit_info["days_held"],
                }
            )
            label = {"tp": "利確", "sl": "損切り", "time": "時間切れ"}[exit_info["exit_reason"]]
            print(f"[close] {pos['ticker']} {label} @ {exit_info['exit_price']:.2f} ({pnl:+.2f}%)")
        else:
            if bars:
                pos["current_price"] = round(bars[-1]["close"], 4)
                pos["current_pnl_pct"] = round((bars[-1]["close"] / pos["entry_price"] - 1) * 100, 2)
                pos["days_held"] = len(bars)
                pos["as_of"] = bars[-1]["date"]
            still_open.append(pos)
    state["positions"] = still_open


def manual_close(state: dict, ticker: str) -> None:
    pos = next((p for p in state["positions"] if p["ticker"] == ticker), None)
    if not pos:
        print(f"[warn] {ticker} は保有していません")
        return
    fetched = fetch_last_close(ticker)
    if not fetched:
        print(f"[warn] {ticker}: 価格を取得できずクローズできません")
        return
    price, date = fetched
    pnl = (price / pos["entry_price"] - 1) * 100
    bars = fetch_bars_since(pos["ticker"], pos["entered_at"])
    state["closed"].append(
        {
            **pos,
            "closed_at": date,
            "exit_price": round(price, 4),
            "exit_reason": "manual",
            "pnl_pct": round(pnl, 2),
            "days_held": len(bars),
        }
    )
    state["positions"] = [p for p in state["positions"] if p["ticker"] != ticker]
    print(f"[close] {ticker} 手動クローズ @ {price:.2f} ({pnl:+.2f}%)")


def print_summary(state: dict, tp_pct: float, sl_pct: float) -> None:
    print("\n=== 保有中(仮想) ===")
    if not state["positions"]:
        print("  なし")
    for p in state["positions"]:
        cur = p.get("current_pnl_pct")
        cur_s = f"{cur:+.2f}%" if cur is not None else "-"
        print(
            f"  {p['ticker']:6s} entry {p['entry_price']:.2f} ({p['entered_at']}) "
            f"現在 {cur_s} [{p.get('days_held', 0)}日] TP{tp_pct:+.0f}%/SL{sl_pct:+.0f}%"
        )
    stats = compute_stats(state["closed"])
    print("\n=== 成績(クローズ済み) ===")
    if stats["trades"] == 0:
        print("  クローズ済みトレードはまだありません")
        return
    print(f"  トレード数: {stats['trades']} / 勝率: {stats['win_rate_pct']}%")
    print(f"  平均損益: {stats['avg_pnl_pct']:+.2f}% (勝ち平均 {stats['avg_win_pct']}% / 負け平均 {stats['avg_loss_pct']}%)")
    if stats["profit_factor"] is not None:
        print(f"  プロフィットファクター: {stats['profit_factor']}")
    print(f"  平均保有: {stats['avg_days_held']}営業日 / 決済内訳: {stats['exit_reasons']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto-enter", type=int, metavar="N", help="最新レポートの上位N銘柄を仮想エントリー")
    parser.add_argument("--enter", type=str, metavar="TICKER", help="手動で1銘柄エントリー")
    parser.add_argument("--close", type=str, metavar="TICKER", help="手動でクローズ(現値)")
    parser.add_argument("--tp", type=float, default=DEFAULT_TP_PCT, help="利確ライン%%(デフォルト+10)")
    parser.add_argument("--sl", type=float, default=DEFAULT_SL_PCT, help="損切りライン%%(デフォルト-7)")
    parser.add_argument("--max-hold", type=int, default=DEFAULT_MAX_HOLD_DAYS, help="最大保有営業日数(デフォルト20)")
    parser.add_argument(
        "--portfolio",
        type=str,
        default="default",
        help="戦略名。戦略ごとに状態ファイルを分離して並行検証する(例: aggressive)",
    )
    args = parser.parse_args()

    path = state_file(args.portfolio)
    state = load_state(path)
    print(f"=== ポートフォリオ: {args.portfolio} ===")

    # 先に既存ポジションの判定を済ませてから新規エントリーする
    update_positions(state, args.tp, args.sl, args.max_hold)
    if args.close:
        manual_close(state, args.close.upper())
    if args.auto_enter:
        auto_enter(state, args.auto_enter)
    if args.enter:
        enter_position(state, args.enter.upper(), args.enter.upper(), None, "manual")

    save_state(state, path, args.portfolio, args.tp, args.sl, args.max_hold)
    print_summary(state, args.tp, args.sl)
    print(f"\n状態を {path} に保存しました。")


if __name__ == "__main__":
    main()
