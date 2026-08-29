# ytnb — YouTube コメント → Google スプレッドシート → NotebookLM

指定チャンネルの YouTube コメントを取得し、スプレッドシートに蓄積、日付ごとの Google ドキュメントを
Drive に生成して NotebookLM のソースにするツール。設計は [PLAN.md](PLAN.md)、進捗は [TODO.md](TODO.md)。

## セットアップ

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env               # YOUTUBE_API_KEY, GOOGLE_SA_JSON を記入
cp config.example.yaml config.yaml  # channel_id, spreadsheet_id, drive.folder_id などを記入
```

### Google 側の準備 (TODO.md Step 0)

1. GCP プロジェクトで **YouTube Data API v3 / Google Sheets API / Google Drive API** を有効化
2. API キーを発行 → `.env` の `YOUTUBE_API_KEY`
3. サービスアカウントを作成し JSON キーを保存 → `.env` の `GOOGLE_SA_JSON`
4. スプレッドシートを作成し、サービスアカウントのメールアドレスに **編集者** で共有 → `sheet.spreadsheet_id`
5. Drive にフォルダを作成 → URL の `/folders/` 以降を `notebook.drive.folder_id`
   (`notebook.sink: local` にすればこの手順は不要で、`out/` に Markdown を書き出す)
6. **OAuth クライアントを作成**(Drive に Doc を作るため。サービスアカウントは Drive の容量を持たず
   個人アカウントでは `storageQuotaExceeded` になる):
   1. Cloud Console「API とサービス」→「OAuth 同意画面」→ ユーザーの種類 **外部** → アプリ名などを入力 →
      **テストユーザー** に自分の Gmail アドレスを追加
   2. 「認証情報」→「+ 認証情報を作成」→「OAuth クライアント ID」→ 種類 **デスクトップ アプリ** → 作成
   3. JSON をダウンロードして `oauth_client.json` としてプロジェクト直下に置く(`.env` の `GOOGLE_OAUTH_CLIENT_JSON`)
   4. `.venv/bin/python -m ytnb auth` を実行 → 表示される URL をブラウザで開き、自分のアカウントでログイン →
      `token.json` が保存される(以後は自動更新。初回のみ)
   5. WSL などで「localhost で接続が拒否されました」になる場合は **手動モード**:
      ```bash
      .venv/bin/python -m ytnb auth --manual        # URL が表示される → ブラウザで開いてログイン
      # 「このサイトにアクセスできません」のページのアドレスバー URL をコピーして
      .venv/bin/python -m ytnb auth --response 'http://localhost:8765/?state=...&code=...&scope=...'
      ```

## 使い方

```bash
.venv/bin/python -m ytnb fetch                 # 取得結果を JSON 表示 (シートに書かない)
.venv/bin/python -m ytnb run --dry-run         # 同上
.venv/bin/python -m ytnb run --skip-notebook   # 取得 + シート保存のみ
.venv/bin/python -m ytnb run                   # 取得 + シート保存 + Drive に日付 Doc 出力
.venv/bin/python -m ytnb run --since 2026-06-01   # 取得開始日時を指定 (初回や取り直し用)
.venv/bin/python -m ytnb export                # シートの内容から保持期間内の Doc を再生成
.venv/bin/python -m ytnb export --date 2026-06-06   # 指定日は retention_days に関係なく出力
.venv/bin/python -m ytnb auth                       # Drive 用 OAuth ログイン (初回のみ)
```

2 回目以降は `state` シートの `last_comment_published_at` から `overlap_days` 分さかのぼって差分取得する。
`comment_id` で重複排除するので、何度実行しても同じコメントは 1 行のまま。

### NotebookLM への取り込み (案 A)

1. NotebookLM でノートブックを開き「ソースを追加」→「Google ドライブ」→ 上記フォルダ内の
   `YYYY-MM-DD コメント` Doc を選択
2. Doc が更新されたら、NotebookLM のソース一覧で「Google ドライブと同期」をクリック
3. `retention_days` を超えた Doc は自動でゴミ箱に移動する (完全削除はしない)

## 定期実行 (例: WSL の cron、毎日 6:00)

```
0 6 * * * .venv/bin/python -m ytnb run >> logs/ytnb.log 2>&1
```

## 終了コード

| コード | 意味 |
|---|---|
| 0 | 正常 |
| 2 | 設定エラー |
| 3 | YouTube API クォータ超過 (翌日再実行) |
| 4 | スプレッドシートにアクセスできない (API 未有効化 / ID 誤り / 共有漏れ) |
| 5 | Drive の認証・API エラー (`ytnb auth` 未実行 / folder_id 誤り など) |

## テスト

```bash
.venv/bin/python -m pytest
```

## 構成

```
ytnb/
├── cli.py          CLI (run / fetch / export / auth)
├── auth.py         Drive 用認証 (OAuth / サービスアカウント)
├── config.py       config.yaml + .env の読み込みと検証
├── models.py       Comment dataclass、シート列定義
├── youtube.py      YouTube Data API v3 からの取得
├── sheet.py        スプレッドシート保存・state
├── export.py       日付ごとのテキスト生成
├── pipeline.py     fetch -> store -> export の結合
└── notebook/       NotebookSink (drive / local / none)
```
