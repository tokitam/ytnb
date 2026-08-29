import pytest

from ytnb.config import load_config


def _write(tmp_path, yaml_text, sa=True):
    (tmp_path / "config.yaml").write_text(yaml_text, encoding="utf-8")
    sa_path = tmp_path / "sa.json"
    if sa:
        sa_path.write_text("{}")
    (tmp_path / ".env").write_text(f"YOUTUBE_API_KEY=k\nGOOGLE_SA_JSON={sa_path}\n")
    return tmp_path / "config.yaml", tmp_path / ".env"


def test_load_ok(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    cfg_path, env_path = _write(
        tmp_path,
        """
youtube: {channel_id: UCabc, max_videos: 5}
sheet: {spreadsheet_id: sheet123}
notebook: {sink: local, local: {out_dir: ./o}}
""",
    )
    cfg = load_config(cfg_path, env_path)
    assert cfg.youtube.max_videos == 5 and cfg.youtube.overlap_days == 3
    assert cfg.notebook.sink == "local" and cfg.notebook.local_out_dir == "./o"
    assert cfg.youtube_api_key == "k"


def test_drive_requires_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    cfg_path, env_path = _write(
        tmp_path,
        """
youtube: {channel_id: UCabc}
sheet: {spreadsheet_id: sheet123}
notebook: {sink: drive}
""",
    )
    with pytest.raises(ValueError, match="folder_id"):
        load_config(cfg_path, env_path)


def test_drive_auth_default_and_validation(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    cfg_path, env_path = _write(
        tmp_path,
        """
youtube: {channel_id: UCabc}
sheet: {spreadsheet_id: sheet123}
notebook: {sink: drive, drive: {folder_id: f1}}
""",
    )
    cfg = load_config(cfg_path, env_path)
    assert cfg.notebook.drive_auth == "oauth"
    assert cfg.oauth_token_path == "./token.json"

    cfg_path, env_path = _write(
        tmp_path,
        """
youtube: {channel_id: UCabc}
sheet: {spreadsheet_id: sheet123}
notebook: {sink: drive, drive: {folder_id: f1, auth: bogus}}
""",
    )
    with pytest.raises(ValueError, match="drive.auth"):
        load_config(cfg_path, env_path)


def test_manual_auth_url_saves_verifier(tmp_path, monkeypatch):
    import json
    from ytnb import auth

    monkeypatch.chdir(tmp_path)
    client = tmp_path / "c.json"
    client.write_text(json.dumps({"installed": {
        "client_id": "id", "client_secret": "sec", "project_id": "p",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}}))
    url = auth.manual_auth_url(str(client))
    assert "code_challenge=" in url and "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2F" in url
    saved = json.loads((tmp_path / auth.MANUAL_STATE_FILE).read_text())
    assert saved["state"] in url and saved["code_verifier"]

    with pytest.raises(auth.AuthError, match="state が一致しません"):
        auth.manual_auth_finish(str(client), "t.json", "http://localhost:8765/?state=WRONG&code=abc")
