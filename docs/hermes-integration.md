# Hermes agent integration (monitoring / query / broadcast)

The hermes agent (Nous Research, on `ssh radxa-32g`) is wired to mtg-showcase
for three bot-facing features over the TG / 微信 / QQ bots. Everything lives on
the hermes side and reads public site data + the GitHub API; **zero changes to
the mtg-showcase repo or its deploy pipeline.**

## Features (A/B/C, D deferred)

- **A — Deploy alerting**: hermes cron every 20 min queries the GitHub API for
  auto-update's recent runs; if the latest success is older than 2h or the most
  recent run failed, it pushes an alert (run URL + conclusion) to all 3 bots.
  Otherwise silent. Complements `heartbeat.yml` (which only opens a GitHub
  issue) and runs on a separate machine (radxa-32g), so it alerts even if the
  runner host is down.
- **B — Card / wants query**: a skill teaches the agent to read
  `claystan.cc/data/cards.json` + `wants.json` and answer "有没有 X" / "谁求购 X"
  (by name/set/seller/city; no prices, contact info included).
- **C — Daily stats broadcast**: hermes cron at 21:00 Asia/Shanghai reads the
  site data via the B skill and reports 在售数 / 卖家数 / 城市数 / 求购数 to all
  3 bots.
- **D — Inventory entry (deferred)**: bot-driven add/remove of cards. WPS
  writeback is infeasible (`fetch_wps_share.py` is download-only; writing the
  whole sheet back clobbers other sellers' edits). Revisit as a data-source
  decision.

## Components (all on radxa-32g, user claystan)

| Component | Path / unit | Notes |
|---|---|---|
| skill (B/C) | `~/.hermes/skills/domain/mtg-showcase/SKILL.md` | data sources, schema, search, answer format |
| A watchdog script | `~/.hermes/scripts/mtg_auto_update_check.py` | `--no-agent`; reads GitHub PAT from `~/.config/gh/hosts.yml` |
| cron jobs | `~/.hermes/cron/jobs.json` | `mtg-auto-update-check` (A), `mtg-daily-broadcast` (C) |
| hermes CLI | `~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main` | |
| gateway service | systemd-user `hermes-gateway` | restart needs `XDG_RUNTIME_DIR=/run/user/$(id -u)` |

## cron jobs

- A: `*/20 * * * *` — `--no-agent --script mtg_auto_update_check.py --deliver all`
- C: `0 21 * * *` — `--skill mtg-showcase --deliver all` (agent reads data, reports)

Manage with `hermes cron list/create/run/edit/rm`. `--deliver all` expands to
every connected channel (telegram / weixin / qqbot).

## Pitfalls (all hit during setup, all resolved)

1. `20m` is a **one-shot** ("once in 20m"), NOT recurring. Use a cron expression
   (`*/20 * * * *`) for repeating jobs.
2. `gh workflow run` succeeds silently, so A's log would not grow on success. A
   uses `--no-agent`, so empty stdout = silent (no delivery); the script prints
   an alert only on anomaly.
3. Telegram delivery fails on a long-running gateway (`httpx ConnectError` /
   `Timed out`) even though `curl` + a fresh venv `httpx` can reach
   `api.telegram.org`. **Restart `hermes-gateway` to fix.**
4. A's "provider rate limit" failure notification was actually the script hitting
   GitHub's anonymous 60/h API limit (HTTP 403). The script now reads a PAT from
   `~/.config/gh/hosts.yml` (5000/h).
5. A's staleness check uses `run_started_at` (fallback `created_at`), NOT
   `updated_at` -- GitHub refreshes `updated_at` after a run completes (later by
   ~the run's duration), so using it would make the 2h threshold effectively
   looser and alert late.

## Troubleshooting

- A not alerting / check status: `hermes cron list`; `cat ~/.hermes/cron/jobs.json`
  (look at `last_status` / `last_error` / `last_delivery_error`); per-run output
  under `~/.hermes/cron/output/<job-id>/`.
- Telegram delivery failing again:
  `export XDG_RUNTIME_DIR=/run/user/$(id -u); systemctl --user restart hermes-gateway`.
- B not answering: verify the skill at `~/.hermes/skills/domain/mtg-showcase/SKILL.md`
  and that `https://claystan.cc/data/cards.json` is reachable from radxa-32g.

Related: [`docs/runner-cron.md`](runner-cron.md) — the deploy chain that A monitors.
