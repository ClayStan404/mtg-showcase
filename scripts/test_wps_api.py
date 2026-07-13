#!/usr/bin/env python3
"""Test WPS/Kingsoft Docs Open Platform API — methods A (download) & B (read cells).

Usage:
  # Full flow (OAuth if needed → test A → test B)
  python3 scripts/test_wps_api.py

  # If redirect_uri is not localhost, pass code manually:
  python3 scripts/test_wps_api.py --code AUTH_CODE_FROM_BROWSER

  # Custom redirect_uri
  python3 scripts/test_wps_api.py --redirect-uri http://your-registered-uri

  # Test only one method
  python3 scripts/test_wps_api.py --method a
  python3 scripts/test_wps_api.py --method b
"""

from __future__ import annotations

import argparse
import http.server
import json
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_FILE = ROOT / "appid_and_key"
TOKEN_CACHE = ROOT / ".cache" / "wps_tokens.json"
WPS_API_BASE = "https://developer.kdocs.cn"
DEFAULT_REDIRECT_URI = "http://localhost:9527/callback"
LOCAL_PORT = 9527
OAUTH_TIMEOUT = 300  # 5 minutes


# ── Credentials & Token Cache ───────────────────────────────────────

def load_credentials() -> tuple[str, str]:
    with open(CREDENTIALS_FILE) as f:
        lines = f.read().strip().splitlines()
    return lines[0].strip(), lines[1].strip()


def load_tokens() -> dict[str, Any] | None:
    if TOKEN_CACHE.exists():
        return json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
    return None


def save_tokens(tokens: dict) -> None:
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


# ── OAuth 2.0 ────────────────────────────────────────────────────────

def exchange_code(app_id: str, app_key: str, code: str) -> dict:
    url = f"{WPS_API_BASE}/api/v1/oauth2/access_token"
    params = {"code": code, "app_id": app_id, "app_key": app_key}
    resp = requests.get(url, params=params, headers={"Content-Type": "application/json"})
    data = resp.json()
    if data.get("code") != 0:
        print(f"获取 token 失败: {json.dumps(data, ensure_ascii=False)}")
        sys.exit(1)
    return data["data"]


def refresh_access_token(app_id: str, app_key: str, refresh_token: str) -> dict | None:
    url = f"{WPS_API_BASE}/api/v1/oauth2/refresh_token"
    params = {"app_id": app_id}
    body = {"app_key": app_key, "refresh_token": refresh_token}
    resp = requests.post(url, params=params, json=body, headers={"Content-Type": "application/json"})
    data = resp.json()
    if data.get("code") != 0:
        return None
    return data["data"]


def catch_callback_local(port: int, timeout: int = OAUTH_TIMEOUT) -> str | None:
    """Start local HTTP server, wait for OAuth redirect, return code."""
    code_holder: dict[str, str] = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("✅ 授权成功！可以关闭此页面。".encode())
            else:
                err = params.get("error", ["unknown"])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"❌ 授权失败: {err}".encode())

        def log_message(self, fmt, *args):
            pass

    server = http.server.HTTPServer(("localhost", port), CallbackHandler)
    server.timeout = timeout
    server.handle_request()
    server.server_close()
    return code_holder.get("code")


def do_oauth(app_id: str, redirect_uri: str) -> str:
    scope = "access_personal_files,download_personal_files"
    auth_url = (
        f"{WPS_API_BASE}/h5/auth"
        f"?app_id={app_id}&scope={scope}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
    )

    print(f"\n{'='*60}")
    print("请在浏览器中打开以下链接进行授权：")
    print(auth_url)
    print(f"{'='*60}")

    try:
        webbrowser.open(auth_url)
        print("已尝试自动打开浏览器\n")
    except Exception:
        pass

    if "localhost" in redirect_uri or "127.0.0.1" in redirect_uri:
        print(f"本地服务监听 localhost:{LOCAL_PORT}，等待回调...")
        code = catch_callback_local(LOCAL_PORT)
        if not code:
            print("❌ 授权超时或失败")
            sys.exit(1)
        return code
    else:
        print("非 localhost redirect_uri，请手动复制授权后的 code：")
        print("（授权后浏览器地址栏会显示 ...?code=XXXX，复制 code 值）")
        code = input("code: ").strip()
        if not code:
            print("❌ 未输入 code")
            sys.exit(1)
        return code


def get_access_token(app_id: str, app_key: str, redirect_uri: str, code: str | None) -> str:
    # Try refresh first
    tokens = load_tokens()
    if tokens and tokens.get("refresh_token") and not code:
        print("尝试刷新 access_token...")
        refreshed = refresh_access_token(app_id, app_key, tokens["refresh_token"])
        if refreshed:
            save_tokens(refreshed)
            print("✓ access_token 刷新成功")
            return refreshed["access_token"]
        print("刷新失败，需要重新授权")

    # OAuth flow
    if code:
        print("使用命令行提供的 code 换取 token...")
        tokens = exchange_code(app_id, app_key, code)
    else:
        print("启动 OAuth 授权流程...")
        auth_code = do_oauth(app_id, redirect_uri)
        tokens = exchange_code(app_id, app_key, auth_code)

    save_tokens(tokens)
    print("✓ 获取 access_token 成功")
    return tokens["access_token"]


# ── API Calls ────────────────────────────────────────────────────────

def list_personal_files(access_token: str) -> list[dict]:
    url = f"{WPS_API_BASE}/api/v1/openapi/personal/files/flat"
    all_files: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(url, params={"access_token": access_token, "offset": offset})
        data = resp.json()
        if data.get("code") != 0:
            print(f"获取文件列表失败: {json.dumps(data, ensure_ascii=False)}")
            return all_files
        files = data.get("data", {}).get("files", [])
        all_files.extend(files)
        if len(files) < 10:
            break
        offset += len(files)
        time.sleep(0.1)
    return all_files


def find_xlsx(files: list[dict]) -> list[dict]:
    return [f for f in files if f.get("name", "").endswith((".xlsx", ".xls"))]


# ── Method A: Download xlsx ──────────────────────────────────────────

def test_method_a(access_token: str, file_token: str | None = None) -> str | None:
    print(f"\n{'='*60}")
    print("方案 A: 下载 xlsx")
    print(f"{'='*60}")

    if not file_token:
        print("正在获取文件列表...")
        files = list_personal_files(access_token)
        print(f"共找到 {len(files)} 个文件")
        for i, f in enumerate(files[:20]):
            print(f"  [{i}] {f.get('name', 'N/A')} (id: {f.get('id', 'N/A')[:20]}...)")

        xlsx_files = find_xlsx(files)
        if not xlsx_files:
            print("❌ 未找到 xlsx 文件")
            return None

        print(f"\n找到 {len(xlsx_files)} 个表格文件，自动选择第一个:")
        target = xlsx_files[0]
        file_token = target["id"]
        print(f"  → {target.get('name', 'N/A')} (token: {file_token[:20]}...)")

    # Get download URL
    url = f"{WPS_API_BASE}/api/v1/openapi/personal/files/{file_token}/download"
    resp = requests.get(url, params={"access_token": access_token})
    data = resp.json()
    print("\n下载接口响应:")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:600])

    if data.get("code") != 0:
        print("❌ 获取下载地址失败")
        return file_token

    download_url = data.get("data", {}).get("url")
    if not download_url:
        print("❌ 响应中未找到下载 URL")
        return file_token

    # Download file
    print(f"\n下载地址: {download_url[:100]}...")
    resp = requests.get(download_url)
    output_path = ROOT / "wps_download_test.xlsx"
    output_path.write_bytes(resp.content)
    print(f"✓ 已下载到: {output_path} ({len(resp.content):,} bytes)")
    return file_token


# ── Method B: Read cells directly ─────────────────────────────────────

def test_method_b(access_token: str, file_token: str | None = None) -> None:
    print(f"\n{'='*60}")
    print("方案 B: 直接读单元格")
    print(f"{'='*60}")

    if not file_token:
        print("正在获取文件列表...")
        files = list_personal_files(access_token)
        xlsx_files = find_xlsx(files)
        if not xlsx_files:
            print("❌ 未找到 xlsx 文件")
            return
        file_token = xlsx_files[0]["id"]
        print(f"选择: {xlsx_files[0].get('name', 'N/A')}")

    # Get sheet info
    print("\n获取工作表信息...")
    url = f"{WPS_API_BASE}/api/v1/openapi/et/{file_token}/sheets"
    resp = requests.get(url, params={"access_token": access_token})
    data = resp.json()
    print("Sheets 响应:")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:800])

    if data.get("code") != 0:
        print("❌ 获取 sheet 信息失败")
        return

    sheets = data.get("data", {}).get("sheets", [])
    if not sheets:
        print("❌ 未找到工作表")
        return

    print(f"\n找到 {len(sheets)} 个工作表:")
    for s in sheets:
        print(f"  - {s.get('name', 'N/A')} (idx: {s.get('idx', 'N/A')})")

    # Read first 10 rows x 10 cols of each sheet
    for sheet in sheets:
        sheet_idx = sheet.get("idx", 0)
        sheet_name = sheet.get("name", "N/A")
        print(f"\n读取 Sheet[{sheet_name}] 前 10 行 x 10 列...")

        url = f"{WPS_API_BASE}/api/v1/openapi/et/{file_token}/sheets/{sheet_idx}/cells"
        resp = requests.get(url, params={
            "access_token": access_token,
            "row_from": 0,
            "row_to": 9,
            "col_from": 0,
            "col_to": 9,
        })
        data = resp.json()

        if data.get("code") != 0:
            print(f"  ❌ 读取失败: {json.dumps(data, ensure_ascii=False)[:300]}")
            continue

        cells = data.get("data", {}).get("cells", [])
        if not cells:
            print("  ❌ 无数据")
            continue

        print(f"  ✓ 成功读取 {len(cells)} 行:")
        for row in cells[:10]:
            if isinstance(row, list):
                vals = []
                for cell in row:
                    if isinstance(cell, dict):
                        v = cell.get("value", cell.get("v", ""))
                        vals.append(str(v) if v else "")
                    elif isinstance(cell, str):
                        vals.append(cell)
                    else:
                        vals.append(str(cell) if cell else "")
                print(f"    {vals}")
            else:
                print(f"    {row}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test WPS/Kingsoft Docs API")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI,
                        help="OAuth redirect URI (must match registered)")
    parser.add_argument("--code", default=None,
                        help="OAuth authorization code (skip local server)")
    parser.add_argument("--file-token", default=None,
                        help="Specific file token (skip file listing)")
    parser.add_argument("--method", choices=["a", "b", "both"], default="both",
                        help="Which method to test")
    args = parser.parse_args()

    app_id, app_key = load_credentials()
    print(f"已加载凭证 (app_id: {app_id[:6]}...)")

    access_token = get_access_token(app_id, app_key, args.redirect_uri, args.code)

    file_token = args.file_token

    if args.method in ("a", "both"):
        result_token = test_method_a(access_token, file_token)
        if result_token and not file_token:
            file_token = result_token

    if args.method in ("b", "both"):
        test_method_b(access_token, file_token)

    print(f"\n{'='*60}")
    print("测试完成！")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
