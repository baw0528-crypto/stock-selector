#!/bin/bash
# 毎日のスクリーニング自動実行(launchd経由)。
# screen.py -> sync_report.py -> docs/の変更をcommit & push まで一気に行う。
#
# 安全装置(2026-07-14追加):
# - ネットワーク待機: スリープ復帰直後などDNSが未確立の状態で走り出すと
#   yfinanceが大量失敗・ハングするため、疎通確認できるまで最大10分待つ
# - ステップ別タイムアウト: 回線断などでプロセスが無限待ちすると、launchdが
#   翌日以降の実行を開始できなくなる(実際に4日間ハングした事故あり)。
#   各ステップにperl alarmで上限時間を設ける
set -euo pipefail

PROJECT_DIR="/Users/mizukiabe/Downloads/files/stock-selector"
PYTHON="$PROJECT_DIR/venv/bin/python"
GIT="/usr/bin/git"

cd "$PROJECT_DIR"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily_run start ====="

# 指定秒数で強制終了するランナー(macOSにGNU timeoutが無いためperl alarmを使う)
with_timeout() {
  local seconds="$1"; shift
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$seconds" "$@"
}

# ネットワーク疎通待ち(最大10分)。復帰しなければ今日はあきらめて終了
net_ok() { /usr/bin/curl -s --max-time 10 -o /dev/null "https://query1.finance.yahoo.com" ; }
for i in $(seq 1 60); do
  if net_ok; then break; fi
  if [ "$i" -eq 60 ]; then
    echo "[error] ネットワークに接続できないため本日の実行を中止します"
    exit 1
  fi
  sleep 10
done

# 2本立てで並行検証する。track_positions.py --auto-enter は「直前のscreen.pyの
# レポート」を読むため、screen→trackの順序を崩さないこと。

# 戦略1(通常): S&P1500全体・重み等分
with_timeout 3600 "$PYTHON" screen.py --universe sp1500 --prefilter-top 50
with_timeout 900 "$PYTHON" track_positions.py --auto-enter 3

# 戦略2(アグレッシブ): 小型株のみ・モメンタム重視
with_timeout 3600 "$PYTHON" screen.py --universe sp600 --weight-technical 0.6 --weight-fundamental 0.25 --weight-news 0.15
with_timeout 900 "$PYTHON" track_positions.py --auto-enter 3 --portfolio aggressive

# フォワードテスト集計(観測が無い日でもJSONは出力される)。失敗しても同期は続行
with_timeout 900 "$PYTHON" forward_test.py --json output/forward_test.json || echo "[warn] forward_test failed (continuing)"

with_timeout 600 "$PYTHON" sync_report.py

"$GIT" add docs/
if ! "$GIT" diff --cached --quiet; then
  "$GIT" commit -m "daily screening $(date '+%Y-%m-%d %H:%M')"
  with_timeout 300 "$GIT" push
  echo "pushed."
else
  echo "docs/に変更なし。pushはスキップ。"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily_run done ====="
