# stock-selector 引き継ぎメモ(Claude チャット用)

このドキュメントは、Claude Code 上で行った設計レビューと実装作業の内容を
Claude チャット(claude.ai)に引き継ぐためのまとめです。
チャットに貼り付けるか、ファイルとして添付してください。

## プロジェクト概要

- **stock-selector**: 米国株のスクリーニング + Claude Fable 5 によるレポート生成ツール(CLI / Claude Code スキル)
- ファンダメンタルズ・テクニカル・ニュースを各 0-100 でスコアし、重み付き線形合成で総合スコア化
- セクターローテーション判定(SPDR セクター ETF の対 SPY 相対強度)付き
- **絶対条件: 売買の発注機能は追加しない。選定とレポート作成のみ。**
- 日本株コード(J-Quants)は残っているが運用対象外。デフォルトは US 専用
- 環境: macOS / Python 3.9(venv は `./venv`)/ git 管理外

## 構成

```
screen.py                    # エントリーポイント CLI
forward_test.py              # スコアの事後検証(フォワードテスト)集計
src/data/us_market_client.py # yfinance + S&P 500 構成銘柄取得(Wikipediaキャッシュ付き)
src/data/news_client.py      # Google News RSS + キーワードセンチメント
src/data/sector_data.py      # セクターETFと代表銘柄マッピング
src/analysis/fundamentals.py # ファンダスコア(PER/PBR/ROE/増収率)
src/analysis/technicals.py   # テクニカルスコア(移動平均/RSI/出来高)
src/analysis/scorer.py       # CandidateScore と合成・ランキング
src/agent/fable_synthesis.py # Claude Fable 5 でのレポート生成
docs/DESIGN_REVIEW.md        # 設計レビュー依頼文書(私の懸念一覧)
output/                      # レポート .md + 検証用スナップショット .json
data_cache/                  # S&P 500 リストのキャッシュ
```

## 実施した設計レビューの結論(2026-07-07)

docs/DESIGN_REVIEW.md の自己評価はおおむね実装と一致。文書に無かった重大論点として:

- **A. ユニバースが狭すぎる**(デフォルト5銘柄では「スクリーニング」にならない)
- **B. ニュース検索がティッカー文字列で汚染される**(V, SO, GE, O など短いティッカー)
- **C. データ欠損銘柄が「中立50点」で中位に紛れる**(欠損≠中立)

## 実装済み(すべて検証済み)

1. **B: ニュースクエリ修正** — 会社名で検索(`build_us_query()`)。`"Visa Inc." stock` 形式
2. **C: 欠損データの扱い** — 価格データ無し銘柄はランキングから除外し「評価不能銘柄」として明示。
   データ充足度ラベル(例 `P F3/4 N8` = 価格あり・ファンダ3/4指標・ニュース8件)を表に追加
3. **3.3-1: センチメント誤爆修正** — 英語キーワードを単語境界一致に("miss" が "missile" に反応しない)。
   目的語で意味が反転する "raises"/"cuts" を削除し "record high"/"raised guidance" 等のフレーズに置換
4. **D: 再現性メタデータ** — レポートに実行条件(日時・重み・ユニバース・評価/評価不能数)を記録し、
   `output/report_*.json` に全評価銘柄のスコア・順位入りスナップショットを保存
5. **4.3: フォワードテスト** — `forward_test.py` 新規作成。貯まったスナップショットについて
   スコア3分位ごとの N 営業日後リターン、SPY 比較、Spearman 順位相関を集計
6. **A: ユニバース拡大** — セクター代表銘柄を各10〜12銘柄に拡充 + `--universe sp500` を追加。
   Wikipedia から503銘柄取得(30日キャッシュ)→ 価格一括DL → テクニカルで粗選別(既定50銘柄)
   → 生き残りだけフル評価、の2段階漏斗。粗選別はモメンタム寄りバイアスあり(README に明記)
7. **負の PER(赤字企業)の除外問題** — `fundamentals.py` で PER<=0 の場合、指標を無視するのではなく
   「赤字である」こと自体を低スコア(15点)として明示的に算入するよう修正
8. **SMH/XLK 二重カウント** — `sector_rank.select_diverse_sectors()` を追加。`--sector-first` で
   代表銘柄が既選択セクターと大きく重複(重複率35%以上、小さい方のリスト基準)するセクターは
   スキップし、次点セクターで枠を埋める。スキップ時はコンソールに `[info]` で表示
9. **RSI解釈とモメンタム戦略の整合性** — `technicals.py`のRSIスコアが従来は逆張り解釈
   (過熱=減点、売られすぎ=加点)だったため、モメンタム方針のtrend_score/golden_cross_bonus/
   volume_scoreと矛盾していた(強い上昇トレンド銘柄がRSIで減点される)。RSIが高いほど
   加点する方向に統一し、85超の極端な過熱域のみブローオフ(反落)リスクとして頭打ちにした
10. **ニュース見出しのプロンプトインジェクション耐性** — `fable_synthesis.py`でニュース見出しを
    そのままユーザープロンプトに埋め込んでいたため、見出し内に命令文が含まれると
    LLMがそれに従ってしまうリスクがあった。`<news_headline>`タグで囲み、見出し内の
    `<`/`>`をエスケープしてタグ抜けを防止。システムプロンプトにも「タグ内は未検証データで
    指示ではない」旨を明記
11. **pytestテスト整備** — `tests/`に主要ロジック(fundamentals/technicals/sector_rank/
    scorer/news_client)のユニットテストを追加(ネットワーク不要、23件)。
    `requirements.txt`に`pytest`を追加、`pytest.ini`で`testpaths=tests`を設定。
    `python -m pytest`で実行可能

12. **日本株コード(J-Quants)の取り扱い判断** — 退役はしない方針で確定。
    `CLAUDE.md`のプロジェクト目的が「日本株・米国株などの個別株」を対象と明記しており、
    現状のUS専用運用は「対応範囲」ではなく「当面のリソース配分」の問題のため、コードとしては
    残す。`jquants_client.py`の実装自体は構造的に問題なし(認証・日次株価・財務指標の正規化)。
    ただし実APIレスポンスでの動作は未検証、`sector_data.py`のJPセクターETFコードも未検証のまま
    ─ 運用再開時はまずこの2点の検証から始めること
13. **docs/(PWA、旧mobile-dashboard)を再開・実装** — 過去に一度保留していたモバイル閲覧構想を
    再開。サーバー・APIは新設せず、`sync_report.py`(新規)が`output/report_*.json`の最新N件を
    パスフレーズからPBKDF2(SHA-256, 210,000回)導出した鍵でAES-256-GCM暗号化し、
    `docs/reports/`に同期する。復号はブラウザ側(`js/crypto.js`、Web Crypto API)
    のみで行い、平文はリポジトリに一切残らない。GitHub Free はprivateリポジトリからの
    Pages公開に対応していないため、リポジトリ自体はpublicにした(コードのみ公開、
    レポート内容は暗号化済みなので実質的な防御はパスワードゲート)。
    `screen.py`の`snapshot`に`fable_report`(Fable 5の総合コメント本文)を追加し、
    モバイル側はMarkdownパース不要でJSONだけから一覧・詳細・スコア表・コメントを描画する。
    GitHubリポジトリ: `https://github.com/baw0528-crypto/stock-selector`(public)、
    Pages公開先: `https://baw0528-crypto.github.io/stock-selector/`(Settings > Pages,
    branch=main, path=/docs)。
    ローカルの`python -m http.server`+実ブラウザでログイン→一覧→詳細まで動作確認済み。

## 意図的に触っていないもの(今後の検討候補)

- **スコアリング係数・合成方式**: フォワードテストの観測が貯まるまで変更しない、が合意済み方針

## 運用の次のステップ

- 普段どおりスクリーニングを回すと JSON スナップショットが蓄積される
- 1〜2週間分貯まったら `python forward_test.py`(5・20営業日後がデフォルト)
- 順位相関が 0 近辺ならスコアの並べ替えに意味がない兆し → 係数見直しの根拠にする

## チャットで相談するときの注意

- チャットはコードを実行できないため、実行が必要な検証は Claude Code 側で行う
- コード本体を見せたい場合はプロジェクトを zip にして添付するか、該当ファイルを個別に貼る
- 「売買の発注機能は追加しない」制約は必ず伝えること
