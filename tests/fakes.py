"""ネットワーク不要のフェイク。"""
from __future__ import annotations

import gspread


class FakeRequest:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc

    def execute(self):
        if self.exc:
            raise self.exc
        return self.result


class FakeYouTubeService:
    """googleapiclient の youtube service を最小限に真似る。"""

    def __init__(self, channel_res, playlist_pages, thread_pages_by_video, replies_by_parent=None):
        self._channel = channel_res
        self._playlist = playlist_pages  # list of dict (page ごと)
        self._threads = thread_pages_by_video  # {video_id: [page, ...] or Exception}
        self._replies = replies_by_parent or {}
        self.calls = []

    def channels(self):
        svc = self

        class _C:
            def list(self, **kw):
                svc.calls.append(("channels.list", kw))
                return FakeRequest(svc._channel)

        return _C()

    def playlistItems(self):
        svc = self

        class _P:
            def list(self, **kw):
                svc.calls.append(("playlistItems.list", kw))
                idx = int(kw.get("pageToken") or 0)
                return FakeRequest(svc._playlist[idx])

        return _P()

    def commentThreads(self):
        svc = self

        class _T:
            def list(self, **kw):
                svc.calls.append(("commentThreads.list", kw))
                pages = svc._threads[kw["videoId"]]
                if isinstance(pages, Exception):
                    return FakeRequest(exc=pages)
                idx = int(kw.get("pageToken") or 0)
                return FakeRequest(pages[idx])

        return _T()

    def comments(self):
        svc = self

        class _R:
            def list(self, **kw):
                svc.calls.append(("comments.list", kw))
                return FakeRequest({"items": svc._replies.get(kw["parentId"], [])})

        return _R()


class FakeWorksheet:
    def __init__(self, rows=None):
        self.rows = [list(r) for r in (rows or [])]

    def row_values(self, i):
        return list(self.rows[i - 1]) if len(self.rows) >= i else []

    def col_values(self, i):
        return [r[i - 1] if len(r) >= i else "" for r in self.rows]

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def append_row(self, row, value_input_option=None):
        self.rows.append([str(v) for v in row])

    def append_rows(self, rows, value_input_option=None):
        for r in rows:
            self.append_row(r)

    def update_cell(self, r, c, v):
        row = self.rows[r - 1]
        while len(row) < c:
            row.append("")
        row[c - 1] = str(v)


class FakeSpreadsheet:
    def __init__(self):
        self.sheets: dict[str, FakeWorksheet] = {}

    def worksheet(self, title):
        if title not in self.sheets:
            raise gspread.WorksheetNotFound(title)
        return self.sheets[title]

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet()
        self.sheets[title] = ws
        return ws


class MemorySink:
    def __init__(self):
        self.docs: dict[str, str] = {}
        self.deleted: list[str] = []

    def upsert(self, date, text):
        self.docs[date] = text
        return f"id-{date}"

    def list_dates(self):
        return {d: f"id-{d}" for d in self.docs}

    def delete(self, identifier):
        self.deleted.append(identifier)
        self.docs.pop(identifier.removeprefix("id-"), None)
