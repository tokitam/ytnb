from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from zoneinfo import ZoneInfo

# シート「comments」の列順。この順で書き込む。
COLUMNS = [
    "comment_id",
    "video_id",
    "video_title",
    "published_at",
    "date",
    "author",
    "text",
    "like_count",
    "reply_count",
    "parent_id",
    "fetched_at",
    "reply_draft",
    "reply_status",
]


@dataclass
class Comment:
    comment_id: str
    video_id: str
    video_title: str
    published_at: str  # ISO8601 (タイムゾーン変換済み)
    date: str  # YYYY-MM-DD
    author: str
    text: str
    like_count: int = 0
    reply_count: int = 0
    parent_id: str = ""
    fetched_at: str = ""
    reply_draft: str = ""
    reply_status: str = ""

    def to_row(self) -> list:
        return [getattr(self, c) for c in COLUMNS]

    @classmethod
    def from_row(cls, row: list) -> "Comment":
        values = dict(zip(COLUMNS, list(row) + [""] * (len(COLUMNS) - len(row))))
        values["like_count"] = _to_int(values["like_count"])
        values["reply_count"] = _to_int(values["reply_count"])
        return cls(**values)


def _to_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def parse_youtube_time(s: str) -> datetime:
    """YouTube の '2026-06-06T12:34:56Z' を aware datetime に。"""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def to_local(s: str, tz: str) -> datetime:
    return parse_youtube_time(s).astimezone(ZoneInfo(tz))
