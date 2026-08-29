import json
from datetime import datetime, timezone

import httplib2
import pytest
from googleapiclient.errors import HttpError

from tests.fakes import FakeYouTubeService
from ytnb.youtube import QuotaExceeded, YouTubeClient, fetch_channel_comments


def _http_error(status, reason):
    body = json.dumps({"error": {"errors": [{"reason": reason}], "code": status}}).encode()
    return HttpError(httplib2.Response({"status": status}), body)


def _thread(cid, published, text, replies=(), total=None):
    return {
        "snippet": {
            "topLevelComment": {
                "id": cid,
                "snippet": {
                    "publishedAt": published,
                    "authorDisplayName": f"user-{cid}",
                    "textOriginal": text,
                    "likeCount": 2,
                },
            },
            "totalReplyCount": total if total is not None else len(replies),
        },
        "replies": {"comments": list(replies)},
    }


def _reply(rid, published, text="reply"):
    return {"id": rid, "snippet": {"publishedAt": published, "authorDisplayName": "rep", "textOriginal": text}}


CHANNEL = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUxxx"}}}]}
PLAYLIST = [
    {
        "items": [
            {"contentDetails": {"videoId": "v1", "videoPublishedAt": "2026-06-01T00:00:00Z"}, "snippet": {"title": "動画1", "publishedAt": "2026-06-01T00:00:00Z"}},
            {"contentDetails": {"videoId": "v2", "videoPublishedAt": "2026-05-01T00:00:00Z"}, "snippet": {"title": "動画2", "publishedAt": "2026-05-01T00:00:00Z"}},
        ]
    }
]


def test_fetch_flattens_replies_and_converts_timezone():
    threads = {
        "v1": [
            {
                "items": [
                    _thread("c1", "2026-06-05T20:00:00Z", "  hello\n world ", replies=[_reply("r1", "2026-06-05T21:00:00Z")]),
                ]
            }
        ],
        "v2": [{"items": []}],
    }
    svc = FakeYouTubeService(CHANNEL, PLAYLIST, threads)
    client = YouTubeClient("key", tz="Asia/Tokyo", service=svc)
    comments = fetch_channel_comments(client, "UCx", 10, since=None)

    assert [c.comment_id for c in comments] == ["c1", "r1"]
    top, rep = comments
    assert top.date == "2026-06-06"  # UTC 20:00 -> JST 翌日 05:00
    assert top.published_at.startswith("2026-06-06T05:00:00+09:00")
    assert top.reply_count == 1 and top.parent_id == ""
    assert rep.parent_id == "c1" and rep.video_title == "動画1"
    assert top.like_count == 2


def test_since_stops_paging():
    threads = {
        "v1": [
            {"items": [_thread("new", "2026-06-06T00:00:00Z", "n"), _thread("old", "2026-06-01T00:00:00Z", "o")], "nextPageToken": "1"},
            {"items": [_thread("older", "2026-05-01T00:00:00Z", "x")]},
        ],
        "v2": [{"items": []}],
    }
    svc = FakeYouTubeService(CHANNEL, PLAYLIST, threads)
    client = YouTubeClient("key", service=svc)
    since = datetime(2026, 6, 3, tzinfo=timezone.utc)
    comments = fetch_channel_comments(client, "UCx", 10, since=since)
    assert [c.comment_id for c in comments] == ["new"]
    # 2 ページ目は取りに行かない
    assert sum(1 for name, kw in svc.calls if name == "commentThreads.list" and kw["videoId"] == "v1") == 1


def test_full_replies_fetched_when_more_than_inline():
    threads = {
        "v1": [{"items": [_thread("c1", "2026-06-06T00:00:00Z", "t", replies=[_reply("r1", "2026-06-06T01:00:00Z")], total=3)]}],
        "v2": [{"items": []}],
    }
    replies = {"c1": [_reply("r1", "2026-06-06T01:00:00Z"), _reply("r2", "2026-06-06T02:00:00Z"), _reply("r3", "2026-06-06T03:00:00Z")]}
    svc = FakeYouTubeService(CHANNEL, PLAYLIST, threads, replies)
    client = YouTubeClient("key", service=svc)
    comments = fetch_channel_comments(client, "UCx", 10, since=None)
    assert [c.comment_id for c in comments] == ["c1", "r1", "r2", "r3"]


def test_comments_disabled_is_skipped():
    threads = {"v1": _http_error(403, "commentsDisabled"), "v2": [{"items": [_thread("c2", "2026-06-06T00:00:00Z", "t")]}]}
    svc = FakeYouTubeService(CHANNEL, PLAYLIST, threads)
    client = YouTubeClient("key", service=svc)
    comments = fetch_channel_comments(client, "UCx", 10, since=None)
    assert [c.comment_id for c in comments] == ["c2"]


def test_quota_exceeded_raises():
    threads = {"v1": _http_error(403, "quotaExceeded"), "v2": [{"items": []}]}
    svc = FakeYouTubeService(CHANNEL, PLAYLIST, threads)
    client = YouTubeClient("key", service=svc)
    with pytest.raises(QuotaExceeded):
        fetch_channel_comments(client, "UCx", 10, since=None)


def test_max_videos_limits():
    svc = FakeYouTubeService(CHANNEL, PLAYLIST, {"v1": [{"items": []}]})
    client = YouTubeClient("key", service=svc)
    assert [v["video_id"] for v in client.list_videos("UCx", 1)] == ["v1"]
