"""Google スプレッドシートへの保存と state 管理。"""
from __future__ import annotations

import logging
from typing import Iterable

import gspread

from ytnb.models import COLUMNS, Comment

log = logging.getLogger(__name__)

STATE_HEADER = ["key", "value"]


class SheetStore:
    def __init__(self, spreadsheet, comments_sheet: str = "comments", state_sheet: str = "state"):
        # spreadsheet は gspread.Spreadsheet (テストでは差し替え可)
        self.ss = spreadsheet
        self.ws_comments = self._get_or_create(comments_sheet, COLUMNS, cols=len(COLUMNS))
        self.ws_state = self._get_or_create(state_sheet, STATE_HEADER, cols=2)

    @classmethod
    def open(cls, sa_json: str, spreadsheet_id: str, comments_sheet: str, state_sheet: str) -> "SheetStore":
        gc = gspread.service_account(filename=sa_json)
        return cls(gc.open_by_key(spreadsheet_id), comments_sheet, state_sheet)

    def _get_or_create(self, title: str, header: list[str], cols: int):
        try:
            ws = self.ss.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.ss.add_worksheet(title=title, rows=1000, cols=cols)
            ws.append_row(header, value_input_option="RAW")
            log.info("シート作成: %s", title)
            return ws
        first = ws.row_values(1)
        if not first:
            ws.append_row(header, value_input_option="RAW")
        elif first[: len(header)] != header:
            raise ValueError(f"シート '{title}' のヘッダーが想定と異なります: {first}")
        return ws

    # ---- comments -------------------------------------------------------

    def existing_ids(self) -> set[str]:
        ids = self.ws_comments.col_values(1)
        return set(ids[1:])  # ヘッダーを除く

    def append_comments(self, comments: Iterable[Comment]) -> list[Comment]:
        """comment_id が未登録のものだけ追記して、追記した分を返す。"""
        known = self.existing_ids()
        new: list[Comment] = []
        seen: set[str] = set()
        for c in comments:
            if c.comment_id in known or c.comment_id in seen:
                continue
            seen.add(c.comment_id)
            new.append(c)
        if new:
            rows = [c.to_row() for c in new]
            # 1 リクエストにまとめる (Sheets API は 60 req/分)
            for i in range(0, len(rows), 500):
                self.ws_comments.append_rows(rows[i : i + 500], value_input_option="RAW")
        log.info("シート追記: %d 件 (既存 %d 件)", len(new), len(known))
        return new

    def all_comments(self) -> list[Comment]:
        values = self.ws_comments.get_all_values()
        return [Comment.from_row(r) for r in values[1:] if r and r[0]]

    def comments_by_date(self, dates: set[str] | None = None) -> dict[str, list[Comment]]:
        grouped: dict[str, list[Comment]] = {}
        for c in self.all_comments():
            if dates is not None and c.date not in dates:
                continue
            grouped.setdefault(c.date, []).append(c)
        return grouped

    # ---- state ----------------------------------------------------------

    def get_state(self, key: str, default: str = "") -> str:
        for row in self.ws_state.get_all_values()[1:]:
            if row and row[0] == key:
                return row[1] if len(row) > 1 else default
        return default

    def set_state(self, key: str, value: str) -> None:
        rows = self.ws_state.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if row and row[0] == key:
                self.ws_state.update_cell(idx, 2, value)
                return
        self.ws_state.append_row([key, value], value_input_option="RAW")
