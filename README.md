# stock-selector

**米国株**を対象に、ファンダメンタルズ・テクニカル・ニュース・セクターローテーションを
組み合わせて銘柄をスコアリングし、Claude Fable 5に総合判断とレポート作成をさせるツール。

**売買の執行はしません。** 選定とレポート出力までが役割です。実際の発注は
別途、証券会社のアプリ／APIで自分の判断で行ってください。

> 日本株関連のコード(`jquants_client.py`等)も残していますが、現状は
> 米国株に対象を絞って運用する方針にしたため、デフォルトでは使いません。
> `--market jp` / `--market both` で呼び出せば動きますが、日本のセクターETF
> コードは未検証なので優先度は低いです。

## できること

1. US株: yfinanceから株価・財務データを取得
2. セクターETF(SPDR等)の相対強度でセクターローテーションを判定
3. RSSからニュース見出しを収集
4. ファンダ・テクニカルの指標を計算してスコア化
5. 上位候補をClaude Fable 5に渡し、総合判断・注目理由・リスクをレポート化

## セットアップ

```bash
cd stock-selector
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env を開いて JQUANTS_MAIL / JQUANTS_PASSWORD / ANTHROPIC_API_KEY を入れる
```

J-Quants APIは https://jpx-jquants.com/ で無料登録できます（無料プランでも
株価・基本財務は取得可能。詳細な財務指標はスタンダード以上が必要）。

## 使い方

```bash
# 米国株をスクリーニングしてレポート生成(デフォルトでmarket=us)
python screen.py --top 10

# テクニカル重視
python screen.py --weight-technical 0.6 --weight-fundamental 0.3 --weight-news 0.1

# 対象銘柄リストを指定
python screen.py --tickers AAPL,MSFT,NVDA,AMZN

# セクターローテーション優先モード:
# まずセクターETFの相対強度をランキングし、上位セクターの代表銘柄だけを
# 個別スクリーニングする(勢いのあるセクターに乗りたい場合向け)
python screen.py --sector-first --top-sectors 2

# S&P 500全銘柄を対象にした2段階スクリーニング:
# 第1段階で全銘柄の価格を一括取得しテクニカルスコアで粗選別(既定50銘柄)、
# 第2段階で生き残りだけをファンダ・ニュース込みでフル評価する。
# 粗選別はテクニカル基準なのでモメンタム寄りのバイアスが乗る点に注意。
python screen.py --universe sp500 --prefilter-top 50
```

`--sector-first` は「今どのセクターが強いか」を先に判定してから、
そのセクター内の銘柄だけをファンダ/テクニカル/ニュースでスコアリングします。
代表銘柄リストは `src/data/sector_data.py` の `US_SECTOR_CONSTITUENTS` にあり、
今は各セクター5銘柄程度の仮リストなので運用しながら拡充してください。

出力は `output/report_YYYYMMDD_HHMM.md`(人間向けレポート)と
`output/report_YYYYMMDD_HHMM.json`(検証用スナップショット)に保存されます。
レポートには実行条件(重み・ユニバース・データ充足度)が記録され、
価格データが取得できなかった銘柄は「中立扱い」ではなくランキング対象外として
明示されます。

## フォワードテスト(スコアの事後検証)

スクリーニングを続けてスナップショットが貯まったら、当時のスコアと
その後の実リターンの関係を集計できます:

```bash
python forward_test.py                 # 5営業日後と20営業日後
python forward_test.py --horizons 10,60
```

スコア上位1/3・中位・下位のフォワードリターンと、スコアと事後リターンの
順位相関(Spearman)を表示します。スコアリング係数(fundamentals.py /
technicals.py の仮置き係数)を調整する際は、この集計を根拠にしてください。

## テスト

スコアリングロジック(ファンダ/テクニカル/セクター選定/ニュース感情/合成)の
ユニットテストが `tests/` にあります。ネットワークアクセスは行いません。

```bash
pip install -r requirements.txt  # pytestを含む
python -m pytest
```

## Claude Codeでスキルとして使う

このディレクトリを Claude Code で開いた状態で `SKILL.md` を読み込ませれば、
「今日の日本株をスクリーニングして」のような自然言語指示で `screen.py` を
適切な引数で実行できるようになります。詳細は SKILL.md を参照してください。

## モバイルでレポートを見る(docs/ = GitHub Pages)

`screen.py` が生成したレポートを、パスワード保護されたPWA(スマホのホーム画面に
追加できるWebアプリ)として閲覧できます。サーバー・API・データベースは一切なく、
`output/` のレポートを暗号化してGitHub Pagesに置くだけです。

```bash
# .env に MOBILE_DASHBOARD_PASSWORD(閲覧用パスフレーズ)を設定してから
python sync_report.py            # output/の最新20件を暗号化してdocs/reports/に同期
python sync_report.py --keep 30  # 保持件数を変える場合
```

同期後、`docs/` を含めてリポジトリにpushしてください。このリポジトリはGitHub Pagesの
Source設定で `main` ブランチの `/docs` を公開するようにしてあります
(Settings > Pages)。公開URLは `https://<GitHubユーザー名>.github.io/stock-selector/`。

**リポジトリはpublicです**(GitHub Free ではprivateリポジトリからPagesを公開できない
ため)。ただし公開されているのは`screen.py`等のスクリーニングロジックのコードのみで、
実際のレポート内容(銘柄名・スコア・Fable 5コメント)は下記の通り暗号化済みの状態
でしかリポジトリに含めていません。`.env`(パスフレーズ本体)は`.gitignore`済みです。

**セキュリティモデル**: レポート本文は`sync_report.py`実行時にパスフレーズから
PBKDF2(SHA-256, 210,000回)で鍵を導出し、AES-256-GCMで暗号化した状態でしか
置きません。復号はブラウザ側(`js/crypto.js`、Web Crypto API)でのみ行われ、
平文がサーバーやリポジトリに残ることはありません。パスワードはある程度の
強度のものを使ってください。

## 構成

```
stock-selector/
  screen.py                    # エントリーポイント
  sync_report.py               # output/のレポートを暗号化してdocs/に同期
  forward_test.py              # スコアの事後検証(フォワードテスト)集計
  src/data/
    jquants_client.py          # JP株データ取得
    us_market_client.py        # US株データ取得(yfinance) + S&P 500リスト取得
    news_client.py             # ニュース見出し取得(RSS)
  src/analysis/
    fundamentals.py            # ファンダ指標スコアリング
    technicals.py               # テクニカル指標スコアリング
    scorer.py                   # 総合スコア合成
  src/agent/
    fable_synthesis.py          # Claude Fable 5への問い合わせとレポート生成
  notes/                       # 設計レビュー・チャット引き継ぎメモ
  data_cache/                  # S&P 500構成銘柄リスト等のキャッシュ(自動生成)
  output/                      # レポート(.md)と検証用スナップショット(.json)
  docs/                        # レポート閲覧用PWA(暗号化データのみを含む)= GitHub Pages公開先
    index.html / css / js/     # アプリ本体(パスワード復号・一覧・詳細表示)
    manifest.json / service-worker.js  # PWA化・オフラインキャッシュ
    reports/                   # sync_report.pyが生成する暗号化済みレポート
```

## 注意

- これは投資助言ツールではありません。出力はあくまで一次スクリーニングの
  参考情報であり、最終判断はご自身で行ってください。
- 無料データソース（yfinance等）は遅延・欠損があり得ます。本番運用前に
  データの妥当性を必ず確認してください。
