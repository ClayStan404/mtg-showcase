#!/usr/bin/env python3
"""Download xlsx from WPS/Kingsoft Docs share link using session cookies.

Usage:
  1. Get your WPS cookies from browser:
     - Open https://www.kdocs.cn (make sure you're logged in)
     - F12 → Network → refresh → click any request
     - Request Headers → copy full Cookie value
     - Save to wps_cookies.txt (single line)

  2. Run:
     python3 scripts/fetch_wps_share.py
     python3 scripts/fetch_wps_share.py --share-id cgyl3WizNfp7
     python3 scripts/fetch_wps_share.py --output ~/下载/库存.xlsx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COOKIE_FILE = ROOT / "wps_cookies.txt"
DEFAULT_SHARE_ID = "cgyl3WizNfp7"
DEFAULT_OUTPUT = ROOT / "wps_download_test.xlsx"
DOWNLOAD_API = "https://www.kdocs.cn/api/v3/office/file/{share_id}/download?format=xlsx"
SHARE_PAGE = "https://www.kdocs.cn/l/{share_id}"


def load_cookies(cookie_file: Path) -> str:
    # Priority: env var WPS_COOKIES > file
    env_cookie = os.environ.get("WPS_COOKIES", "").strip()
    if env_cookie:
        return env_cookie

    if not cookie_file.exists():
        print(f"❌ Cookie 未找到（环境变量 WPS_COOKIES 未设置，文件也不存在: {cookie_file}）")
        print("\n本地获取 Cookie 步骤：")
        print("1. 浏览器打开 https://www.kdocs.cn 并登录")
        print("2. F12 → Network → 刷新页面")
        print("3. 点任意请求 → Request Headers → 找 Cookie")
        print("4. 复制完整 Cookie 值，保存到 wps_cookies.txt")
        print("\nGitHub Actions: 将 Cookie 值设为 Repository Secret WPS_COOKIES")
        sys.exit(1)
    cookie = cookie_file.read_text(encoding="utf-8").strip()
    if not cookie:
        print(f"❌ Cookie 文件为空: {cookie_file}")
        sys.exit(1)
    return cookie


def download_xlsx(share_id: str, cookie: str, output: Path) -> bool:
    url = DOWNLOAD_API.format(share_id=share_id)
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    headers = {
        "User-Agent": ua,
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": SHARE_PAGE.format(share_id=share_id),
    }

    print(f"请求下载: {url}")
    resp = requests.get(url, headers=headers, allow_redirects=False, timeout=30)

    # 302 → redirect to CDN download URL
    if resp.status_code == 302:
        dl_url = resp.headers.get("location", "")
        print(f"获取到 CDN 地址: {dl_url[:100]}...")
        resp = requests.get(dl_url, headers={"User-Agent": ua}, timeout=60)
        if resp.status_code == 200 and len(resp.content) > 100:
            output.write_bytes(resp.content)
            print(f"✓ 已下载: {output} ({len(resp.content):,} bytes)")
            return True
        print(f"❌ CDN 下载失败: {resp.status_code}")
        return False

    # 200 → direct file, JSON with download_url, or JSON error
    if resp.status_code == 200:
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            data = resp.json()
            # Success: API returns {"download_url": "https://..."}
            if "download_url" in data:
                dl_url = data["download_url"]
                print(f"获取到 CDN 地址: {dl_url[:100]}...")
                resp = requests.get(dl_url, headers={"User-Agent": ua}, timeout=60)
                if resp.status_code == 200 and len(resp.content) > 100:
                    output.write_bytes(resp.content)
                    print(f"✓ 已下载: {output} ({len(resp.content):,} bytes)")
                    return True
                print(f"❌ CDN 下载失败: {resp.status_code}")
                return False
            # Error response
            print(f"❌ API 返回错误: {json.dumps(data, ensure_ascii=False)[:300]}")
            if "未登陆" in resp.text:
                print("Cookie 已过期，请重新获取")
            return False
        if len(resp.content) > 100:
            output.write_bytes(resp.content)
            print(f"✓ 已下载: {output} ({len(resp.content):,} bytes)")
            return True
        print(f"❌ 响应内容过小 ({len(resp.content)} bytes)")
        return False

    if resp.status_code == 403:
        print(f"❌ 认证失败: {resp.text[:200]}")
        if "未登陆" in resp.text:
            print("Cookie 已过期，请重新获取")
        return False

    print(f"❌ 未知响应: {resp.status_code} {resp.text[:200]}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Download xlsx from WPS share link")
    parser.add_argument("--share-id", default=os.environ.get("WPS_SHARE_ID", DEFAULT_SHARE_ID),
                        help="WPS share link ID")
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE),
                        help="Cookie file path (ignored if WPS_COOKIES env var is set)")
    parser.add_argument("--output", default=os.environ.get("WPS_OUTPUT", str(DEFAULT_OUTPUT)),
                        help="Output file path")
    args = parser.parse_args()

    cookie = load_cookies(Path(args.cookie_file))
    print(f"已加载 Cookie ({len(cookie)} chars)")

    success = download_xlsx(args.share_id, cookie, Path(args.output))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
