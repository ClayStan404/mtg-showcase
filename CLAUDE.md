# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

静态 **万智牌在售清单** 网站（GitHub Pages，域名 `claystan.cc`）。多位卖家展示实体卡库存，买家检索 / 筛选 / 加意向清单后截图或复制，**站外联系卖家成交**。不做站内下单或支付。

库存的真实数据源是 **WPS 云文档（金山文档 KDocs）**，仓库里只有生成产物与构建脚本。部署 = 推送 `master`。

## 架构：两条流水线

数据从云端表格流向前端是两段式，必须连起来理解：

1. **WPS Excel → `inventory/*.txt`**（`scripts/parse_wps_excel.py`）：解析从 WPS 导出的 `.xlsx`（每个卖家一个工作表），写成 `inventory/<seller>.txt`。一个卖家一个 txt，文件头用 `# seller: / # city: / # contact:`，卡行格式 `[Nx] set number [lang] [foil]`。
2. **`inventory/*.txt` → 站点数据**（`scripts/build_data.py`）：解析所有 txt，按 `seller_id|set|number|lang|foil` 合并重复行，调 Scryfall API 取卡图 / 英文名 / 规则面，非中文卡再调 mtgch 取中文名。**同时写两份产物**：`data/cards.json`（完整缩进）和 `assets/cards-data.js`（`window.__MTG_DATA__=<compact>` 内嵌版）。

`scripts/inventory_format.py` 是两段共用的字段约定库（语言 / 闪 / 数量归一化、`slugify`、`ParseError`）。改字段语义时三处脚本都要兼顾。

### 前端如何取数据

`assets/app.js` 的 `loadData()` 优先读 `window.__MTG_DATA__`（即内嵌的 `cards-data.js`）；只有在未生成时才回退 `fetch data/cards.json`。这是刻意设计——代理 / DNS 环境下 `fetch` 本地 json 会失败，内嵌更稳（见 commit `faa453b`）。**改了 `cards.json` 必须同步重跑 `build_data.py` 让 `cards-data.js` 跟上**，否则前端看不到变化。

前端无构建步骤、无框架：`index.html` + `assets/app.js` + `assets/style.css`，纯 vanilla JS。意向清单持久化在 `localStorage`（key `mtg-wishlist-v1`）。`index.html` 里 CSS/JS 用 `?v=12` 做缓存击穿，改静态资源时记得 bump。

## 常用命令

```bash
# 初始化（首次或换机）
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 从 WPS 导出的 xlsx 校验（不写文件）
python3 scripts/parse_wps_excel.py ~/下载/库存.xlsx --dry-run

# 写入 inventory/*.txt（仅写本次 xlsx 涉及的卖家，不删其他 txt）
python3 scripts/parse_wps_excel.py ~/下载/库存.xlsx

# 拉取 Scryfall 元数据，生成 data/cards.json + assets/cards-data.js
python3 scripts/build_data.py

# 只校验库存、不请求网络（PR / CI 友好）
python3 scripts/build_data.py --validate-only

# 强制重新拉取（忽略 .cache/scryfall 磁盘缓存）
python3 scripts/build_data.py --no-cache
```

无单元测试、无 lint、无前端构建。验证手段：`--dry-run` / `--validate-only`，以及本地打开 `index.html`（或 `python3 -m http.server`）肉眼检查。

## 字段约定（贯穿表格 / txt / 脚本，勿拆散）

| 字段 | 输入 | 内部码 |
|------|------|--------|
| 语言 | `e`/`z`/`j`/`o`（空默认 `e`） | `en` / `zhs` / `ja` / `other` |
| 闪 | 空 / `0`=否，`1`=是 | bool |
| 数量 | 空=1 | int≥1 |

- `o`(other) 展示为「其他」，但拉 Scryfall 图时**回退 `en`**（见 `SCRYFALL_LANG`）。
- 语言 / 闪 / 数量默认走**严格模式**：无法识别的值抛 `ParseError` 而非静默回退。新增可识别别名改 `inventory_format.py` 的 `LANG_INPUT_MAP` / `FOIL_TRUE` / `FOIL_FALSE`。
- WPS 工作表跳过规则：名为「说明 / 使用说明 / 填写说明 / 对照表（一般不用改）」或以「模板 / template / _」开头。表头需含「系列」「编号」列，前 15 行找「昵称 / 城市 / 联系」。

## 资源与外部依赖

- **Scryfall API**：`https://api.scryfall.com/cards/{set}/{number}/{lang}`，节流间隔 0.12s（`REQUEST_GAP`），User-Agent 标注用途。响应缓存在 `.cache/scryfall/`（已 gitignore）。
- **mtgch API**：`https://mtgch.com/api/v1/card/{set}/{number}/`，仅用于取非中文卡的中文名。
- `build_data.py` 会复用上一份 `cards.json` 里同 `set|number|lang` 的元数据加速重建——**清缓存或改了卡时首次构建会慢**。
- `site_config.json`：站点标题 / 副标题 / WPS 文档 URL / 联系方式，会被 `build_data.py` 内嵌进 `cards.json` 的 `site` 字段供前端渲染。
- `templates/WPS库存协作模板.xlsx`：卖家协作模板的本地副本，线上主入口见 `site_config.json` 的 `wps_inventory_url`。

## Git / 部署注意

- 日常更新库存的提交三件套：`inventory/*.txt`、`data/cards.json`、`assets/cards-data.js` 应一起提交（`build_data.py` 一次生成后两者）。
- 全局规则要求：commit message 与 PR 描述用英文；本机不主动 `git commit` / `git push`，需用户明确指示。
