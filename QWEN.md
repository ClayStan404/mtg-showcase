# QWEN.md

## Project Overview

静态 **万智牌在售清单** 网站，用于多人展示实体卡牌库存。买家可搜索、筛选、加入意向清单后截图/复制文本站外联系卖家。**不做站内下单/支付。**

- **站点**：https://claystan.cc/
- **仓库**：https://github.com/ClayStan404/mtg-showcase
- **分支**：`master`
- **部署**：GitHub Pages（CNAME → `claystan.cc`）
- **自动化**：GitHub Actions self-hosted runner，每小时从 WPS 云文档拉取最新数据 → 解析 → Scryfall 富化 → 自动部署

## Tech Stack

- **前端**：原生 HTML / CSS / JS（无框架），`index.html` + `assets/app.js` + `assets/style.css`
- **数据**：`assets/cards-data.js`（`window.__MTG_DATA__` 内嵌，避免额外 fetch）与 `data/cards.json` 同源
- **后端脚本**：Python 3（`requests` + `openpyxl`），职责是解析 WPS Excel → 拉取 Scryfall 元数据 → 生成站点数据
- **自动化**：GitHub Actions + self-hosted runner（Debian），cron 每小时触发
- **数据来源**：WPS 金山文档在线协作表格（在售 + 求购各一个文档），通过分享链接 + Cookie 自动下载

## Architecture / Data Flow

### 自动化流程（GitHub Actions 每小时）

```
WPS 在售文档 (share link)  →  fetch_wps_share.py  →  wps_inventory.xlsx
WPS 求购文档 (share link)  →  fetch_wps_share.py  →  wps_wants.xlsx
  ↓
parse_wps_excel.py        →  inventory/*.txt
parse_wps_wants_excel.py  →  wants/*.txt
  ↓
build_data.py             →  data/cards.json + assets/cards-data.js
build_wants.py            →  data/wants.json + assets/wants-data.js
  ↓
git commit & push → GitHub Pages 自动部署
```

### ClayStan 个人流程（本地维护）

```
claystan.txt（手写，Excel 列顺序：系列 编号 语言 闪 数量）
  ↓  txt_to_wps_xlsx.py  →  claystan.xlsx（WPS 模板格式）
  ↓  手动上传到 WPS 在售文档
```

`claystan.txt` 是个人编辑用，**不参与自动化流程**。改完后跑 `txt_to_wps_xlsx.py` 生成 xlsx，上传到 WPS 文档，下次 workflow 运行自动同步。

### 其他卖家

直接在 WPS 协作文档里编辑自己的工作表，无需本地操作。

## Key Directories

| 路径 | 用途 |
|------|------|
| `scripts/` | Python 脚本（见下表） |
| `.github/workflows/` | GitHub Actions workflow（`auto-update.yml`） |
| `inventory/` | 卖家库存 txt 文件（由 `parse_wps_excel.py` 自动生成） |
| `wants/` | 求购 txt 文件（由 `parse_wps_wants_excel.py` 自动生成） |
| `data/` | `cards.json` / `wants.json` — 富化后的完整数据 |
| `assets/` | 前端资源：`app.js`、`cards-data.js`、`wants-data.js`、`style.css` |
| `templates/` | WPS 协作模板 xlsx |
| `.cache/scryfall/` | Scryfall API 响应缓存（git-ignored） |

### 脚本一览

| 脚本 | 用途 |
|------|------|
| `fetch_wps_share.py` | 从 WPS 分享链接下载 xlsx（读 Cookie 文件） |
| `parse_wps_excel.py` | WPS 在售 xlsx → `inventory/*.txt` |
| `parse_wps_wants_excel.py` | WPS 求购 xlsx → `wants/*.txt`（多一列「必须」） |
| `parse_excel_order_txt.py` | 手写 txt（Excel 列顺序）→ `inventory/*.txt` |
| `txt_to_wps_xlsx.py` | `claystan.txt` → WPS 模板格式 xlsx（上传用） |
| `build_data.py` | `inventory/*.txt` → Scryfall 富化 → `data/cards.json` + `assets/cards-data.js` |
| `build_wants.py` | `wants/*.txt` → Scryfall 富化 → `data/wants.json` + `assets/wants-data.js` |
| `inventory_format.py` | 共享约定：语言/闪/数量归一化、slugify、ParseError、validate_meta |
| `test_wps_api.py` | WPS 开放平台 API 测试脚本（OAuth + 签名认证，需 app 审核） |
| `update.sh` | 一键上线：解析 → Scryfall 富化 → git commit & push |

## Build & Run

```bash
# 环境初始化
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# ── 自动化（GitHub Actions 每小时自动运行，无需手动干预）──
# 手动触发：
gh workflow run auto-update.yml --repo ClayStan404/mtg-showcase

# ── ClayStan 个人更新流程 ──
# 1. 编辑 claystan.txt
# 2. 生成 WPS 格式 xlsx
python3 scripts/txt_to_wps_xlsx.py claystan.txt
# 3. 打开 WPS 在售文档，用 claystan.xlsx 内容更新 ClayStan 工作表

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
# 提交
git add inventory/*.txt wants/*.txt data/ assets/cards-data.js assets/wants-data.js
git commit -m "Update inventory/wants"
git push origin master

# ── 一键上线（本地手动，解析 → 富化 → commit & push）──
./scripts/update.sh                     # 默认解析根目录 claystan.txt
./scripts/update.sh claystan.txt        # 指定 txt
./scripts/update.sh ~/下载/库存.xlsx      # 解析 WPS 导出的 xlsx
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

- 无构建工具/无 npm — 纯静态文件，修改后直接 git push
- 卡牌数据内嵌在 `assets/cards-data.js`（`window.__MTG_DATA__`），`index.html` 通过 `<script>` 加载
- 意向清单存储在 `localStorage`（key: `mtg-wishlist-v1`）
- `app.js` 中所有 DOM 查询用 `$()` 简写，渲染靠 `innerHTML` 模板字符串
- HTML 转义：`escapeHtml()` / `escapeAttr()` 用于所有用户可控内容

### Python 脚本约定

- 共享逻辑在 `scripts/inventory_format.py`（语言/闪/数量归一化、slugify、ParseError、`validate_meta()` 必填校验）
- Scryfall 请求有限速（`REQUEST_GAP = 0.12s`）和磁盘缓存（`.cache/scryfall/`）
- `build_data.py` 有两层增量缓存：已有 `cards.json` 的富化数据复用 + Scryfall 磁盘缓存
- `build_data.py --validate-only` 可只校验不联网（用于 PR 校验）
- `build_data.py --no-cache` 禁用磁盘缓存
- `update.sh` 是一键上线脚本，自动判断 `.txt`/`.xlsx` 并完成解析 → 富化 → commit & push
- `fetch_wps_share.py` Cookie 查找顺序：项目根目录 `wps_cookies.txt` → `~/.config/wps_cookies.txt` → 环境变量 `WPS_COOKIES`（fallback）

## site_config.json

站点级配置：标题、副标题、WPS 文档链接、联系方式。`build_data.py` 会读取并写入 `cards.json` 的 `site` 字段，前端从中渲染。

## Git & Deploy

- 分支 `master`，push 后 GitHub Pages 自动部署
- **GitHub Actions**：每小时整点 cron 触发，self-hosted runner 执行
- 上线产物：`inventory/*.txt` + `data/cards.json` + `assets/cards-data.js`（+ `wants/*.txt` + `assets/wants-data.js`）
- 前端 CSS/JS 有版本号参数（`?v=N`），修改前端文件后需 bump 版本号强制缓存刷新
- `.gitignore`：`.venv/`、`.cache/`、`__pycache__/`、WPS lock files（`**/.~*`）、`appid_and_key`、`wps_cookies.txt`、`*.xlsx`（生成的临时文件）

## WPS Share IDs

| 文档 | 分享 ID | 分享链接 |
|------|---------|----------|
| 在售清单 | `cgyl3WizNfp7` | https://www.kdocs.cn/l/cgyl3WizNfp7 |
| 求购清单 | `cvvaN21e3gm8` | https://www.kdocs.cn/l/cvvaN21e3gm8 |
