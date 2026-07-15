#!/usr/bin/env python3
"""Watchdog: mtg-showcase auto-update freshness. Print alert if stale/failed; empty = silent.

Restorable copy - the live file is at ~/.hermes/scripts/mtg_auto_update_check.py
on radxa-32g. If you change one, update the other.
"""
import json, os, re, sys, urllib.request
from datetime import datetime, timezone

REPO = "ClayStan404/mtg-showcase"
WF = "auto-update.yml"
THRESHOLD_H = 2

# GitHub PAT: env 优先，否则从 gh 配置读（避免匿名 60/h 限流，认证后 5000/h）
token = os.environ.get("MTG_GH_TOKEN", "").strip()
if not token:
    try:
        hosts = open(os.path.expanduser("~/.config/gh/hosts.yml")).read()
        m = re.search(r"oauth_token:\s*([A-Za-z0-9_]+)", hosts)
        if m:
            token = m.group(1)
    except Exception:
        pass

url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WF}/runs?per_page=5"
headers = {"Accept": "application/vnd.github+json"}
if token:
    headers["Authorization"] = f"Bearer {token}"
req = urllib.request.Request(url, headers=headers)
data = json.load(urllib.request.urlopen(req, timeout=15))
runs = data.get("workflow_runs", [])

if not runs:
    print("mtg-showcase 部署告警：GitHub 无 run 记录")
    sys.exit(0)

now = datetime.now(timezone.utc)
alerts = []

latest_success = next((r for r in runs if r.get("conclusion") == "success"), None)
if latest_success:
    # 用 run_started_at（实际开始执行）或 created_at（触发时刻），不用 updated_at：
    # GitHub 在 run 完成后会刷新 updated_at 元数据（晚约一次 run 执行耗时），
    # 用它算 staleness 会偏宽松，报警比阈值晚。
    ts = latest_success.get("run_started_at") or latest_success.get("created_at") or latest_success["updated_at"]
    when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    age_h = (now - when).total_seconds() / 3600
    if age_h > THRESHOLD_H:
        alerts.append(f"auto-update 已 {age_h:.1f}h 无成功部署（阈值 {THRESHOLD_H}h），可能 runner 离线 / cron 挂 / cookie 过期")
else:
    alerts.append("auto-update 无成功 run 记录")

latest = runs[0]
if latest.get("conclusion") in ("failure", "cancelled"):
    alerts.append(f"最近 run {latest['conclusion']}: {latest['html_url']}")

if alerts:
    print("mtg-showcase 部署告警：\n" + "\n".join(alerts))
