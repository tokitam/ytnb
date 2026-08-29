"""NotebookLM に渡す日付単位のテキストを生成する。"""
from __future__ import annotations

from datetime import datetime

from ytnb.models import Comment


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def render_day(date: str, comments: list[Comment], channel_name: str = "") -> str:
    """1 日分のコメントを Markdown 風テキストにする。

    NotebookLM のソースとして読みやすいよう、動画ごとに見出しを付け、
    返信は親コメントの下にぶら下げる。reply_draft は含めない (NotebookLM に生成させる対象のため)。
    """
    title = f"# {date} のコメント"
    if channel_name:
        title += f" ({channel_name})"
    lines = [title, ""]

    tops = [c for c in comments if not c.parent_id]
    replies_by_parent: dict[str, list[Comment]] = {}
    for c in comments:
        if c.parent_id:
            replies_by_parent.setdefault(c.parent_id, []).append(c)

    # 親がこの日付に無い返信 (親は前日以前) は動画ごとに「返信のみ」としてまとめる
    orphan_replies = [c for c in comments if c.parent_id and c.parent_id not in {t.comment_id for t in tops}]

    by_video: dict[str, list[Comment]] = {}
    for c in tops + orphan_replies:
        by_video.setdefault(c.video_id, []).append(c)

    for vid, items in by_video.items():
        vtitle = items[0].video_title
        lines.append(f"## {vtitle}")
        lines.append(video_url(vid))
        lines.append("")
        for c in sorted(items, key=lambda x: x.published_at):
            prefix = "- ↳ 返信 (親: 前日以前のコメント)" if c.parent_id else "-"
            lines.append(f"{prefix} ({c.author}, {_hm(c.published_at)}) {_one_line(c.text)}")
            for r in sorted(replies_by_parent.get(c.comment_id, []), key=lambda x: x.published_at):
                lines.append(f"  - ↳ 返信 ({r.author}, {_hm(r.published_at)}) {_one_line(r.text)}")
        lines.append("")

    lines.append(f"合計 {len(tops)} 件のコメント、{len(comments) - len(tops)} 件の返信")
    return "\n".join(lines) + "\n"


def _hm(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        return iso


def _one_line(text: str) -> str:
    return " ".join(text.split())
