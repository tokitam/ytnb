"""ローカルの Markdown ファイルに出力する Sink。動作確認や、手動で NotebookLM にアップロードする用。"""
from __future__ import annotations

import re
from pathlib import Path

from ytnb.notebook.base import NotebookSink

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class LocalSink(NotebookSink):
    def __init__(self, out_dir: str, title_format: str = "{date} コメント"):
        self.out_dir = Path(out_dir)
        self.title_format = title_format

    def _path(self, date: str) -> Path:
        return self.out_dir / f"{self.title_format.format(date=date)}.md"

    def upsert(self, date: str, text: str) -> str:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        p = self._path(date)
        p.write_text(text, encoding="utf-8")
        return str(p)

    def list_dates(self) -> dict[str, str]:
        if not self.out_dir.exists():
            return {}
        result = {}
        for p in self.out_dir.glob("*.md"):
            m = DATE_RE.search(p.name)
            if m:
                result[m.group(1)] = str(p)
        return result

    def delete(self, identifier: str) -> None:
        Path(identifier).unlink(missing_ok=True)
