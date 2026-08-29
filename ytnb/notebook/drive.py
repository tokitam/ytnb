"""Google Drive 上に日付ごとの Google ドキュメントを作成/更新する Sink (案 A)。

- 認証は ytnb.auth で用意する (個人アカウントは OAuth、Workspace の共有ドライブはサービスアカウント)。
- ユーザーの Drive のフォルダ (folder_id) に Doc を作る -> NotebookLM の「Google ドライブ」から
  ソースとして追加できる。更新後は NotebookLM 側で「Drive と同期」を押す。
- text/plain をアップロードし Google Doc に変換する (Docs API は不要)。
"""
from __future__ import annotations

import io
import logging
import re

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from ytnb.notebook.base import NotebookSink

log = logging.getLogger(__name__)

DOC_MIME = "application/vnd.google-apps.document"
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class DriveSink(NotebookSink):
    def __init__(self, credentials, folder_id: str, title_format: str = "{date} コメント", service=None):
        if service is None:
            service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.svc = service
        self.folder_id = folder_id
        self.title_format = title_format

    def _title(self, date: str) -> str:
        return self.title_format.format(date=date)

    def _find(self, title: str) -> str | None:
        q = (
            f"name = '{title}' and '{self.folder_id}' in parents "
            f"and mimeType = '{DOC_MIME}' and trashed = false"
        )
        res = self.svc.files().list(q=q, fields="files(id,name)", pageSize=1, supportsAllDrives=True).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    def upsert(self, date: str, text: str) -> str:
        title = self._title(date)
        media = MediaIoBaseUpload(io.BytesIO(text.encode("utf-8")), mimetype="text/plain", resumable=False)
        file_id = self._find(title)
        if file_id:
            self.svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            log.info("Drive 更新: %s (%s)", title, file_id)
        else:
            meta = {"name": title, "mimeType": DOC_MIME, "parents": [self.folder_id]}
            res = (
                self.svc.files()
                .create(body=meta, media_body=media, fields="id", supportsAllDrives=True)
                .execute()
            )
            file_id = res["id"]
            log.info("Drive 作成: %s (%s)", title, file_id)
        return file_id

    def list_dates(self) -> dict[str, str]:
        q = f"'{self.folder_id}' in parents and mimeType = '{DOC_MIME}' and trashed = false"
        result: dict[str, str] = {}
        page_token = None
        while True:
            res = (
                self.svc.files()
                .list(q=q, fields="nextPageToken,files(id,name)", pageSize=100, pageToken=page_token,
                      supportsAllDrives=True, includeItemsFromAllDrives=True)
                .execute()
            )
            for f in res.get("files", []):
                m = DATE_RE.search(f["name"])
                if m:
                    result[m.group(1)] = f["id"]
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return result

    def delete(self, identifier: str) -> None:
        # 誤削除に備えてゴミ箱へ (完全削除はしない)
        self.svc.files().update(fileId=identifier, body={"trashed": True}, supportsAllDrives=True).execute()
        log.info("Drive ゴミ箱へ移動: %s", identifier)
