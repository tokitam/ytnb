# YouTube コメント → Google スプレッドシート → NotebookLM 連携 計画

作成日: 2026-08-30 / 元図: a1.jpg

## 1. 概念図の読み取り

```
YouTube                 Google スプレッドシート          NotebookLM
┌──────────┐            ┌──────────────────┐            ┌──────────────┐
│ A コメント │ ──取得──▶ │ 6/6 コメント / 返信文 │ ──保存──▶ │ 返信文作成    │
│ B コメント │           │ 6/5 コメント / 返信文 │ ◀─返信文─  │              │
│ C コメント │           │ 6/4 コメント / 返信文 │  (赤矢印)  │              │
└──────────┘            └──────────────────┘            └──────────────┘
```

- 図では中央が「Google ドキュメント」だが、指示どおり **スプレッドシート** を正とする
  (NotebookLM 側のソースとしては Google ドキュメントを経由する案もあり → §4.3)。
- 日付単位(6/6, 6/5, 6/4)でコメントをまとめ、各コメントに「返信文」欄を持つ。
- 赤矢印(NotebookLM → 返信文欄への書き戻し)は **フェーズ2** とし、今回のスコープは
  「取得 → シート保存 → NotebookLM 保存」まで。

## 2. 全体アーキテクチャ

```
[cron / 手動実行]
      │
      ▼
 fetch_comments  ── YouTube Data API v3 ──▶  コメント一覧 (新着のみ)
      │
      ▼
 store_sheet     ── Sheets API (gspread) ──▶ スプレッドシート「comments」に追記 (comment_id で重複排除)
      │
      ▼
 export_notebook ── 日付ごとの Markdown/Doc を生成 ──▶ NotebookLM ソースとして追加
      │
      ▼
 state 更新      (最終実行時刻、動画ごとの最終チェック時刻)
```

1 本の CLI (`python -m ytnb run`) で上記を順に実行。各段は独立モジュールにし、
`--skip-notebook` のように途中まで実行できるようにする。

## 3. 技術選定

| 項目 | 選定 | 理由 |
|---|---|---|
| 言語 | Python 3.12 | Google 系ライブラリが最も揃っている。非公式 NotebookLM ライブラリも Python |
| YouTube | `google-api-python-client` (Data API v3) | 公式。公開コメントなら API キーのみで取得可 |
| Sheets | `gspread` + サービスアカウント | 認証が簡単(SA のメールをシートに共有するだけ) |
| NotebookLM | §4.3 で 3 案比較。MVP は Drive 経由 | 個人向け公式 API が無いため |
| 設定 | `.env` + `config.yaml` | 秘密情報は `.env`、チャンネル ID などは yaml |
| 実行 | まず手動 → cron (WSL) or GitHub Actions | 1 日 1 回で十分 |

## 4. 各段の設計

### 4.1 YouTube コメント取得

- `allThreadsRelatedToChannelId` は **非推奨** かつ OAuth 必須なので使わない。
- 手順:
  1. `channels.list(part=contentDetails, id=CHANNEL_ID)` → `uploads` プレイリスト ID
  2. `playlistItems.list(playlistId=uploads, maxResults=50)` → 動画 ID 一覧
     (直近 N 本、または `publishedAfter` 相当で絞る)
  3. 動画ごとに `commentThreads.list(videoId, part=snippet,replies, order=time,
     maxResults=100, textFormat=plainText)` をページング
  4. 前回取得済み(`state` シートの `last_fetched_at` / 既存 `comment_id`)より新しいものだけ採用
- クォータ: 10,000 unit/日。`commentThreads.list` は 1 unit/呼び出し(100 件)なので
  動画 50 本 × 数ページでも余裕。
- 認証: 公開コメントのみなら **API キー** で足りる。フェーズ2 で返信投稿するなら OAuth
  (`youtube.force-ssl` スコープ)が必要になるので、認証部分は差し替え可能にしておく。
- コメントが無効化されている動画は 403 `commentsDisabled` → スキップしてログ。

### 4.2 スプレッドシート保存

シート `comments`(1 行 = 1 コメント、返信も同じ表に `parent_id` 付きで格納):

| 列 | 内容 |
|---|---|
| comment_id | 主キー。重複排除に使用 |
| video_id / video_title | 対象動画 |
| published_at | コメント投稿日時 (JST に変換) |
| date | published_at の日付。図の「6/6」「6/5」に対応。フィルタ用 |
| author | 表示名 |
| text | 本文(plainText) |
| like_count / reply_count | 補助情報 |
| parent_id | 返信の場合、親コメント ID |
| fetched_at | 取得日時 |
| reply_draft | **返信文**(フェーズ2 で NotebookLM から書き戻す) |
| reply_status | 空 / draft / posted |

シート `state`(キー・値):`last_run_at`, `last_comment_published_at`, `notebook_last_export_date` など。

- 書き込みは `append_rows` でバッチ(1 件ずつ書かない → API 制限 60 req/分 対策)。
- 既存 `comment_id` を先に一括読込して差分だけ追記。

### 4.3 NotebookLM 保存(3 案)

| 案 | 方法 | 長所 | 短所 |
|---|---|---|---|
| **A. Drive 経由** | 日付ごとに Google ドキュメント(例「2026-06-06 コメント」)を Drive に生成し、NotebookLM に Drive ソースとして追加。更新時は NotebookLM 側で「Drive と同期」 | 公式機能のみ。壊れにくい | ソース追加・同期クリックが **手動** |
| B. 非公式ライブラリ | `notebooklm-py`(ブラウザの認証情報を流用)で `add_text` / `add_drive` / `refresh` | 全自動。フェーズ2 のチャット問い合わせも可 | 非公式。仕様変更で壊れる、規約リスク |
| C. NotebookLM Enterprise API | Google Cloud の公式 API (`notebooks` / `sources`) | 公式・全自動 | Gemini Enterprise ライセンスが必要でコスト大 |

**推奨: MVP は A、`NotebookSink` インターフェースを切って B を差し替え可能にする。**
A であっても「ソースにする Doc を自動生成する」ところまでは自動化できる。

ソース設計:
- 1 日 1 ソース(図の 6/6・6/5・6/4 に対応)。内容は Markdown 風テキスト:
  ```
  # 2026-06-06 のコメント (チャンネル名)
  ## [動画タイトル](URL)
  - (author, 12:34) コメント本文
    - ↳ 返信: ...
  ```
- NotebookLM のソース上限(無料 50 / Pro 300)があるので、
  日次ソースは直近 N 日分だけ保持し、古い分は月次ソースに集約するか削除する方針を決める。
- ソース側に `reply_draft` は含めない(NotebookLM に「生成させる」対象なので)。

## 5. ディレクトリ構成(案)

```
nb/
├── PLAN.md
├── a1.jpg
├── config.yaml          # channel_id, spreadsheet_id, notebook 設定, 取得範囲
├── .env                 # YOUTUBE_API_KEY, GOOGLE_SA_JSON パス
├── pyproject.toml
└── ytnb/
    ├── __main__.py      # CLI: run / fetch / export
    ├── youtube.py       # 4.1
    ├── sheet.py         # 4.2
    ├── notebook/        # 4.3
    │   ├── base.py      # NotebookSink インターフェース
    │   ├── drive.py     # 案A
    │   └── nblm.py      # 案B (任意)
    ├── models.py        # Comment dataclass
    └── state.py
```

## 6. 実装ステップ

| # | 作業 | 完了条件 |
|---|---|---|
| 0 | GCP プロジェクト作成、YouTube Data API / Sheets API / Drive API 有効化、API キー & サービスアカウント発行、シートを SA に共有 | 手動で API 呼び出しが通る |
| 1 | `youtube.py`: チャンネル → 動画 → コメント取得。`--dry-run` で JSON 出力 | 指定チャンネルのコメントが件数一致で取れる |
| 2 | `sheet.py`: スキーマ作成、差分追記、state 読み書き | 2 回実行して重複が増えない |
| 3 | `notebook/drive.py`: 日付ごとの Doc 生成・更新 | Drive に Doc ができ、NotebookLM から手動で追加・同期できる |
| 4 | CLI 統合、ログ、エラー処理(クォータ超過・コメント無効動画) | `python -m ytnb run` 一発で全段通る |
| 5 | 定期実行(cron or GitHub Actions)、秘密情報の扱い | 無人で 1 日 1 回動く |
| 6 | (任意) `notebook/nblm.py` で案 B に置換し完全自動化 | 手動同期なしでソースが更新される |
| 7 | **フェーズ2**: NotebookLM で返信文生成 → `reply_draft` 列へ書き戻し → (将来) YouTube へ返信投稿 | — |

## 7. リスク・注意点

- NotebookLM 個人版に公式 API が無い → 完全自動化は非公式手段に依存する(§4.3)。
- YouTube クォータ超過時は翌日まで待つしかない → 取得範囲(直近 N 本)を設定で絞る。
- コメントには個人名が含まれる → シート・Doc の共有範囲は最小限に。
- 図は「Google ドキュメント」表記。スプレッドシート主 + Doc は NotebookLM 用の派生物、と整理する。

## 8. 確認したいこと(実装前に決めたい)

1. 対象チャンネルは **自分のチャンネル** か、他人のチャンネルか(返信投稿の要否・OAuth に影響)
2. 取得範囲: 全動画の全コメントを初回に取るか、直近 N 本 / 直近 M 日だけか
3. 実行頻度(1 日 1 回想定)
4. NotebookLM 連携は案 A(半手動)で始めてよいか、最初から案 B(非公式・全自動)を試すか
5. 日付ソースの保持期間(直近 30 日など)
6. 言語は Python でよいか(GAS = Google Apps Script で Sheets/Drive 側を書く案もある)
