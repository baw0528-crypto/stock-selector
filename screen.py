"""日本株・米国株のスクリーニングを実行し、Fable 5でレポート化するCLI。

売買の発注は一切行わない。出力はoutput/配下のMarkdownレポートと、
検証(フォワードテスト)用のJSONスナップショットのみ。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.data.jquants_client import JQuantsClient
from src.data import us_market_client
from src.data.news_client import build_us_query, fetch_headlines, news_score
from src.data.sector_data import US_SECTOR_CONSTITUENTS, JP_SECTOR_CONSTITUENTS
from src.analysis.fundamentals import score_fundamentals
from src.analysis.technicals import score_technicals
from src.analysis.scorer import CandidateScore, rank_candidates
from src.analysis.sector_rank import rank_us_sectors, rank_jp_sectors, select_diverse_sectors
from src.agent.fable_synthesis import generate_report

load_dotenv()

DEFAULT_JP_CODES = ["7203", "6758", "9984", "8306", "6501"]  # トヨタ/ソニーG/SBG/MUFG/日立
DEFAULT_US_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]


def build_jp_candidates(codes: list[str]) -> tuple[list[CandidateScore], dict]:
    client = JQuantsClient()
    candidates, headlines_map = [], {}
    for code in codes:
        price_df, fundamentals = None, {}
        try:
            price_df = client.get_daily_quotes(code)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {code}: JP株価格データ取得に失敗しました ({e})")
        try:
            fundamentals = client.fetch_fundamentals(code)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {code}: JP株財務データ取得に失敗しました ({e})")

        headlines = fetch_headlines(code, lang="ja")
        headlines_map[code] = headlines

        has_price = price_df is not None and not price_df.empty
        tech = score_technicals(price_df) if has_price else {"score": 50.0, "detail": "価格データなし"}
        fund = score_fundamentals(fundamentals)
        cand = CandidateScore(
            code=code,
            market="jp",
            name=fundamentals.get("code", code),
            fundamental_score=fund["score"],
            technical_score=tech["score"],
            news_score=news_score(headlines),
            has_price_data=has_price,
            fundamental_metrics=fund["metrics_used"],
            news_count=len(headlines),
            raw={"fundamentals": fundamentals, "technical_detail": tech.get("detail")},
        )
        candidates.append(cand)
    return candidates, headlines_map


def build_us_candidates(tickers: list[str]) -> tuple[list[CandidateScore], dict]:
    candidates, headlines_map = [], {}
    for ticker in tickers:
        price_df, fundamentals = None, {}
        try:
            price_df = us_market_client.get_price_history(ticker)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {ticker}: US株価格データ取得に失敗しました ({e})")
        try:
            fundamentals = us_market_client.fetch_fundamentals(ticker)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {ticker}: US株財務データ取得に失敗しました ({e})")

        # "V"のような短いティッカーの検索は誤ヒットが多いため会社名で検索する
        query = build_us_query(ticker, fundamentals.get("short_name"))
        headlines = fetch_headlines(query, lang="en")
        headlines_map[ticker] = headlines

        has_price = price_df is not None and not price_df.empty
        tech = score_technicals(price_df) if has_price else {"score": 50.0, "detail": "価格データなし"}
        fund = score_fundamentals(fundamentals)
        cand = CandidateScore(
            code=ticker,
            market="us",
            name=fundamentals.get("short_name") or ticker,
            fundamental_score=fund["score"],
            technical_score=tech["score"],
            news_score=news_score(headlines),
            has_price_data=has_price,
            fundamental_metrics=fund["metrics_used"],
            news_count=len(headlines),
            raw={"fundamentals": fundamentals, "technical_detail": tech.get("detail")},
        )
        candidates.append(cand)
    return candidates, headlines_map


def build_us_candidates_prefiltered(
    tickers: list[str], prefilter_top: int
) -> tuple[list[CandidateScore], dict]:
    """広いユニバース向けの2段階スクリーニング。

    第1段階: 価格を一括取得しテクニカルスコアだけで粗選別(安価)。
    第2段階: 生き残りにファンダ・ニュースを含むフル評価(高価)。
    粗選別がテクニカル基準である点に注意(モメンタム寄りのバイアスが乗る)。
    """
    print(f"[1/2] {len(tickers)}銘柄の価格を一括取得し、テクニカルで上位{prefilter_top}銘柄に粗選別します...")
    price_map = us_market_client.get_price_histories(tickers)
    missing = len(tickers) - len(price_map)
    if missing:
        print(f"[info] 価格データを取得できなかった{missing}銘柄は粗選別の対象外です")

    scored = sorted(
        ((t, score_technicals(df)["score"]) for t, df in price_map.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    survivors = [t for t, _ in scored[:prefilter_top]]
    print(f"[2/2] 上位{len(survivors)}銘柄をフル評価(ファンダ+ニュース)します...")
    return build_us_candidates(survivors)


def _candidate_to_dict(c: CandidateScore, rank: int | None = None) -> dict:
    return {
        "rank": rank,
        "code": c.code,
        "market": c.market,
        "name": c.name,
        "total_score": c.total_score,
        "fundamental_score": c.fundamental_score,
        "technical_score": c.technical_score,
        "news_score": c.news_score,
        "has_price_data": c.has_price_data,
        "fundamental_metrics": c.fundamental_metrics,
        "news_count": c.news_count,
        "technical_detail": c.raw.get("technical_detail"),
    }


def main():
    parser = argparse.ArgumentParser(description="JP/US株スクリーニング (発注は行いません)")
    parser.add_argument("--market", choices=["jp", "us", "both"], default="us")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--tickers", type=str, default=None, help="カンマ区切り。未指定ならデフォルトユニバース")
    parser.add_argument("--weight-fundamental", type=float, default=1 / 3)
    parser.add_argument("--weight-technical", type=float, default=1 / 3)
    parser.add_argument("--weight-news", type=float, default=1 / 3)
    parser.add_argument("--no-fable", action="store_true", help="Fable 5への問い合わせをスキップし数値のみ出力")
    parser.add_argument(
        "--sector-first",
        action="store_true",
        help="先にセクター相対強度をランキングし、上位セクターの代表銘柄のみを対象に個別スクリーニングする",
    )
    parser.add_argument("--top-sectors", type=int, default=2, help="--sector-first時に採用する上位セクター数")
    parser.add_argument(
        "--universe",
        choices=["default", "sp500"],
        default="default",
        help="sp500を指定するとS&P 500全銘柄を対象に2段階スクリーニング(テクニカル粗選別→フル評価)する",
    )
    parser.add_argument(
        "--prefilter-top",
        type=int,
        default=50,
        help="--universe sp500時、第1段階(テクニカル粗選別)で残す銘柄数",
    )
    args = parser.parse_args()

    # 黙って無視される組み合わせを明示的に弾く
    if args.tickers and (args.sector_first or args.market == "both"):
        parser.error("--tickers は --sector-first / --market both とは併用できません")
    if args.universe == "sp500" and (args.tickers or args.sector_first or args.market != "us"):
        parser.error("--universe sp500 は --market us 専用で、--tickers / --sector-first とは併用できません")

    run_meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "market": args.market,
        "universe": args.universe,
        "sector_first": args.sector_first,
        "top_sectors": args.top_sectors if args.sector_first else None,
        "prefilter_top": args.prefilter_top if args.universe == "sp500" else None,
        "weights": {
            "fundamental": args.weight_fundamental,
            "technical": args.weight_technical,
            "news": args.weight_news,
        },
        "top": args.top,
    }
    sector_ranking_meta: list[dict] = []
    universe_tickers: list[str] = []

    all_candidates: list[CandidateScore] = []
    headlines_map: dict = {}

    if args.sector_first:
        jp_codes, us_tickers = [], []

        if args.market in ("us", "both"):
            us_sectors = rank_us_sectors()
            print("\n=== 米国セクター相対強度(SPY比) ===")
            for s in us_sectors[:5]:
                print(f"  {s.name}({s.code}): {s.relative_strength_pct:+.2f}%")
            sector_ranking_meta += [
                {
                    "code": s.code,
                    "name": s.name,
                    "market": s.market,
                    "return_pct": s.return_pct,
                    "relative_strength_pct": s.relative_strength_pct,
                }
                for s in us_sectors
            ]
            selected_us_sectors, skipped_us_sectors = select_diverse_sectors(
                us_sectors, US_SECTOR_CONSTITUENTS, args.top_sectors
            )
            for s in skipped_us_sectors:
                sector, overlap = s
                print(
                    f"  [info] {sector.name}({sector.code})は既選択セクターと代表銘柄が"
                    f"{overlap:.0%}重複するためスキップし、次点セクターを採用しました"
                )
            for s in selected_us_sectors:
                us_tickers += US_SECTOR_CONSTITUENTS.get(s.code, [])
            us_tickers = list(dict.fromkeys(us_tickers))  # 重複除去、順序維持

        if args.market in ("jp", "both"):
            jp_sectors = rank_jp_sectors()
            print("\n=== 日本セクター相対強度(TOPIX比) ===")
            for s in jp_sectors[:5]:
                print(f"  {s.name}({s.code}): {s.relative_strength_pct:+.2f}%")
            sector_ranking_meta += [
                {
                    "code": s.code,
                    "name": s.name,
                    "market": s.market,
                    "return_pct": s.return_pct,
                    "relative_strength_pct": s.relative_strength_pct,
                }
                for s in jp_sectors
            ]
            for s in jp_sectors[: args.top_sectors]:
                jp_codes += JP_SECTOR_CONSTITUENTS.get(s.name, [])
            jp_codes = list(dict.fromkeys(jp_codes))

        if not us_tickers and not jp_codes:
            print(
                "[warn] 上位セクターに対応する代表銘柄リストがありません。"
                "src/data/sector_data.py の *_SECTOR_CONSTITUENTS を拡充してください。"
            )

        universe_tickers = jp_codes + us_tickers
        if jp_codes:
            cands, hmap = build_jp_candidates(jp_codes)
            all_candidates += cands
            headlines_map.update(hmap)
        if us_tickers:
            cands, hmap = build_us_candidates(us_tickers)
            all_candidates += cands
            headlines_map.update(hmap)

    elif args.universe == "sp500":
        universe_tickers = us_market_client.get_sp500_tickers()
        cands, hmap = build_us_candidates_prefiltered(universe_tickers, args.prefilter_top)
        all_candidates += cands
        headlines_map.update(hmap)

    else:
        if args.market in ("jp", "both"):
            jp_codes = (
                [t.strip() for t in args.tickers.split(",")] if args.tickers and args.market == "jp"
                else DEFAULT_JP_CODES
            )
            universe_tickers += jp_codes
            cands, hmap = build_jp_candidates(jp_codes)
            all_candidates += cands
            headlines_map.update(hmap)

        if args.market in ("us", "both"):
            us_tickers = (
                [t.strip() for t in args.tickers.split(",")] if args.tickers and args.market == "us"
                else DEFAULT_US_TICKERS
            )
            universe_tickers += us_tickers
            cands, hmap = build_us_candidates(us_tickers)
            all_candidates += cands
            headlines_map.update(hmap)

    for c in all_candidates:
        c.compute_total(args.weight_fundamental, args.weight_technical, args.weight_news)

    # 価格データが無い銘柄はテクニカルが計算不能=「中立」ではなく「評価不能」。
    # 中位に紛れ込ませずランキングから外し、レポートで明示する。
    evaluable = [c for c in all_candidates if c.has_price_data]
    excluded = [c for c in all_candidates if not c.has_price_data]
    if excluded:
        print(f"\n[info] 価格データ取得不可のため評価対象外: {', '.join(c.code for c in excluded)}")

    ranked_all = rank_candidates(evaluable, top_n=len(evaluable))
    top_candidates = ranked_all[: args.top]

    print("\n=== スクリーニング結果(上位) ===")
    for i, c in enumerate(top_candidates, 1):
        print(
            f"{i:2d}. [{c.market.upper()}] {c.code} {c.name} "
            f"total={c.total_score} (F{c.fundamental_score}/T{c.technical_score}/N{c.news_score}) "
            f"data={c.completeness_label()}"
        )

    fable_report = ""
    if not args.no_fable:
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("[warn] ANTHROPIC_API_KEY未設定のためFable 5レポート生成をスキップします")
        else:
            print("\nFable 5にレポート生成を依頼中...")
            fable_report = generate_report(top_candidates, headlines_map)

    Path("output").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = Path("output") / f"report_{ts}.md"
    json_path = Path("output") / f"report_{ts}.json"

    w = run_meta["weights"]
    lines = [f"# スクリーニングレポート {ts}", ""]

    lines += [
        "## 実行条件",
        "",
        f"- 実行日時: {run_meta['generated_at']}",
        f"- 市場: {args.market} / ユニバース: {args.universe}"
        f"({len(universe_tickers)}銘柄)"
        + (f" / sector-first 上位{args.top_sectors}セクター" if args.sector_first else ""),
        f"- 重み: ファンダ {w['fundamental']:.2f} / テクニカル {w['technical']:.2f} / ニュース {w['news']:.2f}",
        f"- 評価銘柄数: {len(evaluable)} (評価不能: {len(excluded)})",
        "",
    ]

    if sector_ranking_meta:
        lines += ["## セクター相対強度", ""]
        lines.append("| セクター | コード | リターン | ベンチマーク比 |")
        lines.append("|---|---|---|---|")
        for s in sector_ranking_meta:
            lines.append(
                f"| {s['name']} | {s['code']} | {s['return_pct']:+.2f}% | {s['relative_strength_pct']:+.2f}% |"
            )
        lines.append("")

    lines += ["## スコア一覧", ""]
    lines.append("| # | 市場 | コード | 銘柄名 | 総合 | ファンダ | テクニカル | ニュース | データ |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(top_candidates, 1):
        lines.append(
            f"| {i} | {c.market.upper()} | {c.code} | {c.name} | {c.total_score} "
            f"| {c.fundamental_score} | {c.technical_score} | {c.news_score} "
            f"| {c.completeness_label()} |"
        )
    lines += [
        "",
        "データ列の見方: P=価格データあり / F n/4=ファンダ指標の取得数 / N n=ニュース見出し数。",
        "取得数が少ない銘柄のスコアはそれだけ根拠が弱い点に注意。",
        "",
    ]

    if excluded:
        lines += ["## 評価不能銘柄(価格データ取得不可)", ""]
        for c in excluded:
            lines.append(f"- {c.code} {c.name}")
        lines.append("")

    if fable_report:
        lines.append("## Fable 5による総合コメント")
        lines.append("")
        lines.append(fable_report)
    lines.append("")
    lines.append("---")
    lines.append("本レポートは投資助言ではありません。最終的な投資判断はご自身の責任で行ってください。")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # フォワードテスト(forward_test.py)用の機械可読スナップショット。
    # 上位だけでなく評価できた全銘柄を残す(スコアと事後リターンの関係を見るため)。
    snapshot = {
        "meta": run_meta,
        "universe_size": len(universe_tickers),
        "sector_ranking": sector_ranking_meta,
        "candidates": [_candidate_to_dict(c, rank=i) for i, c in enumerate(ranked_all, 1)],
        "excluded": [_candidate_to_dict(c) for c in excluded],
        "top_n": args.top,
        "fable_report": fable_report,
    }
    json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nレポートを {out_path} に保存しました。")
    print(f"検証用スナップショットを {json_path} に保存しました。")


if __name__ == "__main__":
    main()
