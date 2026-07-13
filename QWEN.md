# QWEN.md

## Project Overview

静态 **万智牌在售 + 求购清单** 网站，用于多人展示实体卡牌库存与求购。买家可搜索、筛选、加入意向清单后截图/复制文本站外联系卖家。**不做站内下单/支付。**

- **站点**：https://claystan.cc/
- **仓库**：https://github.com/ClayStan404/mtg-showcase
- **分支**：`master`
- **部署**：GitHub Pages（CNAME -> `claystan.cc`），workflow 模式（`build_type: workflow`）
- **自动化**：GitHub Actions self-hosted runner，`push` / 每小时 cron / 手动触发 -> 从 WPS 云文档拉取 -> 解析 -> Scryfall 富化 -> 打包 Pages artifact 发布。产物不入 git，master 只放源码

## Tech Stack

- **前端**：原生 HTML / CSS / JS（无框架），`index.html` + `assets/app.js` + `assets/style.css`
- **数据**：`assets/cards-data.js`（`window.__MTG_DATA__` 内嵌）+ `assets/wants-data.js`（`window.__MTG_WANTS__`），分别与 `data/cards.json` / `data/wants.json` 同源
- **后端脚本**：Python 3（`requests` + `openpyxl`），职责是解析 WPS Excel -> 拉取 Scryfall 元数据 -> 生成站点数据
- **自动化**：GitHub Actions + self-hosted runner（Debian），cron 每小时触发 + push 触发
- **数据来源**：WPS 金山文档在线协作表格（在售 + 求购各一个文档），通过分享链接 + Cookie 自动下载

## Architecture / Data Flow

### 自动化流程（GitHub Actions 每小时）

```
WPS 在售文档 (share link)  ->  fetch_wps_share.py  ->  wps_inventory.xlsx
WPS 求购文档 (share link)  ->  fetch_wps_share.py  ->  wps_wants.xlsx
  ↓
parse_wps_excel.py        ->  inventory/*.txt
parse_wps_wants_excel.py  ->  wants/*.txt
  ↓
build_data.py             ->  data/cards.json + assets/cards-data.js
build_wants.py            ->  data/wants.json + assets/wants-data.js
  ↓
assemble site/（+CNAME +robots.txt +og-image.png）-> upload-pages-artifact -> deploy-pages（产物不入 git）
```

### ClayStan 个人流程（数据走 WPS，无本地上线）

```
claystan.txt（手写，Excel 列顺序：系列 编号 语言 闪 数量）
  ↓  txt_to_wps_xlsx.py  ->  claystan.xlsx（WPS 模板格式）
  ↓  手动上传到 WPS 在售文档
  ↓  下次 workflow 运行自动同步（或 gh workflow run 立即触发）
```

`claystan.txt` 是个人编辑用，**不参与自动化流程**。改完后跑 `txt_to_wps_xlsx.py` 生成 xlsx，上传到 WPS 文档，下次 workflow 运行自动同步。**数据上线统一走 WPS + Actions，无本地直连路径**。

### 其他卖家

直接在 WPS 协作文档里编辑自己的工作表，无需本地操作。

## Key Directories

| 路径 | 用途 |
|------|------|
| `scripts/` | Python 脚本（见下表） |
| `.github/workflows/` | GitHub Actions workflow（`auto-update.yml` 部署 + `heartbeat.yml` 监控） |
| `inventory/` | 卖家库存 txt 文件（由 `parse_wps_excel.py` 自动生成，不入库） |
| `wants/` | 求购 txt 文件（由 `parse_wps_wants_excel.py` 自动生成，不入库） |
| `data/` | `cards.json` / `wants.json` - 富化后的完整数据（不入库） |
| `assets/` | 前端资源：`app.js`、`style.css`（源码）+ `cards-data.js`、`wants-data.js`（生成产物，不入库）+ `favicon.svg`、`og-image.png`（社交分享） |
| `templates/` | WPS 协作模板 xlsx |
| `tests/` | `test_inventory_format.py` - 核心解析函数单元测试（pytest） |
| `pyproject.toml` | ruff + pytest 配置 |
| `requirements-dev.txt` | 开发依赖：`ruff` + `pytest` |
| `robots.txt` | 搜索引擎爬虫指引（部署时 cp 到 site/） |
| `.cache/scryfall/` | Scryfall API 响应缓存（git-ignored，runner 工作区持久） |

### 脚本一览

| 脚本 | 用途 |
|------|------|
| `fetch_wps_share.py` | 从 WPS 分享链接下载 xlsx（读 Cookie 文件） |
| `parse_wps_excel.py` | WPS 在售 xlsx -> `inventory/*.txt` |
| `parse_wps_wants_excel.py` | WPS 求购 xlsx -> `wants/*.txt`（多一列「必须」） |
| `parse_excel_order_txt.py` | 手写 txt（Excel 列顺序）-> `inventory/*.txt` |
| `txt_to_wps_xlsx.py` | `claystan.txt` -> WPS 模板格式 xlsx（上传用） |
| `build_data.py` | `inventory/*.txt` -> Scryfall 富化 -> `data/cards.json` + `assets/cards-data.js` |
| `build_wants.py` | `wants/*.txt` -> Scryfall 富化 -> `data/wants.json` + `assets/wants-data.js` |
| `inventory_format.py` | 共享约定：语言/闪/数量归一化、slugify、ParseError、validate_meta |
| `build_common.py` | build_data / build_wants 共享：Scryfall 富化、磁盘缓存、payload 工具（解耦） |
| `wps_excel_common.py` | parse_wps_* 共享：工作表跳过 / meta / header 查找 / 写入（含冲突检测） |
| `test_wps_api.py` | WPS 开放平台 API 测试脚本（OAuth + 签名认证，需 app 审核） |

## Build & Run

```bash
# 环境初始化
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# ── 自动化（GitHub Actions 每小时自动运行，无需手动干预）──
# 手动触发部署：
gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase

# ── ClayStan 个人更新流程（数据走 WPS，无本地上线）──
# 1. 编辑 claystan.txt
# 2. 生成 WPS 格式 xlsx
python3 scripts/txt_to_wps_xlsx.py claystan.txt
# 3. 打开 WPS 在售文档，用 claystan.xlsx 内容更新 ClayStan 工作表
# 4.（可选）立即触发部署：gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase

# ── 手动分步执行（调试用）──
# 下载 xlsx
python3 scripts/fetch_wps_share.py --share-id cgyl3WizNfp7 --output wps_inventory.xlsx
python3 scripts/fetch_wps_share.py --share-id cvvaN21e3gm8 --output wps_wants.xlsx
# 解析
python3 scripts/parse_wps_excel.py wps_inventory.xlsx
python3 scripts/parse_wps_wants_excel.py wps_wants.xlsx
# Scryfall 富化
python3 scripts/build_data.py
python3 scripts/build_wants.py
# 产物不入库；本地调试生成后用 python3 -m http.server 预览，上线靠 push master 触发 workflow

# ── 测试 + lint（需 pip install -r requirements-dev.txt）──
pip install -r requirements-dev.txt
python3 -m pytest tests/ -q
ruff check scripts/ tests/
```

本地预览：直接用浏览器打开 `index.html`，或 `python3 -m http.server` 后访问 `localhost:8000`。

## Self-Hosted Runner 配置

- **机器**：Debian（SSH 名 `debian`）
- **Runner 目录**：`/home/claystan/actions-runner-personal/`
- **Runner 名称**：`mtg-showcase`
- **Cookie 文件**：`~/.config/wps_cookies.txt`（单行，浏览器复制的 Cookie 值）
- **Python 依赖**：`python3-requests` + `python3-openpyxl`（via apt）

### Cookie 过期后更新

```bash
# 从浏览器复制新 Cookie，直接写入文件，无需重启 runner
cat 新cookie.txt | ssh debian "cat > ~/.config/wps_cookies.txt"
```

## WPS 开放平台 API（待审核）

已注册应用（`developer.kdocs.cn`），但尚未审核通过。审核通过后可切换到 OAuth 方案，无需手动维护 Cookie。

- 测试脚本：`scripts/test_wps_api.py`
- 凭证文件：`appid_and_key`（git-ignored）
- API 文档：https://developer.kdocs.cn

## Conventions

### 库存字段简写

| 字段 | 规则 |
|------|------|
| 语言 | `e`=英文 · `z`=中文 · `j`=日文 · `o`=其他（空默认 `e`） |
| 闪 | 空或 `0`=非闪 · `1`=闪 |
| 数量 | 空=1；多张用 `2x` 前缀 |
| 必须（求购） | 空/`0`=可替其他版 · `1`=必须此印刷（空默认 `0`） |

- 卖光请**删行**，不写 `0`
- 同卡同印刷同语言同行，用数量合并
- inventory txt 文件头用 `# seller: / # city: / # contact:` 声明元数据
- wants txt 文件头用 `# buyer: / # city: / # contact:` 声明元数据
- **`seller`/`buyer`、`city`、`contact` 为必填项**，缺失时脚本会报错退出
- `parse_excel_order_txt.py` 的输入格式为 Excel 列顺序：`系列 编号 语言 闪 数量`（位置固定，与 inventory 格式不同）

### 前端约定

- 无构建工具/无 npm - 纯静态文件，push master 触发 workflow 部署
- 卡牌数据内嵌在 `assets/cards-data.js`（`window.__MTG_DATA__`），`index.html` 通过 `<script>` 加载
- 意向清单存储在 `localStorage`（key: `mtg-wishlist-v1`）
- `app.js` 中所有 DOM 查询用 `$()` 简写，渲染靠 `innerHTML` 模板字符串
- HTML 转义：`escapeHtml()` / `escapeAttr()` 用于所有用户可控内容（`escapeHtml` 转义单引号 `&#39;`）
- CSP meta（`script-src 'self'`，inline `onerror` 改用 `addEventListener` `bindImgErrors`）+ OG/Twitter 分享卡片（`og-image.png` 1200x630）+ `favicon.svg` + noscript 降级
- `style.css` 有 `prefers-reduced-motion` 降级（含 `scroll-behavior`）；卡片列表分页（`PAGE_SIZE=60`，「加载更多」增量追加不重建 DOM）；footer 展示「最后更新」时间
- 可访问性：模态/清单打开时背景加 `inert`；焦点保存/恢复（`_lastFocus`）；`role="tablist"/"tab"` + `aria-selected`
- 安全：`setHrefSafe()` 校验 `http(s)://` 防 `javascript:` 注入；图片加载失败 CSS `.img-failed::after` 显示「图加载失败」
- 数据字段：`image_lang`（卡图实际语言，与 `lang` 不同时在 modal 显示「图:英文」标签）
- 求购视图也有 `lang` / `foil` 筛选器（与在售视图一致）

### Python 脚本约定

- 共享逻辑：`scripts/inventory_format.py`（语言/闪/数量归一化、slugify、ParseError、`validate_meta()` 必填校验）+ `scripts/build_common.py`（`ScryfallClient`、`base_from_cached` / `base_from_card`、`bump_cache_buster`、`payload_unchanged`、`load_site_config` 等富化/缓存/payload 工具）+ `scripts/wps_excel_common.py`（工作表跳过 / meta / header 查找 / 写入含冲突检测）
- `REQUEST_GAP`、`CACHE_TTL`、`bump_cache_buster` 等常量/函数均定义在 `build_common.py` 中（不在 `build_data.py`）
- Scryfall 请求有限速（`REQUEST_GAP = 0.12s`）和磁盘缓存（`.cache/scryfall/`，`CACHE_TTL = 30 天`）；429 读 `Retry-After`；mtgch 负结果也缓存
- `build_data.py` / `build_wants.py` 都有两层增量缓存（已有 JSON 的富化数据复用 + Scryfall 磁盘缓存）；workflow 用 `clean: false` 保留 runner 工作区这两层缓存
- `build_data.py --validate-only` 可只校验不联网（用于 PR 校验）
- `build_data.py --no-cache` 禁用磁盘缓存
- `fetch_wps_share.py` 有 3 次重试 + 5s/10s 退避；Cookie 查找顺序：项目根目录 `wps_cookies.txt` -> `~/.config/wps_cookies.txt` -> 环境变量 `WPS_COOKIES`（fallback）
- `normalize_qty` strict 模式拒绝非整数浮点（如 `1.9`），非 strict 回退 1（不静默截断）
- Workflow sanity check：error 卡比例 > 20% 则中止部署，触发 issue 通知

## site_config.json

站点级配置：标题、副标题、WPS 文档链接、联系方式。`build_common.py` 的 `load_site_config()` 读取，`build_data.py` / `build_wants.py` 各自写入 JSON 的 `site` 字段供前端渲染。Workflow 也从 `site_config.json` 读取 WPS share ID（不再硬编码在 workflow 中）。

## Git & Deploy

- 分支 `master` 只放源码，**生成产物不入库**；部署走 GitHub Actions（workflow 模式，`build_type: workflow`）
- **GitHub Actions**：`push master` / 每小时 cron / `workflow_dispatch` 触发 -> 现场从 WPS 拉取生成产物 -> 组装 `site/`（含 `CNAME` / `robots.txt` / `og-image.png`）-> `upload-pages-artifact` -> `deploy-pages`
- **heartbeat workflow**（`heartbeat.yml`）：GitHub-hosted runner 每 30min 检查 auto-update 新鲜度，超 2h 无成功部署开 issue，恢复自动关闭（GitHub 不对跳过的 cron 发通知）
- 产物：`inventory/*.txt`、`data/cards.json`、`data/wants.json`、`assets/cards-data.js`、`assets/wants-data.js`、`wants/*.txt` 均为中间/生成产物，不入库
- 前端 CSS/JS 版本号（`?v=N`）：`cards-data.js` / `wants-data.js` / `app.js` / `style.css` 均由 `build_common.py` 的 `bump_cache_buster` 用内容哈希自动 bump，bump 只发生在部署 artifact 里，不回写 master
- `.gitignore`：`.venv/`、`.cache/`、`__pycache__/`、WPS lock files（`**/.~*`）、`appid_and_key`、`wps_cookies.txt`、`*.xlsx`（`!templates/*.xlsx` 保留模板）、`site/`、`.qwen/`、`.claude/`，以及生成产物 `inventory/`、`data/cards.json`、`data/wants.json`、`assets/cards-data.js`、`assets/wants-data.js`、`wants/`

### auto-update workflow 新增步骤

- `timeout-minutes: 30`：防止挂起进程锁死 runner
- Verify Python deps：预检 `import requests, openpyxl`，包丢失早失败
- Lint & test（仅 push 触发）：`ruff check` + `pytest`（cron 不跑，省时）
- Read WPS share IDs from `site_config.json`：单一来源，workflow 不再硬编码
- Sanity check enrichment：error 卡比例 > 20% 则中止部署
- Issue 通知改用 Python `urllib.request`（不再用 curl + JSON 拼接）

## WPS Share IDs

| 文档 | 分享 ID | 分享链接 |
|------|---------|----------|
| 在售清单 | `cgyl3WizNfp7` | https://www.kdocs.cn/l/cgyl3WizNfp7 |
| 求购清单 | `cvvaN21e3gm8` | https://www.kdocs.cn/l/cvvaN21e3gm8 |
