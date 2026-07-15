# Runner-local cron trigger for Auto Update

The `Auto Update Inventory` workflow is **not** triggered by a GitHub Actions
`schedule`. Instead, a system cron on the self-hosted runner host calls
`workflow_dispatch` every hour via the GitHub API. `auto-update.yml` keeps only
`push` + `workflow_dispatch` triggers.

This document is the runbook for that setup.

## Why not GitHub Actions `schedule`

GitHub Actions scheduled workflows are delayed or dropped at `:00` under high
load (officially documented: "The schedule event can be delayed during periods
of high loads of GitHub Actions workflow runs. High load times include the
start of every hour. If the load is sufficiently high enough, some queued jobs
may be dropped.").

Measured on this repo with `cron: '0 * * * *'`: only ~13 of 24 hourly slots
fired per day, and actual fire times were never on `:00` (e.g. 23:40, 01:11,
04:37…), with intervals often stretched to 1.5–3h. Moving the trigger onto a
local cron eliminates the delay/drop: the measured first run fired at
`02:00:03Z`, i.e. +3 seconds past the hour.

## How it works

```
claystan user crontab (Debian runner host)
  0 * * * *  trigger.sh  >> trigger.log 2>&1
        |
        v
trigger.sh   export HOME=/home/claystan ; PATH=/usr/bin:/bin
             gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase --ref master
        |
        v
gh reads PAT from ~/.config/gh/hosts.yml (must have `workflow` scope)
  -> POST GitHub API: create workflow_dispatch event
        |
        v
GitHub creates run -> self-hosted runner picks it up immediately when online
```

The cron trigger is just one GitHub API call; it does **not** depend on the
runner being online at trigger time. If the runner is down, the run is created
and queued, then picked up once the runner comes back.

## Components (all on the runner host)

Host: Debian, user `claystan`, timezone `America/New_York`.

| Component | Path / unit | Reboot |
|---|---|---|
| crontab entry | `crontab -l` (claystan) | persisted on disk |
| trigger script | `~/.local/share/mtg-showcase/trigger.sh` | persisted |
| trigger log | `~/.local/share/mtg-showcase/trigger.log` | appended each run |
| gh PAT | `~/.config/gh/hosts.yml` | persisted (needs `workflow` scope) |
| cron daemon | `cron.service` | `enabled`, autostarts |
| runner service | `actions.runner.ClayStan404-mtg-showcase.mtg-showcase.service` | `enabled`, autostarts |
| Scryfall cache | `~/actions-runner/_work/.../.cache/scryfall` | on `ext4`, survives |

## Timezone

The host timezone is `America/New_York` (EDT = UTC-4 / EST = UTC-5). Vixie cron
does **not** support `CRON_TZ`; cron schedules are always interpreted in the
host local timezone. The offset to Beijing (UTC+8) is a whole number of hours
(12 in summer, 13 in winter), so **New_York `:00` == Beijing `:00`** with no
DST drift — that is why `0 *` corresponds to "every Beijing hour".

(Contrast with crontab entries that target a non-whole-hour offset to Beijing,
e.g. a daily 06:10 Beijing job, which must be rewritten at DST transitions.)

## crontab entry

```
# mtg-showcase 每小时触发部署（绕开 GitHub Actions schedule 的整点延迟/丢弃）。
# 服务器时区 America/New_York；北京=UTC+8，New_York 夏 EDT=UTC-4 / 冬 EST=UTC-5，
# 时差恒为整数小时（12 或 13），故 New_York 整点 = 北京整点，无夏令时漂移。
# 由本机 self-hosted runner 拾取 run；机器离线 / cron 挂了时 heartbeat.yml 2h 兜底告警。
0 * * * * /home/claystan/.local/share/mtg-showcase/trigger.sh >> /home/claystan/.local/share/mtg-showcase/trigger.log 2>&1
```

## trigger.sh

```bash
#!/bin/bash
# mtg-showcase auto-update 每小时触发器（由本机 cron 调用）。
#
# 用 workflow_dispatch 绕开 GitHub Actions schedule 的整点延迟/丢弃
# （官方文档：schedule 在整点高负载时会被延迟甚至丢弃；实测本仓库
# cron '0 *' 一天被跳过近一半，间隔常拉到 1.5–3h）。
#
# 触发由本地 cron 发起，run 进入 GitHub 队列后由本机 self-hosted runner
# 立即拾取。若本机离线或 cron 失败，heartbeat.yml 在 GitHub 侧 2h 无成功
# 部署即告警兜底（heartbeat 跑在 ubuntu-latest，不依赖本 runner）。
#
# 每次执行在 trigger.log 留一行时间戳 + 结果，便于排查 cron 是否在跑。
set -euo pipefail
export HOME=/home/claystan
export PATH=/usr/bin:/bin
REPO=ClayStan404/mtg-showcase
WF=auto-update.yml
echo "[$(date -u +%FT%TZ)] triggering auto-update (repo=$REPO wf=$WF)"
if /usr/bin/gh workflow run "$WF" --repo "$REPO" --ref master; then
  echo "[$(date -u +%FT%TZ)] ok: workflow_dispatch created"
else
  rc=$?
  echo "[$(date -u +%FT%TZ)] FAIL exit=$rc" >&2
  exit "$rc"
fi
```

`set -e` would normally abort on `gh` failure, but `if` captures it, so the
`else` branch explicitly `exit "$rc"` to propagate the non-zero exit to cron
(and keep a `FAIL` line in the log).

## Reboot impact

- `cron.service` and the runner service are both `enabled` → autostart.
- crontab / `trigger.sh` / PAT / Scryfall cache are all on disk → survive.
- A run in flight when the reboot hits → killed → GitHub marks it failed →
  `Notify on failure` opens an "Auto-update failed" issue → auto-closed on the
  next successful run.
- A `:00` missed because the reboot straddled the hour → not retried (system
  cron never backfills); the next `:00` resumes.
- Reboot < 2h → heartbeat stays silent. > 2h → heartbeat opens an
  "Auto-update stale" issue, auto-closed on recovery.

## Troubleshooting

"Site not updating?" — check on the runner host first, then GitHub:

```bash
# on runner host
tail ~/.local/share/mtg-showcase/trigger.log        # each cron run leaves a line
crontab -l | grep mtg-showcase                       # entry present?
systemctl status cron                                 # daemon alive?
systemctl status actions.runner.ClayStan404-mtg-showcase.mtg-showcase   # runner online?

# GitHub side (from anywhere with gh)
gh run list --workflow=auto-update.yml --repo ClayStan404/mtg-showcase --limit 5
```

`heartbeat.yml` is the backstop: it runs on `ubuntu-latest` (independent of
the self-hosted runner), checks the latest successful auto-update run, and
opens an issue if none in 2h. So even a silent cron failure is surfaced.

## Reinstall / restore

If the runner host is rebuilt, recreate the trigger with:

```bash
gh auth login   # ensure token has `workflow` scope: gh auth status
mkdir -p ~/.local/share/mtg-showcase
# paste trigger.sh from above, then:
chmod +x ~/.local/share/mtg-showcase/trigger.sh
bash -n ~/.local/share/mtg-showcase/trigger.sh   # syntax check

# add crontab entry (appends to existing crontab, idempotent)
( crontab -l 2>/dev/null; echo; cat <<'EOF'
0 * * * * /home/claystan/.local/share/mtg-showcase/trigger.sh >> /home/claystan/.local/share/mtg-showcase/trigger.log 2>&1
EOF
) | grep -v 'mtg-showcase/trigger.sh' | { cat; echo '0 * * * * /home/claystan/.local/share/mtg-showcase/trigger.sh >> /home/claystan/.local/share/mtg-showcase/trigger.log 2>&1'; } | crontab -
crontab -l   # verify
```
