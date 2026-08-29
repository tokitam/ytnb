from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class YouTubeConfig:
    channel_id: str
    max_videos: int = 20
    overlap_days: int = 3
    full_replies: bool = True


@dataclass
class SheetConfig:
    spreadsheet_id: str
    comments_sheet: str = "comments"
    state_sheet: str = "state"


@dataclass
class NotebookConfig:
    sink: str = "drive"
    retention_days: int = 30
    channel_name: str = ""
    drive_auth: str = "oauth"
    drive_folder_id: str = ""
    drive_title_format: str = "{date} コメント"
    local_out_dir: str = "./out"


@dataclass
class Config:
    youtube: YouTubeConfig
    sheet: SheetConfig
    notebook: NotebookConfig
    timezone: str = "Asia/Tokyo"
    youtube_api_key: str = ""
    sa_json: str = ""
    oauth_client_json: str = "./oauth_client.json"
    oauth_token_path: str = "./token.json"


def load_config(path: str | Path = "config.yaml", env_path: str | Path = ".env") -> Config:
    load_dotenv(env_path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    y = raw.get("youtube", {})
    s = raw.get("sheet", {})
    n = raw.get("notebook", {})
    d = n.get("drive", {}) or {}
    loc = n.get("local", {}) or {}

    cfg = Config(
        youtube=YouTubeConfig(
            channel_id=y.get("channel_id", ""),
            max_videos=int(y.get("max_videos", 20)),
            overlap_days=int(y.get("overlap_days", 3)),
            full_replies=bool(y.get("full_replies", True)),
        ),
        sheet=SheetConfig(
            spreadsheet_id=s.get("spreadsheet_id", ""),
            comments_sheet=s.get("comments_sheet", "comments"),
            state_sheet=s.get("state_sheet", "state"),
        ),
        notebook=NotebookConfig(
            sink=n.get("sink", "drive"),
            retention_days=int(n.get("retention_days", 30)),
            channel_name=n.get("channel_name", "") or "",
            drive_auth=d.get("auth", "oauth") or "oauth",
            drive_folder_id=d.get("folder_id", "") or "",
            drive_title_format=d.get("title_format", "{date} コメント"),
            local_out_dir=loc.get("out_dir", "./out"),
        ),
        timezone=raw.get("timezone", "Asia/Tokyo"),
        youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""),
        sa_json=os.environ.get("GOOGLE_SA_JSON", ""),
        oauth_client_json=os.environ.get("GOOGLE_OAUTH_CLIENT_JSON", "./oauth_client.json"),
        oauth_token_path=os.environ.get("GOOGLE_OAUTH_TOKEN", "./token.json"),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    problems = []
    if not cfg.youtube.channel_id or cfg.youtube.channel_id.startswith("UCxxxx"):
        problems.append("youtube.channel_id が未設定です")
    if not cfg.youtube_api_key:
        problems.append("環境変数 YOUTUBE_API_KEY が未設定です")
    if not cfg.sheet.spreadsheet_id or cfg.sheet.spreadsheet_id.startswith("1xxxx"):
        problems.append("sheet.spreadsheet_id が未設定です")
    if not cfg.sa_json or not Path(cfg.sa_json).exists():
        problems.append(f"GOOGLE_SA_JSON のファイルが見つかりません: {cfg.sa_json!r}")
    if cfg.notebook.sink not in ("drive", "local", "none"):
        problems.append(f"notebook.sink は drive/local/none のいずれか: {cfg.notebook.sink!r}")
    if cfg.notebook.sink == "drive" and not cfg.notebook.drive_folder_id:
        problems.append("notebook.sink=drive の場合 notebook.drive.folder_id が必要です")
    if cfg.notebook.sink == "drive" and cfg.notebook.drive_auth not in ("oauth", "service_account"):
        problems.append(f"notebook.drive.auth は oauth/service_account のいずれか: {cfg.notebook.drive_auth!r}")
    if problems:
        raise ValueError("設定エラー:\n  - " + "\n  - ".join(problems))
