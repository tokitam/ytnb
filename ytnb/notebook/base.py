from __future__ import annotations

from abc import ABC, abstractmethod


class NotebookSink(ABC):
    """NotebookLM のソースとなる「日付ごとのテキスト」の出力先。

    案 A: Drive に Google Doc を置き NotebookLM から手動で追加・同期 (DriveSink)
    案 B: notebooklm-py 等で直接ソース登録 (未実装。ここに追加する)
    """

    @abstractmethod
    def upsert(self, date: str, text: str) -> str:
        """date の内容を text で作成/更新し、識別子 (ファイル ID やパス) を返す。"""

    @abstractmethod
    def list_dates(self) -> dict[str, str]:
        """存在する {date: 識別子} を返す。"""

    @abstractmethod
    def delete(self, identifier: str) -> None: ...


class NullSink(NotebookSink):
    def upsert(self, date: str, text: str) -> str:
        return ""

    def list_dates(self) -> dict[str, str]:
        return {}

    def delete(self, identifier: str) -> None:
        return None
