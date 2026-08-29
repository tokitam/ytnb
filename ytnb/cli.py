from __future__ import annotations

import argparse
import logging
import sys

import gspread
from googleapiclient.errors import HttpError

from ytnb import pipeline
from ytnb.auth import AuthError, drive_credentials, manual_auth_finish, manual_auth_url
from ytnb.config import load_config
from ytnb.sheet import SheetStore
from ytnb.youtube import QuotaExceeded


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ytnb", description="YouTube コメント -> スプレッドシート -> NotebookLM")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--env", default=".env")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="fetch -> シート保存 -> NotebookLM 出力 を一括実行")
    r.add_argument("--since", help="この日時 (ISO8601) 以降のコメントだけ取得。省略時は state から自動")
    r.add_argument("--skip-notebook", action="store_true", help="NotebookLM 出力を行わない")
    r.add_argument("--dry-run", action="store_true", help="シートに書かず、取得結果を JSON で表示")

    f = sub.add_parser("fetch", help="YouTube からコメントを取得して JSON 表示 (シートに書かない)")
    f.add_argument("--since")

    e = sub.add_parser("export", help="シートの内容から NotebookLM 用ソースを再生成")
    e.add_argument("--date", action="append", help="対象日 (YYYY-MM-DD)。複数可。省略時は保持期間内すべて")

    a = sub.add_parser("auth", help="Drive 用の OAuth ログインを行い token.json を保存する (初回のみ)")
    a.add_argument("--manual", action="store_true",
                   help="ログイン URL を表示するだけ (WSL など localhost へのリダイレクトが届かない環境向け)")
    a.add_argument("--response", metavar="URL",
                   help="--manual でログイン後、ブラウザのアドレスバーに出た URL (localhost:8765/?...) を貼り付ける")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        cfg = load_config(args.config, args.env)
    except (FileNotFoundError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2

    try:
        if args.cmd == "auth":
            if args.response:
                manual_auth_finish(cfg.oauth_client_json, cfg.oauth_token_path, args.response)
            elif args.manual:
                print("1. 次の URL をブラウザで開いてログインしてください:\n")
                print(manual_auth_url(cfg.oauth_client_json))
                print(
                    "\n2. 「このサイトにアクセスできません (localhost)」と出たら、そのページの"
                    " アドレスバーの URL 全体をコピーして次を実行:\n"
                    "   python -m ytnb auth --response 'http://localhost:8765/?state=...&code=...'"
                )
                return 0
            else:
                drive_credentials(cfg, interactive=True)
            print(f"OK: 認証済み (token: {cfg.oauth_token_path})")
            return 0
        if args.cmd == "run":
            return pipeline.run(cfg, args.since, args.skip_notebook, args.dry_run)
        if args.cmd == "fetch":
            return pipeline.run(cfg, args.since, skip_notebook=True, dry_run=True)
        if args.cmd == "export":
            store = SheetStore.open(
                cfg.sa_json, cfg.sheet.spreadsheet_id, cfg.sheet.comments_sheet, cfg.sheet.state_sheet
            )
            dates = set(args.date) if args.date else None
            exported = pipeline.export(cfg, store, dates)
            print(f"出力: {len(exported)} 日分 {sorted(exported)}")
            return 0
    except QuotaExceeded as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 3
    except (PermissionError, gspread.exceptions.SpreadsheetNotFound) as e:
        cause = e.__cause__ or e
        print(f"エラー: スプレッドシートにアクセスできません: {cause}", file=sys.stderr)
        print(
            "確認すること:\n"
            "  - Google Sheets API がプロジェクトで有効化されているか\n"
            "  - sheet.spreadsheet_id が正しいか (URL の /d/ と /edit の間)\n"
            "  - サービスアカウントの client_email にシートを「編集者」で共有したか",
            file=sys.stderr,
        )
        return 4
    except gspread.exceptions.APIError as e:
        print(f"エラー: Google Sheets API: {e}", file=sys.stderr)
        return 4
    except AuthError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 5
    except HttpError as e:
        reasons = {d.get("reason") for d in (getattr(e, "error_details", None) or []) if isinstance(d, dict)}
        print(f"エラー: Google API: {e}", file=sys.stderr)
        if "storageQuotaExceeded" in reasons:
            print(
                "  サービスアカウントは Drive の容量を持たないため Doc を作れません。\n"
                "  notebook.drive.auth を \"oauth\" にして `python -m ytnb auth` でログインしてください",
                file=sys.stderr,
            )
        elif "notFound" in reasons:
            print("  notebook.drive.folder_id が正しいか、そのフォルダにアクセスできるか確認してください", file=sys.stderr)
        return 5
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
