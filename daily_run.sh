#!/bin/bash
# 毎日のスクリーニング自動実行(launchd経由)。
# screen.py -> sync_report.py -> docs/の変更をcommit & push まで一気に行う。
set -euo pipefail

PROJECT_DIR="/Users/mizukiabe/Downloads/files/stock-selector"
PYTHON="$PROJECT_DIR/venv/bin/python"
GIT="/usr/bin/git"

cd "$PROJECT_DIR"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily_run start ====="

# 2本立てで並行検証する。track_positions.py --auto-enter は「直前のscreen.pyの
# レポート」を読むため、screen→trackの順序を崩さないこと。

# 戦略1(通常): S&P1500全体・重み等分
"$PYTHON" screen.py --universe sp1500 --prefilter-top 50
"$PYTHON" track_positions.py --auto-enter 3

# 戦略2(アグレッシブ): 小型株のみ・モメンタム重視
"$PYTHON" screen.py --universe sp600 --weight-technical 0.6 --weight-fundamental 0.25 --weight-news 0.15
"$PYTHON" track_positions.py --auto-enter 3 --portfolio aggressive

# フォワードテスト集計(観測が無い日でもJSONは出力される)。失敗しても同期は続行
"$PYTHON" forward_test.py --json output/forward_test.json || echo "[warn] forward_test failed (continuing)"

"$PYTHON" sync_report.py

"$GIT" add docs/
if ! "$GIT" diff --cached --quiet; then
  "$GIT" commit -m "daily screening $(date '+%Y-%m-%d %H:%M')"
  "$GIT" push
  echo "pushed."
else
  echo "docs/に変更なし。pushはスキップ。"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily_run done ====="
