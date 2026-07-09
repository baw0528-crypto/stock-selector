#!/bin/bash
# 毎日のスクリーニング自動実行(launchd経由)。
# screen.py -> sync_report.py -> docs/の変更をcommit & push まで一気に行う。
set -euo pipefail

PROJECT_DIR="/Users/mizukiabe/Downloads/files/stock-selector"
PYTHON="$PROJECT_DIR/venv/bin/python"
GIT="/usr/bin/git"

cd "$PROJECT_DIR"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily_run start ====="

# S&P 1500(大型500+中型400+小型600)から2段階スクリーニング
# (テクニカル粗選別→フル評価)。中小型株も対象にするためsp1500を使う。
"$PYTHON" screen.py --universe sp1500 --prefilter-top 50
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
