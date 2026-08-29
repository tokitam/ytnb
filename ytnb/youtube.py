"""YouTube Data API v3 からチャンネルのコメントを取得する。

allThreadsRelatedToChannelId は非推奨 (かつ OAuth 必須) のため、
チャンネル -> uploads プレイリスト -> 動画 -> commentThreads の順にたどる。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Iterator

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ytnb.models import Comment, parse_youtube_time, to_local

log = logging.getLogger(__name__)


class QuotaExceeded(Exception):
    """YouTube API の日次クォータを超過した。翌日まで待つしかない。"""


def _error_reasons(e: HttpError) -> set[str]:
    reasons = set()
    for d in getattr(e, "error_details", None) or []:
        if isinstance(d, dict) and d.get("reason"):
            reasons.add(d["reason"])
    if not reasons:
        # error_details が無い古い形式
        try:
            import json

            body = json.loads(e.content.decode("utf-8"))
            for err in body.get("error", {}).get("errors", []):
                if err.get("reason"):
                    reasons.add(err["reason"])
        except Exception:  # noqa: BLE001
            pass
    return reasons


class YouTubeClient:
    def __init__(self, api_key: str, tz: str = "Asia/Tokyo", service=None):
        # service を渡せるようにしてテストでモック可能にする
        self.svc = service or build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        self.tz = tz

    # ---- 動画一覧 -------------------------------------------------------

    def uploads_playlist_id(self, channel_id: str) -> str:
        res = self._call(self.svc.channels().list(part="contentDetails", id=channel_id))
        items = res.get("items", [])
        if not items:
            raise ValueError(f"チャンネルが見つかりません: {channel_id}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def list_videos(self, channel_id: str, max_videos: int = 20) -> list[dict]:
        """直近 max_videos 本の {video_id, title, published_at} を返す。"""
        playlist_id = self.uploads_playlist_id(channel_id)
        videos: list[dict] = []
        page_token = None
        while len(videos) < max_videos:
            res = self._call(
                self.svc.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=playlist_id,
                    maxResults=min(50, max_videos - len(videos)),
                    pageToken=page_token,
                )
            )
            for it in res.get("items", []):
                videos.append(
                    {
                        "video_id": it["contentDetails"]["videoId"],
                        "title": it["snippet"]["title"],
                        "published_at": it["contentDetails"].get(
                            "videoPublishedAt", it["snippet"]["publishedAt"]
                        ),
                    }
                )
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return videos[:max_videos]

    # ---- コメント -------------------------------------------------------

    def fetch_video_comments(
        self,
        video_id: str,
        video_title: str,
        since: datetime | None = None,
        full_replies: bool = True,
    ) -> Iterator[Comment]:
        """1 動画分のコメント(トップレベル + 返信)を新しい順に返す。

        since を指定した場合、トップレベルコメントの publishedAt が since より古くなった
        時点でページングを打ち切る (order=time は新しい順のため)。
        """
        fetched_at = datetime.now(timezone.utc).isoformat()
        page_token = None
        while True:
            try:
                res = self._call(
                    self.svc.commentThreads().list(
                        part="snippet,replies",
                        videoId=video_id,
                        order="time",
                        maxResults=100,
                        textFormat="plainText",
                        pageToken=page_token,
                    )
                )
            except HttpError as e:
                reasons = _error_reasons(e)
                if e.resp.status == 403 and "commentsDisabled" in reasons:
                    log.warning("コメント無効のためスキップ: %s (%s)", video_id, video_title)
                    return
                if e.resp.status == 404:
                    log.warning("動画が見つからないためスキップ: %s", video_id)
                    return
                raise

            stop = False
            for thread in res.get("items", []):
                top = thread["snippet"]["topLevelComment"]
                top_snip = top["snippet"]
                published = parse_youtube_time(top_snip["publishedAt"])
                if since and published < since:
                    stop = True
                    break

                total_replies = int(thread["snippet"].get("totalReplyCount", 0))
                yield self._to_comment(top, video_id, video_title, fetched_at, reply_count=total_replies)

                inline = thread.get("replies", {}).get("comments", [])
                if full_replies and total_replies > len(inline):
                    replies: Iterable[dict] = self._all_replies(top["id"])
                else:
                    replies = inline
                for r in replies:
                    yield self._to_comment(r, video_id, video_title, fetched_at, parent_id=top["id"])

            page_token = res.get("nextPageToken")
            if stop or not page_token:
                return

    def _all_replies(self, parent_id: str) -> Iterator[dict]:
        page_token = None
        while True:
            res = self._call(
                self.svc.comments().list(
                    part="snippet",
                    parentId=parent_id,
                    maxResults=100,
                    textFormat="plainText",
                    pageToken=page_token,
                )
            )
            yield from res.get("items", [])
            page_token = res.get("nextPageToken")
            if not page_token:
                return

    def _to_comment(
        self,
        item: dict,
        video_id: str,
        video_title: str,
        fetched_at: str,
        parent_id: str = "",
        reply_count: int = 0,
    ) -> Comment:
        s = item["snippet"]
        local = to_local(s["publishedAt"], self.tz)
        return Comment(
            comment_id=item["id"],
            video_id=video_id,
            video_title=video_title,
            published_at=local.isoformat(),
            date=local.strftime("%Y-%m-%d"),
            author=s.get("authorDisplayName", ""),
            text=s.get("textOriginal") or s.get("textDisplay", ""),
            like_count=int(s.get("likeCount", 0)),
            reply_count=reply_count,
            parent_id=parent_id,
            fetched_at=fetched_at,
        )

    # ---- 共通 -----------------------------------------------------------

    @staticmethod
    def _call(request):
        try:
            return request.execute()
        except HttpError as e:
            if e.resp.status == 403 and "quotaExceeded" in _error_reasons(e):
                raise QuotaExceeded("YouTube API のクォータを超過しました。翌日再実行してください。") from e
            raise


def fetch_channel_comments(
    client: YouTubeClient,
    channel_id: str,
    max_videos: int,
    since: datetime | None,
    full_replies: bool = True,
) -> list[Comment]:
    videos = client.list_videos(channel_id, max_videos)
    log.info("対象動画: %d 本", len(videos))
    comments: list[Comment] = []
    for v in videos:
        # 動画のトップレベルコメントは動画公開日より前には存在しないので、
        # 動画自体が since より古くてもコメントは新しい可能性がある -> 全動画チェックする
        n_before = len(comments)
        comments.extend(
            client.fetch_video_comments(v["video_id"], v["title"], since=since, full_replies=full_replies)
        )
        log.info("  %s: %d 件  (%s)", v["video_id"], len(comments) - n_before, v["title"])
    return comments
