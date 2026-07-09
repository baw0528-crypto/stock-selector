#!/bin/bash
# 毎日のスクリーニング自動実行(launchd経由)。
# screen.py -> sync_report.py -> docs/の変更をcommit & push まで一気に行う。
set -euo pipefail

PROJECT_DIR="/Users/mizukiabe/Downloads/files/stock-selector"
PYTHON="$PROJECT_DIR/venv/bin/python"
GIT="/usr/bin/git"

cd "$PROJECT_DIR"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily_run start ====="

# S&P 500全体から2段階スクリーニング(テクニカル粗選別50銘柄→フル評価)。
# デフォルト5銘柄では相対強度が「巨大テック内の比較」にしかならないため全市場対象にする。
"$PYTHON" screen.py --universe sp500
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
