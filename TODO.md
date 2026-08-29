# TODO — YouTube コメント → スプレッドシート → NotebookLM

詳細設計は [PLAN.md](PLAN.md) を参照。上から順に進める。

## Step 0: 事前準備(手動・GCP 側)
- [ ] GCP プロジェクトを作成(または既存を選択)
- [ ] API を有効化: YouTube Data API v3 / Google Sheets API / Google Drive API
- [ ] YouTube 用 API キーを発行(YouTube Data API のみに制限)
- [ ] サービスアカウントを作成し、JSON キーをダウンロード
- [ ] スプレッドシートを新規作成し、サービスアカウントのメールに「編集者」で共有
- [ ] `spreadsheet_id` と対象 `channel_id` を控える
- [x] `.env` / `config.yaml` の雛形を用意(`.env` は `.gitignore` に追加)
- [ ] 完了条件: curl 等で `channels.list` と Sheets の読み取りが手動で通る

## Step 1: YouTube コメント取得 (`ytnb/youtube.py`)
- [x] `pyproject.toml` 作成、依存追加(`google-api-python-client`, `gspread`, `pyyaml`, `python-dotenv`)
- [x] `models.py`: `Comment` dataclass(PLAN §4.2 の列に対応)
- [x] `channels.list` → uploads プレイリスト ID を取得
- [x] `playlistItems.list` → 動画 ID 一覧(直近 N 本 / 日付で絞る設定)
- [x] `commentThreads.list` を動画ごとにページング取得(`part=snippet,replies`, `order=time`, `textFormat=plainText`)
- [x] 返信(`replies.comments`)も `parent_id` 付きで平坦化
- [x] `published_at` を JST に変換し `date` 列を作る
- [x] コメント無効動画(403 `commentsDisabled`)をスキップしてログ出力
- [x] クォータ超過(403 `quotaExceeded`)を検知して中断
- [x] `python -m ytnb fetch --dry-run` で JSON を標準出力に出せる
- [ ] 完了条件: 指定チャンネルのコメント件数が YouTube 画面の表示と一致する

## Step 2: スプレッドシート保存 (`ytnb/sheet.py`, `ytnb/state.py`)
- [x] サービスアカウントで `gspread` 認証
- [x] シート `comments` のヘッダー行を自動作成(未作成時)
- [x] シート `state` のキー・値の読み書き(`last_run_at`, `last_comment_published_at` など)
- [x] 既存 `comment_id` を一括読込 → 差分のみ `append_rows` でバッチ追記
- [x] `state` の最終取得日時を使って YouTube 側の取得範囲を絞る
- [ ] 完了条件: `python -m ytnb run --skip-notebook` を 2 回実行して行数が増えない

## Step 3: NotebookLM 連携・案 A Drive 経由 (`ytnb/notebook/`)
- [x] `base.py`: `NotebookSink` インターフェース(`export(date, comments)`)
- [x] 日付ごとの Markdown 風テキストを生成(PLAN §4.3 のフォーマット)
- [x] `drive.py`: Drive API で「YYYY-MM-DD コメント」Doc を作成/更新
- [x] `auth.py`: OAuth (デスクトップ アプリ) で自分のアカウント所有の Doc を作る(SA は Drive 容量を持たないため)
- [x] OAuth クライアント ID を作成し `oauth_client.json` を配置、`python -m ytnb auth` でログイン
- [x] `state` に `notebook_last_export_date` を保存し、未出力の日付だけ処理
- [x] 保持期間(直近 N 日)を超えた Doc の扱いを決めて実装(削除 or 月次集約)
- [x] `python -m ytnb export --date 2026-07-08` で Drive に Doc ができることを確認
- [ ] NotebookLM に手動でソース追加 → 「Drive と同期」で更新が反映されることを確認
- [ ] 完了条件: Drive に日付 Doc ができ、NotebookLM から内容を参照できる

## Step 4: CLI 統合・運用品質 (`ytnb/__main__.py`)
- [x] サブコマンド: `run` / `fetch` / `export`、オプション: `--dry-run`, `--skip-notebook`, `--since`
- [x] `config.yaml` 読み込みと `.env` からの秘密情報読み込み
- [x] `logging` 設定(件数・スキップ動画・エラーを出力)
- [x] 失敗しても途中までの結果が壊れないように(シート追記後に state 更新)
- [x] README に実行手順を記載
- [ ] 完了条件: `python -m ytnb run` 一発で全段通る

## Step 5: 定期実行
- [ ] 実行方法を決める(WSL cron / GitHub Actions / Cloud Run Jobs)
- [ ] 秘密情報の置き場所を決める(GitHub Secrets 等)
- [ ] 1 日 1 回のスケジュール設定
- [ ] 失敗時の通知(メール / ログ確認方法)
- [ ] 完了条件: 無人で 1 日 1 回動き、翌日シートに新着が入っている

## Step 6 (任意): 案 B で完全自動化 (`ytnb/notebook/nblm.py`)
- [ ] `notebooklm-py` の動作確認(認証方法、規約リスクの再確認)
- [ ] `NotebookSink` 実装: `add_text` / `add_drive` / `refresh`
- [ ] `config.yaml` で案 A / B を切替
- [ ] 完了条件: 手動同期なしで NotebookLM のソースが更新される

## Step 7 (フェーズ2・図の赤矢印): 返信文の書き戻し
- [ ] NotebookLM に返信文を生成させる方法を決める(案 B のチャット API / 手動コピー)
- [ ] 生成した返信文を `reply_draft` 列に書き戻し、`reply_status=draft` にする
- [ ] (将来) OAuth(`youtube.force-ssl`)で YouTube に返信投稿 → `reply_status=posted`

---

## 実装前に決めること(PLAN §8)
- [ ] 対象チャンネルは自分のものか、他人のものか
- [ ] 取得範囲(全動画 or 直近 N 本 / M 日)
- [ ] 実行頻度(1 日 1 回?)
- [ ] NotebookLM 連携は案 A から始めるか、案 B を最初から試すか
- [ ] 日付ソースの保持期間
- [ ] 言語は Python でよいか(GAS 案もあり)
