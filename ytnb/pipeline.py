"""fetch -> store -> export の各段をつなぐ。"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date as date_type, datetime, timedelta, timezone

from ytnb.config import Config
from ytnb.export import render_day
from ytnb.models import Comment
from ytnb.notebook import make_sink
from ytnb.notebook.base import NotebookSink
from ytnb.sheet import SheetStore
from ytnb.youtube import YouTubeClient, fetch_channel_comments

log = logging.getLogger(__name__)

KEY_LAST_RUN = "last_run_at"
KEY_LAST_PUBLISHED = "last_comment_published_at"
KEY_LAST_EXPORT = "notebook_last_export_date"


def resolve_since(store: SheetStore | None, cfg: Config, since_arg: str | None) -> datetime | None:
    """取得開始日時を決める。優先: --since > state の最終取得 - overlap_days > None (全件)。"""
    if since_arg:
        dt = datetime.fromisoformat(since_arg)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if store is None:
        return None
    last = store.get_state(KEY_LAST_PUBLISHED)
    if not last:
        return None
    return datetime.fromisoformat(last) - timedelta(days=cfg.youtube.overlap_days)


def fetch(cfg: Config, since: datetime | None, client: YouTubeClient | None = None) -> list[Comment]:
    client = client or YouTubeClient(cfg.youtube_api_key, tz=cfg.timezone)
    log.info("取得開始: channel=%s since=%s", cfg.youtube.channel_id, since.isoformat() if since else "全件")
    return fetch_channel_comments(
        client,
        cfg.youtube.channel_id,
        cfg.youtube.max_videos,
        since,
        full_replies=cfg.youtube.full_replies,
    )


def store(store: SheetStore, comments: list[Comment]) -> list[Comment]:
    new = store.append_comments(comments)
    # シート追記が成功してから state を更新する (途中失敗で取りこぼさないため)
    if comments:
        newest = max(c.published_at for c in comments)
        prev = store.get_state(KEY_LAST_PUBLISHED)
        if not prev or newest > prev:
            store.set_state(KEY_LAST_PUBLISHED, newest)
    store.set_state(KEY_LAST_RUN, datetime.now(timezone.utc).isoformat())
    return new


def export(
    cfg: Config,
    store: SheetStore,
    dates: set[str] | None,
    sink: NotebookSink | None = None,
    today: date_type | None = None,
) -> list[str]:
    """dates (None なら保持期間内の全日付) の Doc を再生成し、保持期間外を削除する。"""
    sink = sink or make_sink(cfg)
    today = today or datetime.now().date()
    retention = cfg.notebook.retention_days
    cutoff = (today - timedelta(days=retention)).isoformat() if retention > 0 else None

    grouped = store.comments_by_date(dates)
    if dates is not None:
        missing = sorted(set(dates) - set(grouped))
        if missing:
            log.warning("シートに該当コメントが無い日付: %s", ", ".join(missing))
    exported: list[str] = []
    for d in sorted(grouped):
        # 明示的に --date で指定された日付は保持期間に関係なく出力する
        if cutoff and d < cutoff and dates is None:
            log.info("保持期間外のためスキップ: %s (cutoff=%s)", d, cutoff)
            continue
        text = render_day(d, grouped[d], cfg.notebook.channel_name or cfg.youtube.channel_id)
        ident = sink.upsert(d, text)
        exported.append(d)
        log.info("NotebookLM ソース出力: %s -> %s (%d 件)", d, ident, len(grouped[d]))

    # 保持期間外の Doc の掃除は全体出力 (dates=None) のときだけ行う
    if cutoff and dates is None:
        for d, ident in sink.list_dates().items():
            if d < cutoff:
                sink.delete(ident)
                log.info("保持期間外のため削除: %s", d)

    if exported:
        store.set_state(KEY_LAST_EXPORT, max(exported))
    else:
        log.warning("出力対象の日付がありません (シートの日付と retention_days を確認してください)")
    return exported


def run(cfg: Config, since_arg: str | None, skip_notebook: bool, dry_run: bool) -> int:
    if dry_run:
        comments = fetch(cfg, resolve_since(None, cfg, since_arg))
        print(json.dumps([asdict(c) for c in comments], ensure_ascii=False, indent=2))
        return 0

    store_ = SheetStore.open(
        cfg.sa_json, cfg.sheet.spreadsheet_id, cfg.sheet.comments_sheet, cfg.sheet.state_sheet
    )
    since = resolve_since(store_, cfg, since_arg)
    comments = fetch(cfg, since)
    new = store(store_, comments)

    if skip_notebook or cfg.notebook.sink == "none":
        return 0
    affected = {c.date for c in new}
    if not affected:
        log.info("新着コメントなし。NotebookLM 出力はスキップ")
        return 0
    export(cfg, store_, affected)
    return 0
