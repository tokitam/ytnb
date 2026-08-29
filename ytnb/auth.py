"""Drive 用の認証情報を用意する。

- oauth: ユーザー自身の Google アカウントでログインし、トークンを token.json に保存する。
  個人 (gmail.com) アカウントでは Doc をユーザー所有にする必要があるためこちらを使う。
- service_account: 共有ドライブ (Google Workspace) に置く場合のみ。
  ※ サービスアカウントは My Drive のストレージ容量を持たないため、個人アカウントでは
    storageQuotaExceeded になる。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

log = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
# 手動モード用。ブラウザはこの URL に接続できず失敗するが、アドレスバーの URL に code が入る
MANUAL_REDIRECT_URI = "http://localhost:8765/"
MANUAL_STATE_FILE = ".ytnb_auth_state.json"


class AuthError(Exception):
    pass


def service_account_credentials(sa_json: str):
    return service_account.Credentials.from_service_account_file(sa_json, scopes=DRIVE_SCOPES)


def oauth_credentials(client_json: str, token_path: str, interactive: bool = False) -> Credentials:
    """token.json があれば読み込み (期限切れなら更新)、無ければ interactive=True のときだけログインする。"""
    token_file = Path(token_path)
    creds: Credentials | None = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), DRIVE_SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_file.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as e:  # noqa: BLE001 - 更新失敗時は再ログインへ
            log.warning("トークン更新に失敗 (%s)。再ログインが必要です", e)
            creds = None

    if not interactive:
        raise AuthError(
            f"OAuth トークンがありません: {token_path}\n"
            "  先に `python -m ytnb auth` を実行してブラウザでログインしてください"
        )

    if not Path(client_json).exists():
        raise AuthError(
            f"OAuth クライアントの JSON が見つかりません: {client_json}\n"
            "  Cloud Console > 認証情報 > OAuth クライアント ID (デスクトップ アプリ) を作成し、JSON をダウンロードしてください"
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_json, DRIVE_SCOPES)
    # WSL などブラウザを自動で開けない環境向けに URL を表示する
    creds = flow.run_local_server(
        port=0,
        open_browser=True,
        authorization_prompt_message="ブラウザで次の URL を開いてログインしてください:\n{url}\n",
        success_message="認証が完了しました。このタブは閉じて構いません。",
    )
    token_file.write_text(creds.to_json(), encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    log.info("トークンを保存しました: %s", token_path)
    return creds


def drive_credentials(cfg, interactive: bool = False):
    mode = cfg.notebook.drive_auth
    if mode == "service_account":
        return service_account_credentials(cfg.sa_json)
    if mode == "oauth":
        return oauth_credentials(cfg.oauth_client_json, cfg.oauth_token_path, interactive=interactive)
    raise AuthError(f"notebook.drive.auth は oauth か service_account: {mode!r}")


# ---- 手動モード (WSL などで localhost へのリダイレクトが届かない環境向け) ----


def manual_auth_url(client_json: str) -> str:
    """認可 URL を生成し、state を一時ファイルに保存して返す。"""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not Path(client_json).exists():
        raise AuthError(f"OAuth クライアントの JSON が見つかりません: {client_json}")
    flow = InstalledAppFlow.from_client_secrets_file(client_json, DRIVE_SCOPES, redirect_uri=MANUAL_REDIRECT_URI)
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    # PKCE の code_verifier は同じものをトークン交換時に使う必要があるので state と一緒に保存する
    Path(MANUAL_STATE_FILE).write_text(
        json.dumps({"state": state, "code_verifier": flow.code_verifier}), encoding="utf-8"
    )
    return url


def manual_auth_finish(client_json: str, token_path: str, response: str) -> Credentials:
    """ブラウザのアドレスバーに出た URL (または code そのもの) からトークンを取得して保存する。"""
    from google_auth_oauthlib.flow import InstalledAppFlow

    response = response.strip()
    code = response
    if response.startswith("http"):
        qs = parse_qs(urlparse(response).query)
        if "error" in qs:
            raise AuthError(f"Google から拒否されました: {qs['error'][0]}")
        if "code" not in qs:
            raise AuthError("URL に code= が含まれていません。アドレスバーの URL 全体を貼り付けてください")
        code = qs["code"][0]

    state_file = Path(MANUAL_STATE_FILE)
    if not state_file.exists():
        raise AuthError("認証の途中状態がありません。`ytnb auth --manual` からやり直してください")
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    if response.startswith("http"):
        got = parse_qs(urlparse(response).query).get("state", [None])[0]
        if saved.get("state") and got and saved["state"] != got:
            raise AuthError("state が一致しません。`ytnb auth --manual` からやり直してください")

    flow = InstalledAppFlow.from_client_secrets_file(
        client_json, DRIVE_SCOPES, redirect_uri=MANUAL_REDIRECT_URI, code_verifier=saved.get("code_verifier")
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    token_file = Path(token_path)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    Path(MANUAL_STATE_FILE).unlink(missing_ok=True)
    log.info("トークンを保存しました: %s", token_path)
    return creds
